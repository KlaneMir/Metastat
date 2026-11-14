"""Instagram account sync: account state and insights (daily), posts, snapshots, images."""
from __future__ import annotations

import logging
from datetime import date, timedelta

from metastat import db, flags, insights
from metastat.config import Campaign
from metastat.context import Ctx
from metastat.graph import GraphError
from metastat.timeutil import day_start_unix, insights_day, iso_local, iso_utc, parse_meta

log = logging.getLogger(__name__)

ACCOUNT_FIELDS = "username,name,followers_count,follows_count,media_count"
MEDIA_FIELDS = ("id,caption,media_type,media_product_type,media_url,thumbnail_url,permalink,timestamp,"
                "like_count,comments_count,children{media_type,media_url,thumbnail_url}")
TYPE_LABELS = {"IMAGE": "Photo", "VIDEO": "Video", "CAROUSEL_ALBUM": "Carousel"}


class IgNotFound(GraphError):
    pass


def resolve(ctx: Ctx, camp: Campaign) -> str:
    row = ctx.conn.execute("SELECT ig_user_id FROM ig_accounts WHERE lower(username) = ?", (camp.ig_username,)).fetchone()
    if row:
        return row["ig_user_id"]
    found = ctx.ig_directory().get(camp.ig_username)
    if not found:
        raise IgNotFound(
            f"The IG account @{camp.ig_username} is not visible to the token. It must be a business or creator "
            f"account linked to a Facebook page, and that page must be assigned to the system user.")
    return found["id"]


def picture_url(m: dict) -> str | None:
    """Video → thumbnail, carousel → first image from children, photo → media_url."""
    if m.get("media_type") == "VIDEO":
        return m.get("thumbnail_url") or m.get("media_url")
    if m.get("media_type") == "CAROUSEL_ALBUM":
        kids = ((m.get("children") or {}).get("data")) or []
        if kids:
            k = kids[0]
            return k.get("media_url") if k.get("media_type") == "IMAGE" else (k.get("thumbnail_url") or k.get("media_url"))
    return m.get("media_url") or m.get("thumbnail_url")


def sync_account(ctx: Ctx, camp: Campaign, fresh: bool) -> dict:
    ig_id = resolve(ctx, camp)  # IgNotFound → flag saved in sync.run
    out = {"media": 0}

    if not fresh:
        info = ctx.graph.get(ig_id, {"fields": ACCOUNT_FIELDS})
        page = (ctx._ig_directory or {}).get(camp.ig_username, {}).get("page_id")
        db.upsert(ctx.conn, "ig_accounts", {
            "ig_user_id": ig_id, "campaign_id": camp.id, "username": info.get("username"),
            "name": info.get("name"), "page_id": page or camp.fb_page_id, "updated_utc": ctx.taken_utc,
        }, ["ig_user_id"])
        db.save_daily(ctx.conn, "ig_account_daily", "ig_user_id", ig_id, ctx.today.isoformat(),
                      {k: info.get(k) for k in ("followers_count", "follows_count", "media_count")}, "field")
        out["followers"] = info.get("followers_count")
        out["days"] = _account_daily(ctx, ig_id)
        flags.check_followers(ctx.conn, ctx.s.flags, table="ig_account_daily", id_col="ig_user_id",
                              obj_id=ig_id, metric="followers_count", scope="ig_account")

    hours = ctx.s.fresh_hours if fresh else ctx.s.snapshot_window_days * 24
    since = ctx.now - timedelta(hours=hours)
    body = ctx.graph.get(f"{ig_id}/media", {"fields": MEDIA_FIELDS, "limit": 50})
    while True:
        any_recent = False
        for m in body.get("data") or []:
            created = parse_meta(m["timestamp"])
            if created >= since:
                any_recent = True
                _save_media(ctx, ig_id, m, created)
                out["media"] += 1
        # Media come newest first, but pinned posts can be old: stop only at a page without recent ones.
        nxt = (body.get("paging") or {}).get("next")
        if not any_recent or not nxt:
            break
        body = ctx.graph.get(nxt)
    return out


def _account_daily(ctx: Ctx, ig_id: str) -> int:
    conn = ctx.conn
    tz = ctx.s.tz
    yesterday = ctx.today - timedelta(days=1)
    last = conn.execute("SELECT MAX(date) FROM ig_account_daily WHERE ig_user_id = ? AND source = 'insights'",
                        (ig_id,)).fetchone()[0]
    # Instagram gives only about 30 days of history; the last 2 days are refreshed because Meta still adds to them.
    start = date.fromisoformat(last) - timedelta(days=1) if last else ctx.today - timedelta(days=29)
    metrics = ctx.s.metrics.get("ig_account_day") or []
    n = 0
    day = start
    while day <= yesterday:
        params = {"period": "day", "metric_type": "total_value",
                  "since": day_start_unix(day, tz), "until": day_start_unix(day + timedelta(days=1), tz)}
        vals = insights.values(ctx.graph, conn, "ig_account_day", ig_id, metrics, params)
        if vals:
            db.save_daily(conn, "ig_account_daily", "ig_user_id", ig_id, day.isoformat(), vals, "insights")
            n += 1
        day += timedelta(days=1)

    # Daily follower series according to Meta (only about 30 days back). Our own state is stored separately.
    ser = insights.series(ctx.graph, conn, "ig_account_series", ig_id, ["follower_count"],
                          {"period": "day", "since": day_start_unix(ctx.today - timedelta(days=29), tz),
                           "until": day_start_unix(ctx.today, tz)})
    for end_time, value in ser.get("follower_count", []):
        db.save_daily(conn, "ig_account_daily", "ig_user_id", ig_id, insights_day(end_time).isoformat(),
                      {"follower_count": value}, "insights")
    return n


def _save_media(ctx: Ctx, ig_id: str, m: dict, created) -> None:
    conn = ctx.conn
    row = conn.execute("SELECT image_id FROM ig_media WHERE media_id = ?", (m["id"],)).fetchone()
    image_id = row["image_id"] if row and row["image_id"] else ctx.images.ensure(picture_url(m), "ig", m["id"])
    db.upsert(conn, "ig_media", {
        "media_id": m["id"], "ig_user_id": ig_id,
        "created_utc": iso_utc(created), "created_local": iso_local(created, ctx.s.tz),
        "media_type": m.get("media_type"), "media_product_type": m.get("media_product_type"),
        "caption": m.get("caption"), "permalink": m.get("permalink"), "picture_url": picture_url(m),
        "image_id": image_id, "first_seen_utc": ctx.taken_utc, "last_seen_utc": ctx.taken_utc,
    }, ["media_id"], keep=("first_seen_utc",))

    scope = f"ig_media:{m.get('media_product_type') or 'FEED'}"
    values = insights.values(ctx.graph, conn, scope, m["id"], ctx.s.metrics.get("ig_media") or [])
    # Counters from the post fields are always available; insights fill in the rest.
    if m.get("like_count") is not None:
        values["likes"] = m["like_count"]
    if m.get("comments_count") is not None:
        values["comments"] = m["comments_count"]
    db.save_snapshot(conn, "ig_media_snapshots", "media_id", m["id"], ctx.taken_utc, values)
