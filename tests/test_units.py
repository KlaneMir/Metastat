from __future__ import annotations

import httpx
import pytest

from metastat import db, flags, images
from metastat.graph import Graph, GraphError
from metastat.images import ImageStore, asset_key
from metastat.insights import split_paid
from metastat.timeutil import insights_day, parse_meta


def test_graph_never_sends_token_outside_meta():
    """The paging.next link comes from an API response: a foreign URL must not get the system user token."""
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={"data": []})

    g = Graph("SECRET", "v24.0", client=httpx.Client(transport=httpx.MockTransport(handle)), sleep=lambda s: None)
    for url in ("https://evil.example/v24.0/me", "http://graph.facebook.com/v24.0/me",
                "https://graph.facebook.com.evil.example/x", "https://graph.facebook.com@evil.example/x"):
        with pytest.raises(GraphError):
            g.get(url)
    assert seen == []
    g.get("https://graph.facebook.com/v24.0/IG1/media?after=X")       # a regular paging.next link still works
    assert [str(r.url.host) for r in seen] == ["graph.facebook.com"]


def test_images_download_only_over_https(tmp_path):
    """The image URL also comes from the API: no http://, file:// or redirects into the local network."""
    seen = []

    def handle(request):
        seen.append(str(request.url))
        if request.url.host == "cdn.example":
            return httpx.Response(302, headers={"location": "http://127.0.0.1:9/admin"})
        return httpx.Response(200, content=b"x")

    store = ImageStore(tmp_path, db.connect(tmp_path / "t.sqlite"),
                       client=images.download_client(transport=httpx.MockTransport(handle)))
    assert store.ensure("http://127.0.0.1:9/a.jpg", "fb", "1") is None
    assert store.ensure("https://cdn.example/b.jpg", "fb", "2") is None
    assert seen == ["https://cdn.example/b.jpg"]


def test_asset_key_ignores_signature():
    a = asset_key("https://scontent.xx.fbcdn.net/v/t39.30808-6/466_1234_n.jpg?_nc_cat=1&oe=6720ABCD")
    b = asset_key("https://scontent.cdninstagram.com/v/t39.30808-6/466_1234_n.jpg?oe=FFFF0000")
    assert a == b == "466_1234_n.jpg"


def test_split_paid_shapes():
    tv = {"total_value": {"breakdowns": [{"results": [
        {"dimension_values": ["1"], "value": 26140}, {"dimension_values": ["0"], "value": 15}]}]}}
    assert split_paid(tv) == {"paid": 26140, "organic": 15}
    assert split_paid({"values": [{"value": {"true": 5, "false": 7}}]}) == {"paid": 5, "organic": 7}
    assert split_paid({"values": [{"value": 12}]}) is None


def test_meta_time_and_insights_day():
    assert parse_meta("2026-10-31T17:04:00+0000").isoformat() == "2026-10-31T17:04:00+00:00"
    assert insights_day("2026-11-02T08:00:00+0000").isoformat() == "2026-11-01"


def test_follower_flags():
    conn = db.connect(":memory:")
    rows = [("2026-10-01", 300), ("2026-10-02", 310), ("2026-10-03", 2), ("2026-10-04", -5), ("2026-10-05", 400), ("2026-10-06", 410)]
    for d, v in rows:
        db.save_daily(conn, "fb_page_daily", "page_id", "P", d, {"followers_count": v}, "field")
    flags.check_followers(conn, {"follower_jump_pct": 20, "follower_collapse_from": 100}, table="fb_page_daily",
                          id_col="page_id", obj_id="P", metric="followers_count", scope="fb_page")
    got = {(r["date"], r["kind"]) for r in conn.execute("SELECT date, kind FROM flags")}
    assert got == {("2026-10-03", "collapse"), ("2026-10-04", "negative_value")}
    # 2 → -5 is not a "jump" (a previous value ≤ 0 is no percentage base); -5 → 400 is not either
    # a jump from 410 → 600 is:
    db.save_daily(conn, "fb_page_daily", "page_id", "P", "2026-10-07", {"followers_count": 600}, "field")
    flags.check_followers(conn, {"follower_jump_pct": 20}, table="fb_page_daily", id_col="page_id",
                          obj_id="P", metric="followers_count", scope="fb_page")
    detail = conn.execute("SELECT detail FROM flags WHERE kind = 'jump'").fetchone()[0]
    assert detail == "Followers (program record): 410 → 600 (+46%, previous record 6 Oct 2026)"


def test_metric_rows_keep_breakdown_raw():
    rows = dict((m, (v, r)) for m, v, r in db.metric_rows({"a": 5, "b": {"like": 2, "love": 3}, "c": None}))
    assert rows["a"] == (5.0, None)
    assert rows["b"][0] == 5.0 and '"love": 3' in rows["b"][1]
    assert rows["c"] == (None, None)
