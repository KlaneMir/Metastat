"""Facebook page sync: page data (daily), posts, post statistics snapshots, images."""
from __future__ import annotations

import logging
from datetime import date, timedelta

from metastat import db, flags, insights
from metastat.config import Campaign
from metastat.context import Ctx
from metastat.timeutil import insights_day, iso_local, iso_utc, local_date, parse_meta

log = logging.getLogger(__name__)

PAGE_FIELDS = "name,username,link,followers_count,instagram_business_account{id,username}"
POST_FIELDS = (
    "id,created_time,message,permalink_url,full_picture,status_type,shares,"
    "attachments{type,media_type},"
    "comments.limit(0).summary(total_count),"
    "reactions.limit(0).summary(total_count).as(reactions_total),"
    "reactions.type(LIKE).limit(0).summary(total_count).as(reactions_like)"
)
# A profile or cover photo change shows up in the API as a post; it is marked separately.
PROFILE_KINDS = {"profile_media": "profile_photo", "cover_photo": "cover_photo"}
KIND_LABELS = {"profile_photo": "Profile photo change", "cover_photo": "Cover photo change"}


def _summary(edge: dict | None) -> int:
    return int(((edge or {}).get("summary") or {}).get("total_count") or 0)


def sync_page(ctx: Ctx, camp: Campaign, fresh: bool) -> dict:
    page_id = camp.fb_page_id
    token = ctx.graph.page_token(page_id)
    out = {"posts": 0}

    if not fresh:
        info = ctx.graph.get(page_id, {"fields": PAGE_FIELDS})
        iba = info.get("instagram_business_account") or {}
        db.upsert(ctx.conn, "fb_pages", {
            "page_id": page_id, "campaign_id": camp.id, "name": info.get("name"),
            "username": info.get("username"), "link": info.get("link"),
            "ig_user_id": iba.get("id"), "updated_utc": ctx.taken_utc,
        }, ["page_id"])
        db.save_daily(ctx.conn, "fb_page_daily", "page_id", page_id, ctx.today.isoformat(),
                      {"followers_count": info.get("followers_count")}, "field")
        out["followers"] = info.get("followers_count")
        out["days"] = _page_daily(ctx, page_id, token)
        for metric in ("followers_count", "page_follows"):
            flags.check_followers(ctx.conn, ctx.s.flags, table="fb_page_daily", id_col="page_id",
                                  obj_id=page_id, metric=metric, scope="fb_page")

    hours = ctx.s.fresh_hours if fresh else ctx.s.snapshot_window_days * 24
    since = ctx.now - timedelta(hours=hours)
    for p in ctx.graph.paginate(f"{page_id}/posts", {"fields": POST_FIELDS, "since": int(since.timestamp()), "limit": 50},
                                token=token):
        _save_post(ctx, page_id, p, token)
        out["posts"] += 1
    return out


def _page_daily(ctx: Ctx, page_id: str, token: str) -> int:
    conn = ctx.conn
    last = conn.execute("SELECT MAX(date) FROM fb_page_daily WHERE page_id = ? AND source = 'insights'",
                        (page_id,)).fetchone()[0]
    end = ctx.today
    if last:
        start = date.fromisoformat(last) - timedelta(days=3)  # Meta adds data with a delay
    elif ctx.s.backfill_since:
        start = date.fromisoformat(ctx.s.backfill_since)
    else:
        start = end - timedelta(days=30)

    metrics = ctx.s.metrics.get("fb_page_day") or []
    breakdowns = (ctx.s.breakdowns.get("fb_page_day") or {}).items()
    rows: dict[date, dict] = {}
    chunk = start
    while chunk <= end:
        chunk_end = min(chunk + timedelta(days=89), end)
        params = {"period": "day", "since": chunk.isoformat(), "until": (chunk_end + timedelta(days=2)).isoformat()}
        for metric, points in insights.series(ctx.graph, conn, "fb_page_day", page_id, metrics, params, token).items():
            for end_time, value in points:
                day = insights_day(end_time)
                if start <= day <= end:
                    rows.setdefault(day, {})[metric] = value
        for metric, bd in breakdowns:
            _, raw = insights.paid_split(ctx.graph, conn, "fb_page_day", page_id, metric, bd, params, token)
            for item in raw or []:
                for v in item.get("values") or []:
                    day = insights_day(v.get("end_time", ""))
                    split = insights.split_paid({"values": [v]})
                    if split and start <= day <= end:
                        rows.setdefault(day, {})[f"{metric}_paid"] = split.get("paid", 0)
                        rows[day][f"{metric}_organic"] = split.get("organic", 0)
        chunk = chunk_end + timedelta(days=1)

    for day, values in rows.items():
        db.save_daily(conn, "fb_page_daily", "page_id", page_id, day.isoformat(), values, "insights")
    return len(rows)


def _save_post(ctx: Ctx, page_id: str, p: dict, token: str) -> None:
    conn = ctx.conn
    created = parse_meta(p["created_time"])
    att = (((p.get("attachments") or {}).get("data")) or [{}])[0]
    kind = PROFILE_KINDS.get(att.get("type"), "post")

    row = conn.execute("SELECT image_id FROM fb_posts WHERE post_id = ?", (p["id"],)).fetchone()
    image_id = row["image_id"] if row and row["image_id"] else ctx.images.ensure(p.get("full_picture"), "fb", p["id"])

    db.upsert(conn, "fb_posts", {
        "post_id": p["id"], "page_id": page_id,
        "created_utc": iso_utc(created), "created_local": iso_local(created, ctx.s.tz),
        "status_type": p.get("status_type"), "attachment_type": att.get("type"), "kind": kind,
        "message": p.get("message"), "permalink": p.get("permalink_url"), "picture_url": p.get("full_picture"),
        "image_id": image_id, "first_seen_utc": ctx.taken_utc, "last_seen_utc": ctx.taken_utc,
    }, ["post_id"], keep=("first_seen_utc",))
    if kind != "post":
        db.add_flag(conn, "fb_post", p["id"], local_date(created, ctx.s.tz).isoformat(), kind, KIND_LABELS[kind])

    values = {
        "comments": _summary(p.get("comments")),
        "shares": int((p.get("shares") or {}).get("count") or 0),  # there is no shares field when there are 0 shares
        "reactions": _summary(p.get("reactions_total")),
        "likes": _summary(p.get("reactions_like")),
    }
    values.update(insights.values(ctx.graph, conn, "fb_post", p["id"], ctx.s.metrics.get("fb_post") or [], token=token))
    for metric, bd in (ctx.s.breakdowns.get("fb_post") or {}).items():
        split, raw = insights.paid_split(ctx.graph, conn, "fb_post", p["id"], metric, bd, token=token)
        if split:
            values[f"{metric}_paid"] = split.get("paid", 0)
            values[f"{metric}_organic"] = split.get("organic", 0)
        elif raw:
            values[f"{metric}_{bd}_raw"] = {"raw": raw}  # unknown shape: kept for analysis
    db.save_snapshot(conn, "fb_post_snapshots", "post_id", p["id"], ctx.taken_utc, values)
