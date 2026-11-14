"""Simulated Meta Graph API and CDN (httpx.MockTransport). The data is test data."""
from __future__ import annotations

import io
from datetime import date, timedelta

import httpx
from PIL import Image

PAGE = "111"
IG = "IG1"
POST_PHOTO = "111_1"
POST_COVER = "111_2"
MEDIA_NEW = "M1"
MEDIA_OLD = "M2"
SHARED_IMG = "https://scontent.example.net/v/t39/555_shared_n.jpg?oe=ABC&_nc=1"
COVER_IMG = "https://scontent.example.net/v/t39/777_cover_n.jpg?oe=DEF"
IG_SECOND_IMG = "https://scontent.cdninstagram.example/v/t51/888_other_n.jpg?oe=GHI"

UNKNOWN_METRICS = {"page_video_views", "post_video_views"}  # "retired" by Meta in the simulation


def jpeg(w=1200, h=900, color=(200, 80, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "JPEG")
    return buf.getvalue()


def err(code, message, subcode=None, status=400):
    e = {"message": message, "type": "OAuthException", "code": code}
    if subcode:
        e["error_subcode"] = subcode
    return httpx.Response(status, json={"error": e})


class FakeMeta:
    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.fail_first: list[httpx.Response] = []  # responses returned before the normal ones (e.g. rate limit, token)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail_first:
            return self.fail_first.pop(0)
        url = request.url
        if "scontent" in url.host:
            if "777_cover" in url.path:
                return httpx.Response(200, content=jpeg(600, 400, (10, 10, 10)), headers={"content-type": "image/jpeg"})
            if "888_other" in url.path:
                return httpx.Response(200, content=jpeg(1080, 1350, (0, 120, 200)), headers={"content-type": "image/jpeg"})
            return httpx.Response(200, content=jpeg(), headers={"content-type": "image/jpeg"})

        parts = url.path.strip("/").split("/")[1:]  # without the version
        q = dict(url.params)
        path = "/".join(parts)

        if path == "me/accounts":
            return httpx.Response(200, json={"data": [
                {"id": PAGE, "name": "Test page", "instagram_business_account": {"id": IG, "username": "test_account"}}]})
        if path == PAGE and q.get("fields") == "access_token":
            return httpx.Response(200, json={"id": PAGE, "access_token": "PAGE_TOKEN"})
        if path == PAGE:
            return httpx.Response(200, json={"id": PAGE, "name": "Test page", "username": "testpage",
                                             "followers_count": 1000,
                                             "instagram_business_account": {"id": IG, "username": "test_account"}})
        if path == f"{PAGE}/insights":
            return self.page_insights(q)
        if path == f"{PAGE}/posts":
            assert request.headers["authorization"] == "Bearer PAGE_TOKEN"   # page token in the header
            assert "access_token" not in q                                      # never in the URL
            return httpx.Response(200, json={"data": [
                {"id": POST_PHOTO, "created_time": "2026-11-10T09:30:00+0000", "message": "Post with a photo 🍗",
                 "permalink_url": "https://facebook.example/p1", "full_picture": SHARED_IMG, "status_type": "added_photos",
                 "attachments": {"data": [{"type": "photo"}]},
                 "comments": {"data": [], "summary": {"total_count": 3}},
                 "reactions_total": {"data": [], "summary": {"total_count": 12}},
                 "reactions_like": {"data": [], "summary": {"total_count": 10}}},  # no shares field → 0
                {"id": POST_COVER, "created_time": "2026-11-09T22:30:00+0000", "message": None,
                 "permalink_url": "https://facebook.example/p2", "full_picture": COVER_IMG, "status_type": "added_photos",
                 "attachments": {"data": [{"type": "cover_photo"}]}, "shares": {"count": 2},
                 "comments": {"data": [], "summary": {"total_count": 0}},
                 "reactions_total": {"data": [], "summary": {"total_count": 5}},
                 "reactions_like": {"data": [], "summary": {"total_count": 5}}},
            ]})
        if path in (f"{POST_PHOTO}/insights", f"{POST_COVER}/insights"):
            return self.post_insights(q)
        if path == IG and "followers_count" in q.get("fields", ""):
            return httpx.Response(200, json={"id": IG, "username": "test_account", "name": "Account",
                                             "followers_count": 500, "follows_count": 10, "media_count": 40})
        if path == f"{IG}/insights":
            if q.get("metric") == "follower_count":
                return httpx.Response(200, json={"data": [{"name": "follower_count", "period": "day", "values": [
                    {"value": 4, "end_time": "2026-11-11T08:00:00+0000"}]}]})
            return httpx.Response(200, json={"data": [
                {"name": m, "period": "day", "total_value": {"value": 7}} for m in q["metric"].split(",")]})
        if path == f"{IG}/media" and q.get("after"):
            # second page: only old posts → the sync stops browsing
            return httpx.Response(200, json={"data": [
                {"id": "M3", "timestamp": "2024-12-01T10:00:00+0000", "media_type": "IMAGE", "media_product_type": "FEED",
                 "media_url": IG_SECOND_IMG}]})
        if path == f"{IG}/media":
            return httpx.Response(200, json={"data": [
                {"id": MEDIA_NEW, "timestamp": "2026-11-10T09:31:00+0000", "caption": "Carousel", "media_type": "CAROUSEL_ALBUM",
                 "media_product_type": "FEED", "permalink": "https://instagram.example/m1", "like_count": 8, "comments_count": 1,
                 "children": {"data": [{"media_type": "IMAGE", "media_url": SHARED_IMG.replace("oe=ABC", "oe=XYZ")},
                                       {"media_type": "IMAGE", "media_url": IG_SECOND_IMG}]}},
                {"id": MEDIA_OLD, "timestamp": "2025-01-01T10:00:00+0000", "caption": "Old", "media_type": "IMAGE",
                 "media_product_type": "FEED", "media_url": IG_SECOND_IMG, "like_count": 1, "comments_count": 0},
            ], "paging": {"next": "https://graph.facebook.com/v24.0/IG1/media?after=X&access_token=T"}})
        if path in (f"{MEDIA_NEW}/insights",):
            return httpx.Response(200, json={"data": [
                {"name": m, "period": "lifetime", "values": [{"value": {"views": 300, "reach": 200, "saved": 4,
                                                                        "shares": 2, "total_interactions": 15}.get(m, 0)}]}
                for m in q["metric"].split(",")]})
        return err(100, f"Unsupported get request: {path}")

    def page_insights(self, q):
        metrics = q["metric"].split(",")
        if set(metrics) & UNKNOWN_METRICS:
            return err(100, "(#100) The value must be a valid insights metric")
        start = date.fromisoformat(q["since"])
        until = date.fromisoformat(q["until"])
        if "breakdown" in q:
            vals = [{"value": {"1": 90, "0": 10}, "end_time": f"{d.isoformat()}T08:00:00+0000"}
                    for d in (start + timedelta(days=i) for i in range(1, (until - start).days + 1))]
            return httpx.Response(200, json={"data": [{"name": metrics[0], "period": "day", "values": vals}]})
        data = []
        for m in metrics:
            vals = []
            for i in range(1, (until - start).days + 1):
                d = start + timedelta(days=i)
                v = 1000 + i if m == "page_follows" else {"like": 2, "love": 1} if m == "page_actions_post_reactions_total" else 50
                vals.append({"value": v, "end_time": f"{d.isoformat()}T08:00:00+0000"})
            data.append({"name": m, "period": "day", "values": vals})
        return httpx.Response(200, json={"data": data})

    def post_insights(self, q):
        metrics = q["metric"].split(",")
        if set(metrics) & UNKNOWN_METRICS:
            return err(100, "(#100) The value must be a valid insights metric")
        if "breakdown" in q:
            return httpx.Response(200, json={"data": [{"name": metrics[0], "period": "lifetime", "total_value": {
                "value": 26155, "breakdowns": [{"dimension_keys": ["is_from_ads"], "results": [
                    {"dimension_values": ["1"], "value": 26140}, {"dimension_values": ["0"], "value": 15}]}]}}]})
        sample = {"post_media_view": 26155, "post_total_media_view_unique": 22800,
                  "post_reactions_by_type_total": {"like": 10, "love": 2}, "post_clicks_by_type": {"link clicks": 1}}
        return httpx.Response(200, json={"data": [
            {"name": m, "period": "lifetime", "values": [{"value": sample.get(m, 0)}]} for m in metrics]})
