"""A sync run: all campaigns, FB and IG, with the run and its errors recorded.

An error in one campaign does not stop the others. A token error stops everything,
because without a token no further campaign can succeed.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from metastat import db, sync_fb, sync_ig
from metastat.config import Settings
from metastat.context import Ctx
from metastat.graph import Graph, GraphError, TokenError
from metastat.images import ImageStore

log = logging.getLogger(__name__)


def save_campaigns(conn, s: Settings) -> None:
    for c in s.campaigns:
        db.upsert(conn, "campaigns", {
            "id": c.id, "name": c.name, "label": c.label, "status": c.status,
            "fb_page_id": c.fb_page_id, "ig_username": c.ig_username, "updated_utc": db.now_utc(),
        }, ["id"])
    conn.commit()


def run(s: Settings, *, fresh: bool = False, only: list[str] | None = None,
        graph: Graph | None = None, http: httpx.Client | None = None, now: datetime | None = None) -> int:
    """Returns an exit code: 0 all ok, 1 some campaigns with errors, 2 token error / no token."""
    conn = db.connect(s.db_path)
    save_campaigns(conn, s)
    mode = "fresh" if fresh else "daily"
    when = now.astimezone(timezone.utc).replace(microsecond=0).isoformat() if now else None  # simulated time in the test history
    run_id = db.start_run(conn, mode, when)

    selected = [c for c in s.campaigns if not only or c.id in only]
    unknown = set(only or []) - {c.id for c in s.campaigns}
    if unknown:
        log.warning("Unknown campaign ids (skipped): %s", ", ".join(sorted(unknown)))

    try:
        graph = graph or Graph(s.token, s.graph_api_version, base=s.graph_base_url)
    except TokenError as e:
        log.error("%s", e)
        db.finish_run(conn, run_id, "failed", 0, {}, str(e), when=when)
        return 2

    images = ImageStore(s.data_dir, conn, client=http or (graph.client if graph.fake else None),
                        report_width=int(s.images.get("report_width", 800)),
                        jpeg_quality=int(s.images.get("jpeg_quality", 85)))
    ctx = Ctx(s=s, graph=graph, conn=conn, images=images, now=now or datetime.now(timezone.utc))

    status = "ok"
    results: dict[str, dict] = {}
    log.info("Sync started (%s): %s campaigns", mode, len(selected))
    try:
        for camp in selected:
            r: dict = {}
            if camp.ig_username and camp.ig_skip:
                r["ig"] = {"skipped": "Instagram skipped in the campaign settings"}
            parts = (("fb", sync_fb.sync_page, camp.fb_page_id),
                     ("ig", sync_ig.sync_account, camp.ig_username and not camp.ig_skip))
            for part, fn, needed in parts:
                if not needed:
                    continue
                try:
                    r[part] = fn(ctx, camp, fresh)
                    conn.commit()
                    log.info("%s / %s: %s", camp.name, part.upper(), r[part])
                except TokenError:
                    conn.rollback()
                    raise
                except GraphError as e:
                    conn.rollback()
                    # the "IG not found" flag is saved even though the rest is rolled back
                    if isinstance(e, sync_ig.IgNotFound):
                        db.add_flag(conn, "campaign", camp.id, ctx.today.isoformat(), "ig_not_found", str(e))
                        conn.commit()
                    r[part] = {"error": str(e)}
                    status = "partial"
                    log.error("%s / %s: %s", camp.name, part.upper(), e)
                except Exception as e:  # the other campaigns keep going
                    conn.rollback()
                    r[part] = {"error": f"{type(e).__name__}: {e}"}
                    status = "partial"
                    log.exception("%s / %s: unexpected error", camp.name, part.upper())
            results[camp.id] = r
    except TokenError as e:
        log.error("%s", e)
        db.finish_run(conn, run_id, "failed", graph.calls, results, str(e), when=when)
        return 2

    summary = {"campaigns": results, "images_downloaded": images.downloaded, "images_failed": images.failed}
    db.finish_run(conn, run_id, status, graph.calls, summary, when=when)
    log.info("Sync finished: %s, API requests: %s, new images: %s", status, graph.calls, images.downloaded)
    conn.close()
    return 0 if status == "ok" else 1
