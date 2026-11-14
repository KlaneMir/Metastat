"""Security audit: regression tests for attacks from the audit list (the numbers match the audit report).

Each test fails when Metastat is vulnerable to that attack. Items that do not apply have no test; the report
explains why (no HTTP/2, SAML, OAuth login, GraphQL, 2FA, JWT, reverse proxy, cache, RLS database, XML input
or WebSocket in this program).
"""
from __future__ import annotations

import ast
import base64
import os
import secrets
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from metastat import paths, secure, store
from metastat.fakeapi import tools
from metastat.web.app import COOKIE, create_app

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "metastat"
APP_FILES = sorted(p for p in SRC.rglob("*.py") if "fakeapi" not in p.parts)  # the simulator is demo/test code
PORT = 8123
BASE = f"http://127.0.0.1:{PORT}"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "app_dir", lambda: tmp_path)
    return tmp_path / "data"


def guarded(home: Path, secret: str) -> TestClient:
    """The app as the program window sees it: with the per-start key and the Host/Origin checks on."""
    return TestClient(create_app(home=home, secret=secret, port=PORT), base_url=BASE)


# ---------- 2. Long input / truncation ----------

def test_02_window_key_is_compared_in_full(home):
    """A key that only starts or ends like the real one must not open the program (no truncation)."""
    secret = secrets.token_urlsafe(32)
    for wrong in (secret + "x", secret[:-1], secret[:20], secret + "A" * 200):
        c = guarded(home, secret)
        assert c.get(f"/start?k={wrong}").status_code == 403, wrong
        c.cookies.set(COOKIE, wrong)
        assert c.get("/").status_code == 403, wrong
    assert guarded(home, secret).get(f"/start?k={secret}", follow_redirects=False).status_code == 303


def test_02_campaign_text_fields_have_a_length_limit(home):
    """Each text field needs its own limit on the server (the browser's maxlength is not a control)."""
    conn = tools.add_connection(store.Store(home), 1)
    camp = conn["campaigns"][0]
    long = "A" * 50_000
    TestClient(create_app(home=home)).post(
        f"/settings/connection/{conn['id']}/campaign/{camp['id']}",
        data={"name": long, "label": long, "status": "active",
              "fb": camp.get("fb_page_id") or "", "ig": camp.get("ig_username") or ""})
    saved = next(x for x in store.Store(home).connections() if x["id"] == conn["id"])["campaigns"]
    saved = next(x for x in saved if x["id"] == camp["id"])
    assert len(saved["name"]) <= 200, f"campaign name stored with {len(saved['name']):,} characters"
    assert len(saved["label"] or "") <= 50, f"label stored with {len(saved['label'] or ''):,} characters"


# ---------- 7. ReDoS ----------

REDOS = r'''
import time
from metastat import connect, images, store, timeutil
from metastat.reports import build
N = 100_000

def attempt(fn, arg):
    try:
        fn(arg)
    except Exception:
        pass

cases = [
    ("clean_token", connect.clean_token, "A" * N + "!"),
    ("clean_token", connect.clean_token, "A|" * N + " "),
    ("slug", store.slug, "a-" * N + "!"),
    ("slug", store.slug, "ł " * N),
    ("ig name", lambda s: store._clean_campaign({"name": "x", "ig_username": s}), "a." * N + "!"),
    ("campaign id", lambda s: store._clean_campaign({"name": "x", "id": s}), "a" + "-_" * N + "!"),
    ("parse_meta", timeutil.parse_meta, "+0000" * N),
    ("parse_meta", timeutil.parse_meta, "2026-01-01T00:00:00" + "+00" * N),
    ("asset_key", images.asset_key, "https://x/" + "a/" * N),
    ("image name", images._safe, "./" * N),
    ("report folder", build._safe, '<>:"' * N + " ." * N),
]
worst, which = 0.0, ""
for name, fn, arg in cases:
    t = time.perf_counter()
    attempt(fn, arg)
    took = time.perf_counter() - t
    if took > worst:
        worst, which = took, name
print(f"{worst:.3f} {which}")
'''


def test_07_regexes_on_user_and_api_data_do_not_backtrack():
    """Every regular expression that sees a token, a name or an API value stays fast on 100,000+ characters."""
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
    try:
        r = subprocess.run([sys.executable, "-c", REDOS], capture_output=True, text=True, timeout=30, cwd=ROOT, env=env)
    except subprocess.TimeoutExpired:
        pytest.fail("a regular expression ran for over 30 s on a long input (catastrophic backtracking)")
    assert r.returncode == 0, r.stderr
    took, which = r.stdout.strip().split(" ", 1)
    assert float(took) < 2.0, f"slowest case ({which}) took {took} s"


# ---------- 11. Spoofed client IP / forwarded headers ----------

SPOOF = {"x-forwarded-host": f"127.0.0.1:{PORT}", "x-forwarded-for": "127.0.0.1", "x-real-ip": "127.0.0.1",
         "x-forwarded-proto": "http", "forwarded": f"for=127.0.0.1;host=127.0.0.1:{PORT};proto=http"}


def test_11_forwarded_headers_do_not_bypass_host_and_origin_checks(home):
    secret = secrets.token_urlsafe(32)
    c = guarded(home, secret)
    assert c.get("/", headers={"host": "evil.example", **SPOOF}).status_code == 400
    assert c.get(f"/start?k={secret}", follow_redirects=False).status_code == 303
    r = c.post("/settings/test", data={"account": "1"}, headers={"origin": "https://evil.example", **SPOOF})
    assert r.status_code == 403 and not store.Store(home).connections()


