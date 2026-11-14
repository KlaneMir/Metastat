"""SQLite: connection, schema and simple writes (upsert)."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path

SCHEMA_VERSION = 1


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(path: Path | str, *, any_thread: bool = False, schema: bool = True) -> sqlite3.Connection:
    """any_thread: a connection for one server request, which FastAPI passes between threads (never in parallel).
    schema=False: read-only for the program's pages; the program creates the schema earlier, when a connection is
    picked, so a page opened during a sync does not wait for the write lock (in WAL mode reads never wait for writes)."""
    if str(path) != ":memory:":
        from metastat.paths import ensure_dir
        ensure_dir(Path(path).parent)
    conn = sqlite3.connect(path, check_same_thread=not any_thread, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if schema:
        conn.execute("PRAGMA journal_mode = WAL")
        migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version < 1:
        conn.executescript(resources.files("metastat").joinpath("schema.sql").read_text(encoding="utf-8"))
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()


def upsert(conn: sqlite3.Connection, table: str, row: dict, keys: list[str], *, keep: tuple[str, ...] = ()) -> None:
    """INSERT or UPDATE by key. Columns in `keep` are not overwritten on update (e.g. first_seen)."""
    cols = list(row)
    updates = [c for c in cols if c not in keys and c not in keep]
    sql = (f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "  # nosec B608
           f"ON CONFLICT ({', '.join(keys)}) DO ")
    sql += ("UPDATE SET " + ", ".join(f"{c} = excluded.{c}" for c in updates)) if updates else "NOTHING"  # nosec B608
    conn.execute(sql, [row[c] for c in cols])


def to_raw(value) -> str | None:
    return None if value is None or isinstance(value, (int, float)) else json.dumps(value, ensure_ascii=False)


def metric_rows(values: dict) -> list[tuple[str, float | None, str | None]]:
    """{metric: value} → (metric, number, raw). Dicts (e.g. reactions by type) are summed; the original stays in raw."""
    out = []
    for name, v in values.items():
        if isinstance(v, dict):
            num = sum(float(x) for x in v.values() if isinstance(x, (int, float)))
        elif isinstance(v, (int, float)):
            num = float(v)
        elif v is None:
            num = None
        else:
            try:
                num = float(v)
            except (TypeError, ValueError):
                num = None
        raw = v if isinstance(v, str) and num is None else to_raw(v) if not isinstance(v, str) else None
        out.append((name, num, raw))
    return out


def save_snapshot(conn: sqlite3.Connection, table: str, id_col: str, obj_id: str, taken_utc: str, values: dict) -> None:
    conn.executemany(
        f"INSERT OR REPLACE INTO {table} ({id_col}, taken_utc, metric, value, raw) VALUES (?, ?, ?, ?, ?)",
        [(obj_id, taken_utc, m, v, r) for m, v, r in metric_rows(values)],
    )


def save_daily(conn: sqlite3.Connection, table: str, id_col: str, obj_id: str, date: str, values: dict, source: str) -> None:
    ts = now_utc()
    conn.executemany(
        f"INSERT OR REPLACE INTO {table} ({id_col}, date, metric, value, raw, source, fetched_utc) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(obj_id, date, m, v, r, source, ts) for m, v, r in metric_rows(values)],
    )


# ---------- handling metrics that Meta retired ----------

def supported(conn: sqlite3.Connection, scope: str, metric: str) -> bool | None:
    row = conn.execute("SELECT ok FROM metric_support WHERE scope = ? AND metric = ?", (scope, metric)).fetchone()
    return None if row is None else bool(row["ok"])


def set_support(conn: sqlite3.Connection, scope: str, metric: str, ok: bool, error: str | None = None) -> None:
    upsert(conn, "metric_support",
           {"scope": scope, "metric": metric, "ok": int(ok), "error": error, "checked_utc": now_utc()},
           ["scope", "metric"])


# ---------- runs and flags ----------

def start_run(conn: sqlite3.Connection, mode: str, when: str | None = None) -> int:
    """`when` allows storing a simulated time (history in test folders)."""
    cur = conn.execute("INSERT INTO sync_runs (mode, started_utc, status) VALUES (?, ?, 'running')", (mode, when or now_utc()))
    conn.commit()
    return cur.lastrowid


def finish_run(conn: sqlite3.Connection, run_id: int, status: str, api_calls: int, summary: dict,
               error: str | None = None, when: str | None = None) -> None:
    conn.execute(
        "UPDATE sync_runs SET finished_utc = ?, status = ?, api_calls = ?, summary = ?, error = ? WHERE id = ?",
        (when or now_utc(), status, api_calls, json.dumps(summary, ensure_ascii=False), error, run_id),
    )
    conn.commit()


def add_flag(conn: sqlite3.Connection, scope: str, object_id: str, date: str, kind: str, detail: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO flags (scope, object_id, date, kind, detail, created_utc) VALUES (?, ?, ?, ?, ?, ?)",
        (scope, object_id, date, kind, detail, now_utc()),
    )
