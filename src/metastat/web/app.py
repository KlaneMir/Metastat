"""The program with a UI: a local server (FastAPI) opened in an Edge app window.

One program, many connections: the active connection (a Meta account or a test account) is switched
in the top bar, and everything else (tokens, campaigns, settings, schedule) lives in Settings.

Local server protection:
- listens on 127.0.0.1 only, on a random port;
- draws a new key on every start; the program window opens /start?k=<key>, which sets an
  HttpOnly + SameSite=Strict cookie. Without the cookie the server shows nothing and changes nothing, so
  other pages in the browser and other programs can neither read data nor submit a form;
- the Host header must point to 127.0.0.1 or localhost (protection against DNS rebinding);
- a form with a foreign Origin header is rejected;
- CSP headers (own scripts only), X-Frame-Options, Referrer-Policy.

The window is closed the usual way. The server shuts down on its own when the page sends no signal for about 90 s.
"""
from __future__ import annotations

import collections
import hmac
import logging
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from metastat import analytics as an
from metastat import charts, config, db, schedule, secure, store, sync
from metastat.config import Settings
from metastat.fmt import MONTHS, dm, dmy, dmyhm, make_localtime, num, signed
from metastat.paths import ensure_dir as paths_ensure_dir
from metastat.timeutil import local_date

HERE = Path(__file__).parent
log = logging.getLogger(__name__)
PRESETS = [("7", "7 days"), ("30", "30 days"), ("month", "This month"), ("prev", "Last month")]
COOKIE = "metastat_k"
MSG = {  # messages after a redirect: fixed texts only, nothing from the URL reaches the page
    "demo": ("info", "In demo mode, connecting to Meta and Windows Task Scheduler tasks are turned off."),
    "busy": ("info", "The program is already busy in the background (a sync or a history build). Wait until it finishes."),
    "no_conn": ("info", "Add a connection first: a Meta token or a test account."),
    "no_token": ("error", "This connection has no token. Paste a token in the connection settings."),
    "switched": ("ok", "Connection switched."),
    "added_meta": ("ok", "Token checked and saved (encrypted by Windows). Choose the pages that should become campaigns."),
    "added_fake": ("ok", "Test account added. Its campaigns are already listed; build a year of history to get data."),
    "token_ok": ("ok", "New token checked and saved."),
    "renamed": ("ok", "Connection renamed."),
    "removed": ("ok", "Connection removed from the list. Its data (database, images, reports) stays on disk."),
    "confirm": ("error", "Tick the confirmation to remove it."),
    "imported": ("ok", "Campaigns added."),
    "none_selected": ("info", "No page was selected."),
    "camp_saved": ("ok", "Campaign saved."),
    "camp_removed": ("ok", "Campaign removed from the list. The collected data stays in the database."),
    "settings_saved": ("ok", "Settings saved."),
    "tasks_ok": ("ok", "The Windows Task Scheduler tasks are created."),
    "tasks_removed": ("ok", "Tasks removed from Task Scheduler."),
    "tasks_err": ("error", "Windows Task Scheduler refused. The details are in the program logs (the data\\logs folder)."),
    "tasks_none": ("info", "The tasks sync Meta connections. Add a Meta token first."),
    "legacy": ("info", "This folder uses the old config\\*.yaml file layout; make changes in those files."),
}


def safe_url(v) -> str | None:
    """Post link: https only (a value that came from the API must not become e.g. javascript:)."""
    s = str(v or "")
    return s if s.startswith("https://") else None


# ---------- background jobs ----------

class MemoryLog(logging.Handler):
    """Last log lines from the background job thread (for the preview in the program)."""

    def __init__(self):
        super().__init__(logging.INFO)
        self.lines: collections.deque[str] = collections.deque(maxlen=300)
        self.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))
        self.addFilter(lambda r: r.threadName == "job" and not r.name.startswith(("httpx", "httpcore")))

    def emit(self, record):
        self.lines.append(self.format(record))