def test_11_app_never_decides_on_client_ip_headers():
    """No rate limit, block or check may rely on X-Forwarded-For / X-Real-IP or the client address."""
    for p in APP_FILES:
        text = p.read_text(encoding="utf-8").lower()
        for marker in ("x-forwarded", "x-real-ip", "request.client"):
            assert marker not in text, f"{p.relative_to(ROOT)} uses {marker}"


# ---------- 13. Cryptographic randomness ----------

def test_13_window_key_comes_from_a_cryptographic_generator():
    tree = ast.parse((SRC / "web" / "app.py").read_text(encoding="utf-8"))
    made = [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "secret" for t in n.targets)]
    assert made, "the per-start key was not found in app.py"
    for call in made:
        assert ast.unparse(call.func) == "secrets.token_urlsafe", ast.unparse(call)
        assert call.args and call.args[0].value >= 32, "the key needs at least 32 random bytes"


def test_13_no_insecure_random_in_program_code():
    for p in APP_FILES:
        tree = ast.parse(p.read_text(encoding="utf-8"))
        mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        mods |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        assert "random" not in mods, f"{p.relative_to(ROOT)} imports random"
    for p in list((SRC / "web").rglob("*.js")) + list((SRC / "web" / "templates").glob("*.html")):
        assert "Math.random" not in p.read_text(encoding="utf-8"), p.name


# ---------- 14. Timing attacks ----------

SECRET_WORDS = ("secret", "token", "proof", "nonce", "password")


def timing_unsafe_comparisons(path: Path) -> list[str]:
    """== / != where one side looks like a secret and the other is not a constant (use hmac.compare_digest)."""
    out = []
    for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not (isinstance(n, ast.Compare) and any(isinstance(op, (ast.Eq, ast.NotEq)) for op in n.ops)):
            continue
        sides = [n.left, *n.comparators]
        if any(isinstance(s, ast.Constant) for s in sides):
            continue
        names = {x.id.lower() for s in sides for x in ast.walk(s) if isinstance(x, ast.Name)}
        names |= {x.attr.lower() for s in sides for x in ast.walk(s) if isinstance(x, ast.Attribute)}
        if any(w in name for name in names for w in SECRET_WORDS):
            out.append(f"{path.name}:{n.lineno}: {ast.unparse(n)}")
    return out


def test_14_secret_comparisons_are_constant_time():
    assert [x for p in APP_FILES for x in timing_unsafe_comparisons(p)] == []


# ---------- 15. Padding oracle / decryption errors ----------

@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")
def test_15_tampered_or_broken_token_ciphertext_fails_one_way():
    """Authenticated encryption (DPAPI): every damaged ciphertext gives the same SecureError, nothing else.

    Bytes appended after the DPAPI blob are ignored by Windows (the blob carries its own length); that cannot change
    the plaintext, so for that case the original token is an accepted result."""
    token = "EAAG-FAKE-TEST-TOKEN-0000-XYZ9"
    enc = secure.encrypt(token)
    blob = bytes(base64.b64decode(enc[len(secure.PREFIX):]))
    damaged = []
    for pos in (0, 30, 60, len(blob) - 90, len(blob) - 80, len(blob) - 30, len(blob) - 1):  # header, data, signature
        b = bytearray(blob)
        b[pos] ^= 0x01
        damaged.append((f"byte {pos} flipped", secure.PREFIX + base64.b64encode(bytes(b)).decode()))
    damaged += [("cut short", secure.PREFIX + base64.b64encode(blob[:-16]).decode()),
                ("not valid base64", secure.PREFIX + "abc"),
                ("junk appended", secure.PREFIX + base64.b64encode(blob + b"\xaa" * 16).decode())]
    messages = set()
    for label, value in damaged:
        try:
            out = secure.decrypt(value)
        except secure.SecureError as e:
            messages.add(str(e))
        except Exception as e:  # noqa: BLE001 - any other error type tells the damage apart
            pytest.fail(f"{label}: {type(e).__name__} instead of SecureError")
        else:
            assert label == "junk appended" and out == token, f"{label}: damaged ciphertext decrypted to {out!r}"
    assert len(messages) == 1, messages


# ---------- 17. Template injection ----------

PAYLOAD = "{{ 7*7 }} {% if true %}SSTI{% endif %} ${7*7} #{7*7}"


def test_17_campaign_names_are_never_rendered_as_templates(home):
    st = store.Store(home)
    conn = tools.add_connection(st, 1)
    camps = [dict(c) for c in conn["campaigns"]]
    camps[0].update(name=PAYLOAD, label="{{7*7}}")
    st.update(conn["id"], campaigns=camps)
    c = TestClient(create_app(home=home))
    # the dashboard lists only campaigns with data in the period, so it is not in this list
    for url in (f"/campaign/{camps[0]['id']}", f"/settings/connection/{conn['id']}", "/reports"):
        html = c.get(url).text
        assert "{{ 7*7 }}" in html and "{% if true %}SSTI{% endif %}" in html, f"{url}: the name was not shown as text"
        assert "SSTI" not in html.replace("{% if true %}SSTI{% endif %}", ""), f"{url}: the template code ran"


def test_17_templates_are_loaded_only_from_files():
    for p in APP_FILES:
        text = p.read_text(encoding="utf-8")
        assert "from_string(" not in text and "jinja2.Template(" not in text, p.relative_to(ROOT)


# ---------- 20. Unicode lookalikes ----------

def test_20_lookalike_campaign_names_never_share_an_id():
    """Names that normalise to the same text (full-width, accents, zero-width space, non-Latin) keep their own ID,
    so a "similar" campaign never takes over another campaign's data, URL or report folder."""
    names = ["Groats", "Ｇｒｏａｔｓ", "groats", "Gróats", "Groats​", "GROATS",
             "Чай", "Кофе"]
    ids = [c["id"] for c in store.clean_campaigns([{"name": n} for n in names])]
    assert len(set(ids)) == len(ids), ids
