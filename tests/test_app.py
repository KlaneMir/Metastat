"""One program with connections: token encryption, Settings in the program, local server protection."""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from metastat import config, connect, paths, secure, store
from metastat.web.app import create_app, safe_url

TOKEN = "EAAG-FAKE-TEST-TOKEN-0000-XYZ9"   # made up; the dashes make it unlike a real token


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "app_dir", lambda: tmp_path)  # no migration of the real config/ and .env
    return tmp_path / "data"


@pytest.fixture
def app_client(home):
    return TestClient(create_app(home=home))


def test_dpapi_roundtrip_and_mask():
    enc = secure.encrypt(TOKEN)
    assert enc.startswith("dpapi:") and TOKEN not in enc
    assert secure.decrypt(enc) == TOKEN
    assert secure.mask(TOKEN) == "EAAG…XYZ9"
    with pytest.raises(secure.SecureError):
        secure.decrypt("dpapi:" + "A" * 40)   # not our ciphertext


def test_store_keeps_token_encrypted(home):
    st = store.Store(home)
    conn = st.add("Campaigns", "meta", TOKEN, campaigns=[
        {"name": "Płyń po formę", "fb_page_id": "123", "ig_username": "@Plyn.Po_Forme"},
        {"name": "Płyń po formę", "fb_page_id": "456"}])
    raw = (home / "metastat.json").read_text(encoding="utf-8")
    assert TOKEN not in raw and "dpapi:" in raw
    s = config.load_store(home=home)
    assert s.token == TOKEN and s.connection["id"] == conn["id"] and not s.fake
    assert [c.id for c in s.campaigns] == ["plyn-po-forme", "plyn-po-forme-2"]  # unique IDs
    assert s.campaigns[0].ig_username == "plyn.po_forme"
    with pytest.raises(store.StoreError):
        st.update(conn["id"], campaigns=[{"name": "X", "fb_page_id": "12a"}])
    with pytest.raises(store.StoreError):
        st.update_settings({"snapshot_window_days": "5"})


def test_token_format_is_checked():
    assert connect.clean_token(" EAAG-FAKE-0000\n -TEST-TOKEN ") == "EAAG-FAKE-0000-TEST-TOKEN"
    for bad in ("", "short", "EAAG1234567890 abc<script>", "x" * 3000):
        with pytest.raises(connect.ConnectError):
            connect.clean_token(bad)


def test_safe_url():
    assert safe_url("https://www.facebook.com/1/posts/2") == "https://www.facebook.com/1/posts/2"
    assert safe_url("javascript:alert(1)") is None and safe_url(None) is None


def test_first_run_and_test_account(app_client):
    r = app_client.get("/")
    assert r.status_code == 200 and "Welcome to Metastat" in r.text
    r = app_client.post("/settings/test", data={"account": "3"}, follow_redirects=False)
    assert r.status_code == 303 and "/settings/connection/fake-" in r.headers["location"]
    r = app_client.get("/")
    assert "Test account (API simulator)" in r.text and "No data yet" in r.text
    assert app_client.get("/settings").status_code == 200


