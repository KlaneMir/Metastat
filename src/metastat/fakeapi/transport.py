"""Simulator responses shaped like the Meta Graph API (the endpoints the program uses) and the image CDN.

The simulator has its own clock (CLOCK). In normal work it is "now"; the `metastat fake history` command
moves it into the past to build a year of readings.
"""
from __future__ import annotations

import io
from datetime import date, datetime, time, timedelta, timezone

import httpx
from PIL import Image, ImageDraw

from metastat.fakeapi import world
from metastat.fakeapi.world import h

FAKE_BASE = "https://graph.fake.metastat.test/"
CDN_HOST = "cdn.fake.metastat.test"
UNSUPPORTED = {"page_video_views", "post_video_views", "follows_and_unfollows"}  # "retired" metrics
PERMISSIONS = ["pages_show_list", "pages_read_engagement", "pages_read_user_content", "read_insights",
               "instagram_basic", "instagram_manage_insights", "business_management"]
PAGE_SIZE = 50


class Clock:
    def __init__(self):
        self.value: datetime | None = None

    def now(self) -> datetime:
        return self.value or datetime.now(timezone.utc)


CLOCK = Clock()


def transport() -> httpx.MockTransport:
    return httpx.MockTransport(handle)


# ---------- helpers ----------

def ok(data) -> httpx.Response:
    return httpx.Response(200, json=data)


def err(code: int, message: str, status: int = 400, subcode: int | None = None) -> httpx.Response:
    e = {"message": message, "type": "OAuthException", "code": code, "fbtrace_id": "FAKE"}
    if subcode:
        e["error_subcode"] = subcode
    return httpx.Response(status, json={"error": e})


