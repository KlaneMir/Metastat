"""Calculations for the UI and reports: periods, comparisons, posts, view curves.

Rules (the same in the program and in reports):
- Followers at the end of the period: our recorded state from the last day ≤ the period end (followers_count).
- Page/account views and interactions: the sum of daily insights in the period (all activity, older posts and ads too).
- Likes, comments, shares: the sum under posts published in the period, from the last reading
  before the period end (and when there is none, from the first later one).
"""
from __future__ import annotations

import json
import sqlite3
import statistics
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from metastat.config import Campaign, Settings
from metastat.fmt import date_range

# Table and column names in SQL queries come only from this constant, and values always go in as "?" parameters.
# That is why queries built with f-strings are marked "nosec B608" (bandit cannot see that these are constants).
PLATFORMS = {
    "fb": {"posts": "fb_posts", "id": "post_id", "owner": "page_id", "snap": "fb_post_snapshots",
           "daily": "fb_page_daily", "daily_id": "page_id", "views": "post_media_view", "text": "message"},
    "ig": {"posts": "ig_media", "id": "media_id", "owner": "ig_user_id", "snap": "ig_media_snapshots",
           "daily": "ig_account_daily", "daily_id": "ig_user_id", "views": "views", "text": "caption"},
}
IG_TYPES = {"IMAGE": "Photo", "VIDEO": "Video", "CAROUSEL_ALBUM": "Carousel", "REELS": "Reel"}
FB_TYPES = {"photo": "Photo", "video_inline": "Video", "video_autoplay": "Video", "share": "Link",
            "album": "Album", "profile_media": "Profile photo", "cover_photo": "Cover photo"}
CURVE_HOURS = [0.25, 1, 3, 6, 9, 12, 18, 24, 30, 36, 48, 72, 96, 120, 144, 168, 240, 336, 504, 720]


# ---------- periods ----------

@dataclass(frozen=True)
class Period:
    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def previous(self) -> "Period":
        return Period(self.start - timedelta(days=self.days), self.start - timedelta(days=1))

    def label(self) -> str:
        return date_range(self.start, self.end)

    @classmethod
    def month(cls, year: int, month: int) -> "Period":
        first = date(year, month, 1)
        nxt = date(year + (month == 12), month % 12 + 1, 1)
        return cls(first, nxt - timedelta(days=1))

    def previous_month(self) -> "Period":
        last = self.start - timedelta(days=1)
        return Period.month(last.year, last.month)


def preset(name: str, today: date) -> Period:
    if name == "7":
        return Period(today - timedelta(days=6), today)
    if name == "month":
        return Period(today.replace(day=1), today)
    if name == "prev":
        last = today.replace(day=1) - timedelta(days=1)
        return Period(last.replace(day=1), last)
    return Period(today - timedelta(days=29), today)  # "30"


def end_bound_utc(day: date, tz: ZoneInfo) -> str:
    """End of the local day as ISO UTC (readings before this moment belong to the period)."""
    return datetime.combine(day + timedelta(days=1), time(0), tzinfo=tz).astimezone(timezone.utc).isoformat()


# ---------- readings ----------

def owner_ids(conn: sqlite3.Connection, camp: Campaign) -> dict:
    ig = None
    if camp.ig_username:
        row = conn.execute("SELECT ig_user_id FROM ig_accounts WHERE lower(username) = ?", (camp.ig_username,)).fetchone()
        ig = row[0] if row else None
    return {"fb": camp.fb_page_id, "ig": ig}


def last_daily(conn, platform: str, owner: str, metric: str, day: date) -> float | None:
    p = PLATFORMS[platform]
    row = conn.execute(
        f"SELECT value FROM {p['daily']} WHERE {p['daily_id']} = ? AND metric = ? AND date <= ? AND value IS NOT NULL "  # nosec B608
        f"ORDER BY date DESC LIMIT 1", (owner, metric, day.isoformat())).fetchone()
    return row[0] if row else None


def sum_daily(conn, platform: str, owner: str, metric: str, period: Period) -> float | None:
    p = PLATFORMS[platform]
    row = conn.execute(
        f"SELECT SUM(value), COUNT(value) FROM {p['daily']} WHERE {p['daily_id']} = ? AND metric = ? AND date BETWEEN ? AND ?",  # nosec B608
        (owner, metric, period.start.isoformat(), period.end.isoformat())).fetchone()
    return row[0] if row and row[1] else None


def daily_series(conn, platform: str, owner: str, metric: str, period: Period) -> list[tuple[date, float]]:
    p = PLATFORMS[platform]
    rows = conn.execute(
        f"SELECT date, value FROM {p['daily']} WHERE {p['daily_id']} = ? AND metric = ? AND date BETWEEN ? AND ? "  # nosec B608
        f"AND value IS NOT NULL ORDER BY date", (owner, metric, period.start.isoformat(), period.end.isoformat()))
    return [(date.fromisoformat(r[0]), r[1]) for r in rows]


