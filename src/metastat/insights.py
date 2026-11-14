"""Fetching insights metrics in a way that survives renames on Meta's side.

All metrics in the list go in one request. When Meta rejects one of them, each is requested separately,
and the ones that no longer exist are remembered in the metric_support table so they are not requested again.
"""
from __future__ import annotations

import logging
import sqlite3

from metastat import db
from metastat.graph import Graph, GraphError, MetricError

log = logging.getLogger(__name__)


def _value(item: dict):
    if "total_value" in item:
        return (item["total_value"] or {}).get("value")
    values = item.get("values") or []
    return values[0].get("value") if values else None


def _query(graph: Graph, object_id: str, metrics: list[str], params: dict, token: str | None) -> list[dict]:
    body = graph.get(f"{object_id}/insights", {**params, "metric": ",".join(metrics)}, token=token)
    return body.get("data") or []


def _with_fallback(graph: Graph, conn: sqlite3.Connection, scope: str, object_id: str,
                   metrics: list[str], params: dict, token: str | None) -> list[dict]:
    candidates = [m for m in metrics if db.supported(conn, scope, m) is not False]
    if not candidates:
        return []
    try:
        data = _query(graph, object_id, candidates, params, token)
        for m in candidates:
            if db.supported(conn, scope, m) is None:
                db.set_support(conn, scope, m, True)
        return data
    except MetricError as e:
        log.info("%s: Meta rejected the metric set (%s), checking each metric separately", scope, e)
    except GraphError as e:
        if e.code != 100:
            raise
        log.info("%s: error #100 for the metric set (%s), checking each metric separately", scope, e)

    data: list[dict] = []
    for m in candidates:
        try:
            data += _query(graph, object_id, [m], params, token)
            db.set_support(conn, scope, m, True)
        except MetricError as e:
            db.set_support(conn, scope, m, False, str(e))
            log.warning("%s: metric %s unavailable: %s", scope, m, e)
        except GraphError as e:
            if e.code != 100:
                raise
            # #100 without the word "metric" usually concerns a specific object, so the metric is not turned off for good.
            log.warning("%s: %s skipped for %s: %s", scope, m, object_id, e)
    return data


def values(graph: Graph, conn: sqlite3.Connection, scope: str, object_id: str, metrics: list[str],
           params: dict | None = None, token: str | None = None) -> dict:
    """One value per metric (post lifetime or total_value for the period)."""
    data = _with_fallback(graph, conn, scope, object_id, metrics, params or {}, token)
    return {item["name"]: _value(item) for item in data if "name" in item}


def series(graph: Graph, conn: sqlite3.Connection, scope: str, object_id: str, metrics: list[str],
           params: dict, token: str | None = None) -> dict[str, list[tuple[str, object]]]:
    """Daily series: {metric: [(end_time, value), ...]}."""
    data = _with_fallback(graph, conn, scope, object_id, metrics, params, token)
    return {item["name"]: [(v.get("end_time"), v.get("value")) for v in item.get("values") or []]
            for item in data if "name" in item}


# ---------- paid / organic split ----------

def _is_paid(dim) -> bool | None:
    s = str(dim).strip().lower()
    if s in ("1", "true", "yes", "paid"):
        return True
    if s in ("0", "false", "no", "organic", "unpaid"):
        return False
    return None


def split_paid(item: dict) -> dict | None:
    """Extracts {'paid': x, 'organic': y} from a breakdown=is_from_ads response.

    Meta returns the split in two shapes (total_value.breakdowns or a dict in values);
    both are handled. For any other shape it returns None, and the raw response stays in the database.
    """
    out = {}
    tv = item.get("total_value") or {}
    for b in tv.get("breakdowns") or []:
        for r in b.get("results") or []:
            paid = _is_paid((r.get("dimension_values") or [None])[0])
            if paid is not None:
                out["paid" if paid else "organic"] = out.get("paid" if paid else "organic", 0) + float(r.get("value") or 0)
    if not out:
        v = _value(item)
        if isinstance(v, dict):
            for k, x in v.items():
                paid = _is_paid(k)
                if paid is not None and isinstance(x, (int, float)):
                    out["paid" if paid else "organic"] = out.get("paid" if paid else "organic", 0) + float(x)
    return out or None


def paid_split(graph: Graph, conn: sqlite3.Connection, scope: str, object_id: str, metric: str, breakdown: str,
               params: dict | None = None, token: str | None = None) -> tuple[dict | None, list | None]:
    """(split, raw data). When the API does not support the split, remembers that and returns (None, None)."""
    key = f"{metric}:{breakdown}"
    bscope = scope + ":breakdown"
    if db.supported(conn, bscope, key) is False:
        return None, None
    try:
        data = _query(graph, object_id, [metric], {**(params or {}), "breakdown": breakdown}, token)
    except GraphError as e:
        if e.code != 100:
            raise
        db.set_support(conn, bscope, key, False, str(e))
        log.warning("%s: split %s unavailable: %s", scope, key, e)
        return None, None
    db.set_support(conn, bscope, key, True)
    split = split_paid(data[0]) if data else None
    return split, data
