"""Bugs found in the final debugging: each has a test here so it does not come back."""
from __future__ import annotations

import json
import shutil

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from metastat import config, paths, store
from metastat.fakeapi import tools
from metastat.reports import build, xlsx
from metastat.web.app import create_app


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "app_dir", lambda: tmp_path)
    return tmp_path / "data"


def client(home, **kw):
    return TestClient(create_app(home=home), **kw)


def test_extreme_and_reversed_periods(home):
    conn = tools.add_connection(store.Store(home), 1)
    camp = conn["campaigns"][0]["id"]
    c = client(home)
    for q in ("from=0001-01-01&to=9999-12-31", "from=1900-01-01&to=2100-12-31", "from=2026-13-01&to=2026-14-01"):
        assert c.get(f"/?{q}").status_code == 200          # before: OverflowError (500)
        assert c.get(f"/campaign/{camp}?{q}").status_code == 200
    r = c.get(f"/campaign/{camp}?from=2026-11-10&to=2026-10-01")   # reversed dates: swapped, not lost
    assert "1 Oct – 10 Nov 2026" in r.text


def test_backfill_date_must_exist(home):
    st = store.Store(home)
    for bad in ("2026-02-30", "today", "1999-01-01", "2999-01-01"):
        with pytest.raises(store.StoreError):
            st.update_settings({"backfill_since": bad})
    st.update_settings({"backfill_since": "2026-02-28"})


@pytest.mark.parametrize("name", ["...", " . . ", "CON", "nul", "com1.txt", "LPT9", "", "a/b\\c:d*e?f\"g<h>i|j",
                                  "tab\tnew\nline", chr(0x202E) + "reversed", "x" * 300])
def test_card_folder_names_are_safe(name):
    s = build._safe(name)
    assert s and not s.startswith(("/", "\\", ".")) and ".." not in s
    assert s.split(".")[0].lower() not in build._RESERVED
    assert not any(ch in s for ch in '<>:"/\\|?*\t\n' + chr(0x202E)) and len(s) <= 90


def test_xlsx_post_link_only_https():
    """The permalink comes from the API: in the sheet only https is clickable (no javascript:, file:, http:)."""
    ws = Workbook().active
    xlsx._post_link(ws, 1, 1, "https://www.facebook.com/p/1")
    xlsx._post_link(ws, 2, 1, "file:///C:/Windows/System32/calc.exe")
    xlsx._post_link(ws, 3, 1, "javascript:alert(1)")
    assert ws["A1"].hyperlink.target == "https://www.facebook.com/p/1"
    assert ws["A2"].hyperlink is None and ws["A3"].hyperlink is None


def test_xlsx_text_never_becomes_formula():
    wb = Workbook()
    ws = wb.active
    ws["A1"] = "=HYPERLINK(\"http://x\",\"click\")"
    ws["A2"] = "=1+1 formula at the start of a post"
    xlsx._no_formulas(wb)
    assert ws["A1"].data_type == "s" and ws["A2"].data_type == "s"


def test_error_pages_are_html_and_api_stays_json(home):
    c = client(home)
    r = c.get("/campaign/missing")
    assert r.status_code == 404 and "text/html" in r.headers["content-type"] and "Back to the dashboard" in r.text
    r = c.get("/sync")
    assert r.status_code == 405 and "text/html" in r.headers["content-type"]
    r = c.post("/settings/general", content=b"a=" + b"x" * 300_000,
               headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 413 and "Too much data" in r.text
    assert c.get("/api/missing").headers["content-type"].startswith("application/json")


def test_settings_file_recovers_from_backup(home):
    st = store.Store(home)
    a = tools.add_connection(st, 1)
    tools.add_connection(st, 2)                              # second write => backup copy of the first
    (home / "metastat.json").write_text('{"connections": [ {"id": ', encoding="utf-8")   # a truncated write
    data = store.Store(home).load()
    assert any(x["id"] == a["id"] for x in data["connections"])
    assert list(home.glob("metastat-corrupt-*.json"))  # the broken file stays for inspection
    assert client(home).get("/").status_code == 200


def test_settings_file_with_bom_is_not_corrupted(home):
    """A file saved in Notepad/PowerShell (BOM) used to pass for corrupt, and the program went back to an older
    backup, losing the most recently added connection."""
    st = store.Store(home)
    tools.add_connection(st, 1)
    newest = tools.add_connection(st, 2)
    raw = (home / "metastat.json").read_bytes()
    (home / "metastat.json").write_bytes(b"\xef\xbb\xbf" + raw.replace(b"\n", b"\r\n"))
    data = store.Store(home).load()
    assert any(x["id"] == newest["id"] for x in data["connections"])
    assert not list(home.glob("metastat-corrupt-*.json"))


def test_settings_file_broken_without_backup_explains(home):
    home.mkdir(parents=True)
    (home / "metastat.json").write_bytes(b"\x00\xff")
    with pytest.raises(store.StoreError, match="corrupt"):
        store.Store(home).load()
    r = client(home, raise_server_exceptions=False).get("/")
    assert r.status_code == 500 and "is corrupt" in r.text


def test_hand_edited_bad_values_fall_back_to_defaults(home):
    tools.add_connection(store.Store(home), 1)
    data = json.loads((home / "metastat.json").read_text(encoding="utf-8"))
    data["settings"].update(snapshot_window_days="abc", timezone="Mars/Olympus", flags="broken")
    (home / "metastat.json").write_text(json.dumps(data), encoding="utf-8")
    s = config.load_store(home=home)
    assert s.snapshot_window_days == 90 and str(s.tz) == "Europe/Warsaw" and isinstance(s.flags, dict)
    assert client(home).get("/").status_code == 200


def test_connection_folder_deleted_while_running(home):
    conn = tools.add_connection(store.Store(home), 1)
    c = client(home)
    assert c.get("/").status_code == 200
    shutil.rmtree(home / "connections" / conn["id"])
    for url in ("/", "/status", "/reports"):
        assert c.get(url).status_code == 200


def test_corrupted_database_page_lets_you_switch(home):
    st = store.Store(home)
    a = tools.add_connection(st, 1)
    b = tools.add_connection(st, 2)                          # active: b
    folder = home / "connections" / b["id"]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "metastat.sqlite").write_bytes(b"this is not a database" * 50)
    c = client(home, raise_server_exceptions=False)
    r = c.get("/")
    assert r.status_code == 500 and "is corrupt or locked" in r.text and str(folder) in r.text and a["id"] in r.text
    r = c.post("/connection", data={"id": a["id"]}, follow_redirects=True)
    assert r.status_code == 200


def test_unreadable_token_is_shown_for_any_connection(home):
    st = store.Store(home)
    conn = tools.add_connection(st, 1)
    data = json.loads((home / "metastat.json").read_text(encoding="utf-8"))
    data["connections"][0]["token"] = "dpapi:QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFB"
    (home / "metastat.json").write_text(json.dumps(data), encoding="utf-8")
    c = client(home)
    assert "cannot be read" in c.get("/settings").text
    assert "no_token" in c.post("/sync", follow_redirects=False).headers["location"]
    assert conn["kind"] == "fake"
