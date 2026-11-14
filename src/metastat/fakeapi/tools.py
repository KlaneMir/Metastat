"""Simulator test accounts in the program and building a year of history ("fast-forwarding time")."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from metastat import sync
from metastat.config import Settings
from metastat.fakeapi import world
from metastat.fakeapi.transport import CLOCK
from metastat.fmt import dmy, dmyhm
from metastat.graph import Graph

# The simulator clock is shared by the whole program, so only one history is built at a time.
_HISTORY = threading.Lock()


def add_connection(st, n: int, *, limit: int | None = None, name: str | None = None) -> dict:
    """Adds test account no. n (1–10) as a connection in the program and makes it active.
    limit: only the account's first campaigns (demo mode: a shorter history build)."""
    if not 1 <= n <= world.ACCOUNTS:
        raise ValueError(f"Test accounts are numbered 1–{world.ACCOUNTS}.")
    acc = world.account(n)
    year_ago = (datetime.now(timezone.utc).date() - timedelta(days=365)).isoformat()
    camps = [{"id": c.id, "name": c.name, "label": c.label, "status": c.status, "fb_page_id": c.page_id,
              "ig_username": c.ig_username} for c in acc.campaigns[:limit]]
    return st.add(name or f"Test account {n:02d}", "fake", acc.token, campaigns=camps,
                  settings={"backfill_since": year_ago}, account=n)


def history(s: Settings, days: int = 365, step: int = 7, out=print, end: datetime | None = None) -> int:
    """Syncs "in the past": every `step` days over a year, daily for the last 2 weeks, hourly for the last day."""
    if not s.fake:
        out("A year of history can be built only on a test account (simulator).")
        return 2
    if not _HISTORY.acquire(blocking=False):
        out("Another test history is being built right now. Wait until it finishes.")
        return 2
    levels = {name: logging.getLogger(name).level for name in ("metastat", "httpx")}
    try:
        return _history(s, days, step, out, end)
    finally:
        for name, level in levels.items():  # after the history build the program logs normally again
            logging.getLogger(name).setLevel(level)
        _HISTORY.release()


def _history(s: Settings, days: int, step: int, out, end: datetime | None = None) -> int:
    # The history always starts from zero: the old database and images (e.g. from before the stock photos
    # were downloaded) are deleted. Reports and the program window profile stay.
    for f in (s.db_path, s.db_path.with_name(s.db_path.name + "-wal"), s.db_path.with_name(s.db_path.name + "-shm")):
        f.unlink(missing_ok=True)
    import shutil
    shutil.rmtree(s.images_dir, ignore_errors=True)
    for name in ("metastat", "httpx"):  # hundreds of runs: the results are in the database (Status screen), not the console
        logging.getLogger(name).setLevel(logging.CRITICAL)
    g = Graph(s.token, s.graph_api_version, base="fake", sleep=lambda _s: None)
    # end: a fixed "today" (tests repeatable regardless of the date); defaults to now
    real_now = (end or datetime.now(timezone.utc)).replace(minute=0, second=0, microsecond=0)
    start = (real_now - timedelta(days=days)).replace(hour=5)
    plan: list[tuple[datetime, bool]] = []
    t = start
    while t < real_now - timedelta(days=14):
        plan.append((t, False))
        t += timedelta(days=step)
    while t < real_now - timedelta(days=1):
        plan.append((t, False))
        t += timedelta(days=1)
    while t < real_now:
        local_hour = t.astimezone(s.tz).hour
        if local_hour == 6:
            plan.append((t, False))
        elif 8 <= local_hour <= 22:
            plan.append((t, True))
        t += timedelta(hours=1)
    out(f"Simulating {len(plan)} syncs from {dmy(start.astimezone(s.tz).date())} to today ({len(s.campaigns)} campaigns).")
    began = time.monotonic()
    errors = 0
    try:
        for i, (when, fresh) in enumerate(plan, 1):
            CLOCK.value = when
            code = sync.run(s, graph=g, http=g.client, now=when, fresh=fresh)
            errors += code == 2
            if i % 10 == 0 or i == len(plan):
                out(f"  {i}/{len(plan)}  as of {dmyhm(when.astimezone(s.tz).isoformat())}  "
                    f"requests: {g.calls}  time: {time.monotonic() - began:.0f} s")
        CLOCK.value = end  # None = the real "now"
        sync.run(s, graph=g, http=g.client, now=end)  # finally a regular sync "now"
    finally:
        CLOCK.value = None
    out(f"Done in {time.monotonic() - began:.0f} s, simulator requests: {g.calls}. "
        "Partial errors (e.g. the deliberately \"private\" IG account) are shown on the Sync screen.")
    return 1 if errors else 0
