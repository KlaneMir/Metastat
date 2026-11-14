from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
import yaml

from metastat import config
from metastat.graph import Graph

from fake_meta import FakeMeta, IG, PAGE

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)
PERIOD = "from=2026-10-01&to=2026-10-31"   # October 2026: a full month in the simulator data


@pytest.fixture(autouse=True)
def _no_demo(monkeypatch):
    monkeypatch.setenv("DEMO", "false")   # a developer's .env file (DEMO=true) does not change test results


@pytest.fixture(scope="session")
def sim(tmp_path_factory):
    """Made-up data from the Meta simulator: 6 campaigns of test account no. 1, 60 days of history ending at NOW.

    Shared by the program and report tests (read-only). The campaigns include deliberate traps:
    an IG account invisible to the API, a campaign without IG and a new page with a broken follower history.
    """
    from metastat import paths, store
    from metastat.fakeapi import tools
    home = tmp_path_factory.mktemp("sim")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(paths, "app_dir", lambda: home)   # without taking over the real config/ and .env
        mp.setenv("DEMO", "false")
        st = store.Store(home / "data")
        conn = tools.add_connection(st, 1, limit=6)
        s = config.load_store(conn["id"], home=st.home)
        assert tools.history(s, days=60, step=7, out=lambda *_: None, end=NOW) in (0, 1)
    return config.load_store(conn["id"], home=st.home)


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A project folder with one test campaign (FB + IG)."""
    (tmp_path / "config").mkdir()
    shutil.copy(ROOT / "config" / "settings.yaml", tmp_path / "config" / "settings.yaml")
    s = yaml.safe_load((tmp_path / "config" / "settings.yaml").read_text(encoding="utf-8"))
    s["backfill_since"] = "2026-11-01"
    (tmp_path / "config" / "settings.yaml").write_text(yaml.safe_dump(s, allow_unicode=True), encoding="utf-8")
    (tmp_path / "config" / "campaigns.yaml").write_text(yaml.safe_dump({"campaigns": [
        {"id": "test", "name": "Test campaign", "label": "TEST", "status": "active",
         "fb_page_id": PAGE, "ig_username": "test_account"},
        {"id": "no-ig-api", "name": "Private account", "status": "active", "fb_page_id": None, "ig_username": "private_ig"},
    ]}, allow_unicode=True), encoding="utf-8")
    monkeypatch.setenv("META_SYSTEM_USER_TOKEN", "TEST_TOKEN")
    return config.load(tmp_path)


@pytest.fixture
def meta():
    return FakeMeta()


@pytest.fixture
def clients(meta):
    http = httpx.Client(transport=meta.transport())
    graph = Graph("TEST_TOKEN", "v24.0", client=http, sleep=lambda s: None)
    return graph, http
