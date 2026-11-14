from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
import yaml

from metastat import config, db, sync
from metastat.fakeapi import tools, world
from metastat.fakeapi.transport import CLOCK, FAKE_BASE, transport
from metastat.graph import Graph

WHEN = datetime(2026, 10, 15, 6, 0, tzinfo=timezone.utc)


def test_world_is_repeatable_and_sized():
    a, b = world.account(3), world.account(3)
    assert [c.name for c in a.campaigns] == [c.name for c in b.campaigns]
    names = [c.name for n in range(1, 11) for c in world.account(n).campaigns]
    assert len(names) == len(set(names))            # no repeats across accounts
    assert all(12 <= len(world.account(n).campaigns) <= 16 for n in range(1, 11))
    camp = a.campaigns[0]
    year = [p for p in camp.posts if datetime(2025, 11, 12, tzinfo=timezone.utc) <= p.created < datetime(2026, 11, 12, tzinfo=timezone.utc)]
    assert len(year) > 70                             # a year of posts


def test_simulator_speaks_graph_api():
    c = httpx.Client(transport=transport())
    tok = world.account(1).token
    assert c.get(FAKE_BASE + "v24.0/me", params={"access_token": "bad"}).json()["error"]["code"] == 190
    pages = c.get(FAKE_BASE + "v24.0/me/accounts", params={"access_token": tok, "limit": 5}).json()
    assert len(pages["data"]) == 5 and "after=5" in pages["paging"]["next"]   # pagination
    page_id = pages["data"][0]["id"]
    bad = c.get(FAKE_BASE + f"v24.0/{page_id}/insights",
                params={"access_token": tok, "metric": "page_media_view,page_video_views", "period": "day",
                        "since": "2026-10-01", "until": "2026-10-05"}).json()
    assert bad["error"]["code"] == 100 and "metric" in bad["error"]["message"]


def test_history_builds_snapshots_and_flags(tmp_path, monkeypatch):
    from conftest import ROOT
    (tmp_path / "config").mkdir()
    s = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))
    s.update(graph_base_url="fake", backfill_since="2026-08-01")
    (tmp_path / "config" / "settings.yaml").write_text(yaml.safe_dump(s, allow_unicode=True), encoding="utf-8")
    acc = world.account(1)
    camps = [{"id": c.id, "name": c.name, "status": "active", "fb_page_id": c.page_id, "ig_username": c.ig_username}
             for c in acc.campaigns if c.index in (0, 4, 5)]   # regular, a new page with a broken history, private IG
    (tmp_path / "config" / "campaigns.yaml").write_text(yaml.safe_dump({"campaigns": camps}, allow_unicode=True),
                                                        encoding="utf-8")
    monkeypatch.setenv("META_SYSTEM_USER_TOKEN", acc.token)
    st = config.load(tmp_path)
    g = Graph(st.token, st.graph_api_version, base="fake", sleep=lambda _s: None)
    try:
        for when in (WHEN, WHEN + timedelta(days=7)):
            CLOCK.value = when
            assert sync.run(st, graph=g, http=g.client, now=when) in (0, 1)
    finally:
        CLOCK.value = None
    conn = db.connect(st.db_path)
    first = acc.campaigns[0]
    two = conn.execute("SELECT COUNT(*) FROM (SELECT post_id FROM fb_post_snapshots s JOIN fb_posts p USING (post_id) "
                       "WHERE p.page_id = ? GROUP BY post_id HAVING COUNT(DISTINCT taken_utc) = 2)", (first.page_id,)).fetchone()[0]
    assert two > 10                                   # the same posts read twice
    kinds = {r[0] for r in conn.execute("SELECT kind FROM flags")}
    assert {"ig_not_found"} <= kinds                  # a deliberately private IG account
    assert kinds & {"collapse", "negative_value", "jump"}  # the new page's broken follower history (1–3, then hundreds)
    assert db.supported(conn, "fb_page_day", "page_video_views") is False
    assert conn.execute("SELECT COUNT(*) FROM images").fetchone()[0] > 20


def test_problems_grouped_and_ig_skip(tmp_path, monkeypatch):
    """The same error across many runs is one problem; ig_skip silences a known IG account."""
    from conftest import ROOT
    from metastat import runlog
    (tmp_path / "config").mkdir()
    s = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))
    s.update(graph_base_url="fake", backfill_since="2026-10-01")
    (tmp_path / "config" / "settings.yaml").write_text(yaml.safe_dump(s, allow_unicode=True), encoding="utf-8")
    acc = world.account(2)
    private = next(c for c in acc.campaigns if c.ig_id and not c.ig_visible)
    camp = {"id": private.id, "name": private.name, "status": "active", "fb_page_id": private.page_id,
            "ig_username": private.ig_username}

    def write(extra):
        (tmp_path / "config" / "campaigns.yaml").write_text(
            yaml.safe_dump({"campaigns": [dict(camp, **extra)]}, allow_unicode=True), encoding="utf-8")
        return config.load(tmp_path)

    monkeypatch.setenv("META_SYSTEM_USER_TOKEN", acc.token)
    st = write({})
    g = Graph(st.token, st.graph_api_version, base="fake", sleep=lambda _s: None)
    try:
        for when in (WHEN, WHEN + timedelta(days=1), WHEN + timedelta(days=2)):
            CLOCK.value = when
            assert sync.run(st, graph=g, http=g.client, now=when) == 1
        conn = db.connect(st.db_path)
        p = runlog.problems(conn)
        assert len(p["current"]) == 1 and p["current"][0]["count"] == 3 and p["current"][0]["part"] == "ig"

        st = write({"ig_skip": True})
        CLOCK.value = WHEN + timedelta(days=3)
        assert sync.run(st, graph=g, http=g.client, now=WHEN + timedelta(days=3)) == 0   # a green run
    finally:
        CLOCK.value = None
    p = runlog.problems(db.connect(st.db_path))
    assert p["current"] == [] and p["resolved"][0]["part"] == "ig"


def test_fake_account_becomes_connection(tmp_path, monkeypatch):
    from metastat import paths, store
    monkeypatch.setattr(paths, "app_dir", lambda: tmp_path)  # no migration of the real config/
    st = store.Store(tmp_path / "data")
    for n in (1, 2):
        conn = tools.add_connection(st, n)
        s = config.load_store(conn["id"], home=st.home)
        assert s.fake and s.token == f"fake-token-{n:02d}" and len(s.campaigns) == len(world.account(n).campaigns)
        assert s.data_dir == st.home / "connections" / conn["id"]
        assert s.backfill_since <= (date.today() - timedelta(days=360)).isoformat()   # history from a year back
    assert config.load_store(home=st.home).connection["id"] == conn["id"]   # the most recently added one is active
    assert b"fake-token" not in (st.home / "metastat.json").read_bytes()    # tokens only encrypted