class Jobs:
    """One background job at a time: a sync, a test account history build or a connection check."""

    def __init__(self):
        self.thread: threading.Thread | None = None
        self.log = MemoryLog()
        self.label = ""
        self.code: int | None = None
        logging.getLogger().addHandler(self.log)

    @property
    def running(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def say(self, msg: str) -> None:
        self.log.lines.append(f"{datetime.now():%H:%M:%S}  {msg}")

    def start(self, label: str, fn) -> bool:
        if self.running:
            return False
        self.log.lines.clear()
        self.label, self.code = label, None

        def work():
            try:
                self.code = fn(self.say)
            except Exception as e:  # shown in the program; the server keeps running
                log.exception("Background job failed")
                self.say(f"Error: {e}")
                self.code = 2

        self.thread = threading.Thread(target=work, daemon=True, name="job")
        self.thread.start()
        return True


class ReportRunner:
    """A report built in the background (cards and the PDF take from several seconds to a few minutes)."""

    def __init__(self):
        self.thread: threading.Thread | None = None
        self.lines: list[str] = []
        self.result: dict | None = None
        self.error: str | None = None
        self.conn_id: str | None = None

    @property
    def running(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def start(self, s: Settings, year: int, month: int, only: list[str] | None, demo: bool) -> bool:
        if self.running:
            return False
        from metastat.reports import build
        self.lines, self.result, self.error = [], None, None
        self.conn_id = (s.connection or {}).get("id")

        def work():
            try:
                self.result = build.generate(s, year, month, only=only, demo=demo,
                                             progress=lambda m: self.lines.append(f"{datetime.now():%H:%M:%S}  {m}"))
            except Exception as e:
                log.exception("Report failed")
                self.error = str(e)

        self.thread = threading.Thread(target=work, daemon=True, name="report")
        self.thread.start()
        return True


async def read_form(request: Request) -> dict[str, list[str]]:
    body = await request.body()
    if len(body) > 200_000:
        raise HTTPException(413, "The form is too large")
    return parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True)  # no python-multipart needed


def first(form: dict, key: str, default: str = "") -> str:
    return (form.get(key) or [default])[0].strip()


def go(path: str, msg: str | None = None) -> RedirectResponse:
    return RedirectResponse(path + (("&" if "?" in path else "?") + f"msg={msg}" if msg else ""), 303)


# ---------- application ----------

def create_app(s: Settings | None = None, *, home: Path | None = None,
               secret: str | None = None, port: int | None = None) -> FastAPI:
    """`s` given: fixed settings (old folder layout, tests). Without `s`: connections from data\\metastat.json.

    `secret` turns on the server protection (key from /start, Host, Origin); unit tests run without it.
    """
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    st = None if s is not None else store.Store(home)
    cur: dict = {"s": s}

    def S() -> Settings:
        if cur["s"] is None:
            cur["s"] = config.load_store(home=st.home)
            db.connect(cur["s"].db_path).close()  # the connection's database schema, before anyone starts writing to it
        return cur["s"]

    if s is not None:
        db.connect(s.db_path).close()

    def reload() -> None:
        if s is None:
            cur["s"] = None

    templates = Jinja2Templates(directory=str(HERE / "templates"))
    templates.env.filters.update(
        num=num, signed=signed, dm=dm, dmy=dmy, dmyhm=dmyhm, safe_url=safe_url, mask=secure.mask,
        localtime=lambda v: make_localtime(S().tz)(v))
    static_v = str(int(max(f.stat().st_mtime for f in (HERE / "static").iterdir())))  # new version = new CSS/JS URL
    from metastat import __version__
    from metastat import demo as demo_mod
    demo = s is None and demo_mod.enabled()  # demo mode (DEMO=true), only in the program with connections
    templates.env.globals.update(demo=demo, presets=PRESETS, v=static_v, version=__version__)
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

    # ---------- error pages (instead of raw JSON) ----------

    TITLES = {400: "This cannot be done", 404: "Page not found", 405: "Page not found",
              413: "Too much data in the form", 500: "Something went wrong"}

    def error_page(request: Request, status: int, message: str | None = None):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"error": message or TITLES.get(status, "Error")}, status_code=status)
        default = {404: "This address does not lead to any page of the program. The campaign, post or connection "
                        "may have been removed.", 500: "The program ran into an unexpected error. The details are in "
                        "the logs (Settings → Open data folder → logs)."}
        detail = message if message and message not in ("Not Found", "Method Not Allowed") else None
        try:  # connection switcher on the error page: a way out of a connection with a broken database
            conns = st.connections() if st else []
        except Exception:
            conns = []
        return templates.TemplateResponse(request, "error.html", {
            "title": TITLES.get(status, "Error"), "message": detail or default.get(status, "Please try again."),
            "connections": conns if status == 500 else [], "active_id": (cur["s"].connection or {}).get("id")
            if cur["s"] and cur["s"].connection else None}, status_code=status)

    from starlette.exceptions import HTTPException as StarletteHTTPException

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        return error_page(request, exc.status_code, exc.detail if isinstance(exc.detail, str) else None)

    @app.exception_handler(Exception)
    async def server_error(request: Request, exc: Exception):
        import sqlite3
        log.error("Page error %s", request.url.path, exc_info=exc)
        if isinstance(exc, sqlite3.DatabaseError) and cur["s"] is not None:
            return error_page(request, 500, (
                f"This connection's database is corrupt or locked ({exc}). File: {cur['s'].db_path}. "
                "Switch to another connection below, or close the program and rename this file: the program "
                "will create a new, empty database (the history in the broken one is lost)."))
        if isinstance(exc, store.StoreError):
            return error_page(request, 500, str(exc))
        return error_page(request, 500)

    jobs = Jobs()
    reports = ReportRunner()
    if demo:  # first start in demo mode: made-up accounts and their history, built in the background (the window opens right away)
        new = demo_mod.setup(st)
        if new:
            jobs.start("Preparing demo data", lambda say: demo_mod.build_history(st.home, new, say))
    app.state.last_ping = None
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    allowed_origins = {f"http://{h}" for h in allowed_hosts}

    # ---------- protection ----------

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if secret is not None:
            if request.headers.get("host", "") not in allowed_hosts:
                return HTMLResponse("Invalid address.", 400)
            if request.url.path == "/start":
                if hmac.compare_digest(request.query_params.get("k", ""), secret):
                    resp = RedirectResponse("/", 303)
                    resp.set_cookie(COOKIE, secret, httponly=True, samesite="strict", path="/")
                    return resp
                return HTMLResponse("Invalid key.", 403)
            if not hmac.compare_digest(request.cookies.get(COOKIE, ""), secret):
                return HTMLResponse("<!doctype html><html lang=en><meta charset=utf-8><title>Metastat</title>"
                                    "<p style='font:15px Segoe UI,sans-serif;margin:40px'>Open Metastat from the program icon. "
                                    "This address works only in the program window.</p>", 403)
            if request.method not in ("GET", "HEAD"):
                # Sec-Fetch-Site and Origin are set by the browser itself; a web page cannot forge them.
                # Sec-Fetch-Site takes precedence: Edge can send Origin "null" even from the program's own window.
                # Only "same-origin": another program on 127.0.0.1 (another port) is "same-site" to the browser.
                site = request.headers.get("sec-fetch-site")
                origin = request.headers.get("origin")
                ok = site in ("same-origin", "none") if site else (origin is None or origin in allowed_origins)
                if not ok:
                    return HTMLResponse("A form from another site was rejected.", 403)
        resp = await call_next(request)
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
            "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        # same-origin: the program's forms carry its own address, and links to Facebook do not get the program's address
        resp.headers["Referrer-Policy"] = "same-origin"
        if resp.headers.get("content-type", "").startswith("text/html"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    # ---------- shared ----------

    def get_conn():
        path = S().db_path
        # schema only when the database is missing (e.g. someone deleted the connection folder while the program was running)
        conn = db.connect(path, any_thread=True, schema=not path.exists())
        try:
            yield conn
        finally:
            conn.close()

    def today() -> date:
        return local_date(datetime.now(timezone.utc), S().tz)

    def period_from(request: Request) -> tuple[an.Period, str]:
        q = request.query_params
        try:
            if q.get("from") and q.get("to"):
                a, b = sorted((date.fromisoformat(q["from"]), date.fromisoformat(q["to"])))  # reversed dates: swap them
                lo, hi = date(2004, 1, 1), date(2100, 12, 31)  # no extreme dates (the comparison counts a period backwards)
                return an.Period(min(max(a, lo), hi), min(max(b, lo), hi)), ""
        except ValueError:
            pass
        key = q.get("p") if q.get("p") in dict(PRESETS) else "30"
        return an.preset(key, today()), key

    def ctx(request: Request, conn, **kw) -> dict:
        cs = S()
        period, key = period_from(request)
        last = conn.execute("SELECT * FROM sync_runs WHERE status != 'running' ORDER BY id DESC LIMIT 1").fetchone()
        params = {"p": key} if key else {"from": period.start.isoformat(), "to": period.end.isoformat()}
        return {"request": request, "period": period, "preset_key": key, "prev": period.previous(),
                "pq": urlencode(params), "last_run": last, "syncing": jobs.running, "job_label": jobs.label,
                "fake": cs.fake, "active": cs.connection, "store_mode": st is not None,
                "connections": st.connections() if st else [],
                "msg": MSG.get(request.query_params.get("msg") or ""), **kw}

    def page(name: str, c: dict, status: int = 200):
        return templates.TemplateResponse(c["request"], name, c, status_code=status)

    def conn_or_404(conn_id: str) -> dict:
        if st is None:
            raise HTTPException(404)
        c = st.get(conn_id)
        if not c:
            raise HTTPException(404, "No such connection")
        return c

    # ---------- statistics ----------

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request, conn=Depends(get_conn)):
        cs = S()
        c = ctx(request, conn, nav="dashboard")
        rows = an.summary(conn, cs, c["period"])
        c.update(rows=rows, total_fb=an.totals(rows, "fb"), total_ig=an.totals(rows, "ig"),
                 top=an.top_posts(conn, cs, c["period"]),
                 flag_counts={camp.id: len(an.flags(conn, cs, camp, c["period"])) for camp in cs.campaigns},
                 empty=not conn.execute("SELECT 1 FROM sync_runs WHERE status IN ('ok', 'partial') LIMIT 1").fetchone(),
                 no_connection=st is not None and not cs.connection)
        return page("dashboard.html", c)

    @app.get("/campaign/{camp_id}", response_class=HTMLResponse)
    def campaign(camp_id: str, request: Request, conn=Depends(get_conn)):
        cs = S()
        camp = next((x for x in cs.campaigns if x.id == camp_id), None)
        if not camp:
            raise HTTPException(404, "No such campaign")
        c = ctx(request, conn, nav="dashboard", camp=camp)
        q = request.query_params
        platform = q.get("platform") if q.get("platform") in ("fb", "ig") else "all"
        view = "table" if q.get("view") == "table" else "grid"
        sort = q.get("sort") if q.get("sort") in ("views", "likes", "comments", "shares") else "date"
        period = c["period"]
        metrics = {pl: an.platform_metrics(conn, cs, camp, pl, period) for pl in ("fb", "ig")}
        owners = an.owner_ids(conn, camp)
        chart = {}
        for pl, cls, label in (("fb", "s2", "Facebook followers"), ("ig", "s0", "Instagram followers")):
            if owners[pl]:
                chart[pl] = charts.followers_chart(an.daily_series(conn, pl, owners[pl], "followers_count", period),
                                                   period.start, period.end, cls, label)
        ps = []
        for pl in ("fb", "ig"):
            if platform in ("all", pl):
                ps += an.posts(conn, cs, camp, pl, period)
        key = {"date": lambda p: p["created_utc"], "views": lambda p: p["views"] or 0,
               "likes": lambda p: p["reactions"] or 0, "comments": lambda p: p["comments"] or 0,
               "shares": lambda p: p["shares"] or 0}[sort]
        ps.sort(key=key, reverse=True)
        top_id = max(ps, key=lambda p: p["views"] or 0)["id"] if ps and any(p["views"] for p in ps) else None
        max_views = max([p["views"] or 0 for p in ps] + [0])
        c.update(metrics=metrics, chart=chart, posts=ps, platform=platform, view=view,
                 sort=sort, top_id=top_id, max_views=max_views, owners=owners,
                 flags=an.flags(conn, cs, camp, period),
                 keep={k: v for k, v in (("platform", platform), ("view", view), ("sort", sort)) if v not in ("all", "grid", "date")})
        return page("campaign.html", c)

    @app.get("/post/{platform}/{post_id}", response_class=HTMLResponse)
    def post(platform: str, post_id: str, request: Request, conn=Depends(get_conn)):
        if platform not in ("fb", "ig"):
            raise HTTPException(404)
        d = an.post_detail(conn, S(), platform, post_id)
        if not d:
            raise HTTPException(404, "No such post in the database")
        c = ctx(request, conn, nav="dashboard", p=d, chart=charts.post_curve_chart(d["curve"], d["typical"]))
        return page("post.html", c)

    @app.get("/img/{rel:path}")
    def image(rel: str):
        base = (S().data_dir / "images").resolve()
        path = (base / rel).resolve()
        if base not in path.parents or not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, headers={"Cache-Control": "max-age=86400"})

    # ---------- sync ----------

    @app.get("/status", response_class=HTMLResponse)
    def status_page(request: Request, conn=Depends(get_conn)):
        import json
        from metastat import runlog
        cs = S()
        names = {c.id: c.name for c in cs.campaigns}
        runs = []
        for r in conn.execute("SELECT * FROM sync_runs ORDER BY id DESC LIMIT 15").fetchall():
            errs = runlog.run_errors(json.loads(r["summary"] or "{}"))
            runs.append(dict(r, problems=[f"{names.get(camp, camp)} / {part.upper()}" for camp, part, _ in errs]))
        c = ctx(request, conn, nav="status", runs=runs, token=bool(cs.token), names=names,
                problems=runlog.problems(conn),
                flags=conn.execute(
                    "SELECT f.*, c.name AS campaign FROM flags f "
                    "LEFT JOIN fb_pages fp ON fp.page_id = f.object_id LEFT JOIN ig_accounts ia ON ia.ig_user_id = f.object_id "
                    "LEFT JOIN campaigns c ON c.id = coalesce(fp.campaign_id, ia.campaign_id, f.object_id) "
                    "WHERE f.date >= date('now', '-60 day') AND f.kind NOT IN ('profile_photo', 'cover_photo') "
                    "ORDER BY f.date DESC LIMIT 50").fetchall(),
                off=conn.execute("SELECT * FROM metric_support WHERE ok = 0 ORDER BY scope, metric").fetchall(),
                version=cs.graph_api_version, job_lines=list(jobs.log.lines))
        return page("status.html", c)

    @app.post("/sync")
    def start_sync():
        cs = S()
        if st is not None and not cs.connection:
            return go("/settings", "no_conn")
        if not cs.token:
            return go("/status", "no_token")
        if not jobs.start(f"Sync of {(cs.connection or {}).get('name', 'the program')}", lambda say: sync.run(cs)):
            return go("/status", "busy")
        return go("/status")

    @app.get("/api/sync")
    def sync_state():
        return JSONResponse({"running": jobs.running, "label": jobs.label, "lines": list(jobs.log.lines)[-60:]})

    @app.post("/api/ping")
    def ping():
        app.state.last_ping = time.monotonic()
        return {"ok": True}

    # ---------- reports ----------

    def reports_dir() -> Path:
        return S().data_dir / "reports"

    @app.get("/reports", response_class=HTMLResponse)
    def reports_page(request: Request, conn=Depends(get_conn)):
        t = today()
        months = []
        y, m = t.year, t.month
        for _ in range(12):
            months.append((f"{y}-{m:02d}", f"{MONTHS[m - 1]} {y}"))
            y, m = (y - 1, 12) if m == 1 else (y, m - 1)
        files = []
        rd = reports_dir()
        if rd.exists():
            for f in sorted(rd.glob("*/*"), key=lambda p: p.stat().st_mtime, reverse=True):
                if f.suffix in (".xlsx", ".pdf", ".zip"):
                    files.append({"name": f.name, "rel": f.relative_to(rd).as_posix(), "month": f.parent.name,
                                  "size": f.stat().st_size, "mtime": datetime.fromtimestamp(f.stat().st_mtime)})
        default = months[1][0] if t.day <= 15 else months[0][0]  # early in the month the report is usually for the previous one
        mine = reports.conn_id == (S().connection or {}).get("id")
        c = ctx(request, conn, nav="reports", months=months, default_month=default, campaigns=S().campaigns,
                files=files[:60], running=reports.running,
                lines=reports.lines if mine else [], result=reports.result if mine else None,
                error=reports.error if mine else None)
        return page("reports.html", c)

    @app.post("/reports")
    async def start_report(request: Request):
        form = await read_form(request)
        cs = S()
        try:
            y, m = (int(x) for x in first(form, "month").split("-"))
            if not 1 <= m <= 12:
                raise ValueError
        except ValueError:
            return go("/reports")
        camp = first(form, "campaign")
        if camp and camp not in {c.id for c in cs.campaigns}:
            camp = ""
        reports.start(cs, y, m, [camp] if camp else None, cs.fake)
        return go("/reports")

    @app.get("/api/report")
    def report_state():
        return JSONResponse({"running": reports.running, "lines": reports.lines[-40:], "error": reports.error})

    @app.get("/reports/file/{rel:path}")
    def report_file(rel: str):
        rd = reports_dir().resolve()
        path = (rd / rel).resolve()
        if rd not in path.parents or not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, filename=path.name)

    def open_in_explorer(folder: Path) -> None:
        paths_ensure_dir(folder)
        if hasattr(os, "startfile"):  # Windows Explorer on the program's folder; the path does not come from the user
            os.startfile(folder)  # nosec B606

    @app.post("/reports/folder")
    def open_reports():
        open_in_explorer(reports_dir())
        return go("/reports")

    # ---------- connections and settings ----------

    @app.post("/connection")
    async def switch(request: Request):
        form = await read_form(request)
        if st is None:
            return go("/", "legacy")
        try:
            st.set_active(first(form, "id"))
        except store.StoreError:
            raise HTTPException(404)
        reload()
        return go("/", "switched")

    def connections_view() -> list[dict]:
        out = []
        for x in st.connections():
            try:
                tok, bad = secure.mask(st.token(x)), False
            except secure.SecureError:
                tok, bad = "cannot be read", True
            out.append(dict(x, token_mask=tok, token_bad=bad))
        return out

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request, conn=Depends(get_conn)):
        return render_settings(request, conn)

    def render_settings(request: Request, conn, error: str | None = None, name: str = ""):
        c = ctx(request, conn, nav="settings", error=error, form_name=name)
        if st is not None:
            from metastat.fakeapi import world
            data = st.load()
            used = {x.get("account") for x in data["connections"] if x["kind"] == "fake"}
            from metastat import paths
            c.update(conns=connections_view(), settings=data["settings"], home=st.home,
                     legacy_env=(paths.app_dir() / ".env").is_file(),
                     tasks=schedule.state(), has_meta=any(x["kind"] == "meta" for x in data["connections"]),
                     accounts=[(n, world.account(n).name, n in used) for n in range(1, world.ACCOUNTS + 1)])
        return page("settings.html", c, 400 if error else 200)

    @app.post("/settings/meta")
    async def add_meta(request: Request, conn=Depends(get_conn)):
        from metastat import connect
        form = await read_form(request)
        if st is None:
            return go("/settings", "legacy")
        if demo:  # in demo mode the program does not connect to Meta and does not accept real tokens
            return go("/settings", "demo")
        name = first(form, "name")[:80] or "Meta"
        try:
            token = connect.clean_token(first(form, "token"))
            info = connect.check(token, S().graph_api_version)
        except connect.ConnectError as e:
            return render_settings(request, conn, error=str(e), name=name)  # the token is not put back into the form
        new = st.add(name, "meta", token, owner=info["name"], missing=info["missing"])
        reload()
        return go(f"/settings/connection/{new['id']}/import", "added_meta")

    @app.post("/settings/test")
    async def add_fake(request: Request):
        from metastat.fakeapi import tools
        form = await read_form(request)
        if st is None:
            return go("/settings", "legacy")
        try:
            new = tools.add_connection(st, int(first(form, "account", "0")))
        except ValueError:
            raise HTTPException(400, "Invalid test account number")
        reload()
        if first(form, "history"):
            return start_history(new["id"])
        return go(f"/settings/connection/{new['id']}", "added_fake")

    @app.post("/settings/general")
    async def save_settings(request: Request, conn=Depends(get_conn)):
        form = await read_form(request)
        if st is None:
            return go("/settings", "legacy")
        try:
            st.update_settings({k: first(form, k) for k in store.EDITABLE if k in form})
        except store.StoreError as e:
            return render_settings(request, conn, error=str(e))
        reload()
        return go("/settings", "settings_saved")

    @app.post("/settings/folder")
    def open_data():
        open_in_explorer(st.home if st else S().data_dir)
        return go("/settings")

    @app.post("/schedule")
    async def tasks(request: Request):
        form = await read_form(request)
        if demo or st is None:
            return go("/settings", "demo" if demo else "legacy")
        remove = first(form, "tasks") == "remove"
        if not remove and not any(x["kind"] == "meta" for x in st.connections()):
            return go("/settings", "tasks_none")
        out: list[str] = []
        code = schedule.run(S(), install=not remove, remove=remove, out=out.append)
        log.info("Task Scheduler: %s", " | ".join(out))
        return go("/settings", ("tasks_removed" if remove else "tasks_ok") if code == 0 else "tasks_err")

    # ---------- a single connection ----------

    @app.get("/settings/connection/{conn_id}", response_class=HTMLResponse)
    def connection(conn_id: str, request: Request, conn=Depends(get_conn)):
        return render_connection(conn_id, request, conn)

    def render_connection(conn_id: str, request: Request, conn, error: str | None = None):
        conn_or_404(conn_id)
        view = next(v for v in connections_view() if v["id"] == conn_id)
        c = ctx(request, conn, nav="settings", x=view, error=error)
        return page("connection.html", c, 400 if error else 200)

    @app.post("/settings/connection/{conn_id}/activate")
    def make_active(conn_id: str):
        conn_or_404(conn_id)
        st.set_active(conn_id)
        reload()
        return go("/", "switched")

    @app.post("/settings/connection/{conn_id}/name")
    async def rename(conn_id: str, request: Request):
        conn_or_404(conn_id)
        form = await read_form(request)
        st.update(conn_id, name=first(form, "name"))
        reload()
        return go(f"/settings/connection/{conn_id}", "renamed")

    @app.post("/settings/connection/{conn_id}/token")
    async def replace_token(conn_id: str, request: Request, conn=Depends(get_conn)):
        from metastat import connect
        x = conn_or_404(conn_id)
        if x["kind"] != "meta":
            raise HTTPException(400)
        form = await read_form(request)
        try:
            token = connect.clean_token(first(form, "token"))
            info = connect.check(token, S().graph_api_version)
        except connect.ConnectError as e:
            return render_connection(conn_id, request, conn, error=str(e))
        st.update(conn_id, token=token, owner=info["name"], missing=info["missing"])
        reload()
        return go(f"/settings/connection/{conn_id}", "token_ok")

    @app.post("/settings/connection/{conn_id}/remove")
    async def remove(conn_id: str, request: Request):
        conn_or_404(conn_id)
        form = await read_form(request)
        if first(form, "confirm") != "1":
            return go(f"/settings/connection/{conn_id}", "confirm")
        st.remove(conn_id)
        reload()
        return go("/settings", "removed")

    def conn_settings(conn_id: str) -> Settings:
        return config.load_store(conn_id, home=st.home)

    @app.post("/settings/connection/{conn_id}/check")
    def check_connection(conn_id: str):
        from metastat import probe
        conn_or_404(conn_id)
        cs = conn_settings(conn_id)
        if not cs.token:
            return go(f"/settings/connection/{conn_id}", "no_token")
        if not jobs.start(f"Connection check for {cs.connection['name']}", lambda say: probe.run(cs, out=say)):
            return go("/status", "busy")
        return go("/status")

    @app.post("/settings/connection/{conn_id}/history")
    def start_history(conn_id: str):
        from metastat.fakeapi import tools
        x = conn_or_404(conn_id)
        if x["kind"] != "fake":
            raise HTTPException(400)
        cs = conn_settings(conn_id)
        if not jobs.start(f"History build for {x['name']}", lambda say: tools.history(cs, out=say)):
            return go("/status", "busy")
        return go("/status")

    # ---------- a connection's campaigns ----------

    @app.get("/settings/connection/{conn_id}/import", response_class=HTMLResponse)
    def import_pages(conn_id: str, request: Request, conn=Depends(get_conn)):
        from metastat import connect
        x = conn_or_404(conn_id)
        error, found = None, []
        try:
            token = st.token(x)
            if not token:
                raise connect.ConnectError("This connection has no token.")
            found = connect.list_pages(token, S().graph_api_version, base="fake" if x["kind"] == "fake" else None)
        except (connect.ConnectError, secure.SecureError) as e:
            error = str(e)
        have = {c["fb_page_id"] for c in x["campaigns"] if c.get("fb_page_id")}
        c = ctx(request, conn, nav="settings", x=x, pages=found, have=have, error=error)
        return page("import.html", c)

    @app.post("/settings/connection/{conn_id}/import")
    async def import_save(conn_id: str, request: Request):
        x = conn_or_404(conn_id)
        form = await read_form(request)
        chosen = form.get("page") or []
        if not chosen:
            return go(f"/settings/connection/{conn_id}/import", "none_selected")
        camps = list(x["campaigns"])
        have = {c["fb_page_id"] for c in camps if c.get("fb_page_id")}
        for pid in chosen:
            if not pid.isdigit() or pid in have:
                continue
            camps.append({"name": first(form, f"name_{pid}") or pid, "fb_page_id": pid,
                          "ig_username": first(form, f"ig_{pid}") or None, "label": first(form, f"label_{pid}") or None})
        try:
            st.update(conn_id, campaigns=camps)
        except store.StoreError as e:
            raise HTTPException(400, str(e))
        reload()
        return go(f"/settings/connection/{conn_id}", "imported")

    @app.get("/settings/connection/{conn_id}/campaign/{camp_id}", response_class=HTMLResponse)
    def campaign_form(conn_id: str, camp_id: str, request: Request, conn=Depends(get_conn)):
        return render_campaign(conn_id, camp_id, request, conn)

    def render_campaign(conn_id: str, camp_id: str, request: Request, conn,
                        error: str | None = None, values: dict | None = None):
        x = conn_or_404(conn_id)
        camp = next((cc for cc in x["campaigns"] if cc["id"] == camp_id), None)
        if camp_id != "new" and not camp:
            raise HTTPException(404)
        c = ctx(request, conn, nav="settings", x=x, camp=values or camp or {}, new=camp_id == "new",
                camp_id=camp_id, error=error)
        return page("campaign_edit.html", c, 400 if error else 200)

    @app.post("/settings/connection/{conn_id}/campaign/{camp_id}")
    async def campaign_save(conn_id: str, camp_id: str, request: Request, conn=Depends(get_conn)):
        x = conn_or_404(conn_id)
        form = await read_form(request)
        values = {"name": first(form, "name"), "label": first(form, "label") or None,
                  "status": first(form, "status"), "fb_page_id": first(form, "fb") or None,
                  "ig_username": first(form, "ig") or None, "ig_skip": first(form, "ig_skip") == "1"}
        camps = list(x["campaigns"])
        if camp_id == "new":
            camps.append(values)
        else:
            i = next((i for i, cc in enumerate(camps) if cc["id"] == camp_id), None)
            if i is None:
                raise HTTPException(404)
            camps[i] = dict(values, id=camp_id)  # the ID stays: the database links collected data by it
        try:
            st.update(conn_id, campaigns=camps)
        except store.StoreError as e:
            return render_campaign(conn_id, camp_id, request, conn, error=str(e), values=values)
        reload()
        return go(f"/settings/connection/{conn_id}", "camp_saved")

    @app.post("/settings/connection/{conn_id}/campaign/{camp_id}/remove")
    def campaign_remove(conn_id: str, camp_id: str):
        x = conn_or_404(conn_id)
        st.update(conn_id, campaigns=[cc for cc in x["campaigns"] if cc["id"] != camp_id])
        reload()
        return go(f"/settings/connection/{conn_id}", "camp_removed")

    return app


