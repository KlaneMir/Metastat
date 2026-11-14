"""Error summary across sync runs: the same problem is shown once, with how long it has lasted."""
from __future__ import annotations

import json
import sqlite3


def run_errors(summary: dict) -> list[tuple[str, str, str]]:
    """[(campaign id, platform, message)] from the summary of one run."""
    out = []
    for camp, parts in (summary.get("campaigns") or {}).items():
        for part, res in (parts or {}).items():
            if isinstance(res, dict) and res.get("error"):
                out.append((camp, part, res["error"]))
    return out


def problems(conn: sqlite3.Connection, limit: int = 500) -> dict:
    """{'current': [...], 'resolved': [...]}: problems from the latest run and the ones that are gone.

    Each problem: campaign, part, error, first (first run with this error), last, count (number of runs).
    """
    rows = conn.execute("SELECT id, started_utc, status, summary FROM sync_runs WHERE status != 'running' "
                        "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()[::-1]
    seen: dict[tuple, dict] = {}
    for r in rows:
        for camp, part, err in run_errors(json.loads(r["summary"] or "{}")):
            p = seen.setdefault((camp, part, err), {"campaign": camp, "part": part, "error": err,
                                                    "first": r["started_utc"], "count": 0})
            p["count"] += 1
            p["last"] = r["started_utc"]
    latest = set(run_errors(json.loads(rows[-1]["summary"] or "{}"))) if rows else set()
    current = [p for k, p in seen.items() if k in latest]
    resolved = [p for k, p in seen.items() if k not in latest]
    return {"current": sorted(current, key=lambda p: p["first"]),
            "resolved": sorted(resolved, key=lambda p: p["last"], reverse=True)[:10]}