def snapshot_values(conn, platform: str, ids: list[str], bound_utc: str | None = None) -> dict[str, dict]:
    """{post_id: {metric: (value, raw)}} from the last reading before bound (or the first one after it)."""
    if not ids:
        return {}
    p = PLATFORMS[platform]
    bound = bound_utc or "9999"
    marks = ",".join("?" * len(ids))
    sql = (f"SELECT {p['id']} AS id, metric, value, raw, taken_utc FROM ("  # nosec B608
           f" SELECT {p['id']}, metric, value, raw, taken_utc, ROW_NUMBER() OVER ("
           f"  PARTITION BY {p['id']}, metric"
           f"  ORDER BY (taken_utc < ?) DESC, CASE WHEN taken_utc < ? THEN taken_utc END DESC, taken_utc ASC) AS rn"
           f" FROM {p['snap']} WHERE {p['id']} IN ({marks})"
           f") WHERE rn = 1")
    rows = conn.execute(sql, (bound, bound, *ids)).fetchall()
    out: dict[str, dict] = {}
    for r in rows:
        out.setdefault(r["id"], {})[r["metric"]] = (r["value"], r["raw"], r["taken_utc"])
    return out


def _v(vals: dict, metric: str) -> float | None:
    x = vals.get(metric)
    return x[0] if x else None


def _sum(values) -> float | None:
    xs = [v for v in values if v is not None]
    return sum(xs) if xs else None


# ---------- posts ----------

def post_type(platform: str, row) -> str:
    if platform == "fb":
        if row["kind"] != "post":
            return FB_TYPES.get(row["attachment_type"], "Photo change")
        return FB_TYPES.get(row["attachment_type"] or "", "Post")
    if row["media_product_type"] == "REELS":
        return "Reel"
    return IG_TYPES.get(row["media_type"] or "", row["media_type"] or "Post")


def _post_dict(platform: str, row, vals: dict, camp: Campaign | None) -> dict:
    p = PLATFORMS[platform]
    views = _v(vals, p["views"])
    d = {
        "platform": platform, "id": row[p["id"]], "owner": row[p["owner"]],
        "created_local": row["created_local"], "created_utc": row["created_utc"],
        "type": post_type(platform, row), "kind": row["kind"] if platform == "fb" else "post",
        "text": row[p["text"]] or "", "permalink": row["permalink"], "image": row["report_path"],
        "campaign": camp, "views": views,
        "likes": _v(vals, "likes"), "comments": _v(vals, "comments"), "shares": _v(vals, "shares"),
        "saves": _v(vals, "saved"), "reach": _v(vals, "reach") if platform == "ig" else _v(vals, "post_total_media_view_unique"),
        "paid": _v(vals, "post_media_view_paid"), "organic": _v(vals, "post_media_view_organic"),
        "reactions": _v(vals, "reactions") if platform == "fb" else _v(vals, "likes"),
        "interactions_ig": _v(vals, "total_interactions") if platform == "ig" else None,
        "has_data": bool(vals),
        "taken_utc": max((x[2] for x in vals.values() if len(x) > 2), default=None),  # which reading the numbers come from
    }
    return d


def posts(conn, s: Settings, camp: Campaign, platform: str, period: Period, *, include_profile: bool = True) -> list[dict]:
    owner = owner_ids(conn, camp)[platform]
    if not owner:
        return []
    p = PLATFORMS[platform]
    rows = conn.execute(
        f"SELECT x.*, i.report_path FROM {p['posts']} x LEFT JOIN images i ON i.image_id = x.image_id "  # nosec B608
        f"WHERE x.{p['owner']} = ? AND substr(x.created_local, 1, 10) BETWEEN ? AND ? ORDER BY x.created_utc DESC",
        (owner, period.start.isoformat(), period.end.isoformat())).fetchall()
    if platform == "fb" and not include_profile:
        rows = [r for r in rows if r["kind"] == "post"]
    vals = snapshot_values(conn, platform, [r[p["id"]] for r in rows], end_bound_utc(period.end, s.tz))
    return [_post_dict(platform, r, vals.get(r[p["id"]], {}), camp) for r in rows]


# ---------- campaign summary ----------