# ---------- opening the window ----------

def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _edge() -> str | None:
    for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
        if Path(p).exists():
            return p
    return shutil.which("msedge")


def _open_window(url: str, profile: Path) -> None:
    edge = _edge()
    if edge:  # Edge from its full path, arguments from the program (no shell)
        subprocess.Popen([edge, f"--app={url}", f"--user-data-dir={profile}", "--window-size=1440,900", "--lang=en-GB",  # nosec B603
                          "--no-first-run", "--no-default-browser-check"])
    else:
        webbrowser.open(url)


_MUTEXES: list = []  # handles kept until the process exits


def _first_instance(home: Path) -> bool:
    """True when this is the only running program on this data folder (a named Windows mutex)."""
    if sys.platform != "win32":
        return True
    import ctypes
    import hashlib
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    name = "Local\\Metastat-" + hashlib.sha1(str(home).lower().encode(), usedforsecurity=False).hexdigest()[:16]
    handle = kernel32.CreateMutexW(None, False, name)
    already = ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS
    _MUTEXES.append(handle)
    return not already


def run_app(s: Settings | None = None, *, port: int | None = None, open_window: bool = True) -> int:
    import uvicorn
    from metastat import paths

    home = paths.home() if s is None else s.data_dir
    profile = home / ".window"
    # Address with the key for the next start: DPAPI-encrypted, so only the same Windows account can read it.
    address = home / ".window-address"
    if not _first_instance(home):
        # The program is already running (e.g. a second click or a window closed a moment ago): open its window.
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                url = secure.decrypt(address.read_text(encoding="ascii"))
            except (OSError, ValueError, secure.SecureError):
                url = None
            if url:
                if open_window:
                    _open_window(url, profile)
                return 0
            time.sleep(0.5)
        return 0
    address.unlink(missing_ok=True)  # leftover from an interrupted start

    secret = secrets.token_urlsafe(32)
    port = port or _free_port()
    app = create_app(s, secret=secret, port=port)
    url = f"http://127.0.0.1:{port}/start?k={secret}"
    # log_config=None: uvicorn does not set up its own console (without one, under pythonw/EXE, it would shut down)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                                           log_config=None, access_log=False))

    def opener():
        while not server.started:
            if server.should_exit:
                return
            time.sleep(0.1)
        try:
            paths.ensure_dir(home)
            address.write_text(secure.encrypt(url), encoding="ascii")
        except (OSError, secure.SecureError):
            log.warning("Could not save the window address; the next start will open a second program")
        if open_window:
            _open_window(url, profile)
        print(f"Metastat is running on port {port} (close the program window to quit)")
        started = prev = time.monotonic()
        while not server.should_exit:  # stop the server when the window stops checking in
            time.sleep(5)
            now = time.monotonic()
            if now - prev > 30:  # the computer was asleep: give the open window time to check in again
                app.state.last_ping = now
            prev = now
            last = app.state.last_ping
            if last is None:
                if open_window and now - started > 300:  # the window never opened (e.g. no Edge)
                    server.should_exit = True
            elif now - last > 150:  # a minimized Edge window checks in less often (down to once a minute)
                server.should_exit = True

    threading.Thread(target=opener, daemon=True).start()
    try:
        server.run()
    finally:
        address.unlink(missing_ok=True)
    return 0
