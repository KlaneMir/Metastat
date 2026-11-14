"""Commands: probe, sync, status, schedule and more."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from metastat import config, db
from metastat.graph import TokenError


def setup_logging(s: config.Settings) -> None:
    from metastat.paths import ensure_dir
    ensure_dir(s.log_dir)
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(logging.INFO)
    fh = logging.FileHandler(s.log_dir / f"metastat-{datetime.now():%Y-%m}.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root.addHandler(fh)
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(levelname)-7s %(message)s"))
    root.addHandler(ch)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # request URLs contain the token


def status(s: config.Settings) -> int:
    conn = db.connect(s.db_path)
    print("== Recent syncs ==")
    for r in conn.execute("SELECT * FROM sync_runs ORDER BY id DESC LIMIT 5"):
        print(f"{r['started_utc']}  {r['mode']:6} {r['status']:8} requests: {r['api_calls'] or 0}"
              + (f"  ERROR: {r['error']}" if r["error"] else ""))
        for camp, parts in (json.loads(r["summary"] or "{}").get("campaigns") or {}).items():
            for part, res in parts.items():
                if "error" in res:
                    print(f"      {camp} / {part.upper()}: {res['error']}")

    print("\n== Campaigns ==")
    for c in s.campaigns:
        fb = conn.execute(
            "SELECT (SELECT value FROM fb_page_daily WHERE page_id = ? AND metric = 'followers_count' ORDER BY date DESC LIMIT 1) f,"
            " (SELECT COUNT(*) FROM fb_posts WHERE page_id = ?) n,"
            " (SELECT COUNT(DISTINCT taken_utc) FROM fb_post_snapshots s JOIN fb_posts p USING (post_id) WHERE p.page_id = ?) t",
            (c.fb_page_id, c.fb_page_id, c.fb_page_id)).fetchone()
        ig = conn.execute(
            "SELECT a.ig_user_id id, (SELECT value FROM ig_account_daily d WHERE d.ig_user_id = a.ig_user_id"
            " AND metric = 'followers_count' ORDER BY date DESC LIMIT 1) f,"
            " (SELECT COUNT(*) FROM ig_media m WHERE m.ig_user_id = a.ig_user_id) n"
            " FROM ig_accounts a WHERE lower(a.username) = ?", (c.ig_username,)).fetchone()
        from metastat.fmt import num
        line = f"{c.name}"
        if c.fb_page_id:
            line += f"\n   FB: followers {num(fb['f'])}, posts {fb['n']}, readings {fb['t']}"
        if c.ig_username:
            line += (f"\n   IG: followers {num(ig['f'])}, posts {ig['n']}" if ig
                     else f"\n   IG: @{c.ig_username} not synced yet")
        print(line)

    print("\n== Flags from the last 60 days ==")
    rows = conn.execute("SELECT * FROM flags WHERE date >= date('now', '-60 day') ORDER BY date DESC LIMIT 40").fetchall()
    for f in rows:
        print(f"{f['date']}  {f['scope']:10} {f['object_id']:20} {f['kind']:18} {f['detail'] or ''}")
    if not rows:
        print("none")

    off = conn.execute("SELECT scope, metric FROM metric_support WHERE ok = 0 ORDER BY scope, metric").fetchall()
    if off:
        print("\n== Metrics unavailable in the API (skipped) ==")
        for r in off:
            print(f"{r['scope']}: {r['metric']}")
    return 0


def _log_start_error() -> str | None:
    """Full dump of a start-up error to a file (the message box shows only one line). Returns the path or None."""
    import os
    import tempfile
    import traceback
    from metastat import paths
    text = f"{datetime.now():%Y-%m-%d %H:%M:%S} pid {os.getpid()} {sys.argv}\n{traceback.format_exc()}\n"
    for folder in (paths.home() / "logs", Path(tempfile.gettempdir())):
        try:
            paths.ensure_dir(folder)
            path = folder / "metastat-start-errors.log"
            with path.open("a", encoding="utf-8") as f:
                f.write(text)
            return str(path)
        except OSError:
            continue
    return None


def _message_box(text: str) -> None:
    """A Windows message box (program without a console)."""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, "Metastat", 0x10)  # error icon
    except (AttributeError, OSError):
        pass


def sync_all(s: config.Settings, *, fresh: bool, only: list[str] | None) -> int:
    """Task Scheduler job: all Meta connections one after another (test accounts are skipped)."""
    from metastat import store, sync
    log = logging.getLogger("metastat")
    ids = [c["id"] for c in store.Store(s.home).connections() if c["kind"] == "meta"]
    if not ids:
        print("There are no Meta connections. Add a token in the program: Settings → Add Meta connection.")
        return 2
    worst = 0
    for cid in ids:
        one = config.load_store(cid, home=s.home)
        if only and not any(c.id in only for c in one.campaigns):
            continue
        log.info("== Connection: %s ==", one.connection["name"])
        worst = max(worst, sync.run(one, fresh=fresh, only=only))
    return worst


def main(argv: list[str] | None = None) -> int:
    windowless = sys.stdout is None or sys.stderr is None  # pythonw.exe (Metastat.cmd, Program.cmd): no console
    if windowless:
        import io
        import os
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
        sys.stderr = io.StringIO()  # until the config is loaded; then into a file in logs\
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(prog="metastat", description="Facebook and Instagram statistics with history and "
                                     "post images. Without a command it opens the program window.")
    sub = parser.add_subparsers(dest="cmd")
    conn_help = "connection id (Settings in the program); defaults to the active one"
    p = sub.add_parser("probe", help="check the token, access to pages and IG accounts, and the available metrics")
    p.add_argument("--connection", metavar="ID", help=conn_help)
    p = sub.add_parser("sync", help="fetch data (daily); without --connection: all Meta connections")
    p.add_argument("--fresh", action="store_true", help="only snapshots of fresh posts (hourly)")
    p.add_argument("--campaign", action="append", metavar="ID", help="only this campaign; can be repeated")
    p.add_argument("--connection", metavar="ID", help="only this connection (can be a test account)")
    p = sub.add_parser("status", help="recent syncs, campaign state, flags")
    p.add_argument("--connection", metavar="ID", help=conn_help)
    sub.add_parser("connections", help="list of connections (id, name, kind)")
    p = sub.add_parser("schedule", help="tasks in Windows Task Scheduler")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--install", action="store_true", help="create the tasks")
    g.add_argument("--remove", action="store_true", help="remove the tasks")
    p = sub.add_parser("app", help="open the program window (same as running without a command); "
                                   "demo mode: DEMO=true variable")
    p.add_argument("--port", type=int, help="fixed port instead of a random one")
    p.add_argument("--no-window", action="store_true", help="server only, without opening the window")
    p = sub.add_parser("report", help="monthly report: XLSX, PDF and a ZIP with post cards")
    p.add_argument("--month", required=True, metavar="YYYY-MM", help="e.g. 2026-10")
    p.add_argument("--campaign", action="append", metavar="ID_OR_NAME", help="only this campaign; can be repeated")
    p.add_argument("--connection", metavar="ID", help=conn_help)
    p = sub.add_parser("fake", help="Meta API simulator for tests (10 fake accounts)")
    fsub = p.add_subparsers(dest="fake_cmd", required=True)
    fa = fsub.add_parser("add", help="add a test account as a connection in the program")
    fa.add_argument("--account", type=int, required=True, help="test account number 1–10")
    fh = fsub.add_parser("history", help="on a test account: build a year of history through the simulator")
    fh.add_argument("--connection", metavar="ID", help=conn_help)
    fh.add_argument("--days", type=int, default=365, help="days of history")
    fh.add_argument("--step", type=int, default=7, help="days between syncs in the older part of the history")
    fp = fsub.add_parser("photos", help="download free photos (Wikimedia Commons, free licenses) for test posts")
    fp.add_argument("--per-product", type=int, default=2, help="photos per product (1–5)")
    args = parser.parse_args(argv)
    args.cmd = args.cmd or "app"
    for name, default in (("port", None), ("no_window", False), ("connection", None)):
        if not hasattr(args, name):
            setattr(args, name, default)

    try:
        s = config.load(connection=args.connection)
    except Exception as e:  # without a console nobody sees print(), so a message box is shown
        msg = f"Metastat cannot load its settings: {e}"
        where = _log_start_error()
        if windowless and args.cmd == "app":
            _message_box(msg + (f"\n\nDetails: {where}" if where else ""))
        print(msg)
        return 2
    if windowless:  # errors of a program without a console go to a file so they can be read
        from metastat.paths import ensure_dir
        ensure_dir(s.log_dir)
        early = sys.stderr.getvalue()
        sys.stderr = open(s.log_dir / "program-errors.log", "a", encoding="utf-8")
        sys.stderr.write(early)
    setup_logging(s)

    try:
        if args.cmd == "probe":
            from metastat import probe
            return probe.run(s)
        if args.cmd == "sync":
            from metastat import sync
            if s.connection is None or args.connection:  # old folder layout or a single given connection
                return sync.run(s, fresh=args.fresh, only=args.campaign)
            return sync_all(s, fresh=args.fresh, only=args.campaign)
        if args.cmd == "status":
            return status(s)
        if args.cmd == "connections":
            from metastat import secure, store
            st = store.Store(s.home)
            active = (st.active() or {}).get("id")
            for c in st.connections():
                kind = "Meta" if c["kind"] == "meta" else "test"
                print(f"{'*' if c['id'] == active else ' '} {c['id']:16} {kind:5} {c['name']}  "
                      f"(campaigns: {len(c['campaigns'])}, token: {'yes' if c.get('token') else 'none'})")
            return 0
        if args.cmd == "schedule":
            from metastat import schedule
            if s.connection is None and s.fake and (args.install or args.remove):
                print("This is a test folder (simulator). Create Task Scheduler tasks only in the real program.")
                return 2
            return schedule.run(s, install=args.install, remove=args.remove)
        if args.cmd == "fake":
            from metastat.fakeapi import tools
            if args.fake_cmd == "add":
                from metastat import store
                try:
                    conn = tools.add_connection(store.Store(s.home), args.account)
                except ValueError as e:
                    print(e)
                    return 2
                print(f"Added the test account \"{conn['name']}\" (id {conn['id']}); it is now active. "
                      f"A year of history: metastat fake history --connection {conn['id']}")
                return 0
            if args.fake_cmd == "photos":
                from metastat.fakeapi import stock
                stock.download(max(1, min(args.per_product, 5)))
                print("Now rebuild the test account history (Settings → test account → Build a year of history).")
                return 0
            return tools.history(s, days=args.days, step=args.step)
        if args.cmd == "report":
            import re
            from metastat.reports import build
            from metastat.reports.render import RenderError
            m = re.fullmatch(r"(\d{4})-(\d{2})", args.month)
            if not m or not 1 <= int(m.group(2)) <= 12:
                print("Give the month as YYYY-MM, e.g. --month 2026-10")
                return 2
            try:
                only = [build.resolve_campaign(s, c) for c in args.campaign] if args.campaign else None
                paths = build.generate(s, int(m.group(1)), int(m.group(2)), only=only, progress=print)
            except (ValueError, RenderError) as e:
                print(e)
                return 2
            for kind, path in paths.items():
                print(f"{kind.upper():5} {path}")
            return 0
        if args.cmd == "app":
            from metastat.web.app import run_app
            # in the single-program layout the server reads the settings (connection switching); old folder: fixed
            fixed = s if s.connection is None and s.home is None else None
            return run_app(fixed, port=args.port, open_window=not args.no_window)
    except TokenError as e:
        print(e)
        return 2
    except Exception as e:
        # Without a console (EXE, Task Scheduler at 6:00) an unhandled error would show a PyInstaller box; log it instead.
        if not windowless:
            raise
        logging.getLogger("metastat").exception("Command %s stopped with an error", args.cmd)
        if args.cmd == "app":
            _message_box(f"Metastat stopped working: {e}\n\nDetails: {s.log_dir}")
        return 2
    return 0
