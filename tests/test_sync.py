from __future__ import annotations

import json

from PIL import Image

from metastat import db, sync
from metastat.graph import Graph

from conftest import NOW
from fake_meta import IG, MEDIA_NEW, MEDIA_OLD, PAGE, POST_COVER, POST_PHOTO, err


def snap(conn, table, id_col, obj_id):
    rows = conn.execute(f"SELECT metric, value, raw FROM {table} WHERE {id_col} = ?", (obj_id,)).fetchall()
    return {r["metric"]: (r["value"], r["raw"]) for r in rows}


def test_full_sync(project, clients, meta):
    graph, http = clients
    code = sync.run(project, graph=graph, http=http, now=NOW)
    assert code == 1  # second campaign: IG account invisible to the API → partial success
    conn = db.connect(project.db_path)

    # FB posts, including a cover photo change marked separately
    posts = {r["post_id"]: r for r in conn.execute("SELECT * FROM fb_posts")}
    assert set(posts) == {POST_PHOTO, POST_COVER}
    assert posts[POST_PHOTO]["kind"] == "post"
    assert posts[POST_COVER]["kind"] == "cover_photo"
    assert posts[POST_PHOTO]["created_local"] == "2026-11-10T10:30:00"  # UTC → Warsaw
    assert conn.execute("SELECT kind FROM flags WHERE object_id = ?", (POST_COVER,)).fetchone()["kind"] == "cover_photo"

    s = snap(conn, "fb_post_snapshots", "post_id", POST_PHOTO)
    assert s["shares"][0] == 0           # no shares field → 0
    assert s["comments"][0] == 3
    assert s["likes"][0] == 10 and s["reactions"][0] == 12
    assert s["post_media_view"][0] == 26155
    assert s["post_media_view_paid"][0] == 26140 and s["post_media_view_organic"][0] == 15
    assert json.loads(s["post_reactions_by_type_total"][1]) == {"like": 10, "love": 2}
    assert s["post_reactions_by_type_total"][0] == 12
    assert "post_video_views" not in s   # "retired" metric → skipped

    # metrics rejected by Meta are remembered and not requested again
    assert db.supported(conn, "fb_post", "post_video_views") is False
    assert db.supported(conn, "fb_page_day", "page_video_views") is False
    assert db.supported(conn, "fb_post", "post_media_view") is True

    # daily page data: end_time shifted by a day, paid/organic split, follower state
    daily = {(r["date"], r["metric"]): r["value"] for r in conn.execute("SELECT * FROM fb_page_daily WHERE page_id = ?", (PAGE,))}
    assert daily[("2026-11-01", "page_follows")] == 1001
    assert daily[("2026-11-01", "page_media_view_paid")] == 90
    assert daily[("2026-11-01", "page_actions_post_reactions_total")] == 3
    assert daily[("2026-11-12", "followers_count")] == 1000

    # Instagram: account, daily insights, only the new post (the old one is outside the window), carousel → first photo
    assert conn.execute("SELECT username FROM ig_accounts WHERE ig_user_id = ?", (IG,)).fetchone()[0] == "test_account"
    media = [r["media_id"] for r in conn.execute("SELECT media_id FROM ig_media")]
    assert media == [MEDIA_NEW] and MEDIA_OLD not in media
    m = snap(conn, "ig_media_snapshots", "media_id", MEDIA_NEW)
    assert m["likes"][0] == 8 and m["comments"][0] == 1 and m["views"][0] == 300 and m["saved"][0] == 4
    ig_days = conn.execute("SELECT COUNT(DISTINCT date) FROM ig_account_daily WHERE source = 'insights'").fetchone()[0]
    assert ig_days >= 29
    assert conn.execute("SELECT value FROM ig_account_daily WHERE metric = 'followers_count'").fetchone()[0] == 500

    # images: a shared FB/IG image stored once (the same asset name, a different signature in the URL)
    imgs = conn.execute("SELECT * FROM images").fetchall()
    assert len(imgs) == 2
    ig_img = conn.execute("SELECT image_id FROM ig_media WHERE media_id = ?", (MEDIA_NEW,)).fetchone()[0]
    assert ig_img == posts[POST_PHOTO]["image_id"] == "555_shared_n.jpg"
    rep = conn.execute("SELECT report_path FROM images WHERE image_id = '555_shared_n.jpg'").fetchone()[0]
    with Image.open(project.data_dir / rep) as im:
        assert im.width == 800
    assert (project.data_dir / "images" / "original" / f"fb_{POST_PHOTO}.jpg").exists()

    # the run is recorded, the second campaign's error is described
    run = conn.execute("SELECT * FROM sync_runs ORDER BY id DESC").fetchone()
    assert run["status"] == "partial"
    summary = json.loads(run["summary"])
    assert "is not visible" in summary["campaigns"]["no-ig-api"]["ig"]["error"]
    assert conn.execute("SELECT COUNT(*) FROM flags WHERE kind = 'ig_not_found'").fetchone()[0] == 1