def test_add_meta_token_flow(app_client, home, monkeypatch):
    # bad token: an error on the page, the token is not put back into the form, nothing saved
    r = app_client.post("/settings/meta", data={"name": "Agency", "token": "EAAG bad"})
    assert r.status_code == 400 and "does not look like a Meta token" in r.text
    assert not store.Store(home).connections()

    pages = [{"id": "111", "name": "Page A", "ig": "account_a"}, {"id": "222", "name": "Page B", "ig": None}]
    monkeypatch.setattr(connect, "check", lambda token, version, base=None: {
        "name": "System user", "id": "9", "missing": [], "pages": pages})
    monkeypatch.setattr(connect, "list_pages", lambda token, version, base=None: pages)
    r = app_client.post("/settings/meta", data={"name": "Agency", "token": TOKEN}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/import?msg=added_meta")
    conn_id = r.headers["location"].split("/")[3]
    r = app_client.get(f"/settings/connection/{conn_id}/import")
    assert "Page A" in r.text and "@account_a" in r.text and TOKEN not in r.text

    r = app_client.post(f"/settings/connection/{conn_id}/import",
                        data={"page": ["111"], "name_111": "Campaign A", "ig_111": "account_a", "label_111": "DAIRY"},
                        follow_redirects=False)
    assert r.status_code == 303
    s = config.load_store(conn_id, home=home)
    assert [(c.name, c.fb_page_id, c.ig_username, c.label) for c in s.campaigns] == [("Campaign A", "111", "account_a", "DAIRY")]

    # campaign edit: the ID stays, skipping IG works
    cid = s.campaigns[0].id
    app_client.post(f"/settings/connection/{conn_id}/campaign/{cid}",
                    data={"name": "Campaign A2", "fb": "111", "ig": "account_a", "status": "ended", "ig_skip": "1"})
    c = config.load_store(conn_id, home=home).campaigns[0]
    assert (c.id, c.name, c.status, c.ig_skip) == (cid, "Campaign A2", "ended", True)
    r = app_client.post(f"/settings/connection/{conn_id}/campaign/{cid}", data={"name": "X", "fb": "12a"})
    assert r.status_code == 400 and "digits only" in r.text

    page = app_client.get(f"/settings/connection/{conn_id}").text
    assert TOKEN not in page and "EAAG…XYZ9" in page

    # removal requires confirmation
    assert "msg=confirm" in app_client.post(f"/settings/connection/{conn_id}/remove", follow_redirects=False).headers["location"]
    app_client.post(f"/settings/connection/{conn_id}/remove", data={"confirm": "1"})
    assert not store.Store(home).connections()


def test_switch_connection(app_client, home):
    from metastat.fakeapi import tools
    st = store.Store(home)
    a = tools.add_connection(st, 1)
    b = tools.add_connection(st, 2)
    assert f'value="{b["id"]}" selected' in app_client.get("/").text
    app_client.post("/connection", data={"id": a["id"]})
    assert f'value="{a["id"]}" selected' in app_client.get("/").text
    assert app_client.post("/connection", data={"id": "missing"}).status_code == 404


def test_messages_are_not_reflected(app_client):
    r = app_client.get("/settings?msg=<b>hack</b>&error=<script>x</script>")
    assert "hack" not in r.text and "<script>x" not in r.text


def test_server_guard(home):
    app = create_app(home=home, secret="secret-123", port=8123)
    c = TestClient(app, base_url="http://127.0.0.1:8123")
    r = c.get("/")
    assert r.status_code == 403 and "Open Metastat" in r.text          # nothing is visible without the key
    assert c.get("/start?k=bad").status_code == 403
    r = c.get("/start?k=secret-123", follow_redirects=False)
    assert r.status_code == 303 and "httponly" in r.headers["set-cookie"].lower()
    assert "samesite=strict" in r.headers["set-cookie"].lower()
    r = c.get("/")
    assert r.status_code == 200
    csp = r.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp and r.headers["x-frame-options"] == "DENY"
    # DNS rebinding: a foreign Host; a form from a foreign page
    assert c.get("/", headers={"host": "evil.example:8123"}).status_code == 400
    r = c.post("/settings/test", data={"account": "1"}, headers={"origin": "https://evil.example"})
    assert r.status_code == 403 and not store.Store(home).connections()
    # another program on 127.0.0.1 (another port) is "same-site" to the browser, not "same-origin"
    r = c.post("/settings/test", data={"account": "1"},
               headers={"origin": "http://127.0.0.1:9999", "sec-fetch-site": "same-site"})
    assert r.status_code == 403 and not store.Store(home).connections()
    # this is what Edge sends from the program window: Origin "null", Sec-Fetch-Site "same-origin" (rejected before; the error on the screenshot)
    r = c.post("/settings/test", data={"account": "1"},
               headers={"origin": "null", "sec-fetch-site": "same-origin"}, follow_redirects=False)
    assert r.status_code == 303
    r = c.post("/sync", headers={"origin": "http://127.0.0.1:8123", "sec-fetch-site": "same-origin"}, follow_redirects=False)
    assert r.status_code == 303
    assert c.get("/").headers["referrer-policy"] == "same-origin"


def test_image_route_stays_in_images(app_client, home):
    from metastat.fakeapi import tools
    conn = tools.add_connection(store.Store(home), 1)
    img = home / "connections" / conn["id"] / "images" / "report" / "a.jpg"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"\xff\xd8\xff")
    (home / "metastat.json").exists()
    assert app_client.get("/img/report/a.jpg").status_code == 200
    assert app_client.get("/img/../../metastat.json").status_code == 404
    assert app_client.get("/img/..%2F..%2Fmetastat.json").status_code == 404


def test_no_secrets_in_source():
    """The code contains no tokens, keys or personal data (a simple scanner that complements a manual review)."""
    root = paths.Path(__file__).resolve().parents[1] / "src"
    pattern = re.compile(r"EAA[A-Za-z0-9]{30,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|[\w.+-]+@(gmail|outlook|wp|onet)\.\w+")
    hits = [f"{p}:{m.group(0)[:12]}" for p in root.rglob("*") if p.suffix in (".py", ".html", ".js", ".css", ".sql")
            for m in pattern.finditer(p.read_text(encoding="utf-8", errors="ignore"))]
    assert hits == []