def platform_metrics(conn, s: Settings, camp: Campaign, platform: str, period: Period) -> dict | None:
    owner = owner_ids(conn, camp)[platform]
    if not owner:
        return None
    before = period.start - timedelta(days=1)
    f_end = last_daily(conn, platform, owner, "followers_count", period.end)
    f_start = last_daily(conn, platform, owner, "followers_count", before)
    ps = posts(conn, s, camp, platform, period, include_profile=False)
    m = {
        "followers": f_end,
        "followers_change": (f_end - f_start) if f_end is not None and f_start is not None else None,
        "posts": len(ps),
        "likes": _sum(x["reactions"] for x in ps) if ps else (0 if f_end is not None else None),
        "comments": _sum(x["comments"] for x in ps) if ps else (0 if f_end is not None else None),
        "shares": _sum(x["shares"] for x in ps) if ps else (0 if f_end is not None else None),
        "post_views": _sum(x["views"] for x in ps),
    }
    if platform == "fb":
        m["views"] = sum_daily(conn, "fb", owner, "page_media_view", period)
        m["views_paid"] = sum_daily(conn, "fb", owner, "page_media_view_paid", period)
        m["interactions"] = sum_daily(conn, "fb", owner, "page_post_engagements", period)
        m["page_reactions"] = sum_daily(conn, "fb", owner, "page_actions_post_reactions_total", period)
    else:
        m["views"] = sum_daily(conn, "ig", owner, "views", period)
        m["views_paid"] = None
        m["interactions"] = sum_daily(conn, "ig", owner, "total_interactions", period)
        m["saves"] = _sum(x["saves"] for x in ps)
    return m


def change(cur, prev) -> dict | None:
    """Change against the previous period: {'abs', 'pct', 'dir'} or None when there is no data."""
    if cur is None or prev is None:
        return None
    diff = cur - prev
    return {"abs": diff, "pct": (diff / prev * 100) if prev else None, "dir": "up" if diff > 0 else "down" if diff < 0 else "same"}


COMPARED = ("views", "posts", "likes", "comments", "shares", "interactions")


def summary(conn, s: Settings, period: Period, prev: Period | None = None,
            campaigns: list[Campaign] | None = None) -> list[dict]:
    prev = prev or period.previous()
    out = []
    for camp in campaigns or s.campaigns:
        row = {"campaign": camp, "platforms": {}, "prev": {}}
        for platform in ("fb", "ig"):
            if (platform == "fb" and not camp.fb_page_id) or (platform == "ig" and not camp.ig_username):
                continue
            cur = platform_metrics(conn, s, camp, platform, period)
            if cur is None:
                row["platforms"][platform] = None  # configured, but not synced yet / not visible
                continue
            old = platform_metrics(conn, s, camp, platform, prev) or {}
            row["prev"][platform] = old
            cur["delta"] = {k: change(cur.get(k), old.get(k)) for k in COMPARED}
            cur["delta"]["followers_change"] = change(cur.get("followers_change"), old.get("followers_change"))
            row["platforms"][platform] = cur
        out.append(row)
    return out


def totals(rows: list[dict], platform: str) -> dict:
    ms = [r["platforms"].get(platform) for r in rows if r["platforms"].get(platform)]
    keys = ("followers", "followers_change", "views", "posts", "likes", "comments", "shares", "interactions")
    return {k: _sum(m.get(k) for m in ms) for k in keys}


def flags(conn, s: Settings, camp: Campaign | None, period: Period, *, informational: bool = False) -> list:
    owners = []
    for c in ([camp] if camp else s.campaigns):
        ids = owner_ids(conn, c)
        owners += [x for x in (ids["fb"], ids["ig"], c.id) if x]
    if not owners:
        return []
    marks = ",".join("?" * len(owners))
    kinds = "" if informational else "AND kind NOT IN ('profile_photo', 'cover_photo')"
    return conn.execute(
        f"SELECT * FROM flags WHERE object_id IN ({marks}) AND date BETWEEN ? AND ? {kinds} ORDER BY date DESC",  # nosec B608
        (*owners, period.start.isoformat(), period.end.isoformat())).fetchall()


def top_posts(conn, s: Settings, period: Period, limit: int = 6) -> list[dict]:
    allp = []
    for camp in s.campaigns:
        for platform in ("fb", "ig"):
            allp += [p for p in posts(conn, s, camp, platform, period, include_profile=False) if p["views"]]
    return sorted(allp, key=lambda p: p["views"], reverse=True)[:limit]


# ---------- a single post ----------

def _hours(created_utc: str, taken_utc: str) -> float:
    return (datetime.fromisoformat(taken_utc) - datetime.fromisoformat(created_utc)).total_seconds() / 3600


def curve(conn, platform: str, post_id: str, created_utc: str, metric: str) -> list[tuple[float, float]]:
    p = PLATFORMS[platform]
    rows = conn.execute(f"SELECT taken_utc, value FROM {p['snap']} WHERE {p['id']} = ? AND metric = ? AND value IS NOT NULL "  # nosec B608
                        f"ORDER BY taken_utc", (post_id, metric))
    return [(max(_hours(created_utc, r[0]), 0.01), r[1]) for r in rows]