def test_second_run_adds_snapshots_and_skips_dead_metrics(project, clients, meta):
    graph, http = clients
    sync.run(project, graph=graph, http=http, now=NOW, only=["test"])
    before = len(meta.requests)
    later = NOW.replace(hour=11)
    assert sync.run(project, graph=graph, http=http, now=later, only=["test"]) == 0
    conn = db.connect(project.db_path)
    taken = conn.execute("SELECT COUNT(DISTINCT taken_utc) FROM fb_post_snapshots WHERE post_id = ?", (POST_PHOTO,)).fetchone()[0]
    assert taken == 2
    new = meta.requests[before:]
    assert not any("video_views" in r.url.params.get("metric", "") for r in new)
    assert not any("scontent" in r.url.host for r in new)  # the images are already there
    # the token is never in the URL (paging.next too); fields=access_token is a field name, not a token
    assert not any("TOKEN" in str(r.url) or "access_token" in r.url.params for r in meta.requests)
    # first_seen is not overwritten
    row = conn.execute("SELECT first_seen_utc, last_seen_utc FROM fb_posts WHERE post_id = ?", (POST_PHOTO,)).fetchone()
    assert row["first_seen_utc"] < row["last_seen_utc"]


def test_fresh_mode_only_snapshots(project, clients, meta):
    graph, http = clients
    sync.run(project, graph=graph, http=http, now=NOW, only=["test"], fresh=True)
    paths = {r.url.path for r in meta.requests}
    assert not any(p.endswith(f"/{PAGE}/insights") for p in paths)  # no daily page data
    conn = db.connect(project.db_path)
    assert conn.execute("SELECT COUNT(*) FROM fb_post_snapshots").fetchone()[0] > 0


def test_expired_token_stops_sync(project, clients, meta):
    graph, http = clients
    meta.fail_first = [err(190, "Error validating access token: Session has expired", subcode=463)]
    assert sync.run(project, graph=graph, http=http, now=NOW) == 2
    conn = db.connect(project.db_path)
    run = conn.execute("SELECT * FROM sync_runs ORDER BY id DESC").fetchone()
    assert run["status"] == "failed"
    assert "The token has expired" in run["error"] and "Change token" in run["error"]


def test_rate_limit_is_retried(project, meta):
    import httpx
    slept = []
    graph = Graph("TEST_TOKEN", "v24.0", client=httpx.Client(transport=meta.transport()), sleep=slept.append)
    meta.fail_first = [err(4, "Application request limit reached"), err(4, "Application request limit reached")]
    assert graph.get("me/accounts")["data"]
    assert len(slept) == 2 and slept[0] < slept[1]


def test_no_token_message(project, monkeypatch):
    monkeypatch.delenv("META_SYSTEM_USER_TOKEN")
    from metastat import config
    s = config.load(project.root)
    assert s.token is None
    assert sync.run(s) == 2
