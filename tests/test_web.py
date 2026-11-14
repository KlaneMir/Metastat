from __future__ import annotations

import re
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from metastat import analytics as an
from metastat import db
from metastat.web.app import create_app

from conftest import NOW, PERIOD


@pytest.fixture
def client(sim):
    return TestClient(create_app(sim))


def test_pages_render(client, sim):
    camp = sim.campaigns[0]
    r = client.get(f"/?{PERIOD}")
    assert r.status_code == 200
    assert "Test account (API simulator)" in r.text and camp.name in r.text
    assert "Most viewed posts" in r.text

    r = client.get(f"/campaign/{camp.id}?{PERIOD}&view=grid")
    assert r.status_code == 200 and 'class="pcard"' in r.text and "Most views" in r.text
    r = client.get(f"/campaign/{camp.id}?{PERIOD}&view=table&platform=ig&sort=likes")
    assert r.status_code == 200 and "Instagram" in r.text

    post = re.search(r'href="/post/(fb|ig)/([^"]+)"', client.get(f"/campaign/{camp.id}?{PERIOD}").text)
    r = client.get(f"/post/{post.group(1)}/{post.group(2)}")
    assert r.status_code == 200 and "Views since publication" in r.text and "<svg class=\"chart\"" in r.text

    assert client.get("/status").status_code == 200
    r = client.get("/reports")
    assert r.status_code == 200 and "Create report" in r.text
    assert client.get("/reports/file/../../config/settings.yaml").status_code == 404  # report files only
    assert client.get("/campaign/missing").status_code == 404


def test_flags_shown(client, sim):
    """A new page with a broken follower history (a simulator trap) has a "To check" section."""
    conn = db.connect(sim.db_path)
    flagged = {r[0] for r in conn.execute("SELECT object_id FROM flags WHERE kind IN ('jump', 'collapse', 'negative_value')")}
    camp = next(c for c in sim.campaigns if c.fb_page_id in flagged)
    r = client.get(f"/campaign/{camp.id}?from=2026-01-01&to=2026-12-31")
    assert 'id="flags"' in r.text and "To check" in r.text


def test_summary_totals_match_posts(sim):
    """The summary totals must match the totals from the post lists (acceptance criterion)."""
    s = sim
    conn = db.connect(s.db_path)
    period = an.Period(date(2026, 10, 1), date(2026, 10, 31))
    rows = an.summary(conn, s, period)
    checked = 0
    for platform in ("fb", "ig"):
        for r in rows:
            m = r["platforms"].get(platform)
            if not m:
                continue
            ps = an.posts(conn, s, r["campaign"], platform, period, include_profile=False)
            assert m["posts"] == len(ps)
            for key, field in (("likes", "reactions"), ("comments", "comments"), ("shares", "shares")):
                assert (m[key] or 0) == sum(p[field] or 0 for p in ps), (r["campaign"].id, platform, key)
            checked += 1
        tot = an.totals(rows, platform)
        assert tot["posts"] == sum((r["platforms"].get(platform) or {}).get("posts", 0) for r in rows)
    assert checked >= 6


def test_snapshot_as_of_period_end(sim):
    s = sim
    conn = db.connect(s.db_path)
    lo, hi = (NOW - timedelta(days=10)).isoformat(), (NOW - timedelta(days=3)).isoformat()
    pid, created = conn.execute("SELECT post_id, created_local FROM fb_posts WHERE kind = 'post' AND created_utc BETWEEN ? AND ? "
                                "ORDER BY created_utc LIMIT 1", (lo, hi)).fetchone()
    full = an.snapshot_values(conn, "fb", [pid])[pid]["post_media_view"][0]
    day = date.fromisoformat(created[:10])
    early = an.snapshot_values(conn, "fb", [pid], an.end_bound_utc(day, s.tz))[pid]["post_media_view"][0]
    assert early < full  # the state from early in the post's life is smaller than the current one


def test_typical_curve_is_median(sim):
    s = sim
    conn = db.connect(s.db_path)
    camp = next(c for c in s.campaigns if c.fb_page_id)
    pid = conn.execute("SELECT post_id FROM fb_posts WHERE page_id = ? AND kind = 'post' LIMIT 1", (camp.fb_page_id,)).fetchone()[0]
    t = an.typical_curve(conn, "fb", camp.fb_page_id, pid, "post_media_view")
    assert t and all(b[1] >= a[1] for a, b in zip(t, t[1:]))  # a rising curve


def test_now_is_inside_simulator_world():
    from metastat.fakeapi import world
    assert world.WORLD_START < NOW.date() < world.WORLD_END
    assert isinstance(NOW, datetime)
