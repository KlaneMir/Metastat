"""Demo mode (DEMO=true) and the .env file."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from metastat import demo, paths, secure, store
from metastat.web.app import create_app


@pytest.fixture
def app_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "app_dir", lambda: tmp_path)
    monkeypatch.delenv("METASTAT_DATA", raising=False)
    return tmp_path


def test_demo_switch_from_env_and_dotenv(app_dir, monkeypatch):
    monkeypatch.setenv("DEMO", "false")
    assert not paths.demo() and paths.home() == app_dir / "data"
    monkeypatch.setenv("DEMO", "true")
    assert paths.demo() and paths.home() == app_dir / "data-demo"      # a separate folder: made-up data kept apart
    monkeypatch.delenv("DEMO")
    (app_dir / ".env").write_text("DEMO=yes\n", encoding="utf-8")
    assert paths.demo()
    monkeypatch.setenv("DEMO", "0")                                       # the environment variable beats .env
    assert not paths.demo()


def test_demo_mode_builds_fake_data_and_blocks_meta(app_dir, monkeypatch):
    monkeypatch.setenv("DEMO", "true")
    monkeypatch.setattr(demo, "CAMPAIGNS", 2)
    monkeypatch.setattr(demo, "DAYS", 14)
    (app_dir / ".env").write_text("META_SYSTEM_USER_TOKEN=EAAG-FAKE-TOKEN-DO-NOT-IMPORT\n", encoding="utf-8")
    home = paths.home()
    c = TestClient(create_app(home=home))
    st = store.Store(home)
    assert [x["kind"] for x in st.connections()] == ["fake", "fake"]     # two demo accounts, without the token from .env
    for _ in range(240):
        if not c.get("/api/sync").json()["running"]:
            break
        time.sleep(0.5)
    r = c.get("/?p=30")
    assert r.status_code == 200 and "Demo mode" in r.text and "Campaigns" in r.text
    assert "Most viewed posts" in r.text
    r = c.get("/settings")
    assert 'action="/settings/meta"' not in r.text and "Meta tokens cannot be added in demo mode" in r.text
    assert "msg=demo" in c.post("/settings/meta", data={"name": "x", "token": "EAAG-FAKE-0000-0000-0000"},
                                follow_redirects=False).headers["location"]
    assert "msg=demo" in c.post("/schedule", data={"tasks": "install"}, follow_redirects=False).headers["location"]
    assert all(x["kind"] == "fake" for x in store.Store(home).connections())
    assert c.post("/sync", follow_redirects=False).status_code == 303     # syncing with the simulator works


def test_demo_images_are_placeholders(monkeypatch):
    from metastat.fakeapi import stock, transport
    called = []
    monkeypatch.setattr(stock, "pool", lambda: [{"product": "Poultry"}])
    monkeypatch.setattr(stock, "watermarked", lambda *a, **k: called.append(a) or b"x")
    monkeypatch.setenv("DEMO", "true")
    r = transport.image("100000010000007_100001")
    assert r.headers["content-type"] == "image/jpeg" and r.content[:2] == b"\xff\xd8" and not called
    monkeypatch.setenv("DEMO", "false")
    transport.image("100000010000007_100001")
    assert called                                                         # outside demo: photos, if they were downloaded


def test_env_token_imported_once_and_encrypted(app_dir, monkeypatch):
    monkeypatch.setenv("DEMO", "false")
    (app_dir / ".env").write_text("META_SYSTEM_USER_TOKEN=EAAG-FAKE-TOKEN-FROM-DOTENV-1234\n", encoding="utf-8")
    st = store.Store(app_dir / "data")
    conns = st.connections()
    assert len(conns) == 1 and conns[0]["kind"] == "meta" and conns[0]["campaigns"] == []
    assert st.token(conns[0]) == "EAAG-FAKE-TOKEN-FROM-DOTENV-1234"
    assert "EAAG-FAKE-TOKEN-FROM-DOTENV" not in (app_dir / "data" / "metastat.json").read_text(encoding="utf-8")
    assert conns[0]["token"].startswith(secure.PREFIX)


def test_env_token_with_bad_format_is_ignored(app_dir, monkeypatch):
    monkeypatch.setenv("DEMO", "false")
    (app_dir / ".env").write_text("META_SYSTEM_USER_TOKEN=\n", encoding="utf-8")   # an empty value as in .env.example
    assert store.Store(app_dir / "data").connections() == []