def meta_time(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000")


def parse_when(v: str | None) -> datetime | None:
    if not v:
        return None
    if v.isdigit():
        return datetime.fromtimestamp(int(v), timezone.utc)
    return datetime.combine(date.fromisoformat(v[:10]), time(0), tzinfo=timezone.utc)


def img_url(asset: str) -> str:
    return f"https://{CDN_HOST}/v/t39/{asset}.jpg?oe={h(asset) % 99999999:08X}&_nc_ht=fake"


def page(items: list, q: dict, url: httpx.URL) -> dict:
    """Pagination as in the Graph API: an `after` cursor, a `paging.next` link with the full URL."""
    start = int(q.get("after") or 0)
    limit = min(int(q.get("limit") or 25), 100)
    chunk = items[start:start + limit]
    out = {"data": chunk}
    if start + limit < len(items):
        out["paging"] = {"cursors": {"after": str(start + limit)},
                         "next": str(url.copy_merge_params({"after": str(start + limit)}))}
    return out


def metrics_or_error(q: dict) -> list[str] | httpx.Response:
    names = [m for m in (q.get("metric") or "").split(",") if m]
    bad = [m for m in names if m in UNSUPPORTED]
    if bad:
        return err(100, f"(#100) The value must be a valid insights metric: {bad[0]}")
    return names


# ---------- request handling ----------

def handle(request: httpx.Request) -> httpx.Response:
    url = request.url
    if url.host == CDN_HOST:
        return image(url.path.rsplit("/", 1)[-1].removesuffix(".jpg"))
    q = dict(url.params)
    auth = request.headers.get("authorization", "")
    acc = world.by_token(auth[7:] if auth.lower().startswith("bearer ") else q.get("access_token"))
    if not acc:
        return err(190, "Error validating access token: The session is invalid.", 401, 467)
    parts = url.path.strip("/").split("/")
    if parts and parts[0].startswith("v") and parts[0][1:2].isdigit():
        parts = parts[1:]
    now = CLOCK.now()
    index = _index(acc.number)

    if parts == ["me"]:
        return ok({"id": f"sys{acc.number:02d}", "name": acc.name})
    if parts == ["me", "permissions"]:
        return ok({"data": [{"permission": p, "status": "granted"} for p in PERMISSIONS]})
    if parts == ["me", "accounts"]:
        data = []
        for c in acc.campaigns:
            row = {"id": c.page_id, "name": c.name}
            if c.ig_id and c.ig_visible:
                row["instagram_business_account"] = {"id": c.ig_id, "username": c.ig_username}
            data.append(row)
        return ok(page(data, q, url))

    obj = index.get(parts[0]) if parts else None
    if obj is None:
        return err(100, f"Unsupported get request. Object with ID '{parts[0] if parts else ''}' does not exist "
                        f"or cannot be loaded due to missing permissions.", subcode=33)
    kind, c, p = obj
    tail = parts[1:]
    if kind == "page":
        if not tail:
            if q.get("fields") == "access_token":
                return ok({"id": c.page_id, "access_token": f"pt-{c.page_id}"})
            data = {"id": c.page_id, "name": c.name, "username": world.slug(c.name)[:30],
                    "link": f"https://www.facebook.com/{c.page_id}", "followers_count": c.fb_followers(now.date())}
            if c.ig_id and c.ig_visible:
                data["instagram_business_account"] = {"id": c.ig_id, "username": c.ig_username}
            return ok(data)
        if tail == ["insights"]:
            return page_insights(c, q, now)
        if tail in (["posts"], ["published_posts"]):
            return posts(c, q, url, now)
    if kind == "post" and tail == ["insights"]:
        return post_insights(p, q, now)
    if kind == "ig":
        if not c.ig_visible:
            return err(10, "(#10) Application does not have permission for this action")
        if not tail:
            media = [x for x in c.posts if x.ig_id and x.created <= now]
            return ok({"id": c.ig_id, "username": c.ig_username, "name": c.name,
                       "followers_count": c.ig_followers(now.date()), "follows_count": 12, "media_count": 20 + len(media)})
        if tail == ["insights"]:
            return ig_insights(c, q, now)
        if tail == ["media"]:
            return ig_media(c, q, url, now)
    if kind == "media" and tail == ["insights"]:
        return media_insights(p, q, now)
    return err(100, f"Unsupported get request: {'/'.join(parts)}")


def _index(number: int, _cache: dict = {}) -> dict:
    if number not in _cache:
        idx = {}
        for c in world.account(number).campaigns:
            idx[c.page_id] = ("page", c, None)
            if c.ig_id:
                idx[c.ig_id] = ("ig", c, None)
            for p in c.posts:
                idx[p.fb_id] = ("post", c, p)
                if p.ig_id:
                    idx[p.ig_id] = ("media", c, p)
        _cache[number] = idx
    return _cache[number]


# ---------- Facebook ----------

def page_day(c: world.Campaign, metric: str, d: date):
    if not c.active(d) and metric not in ("page_follows",):
        base = 0
    else:
        base = 1
    v = 3000 + h(c.page_id, d, "v") % 7000 if base else 40 + h(c.page_id, d, "v") % 200
    if metric == "page_follows":
        return c.meta_followers(d)
    if metric == "page_daily_follows_unique":
        return int(c.fb_growth) + h(c.page_id, d, "f") % 3
    if metric == "page_daily_unfollows_unique":
        return h(c.page_id, d, "u") % 2
    if metric == "page_media_view":
        return v
    if metric == "page_total_media_view_unique":
        return int(v * 0.82)
    if metric == "page_post_engagements":
        return (20 + h(c.page_id, d, "e") % 180) if base else h(c.page_id, d, "e") % 5
    if metric == "page_actions_post_reactions_total":
        return {"like": h(c.page_id, d, "l") % 12 * base, "love": h(c.page_id, d, "o") % 3 * base}
    return 0


def page_insights(c: world.Campaign, q: dict, now: datetime) -> httpx.Response:
    names = metrics_or_error(q)
    if isinstance(names, httpx.Response):
        return names
    since, until = parse_when(q.get("since")), parse_when(q.get("until"))
    if not since or not until or (until - since).days > 93:
        return err(100, "(#100) The since and until parameters must be no more than 93 days apart")
    days = []
    d = since.date()
    while d < until.date() and d < now.date():
        days.append(d)
        d += timedelta(days=1)
    data = []
    for m in names:
        values = []
        for d in days:
            end_time = f"{(d + timedelta(days=1)).isoformat()}T08:00:00+0000"
            v = page_day(c, m, d)
            if q.get("breakdown") == "is_from_ads" and m == "page_media_view":
                paid = int(v * 0.96) if c.active(d) else 0
                v = {"1": paid, "0": v - paid}
            values.append({"value": v, "end_time": end_time})
        data.append({"name": m, "period": "day", "values": values, "title": m, "id": f"{c.page_id}/insights/{m}/day"})
    return ok({"data": data})


def _post_now(p: world.Post, now: datetime) -> dict:
    s = p.share(now)
    likes = round(p.likes * s)
    return {"views": round(p.views * s), "likes": likes, "reactions": likes + round(p.love * s),
            "love": round(p.love * s), "comments": round(p.comments * s), "shares": round(p.shares * s),
            "clicks": round(p.clicks * s)}


def posts(c: world.Campaign, q: dict, url: httpx.URL, now: datetime) -> httpx.Response:
    since, until = parse_when(q.get("since")), parse_when(q.get("until"))
    items = []
    for p in sorted(c.posts, key=lambda x: x.created, reverse=True):
        if p.created > now or (since and p.created < since) or (until and p.created >= until):
            continue
        v = _post_now(p, now)
        att = {"post": "photo", "cover_photo": "cover_photo", "profile_media": "profile_media"}[p.kind]
        if p.kind == "post" and p.media_type in ("VIDEO", "REELS"):
            att = "video_inline"
        row = {
            "id": p.fb_id, "created_time": meta_time(p.created), "permalink_url": f"https://www.facebook.com/{p.fb_id}",
            "full_picture": img_url(p.asset), "status_type": "added_video" if att == "video_inline" else "added_photos",
            "attachments": {"data": [{"type": att, "media_type": "video" if att == "video_inline" else "photo"}]},
            "comments": {"data": [], "summary": {"order": "ranked", "total_count": v["comments"], "can_comment": True}},
            "reactions_total": {"data": [], "summary": {"total_count": v["reactions"]}},
            "reactions_like": {"data": [], "summary": {"total_count": v["likes"]}},
        }
        if p.text:
            row["message"] = p.text
        if v["shares"]:
            row["shares"] = {"count": v["shares"]}   # with 0 shares Meta does not return the field
        items.append(row)
    return ok(page(items, q, url))


def post_insights(p: world.Post, q: dict, now: datetime) -> httpx.Response:
    names = metrics_or_error(q)
    if isinstance(names, httpx.Response):
        return names
    v = _post_now(p, now)
    data = []
    for m in names:
        if q.get("breakdown") == "is_from_ads" and m == "post_media_view":
            paid = round(v["views"] * p.paid)
            data.append({"name": m, "period": "lifetime", "total_value": {"value": v["views"], "breakdowns": [
                {"dimension_keys": ["is_from_ads"], "results": [
                    {"dimension_values": ["1"], "value": paid}, {"dimension_values": ["0"], "value": v["views"] - paid}]}]}})
            continue
        value = {"post_media_view": v["views"], "post_total_media_view_unique": round(v["views"] * 0.88),
                 "post_reactions_by_type_total": {"like": v["likes"], "love": v["love"]},
                 "post_clicks_by_type": {"link clicks": v["clicks"], "other clicks": v["clicks"] * 3}}.get(m, 0)
        data.append({"name": m, "period": "lifetime", "values": [{"value": value}]})
    return ok({"data": data})


# ---------- Instagram ----------

def ig_insights(c: world.Campaign, q: dict, now: datetime) -> httpx.Response:
    names = metrics_or_error(q)
    if isinstance(names, httpx.Response):
        return names
    since, until = parse_when(q.get("since")), parse_when(q.get("until"))
    if names == ["follower_count"]:
        if not since or since < now - timedelta(days=31):
            return err(100, "(#100) follower_count only supports the last 30 days")
        values = []
        d = since.date()
        while until and d < until.date() and d < now.date():
            values.append({"value": int(c.ig_growth) + h(c.ig_id, d) % 3,
                           "end_time": f"{(d + timedelta(days=1)).isoformat()}T07:00:00+0000"})
            d += timedelta(days=1)
        return ok({"data": [{"name": "follower_count", "period": "day", "values": values}]})
    d = since.date() if since else now.date()
    active = c.active(d)
    base = {"views": 60 + h(c.ig_id, d, "v") % 400, "reach": 30 + h(c.ig_id, d, "r") % 200,
            "accounts_engaged": h(c.ig_id, d, "a") % 25, "total_interactions": h(c.ig_id, d, "t") % 30,
            "likes": h(c.ig_id, d, "l") % 20, "comments": h(c.ig_id, d, "c") % 3, "shares": h(c.ig_id, d, "s") % 4,
            "saves": h(c.ig_id, d, "sv") % 5}
    return ok({"data": [{"name": m, "period": "day", "total_value": {"value": base.get(m, 0) if active else base.get(m, 0) // 10}}
                        for m in names]})


def _media_now(p: world.Post, now: datetime) -> dict:
    s = p.share(now, ig=True)
    return {"views": round(p.ig_views * s), "reach": round(p.ig_reach * s), "likes": round(p.ig_likes * s),
            "comments": round(p.ig_comments * s), "shares": round(p.ig_shares * s), "saved": round(p.ig_saves * s)}


def ig_media(c: world.Campaign, q: dict, url: httpx.URL, now: datetime) -> httpx.Response:
    items = []
    for p in sorted((x for x in c.posts if x.ig_id and x.created <= now), key=lambda x: x.created, reverse=True):
        v = _media_now(p, now)
        reel = p.media_type == "REELS"
        row = {"id": p.ig_id, "timestamp": meta_time(p.created + timedelta(minutes=1)), "caption": p.text,
               "media_type": "VIDEO" if reel else p.media_type, "media_product_type": "REELS" if reel else "FEED",
               "permalink": f"https://www.instagram.com/p/{p.ig_id}/", "like_count": v["likes"], "comments_count": v["comments"]}
        if p.media_type in ("VIDEO", "REELS"):
            row["media_url"] = f"https://{CDN_HOST}/v/video/{p.asset}.mp4"
            row["thumbnail_url"] = img_url(p.asset)
        elif p.media_type == "CAROUSEL_ALBUM":
            row["media_url"] = img_url(p.asset)
            row["children"] = {"data": [{"media_type": "IMAGE", "media_url": img_url(p.asset)},
                                        {"media_type": "IMAGE", "media_url": img_url(p.asset2)}]}
        else:
            row["media_url"] = img_url(p.asset)
        items.append(row)
    return ok(page(items, q, url))


def media_insights(p: world.Post, q: dict, now: datetime) -> httpx.Response:
    names = metrics_or_error(q)
    if isinstance(names, httpx.Response):
        return names
    v = _media_now(p, now)
    v["total_interactions"] = v["likes"] + v["comments"] + v["shares"] + v["saved"]
    return ok({"data": [{"name": m, "period": "lifetime", "values": [{"value": v.get(m, 0)}]} for m in names]})


# ---------- images ----------

def _products(_cache: dict = {}) -> dict[str, str]:
    """page_id → the campaign's product (the start of its name, e.g. "Poultry", "Rapeseed oil")."""
    if not _cache:
        for n in range(1, world.ACCOUNTS + 1):
            for c in world.account(n).campaigns:
                _cache[c.page_id] = world.product_of(c.name)
    return _cache


PALETTE = [((214, 170, 120), (120, 70, 40)), ((150, 180, 200), (40, 70, 110)), ((200, 120, 100), (110, 40, 30)),
           ((150, 190, 140), (40, 90, 60)), ((220, 200, 120), (120, 100, 30)), ((190, 150, 190), (80, 40, 90)),
           ((230, 225, 210), (90, 80, 60)), ((120, 160, 150), (20, 60, 55))]


def image(asset: str) -> httpx.Response:
    """Post image (720×900 JPG), always the same for the same asset.

    When stock photos were downloaded (`metastat fake photos`), it is a Wikimedia Commons photo with a
    "TEST" watermark; otherwise (and always in demo mode) a placeholder made of shapes with a "DEMO" label.
    """
    from metastat import paths
    from metastat.fakeapi import stock
    photos = [] if paths.demo() else stock.pool()
    n = h(asset)
    if photos:
        page_id, post_no = (asset.split("_") + ["", ""])[:2]
        product = _products().get(page_id)
        matching = [x for x in photos if x.get("product") == product] or photos   # a photo matching the campaign's product
        body = stock.watermarked(matching[n % len(matching)], f"post {post_no}")
        return httpx.Response(200, content=body, headers={"content-type": "image/jpeg"})
    bg, fg = PALETTE[n % len(PALETTE)]
    im = Image.new("RGB", (720, 900), bg)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 580, 720, 900], fill=tuple(int(x * 0.8) for x in bg))
    r = 90 + n % 120
    cx, cy = 180 + n % 360, 220 + (n // 7) % 260
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fg)
    d.rectangle([54, 650, 666, 690], fill=tuple(min(255, x + 35) for x in bg))
    d.rectangle([54, 715, 470, 742], fill=tuple(min(255, x + 35) for x in bg))
    try:  # a "DEMO" label: it is obvious right away that this is a placeholder, not a post image
        from PIL import ImageFont
        font = ImageFont.load_default(size=110)
        d.text((360, 800), "DEMO", fill=(255, 255, 255), font=font, anchor="mm")
    except (OSError, TypeError, ValueError):  # older Pillow without a scalable font: no label
        pass
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=82)
    return httpx.Response(200, content=buf.getvalue(), headers={"content-type": "image/jpeg"})
