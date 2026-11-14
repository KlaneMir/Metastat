"""Follower count validation. Suspicious values are flagged, never hidden or corrected."""
from __future__ import annotations

import sqlite3

from metastat import db
from metastat.fmt import dmy

LABELS = {"followers_count": "Followers (program record)", "page_follows": "Followers according to Meta"}


def _n(v: float) -> str:
    return f"{v:,.0f}"


def _d(iso: str) -> str:
    return dmy(iso)


def check_followers(conn: sqlite3.Connection, flags_cfg: dict, *, table: str, id_col: str, obj_id: str,
                    metric: str, scope: str) -> int:
    jump_pct = float(flags_cfg.get("follower_jump_pct", 20))
    collapse_from = float(flags_cfg.get("follower_collapse_from", 100))
    rows = conn.execute(
        f"SELECT date, value FROM {table} WHERE {id_col} = ? AND metric = ? AND value IS NOT NULL ORDER BY date",  # nosec B608
        (obj_id, metric),
    ).fetchall()[-120:]
    before = conn.total_changes
    label = LABELS.get(metric, metric)
    prev = None
    for r in rows:
        v = r["value"]
        if v < 0:
            db.add_flag(conn, scope, obj_id, r["date"], "negative_value", f"{label}: {_n(v)}")
        elif prev is not None and prev["value"] > 0:
            p = prev["value"]
            if p >= collapse_from and v < 10:
                db.add_flag(conn, scope, obj_id, r["date"], "collapse",
                            f"{label}: {_n(p)} → {_n(v)} (previous record {_d(prev['date'])})")
            elif abs(v - p) / p * 100 > jump_pct:
                db.add_flag(conn, scope, obj_id, r["date"], "jump",
                            f"{label}: {_n(p)} → {_n(v)} ({(v - p) / p * 100:+.0f}%, previous record {_d(prev['date'])})")
        prev = r
    return conn.total_changes - before