def typical_curve(conn, platform: str, owner: str, exclude: str, metric: str, min_posts: int = 3) -> list[tuple[float, float]]:
    """Median of the curves of the profile's other posts (like "typical views" in Business Suite)."""
    p = PLATFORMS[platform]
    only_posts = "AND x.kind = 'post'" if platform == "fb" else ""
    rows = conn.execute(
        f"SELECT x.{p['id']} AS id, x.created_utc, s.taken_utc, s.value FROM {p['posts']} x "  # nosec B608
        f"JOIN {p['snap']} s ON s.{p['id']} = x.{p['id']} "
        f"WHERE x.{p['owner']} = ? AND x.{p['id']} != ? AND s.metric = ? AND s.value IS NOT NULL "
        f"{only_posts} ORDER BY s.taken_utc",
        (owner, exclude, metric)).fetchall()
    per_post: dict[str, list[tuple[float, float]]] = {}
    for r in rows:
        per_post.setdefault(r["id"], []).append((_hours(r["created_utc"], r["taken_utc"]), r["value"]))
    out = []
    for b in CURVE_HOURS:
        vals = []
        for pts in per_post.values():
            if pts[-1][0] < b:  # post not observed for that long
                continue
            before = [v for h, v in pts if h <= b]
            if before:
                vals.append(before[-1])
        if len(vals) >= min_posts:
            # The set of posts differs between points (young posts have not reached the later hours),
            # so make sure the cumulative curve never goes down.
            out.append((b, max(statistics.median(vals), out[-1][1] if out else 0)))
    return out


def snapshot_history(conn, platform: str, post_id: str, metrics: list[str]) -> list[dict]:
    p = PLATFORMS[platform]
    marks = ",".join("?" * len(metrics))
    rows = conn.execute(f"SELECT taken_utc, metric, value FROM {p['snap']} WHERE {p['id']} = ? AND metric IN ({marks}) "  # nosec B608
                        f"ORDER BY taken_utc DESC", (post_id, *metrics))
    hist: dict[str, dict] = {}
    for r in rows:
        hist.setdefault(r["taken_utc"], {"taken_utc": r["taken_utc"]})[r["metric"]] = r["value"]
    return list(hist.values())


def post_detail(conn, s: Settings, platform: str, post_id: str) -> dict | None:
    p = PLATFORMS[platform]
    row = conn.execute(f"SELECT x.*, i.report_path FROM {p['posts']} x LEFT JOIN images i ON i.image_id = x.image_id "  # nosec B608
                       f"WHERE x.{p['id']} = ?", (post_id,)).fetchone()
    if not row:
        return None
    owner = row[p["owner"]]
    camp = None
    for c in s.campaigns:
        if owner_ids(conn, c)[platform] == owner:
            camp = c
            break
    if platform == "fb":
        prof = conn.execute("SELECT name FROM fb_pages WHERE page_id = ?", (owner,)).fetchone()
    else:
        prof = conn.execute("SELECT coalesce(name, username) FROM ig_accounts WHERE ig_user_id = ?", (owner,)).fetchone()
    vals = snapshot_values(conn, platform, [post_id]).get(post_id, {})
    d = _post_dict(platform, row, vals, camp)
    d["profile"] = prof[0] if prof else (camp.name if camp else "")
    d["clicks"] = None
    d["by_type"] = {}
    if platform == "fb":
        raw = (vals.get("post_clicks_by_type") or (None, None))[1]
        if raw:
            clicks = json.loads(raw)
            d["clicks"] = clicks.get("link clicks", 0)
        raw = (vals.get("post_reactions_by_type_total") or (None, None))[1]
        if raw:
            d["by_type"] = {k: v for k, v in sorted(json.loads(raw).items(), key=lambda kv: -kv[1]) if v}
        d["viewers"] = _v(vals, "post_total_media_view_unique")
    d["interactions"] = _sum([d["reactions"], d["comments"], d["shares"]] + ([d["saves"]] if platform == "ig" else []))
    if platform == "ig":
        d["interactions"] = _v(vals, "total_interactions") or d["interactions"]
    d["curve"] = curve(conn, platform, post_id, row["created_utc"], p["views"])
    d["typical"] = typical_curve(conn, platform, owner, post_id, p["views"])
    hist_metrics = [p["views"], "likes", "reactions", "comments", "shares"] + (["saved"] if platform == "ig" else [])
    d["history"] = snapshot_history(conn, platform, post_id, hist_metrics)
    return d
