"""Stage 0: check with a real token what Meta actually provides.

Checks the token and permissions, the visibility of the pages and IG accounts from campaigns.yaml, and every
metric from settings.yaml separately. Saves the result to data/probe-YYYYMMDD-HHMM.json and to the
metric_support table, which the sync uses.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Callable

from metastat import db, insights
from metastat.config import Settings
from metastat.connect import REQUIRED
from metastat.graph import Graph, GraphError, TokenError
from metastat.paths import ensure_dir
from metastat.timeutil import day_start_unix, local_date

OPTIONAL = ["pages_read_user_content", "ads_read"]


def _short(v) -> str:
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    return s if len(s) <= 160 else s[:157] + "…"


def _test_metrics(g: Graph, conn, scope: str, object_id: str, metrics: list[str], params: dict,
                  token: str | None, out: Callable) -> dict:
    res = {}
    for m in metrics:
        try:
            data = insights._query(g, object_id, [m], params, token)
            sample = [{k: item.get(k) for k in ("values", "total_value") if k in item} for item in data]
            res[m] = {"ok": True, "sample": sample}
            db.set_support(conn, scope, m, True)
            out(f"   OK    {m:34} {_short(sample)}")
        except TokenError:
            raise
        except GraphError as e:
            res[m] = {"ok": False, "error": str(e), "code": e.code}
            db.set_support(conn, scope, m, False, str(e))
            out(f"   NO    {m:34} {_short(str(e))}")
    conn.commit()
    return res


def _test_breakdowns(g: Graph, conn, scope: str, object_id: str, breakdowns: dict, params: dict,
                     token: str | None, out: Callable) -> dict:
    res = {}
    for metric, bd in breakdowns.items():
        split, raw = insights.paid_split(g, conn, scope, object_id, metric, bd, params, token)
        key = f"{metric} + breakdown={bd}"
        if raw is None:
            res[key] = {"ok": False}
            out(f"   NO    {key}: the API gives no paid/organic split")
        else:
            res[key] = {"ok": bool(split), "split": split, "raw": raw}
            out(f"   {'OK' if split else '???':5} {key}: {split if split else 'unknown response shape'} | {_short(raw)}")
    conn.commit()
    return res


def run(s: Settings, *, graph: Graph | None = None, out: Callable[[str], None] = print) -> int:
    conn = db.connect(s.db_path)
    g = graph or Graph(s.token, s.graph_api_version, base=s.graph_base_url)
    now = datetime.now(timezone.utc)
    today = local_date(now, s.tz)
    rep: dict = {"time_utc": db.now_utc(), "configured_version": s.graph_api_version}
    problems = 0

    out("== Token ==")
    me = g.get("me", {"fields": "id,name"})
    out(f"Token owner: {me.get('name')} (id {me.get('id')})")
    try:
        r = g.client.get(g.base + "me", params={"fields": "id"}, headers={"Authorization": f"Bearer {g.token}"})
        default_version = r.headers.get("facebook-api-version")
    except Exception:
        default_version = None
    rep["default_version"] = default_version
    out(f"Configured API version: {s.graph_api_version}; your app's default version: {default_version or 'unknown'}")

    try:
        perms = {p["permission"]: p["status"] for p in g.get("me/permissions").get("data", [])}
    except GraphError as e:
        perms = {}
        out(f"Could not read the permissions: {e}")
    rep["permissions"] = perms
    missing = [p for p in REQUIRED if perms and perms.get(p) != "granted"]
    if missing:
        problems += 1
        out("MISSING permissions: " + ", ".join(missing))
    elif perms:
        out("Required permissions: all granted.")
    opt = [p for p in OPTIONAL if perms.get(p) != "granted"]
    if perms and opt:
        out("Optional, not granted: " + ", ".join(opt) + " (pages_read_user_content helps with comments under posts)")

    out("")
    out("== Campaigns ==")
    pages = {p["id"]: p for p in g.paginate("me/accounts", {"fields": "id,name,instagram_business_account{id,username}", "limit": 100})}
    igs = {p["instagram_business_account"]["username"].lower(): p for p in pages.values()
           if (p.get("instagram_business_account") or {}).get("username")}
    rep["campaigns"] = []
    sample_page = sample_ig = None
    for c in s.campaigns:
        row = {"id": c.id}
        fb = "–"
        if c.fb_page_id:
            if c.fb_page_id in pages:
                fb = f"OK ({pages[c.fb_page_id]['name']})"
                sample_page = sample_page or c.fb_page_id
                linked = (pages[c.fb_page_id].get("instagram_business_account") or {}).get("username")
                if c.ig_username and linked and linked.lower() != c.ig_username:
                    fb += f", but the linked IG is @{linked}, while the config says @{c.ig_username}"
            else:
                fb = "MISSING: the page is not assigned to the system user"
                problems += 1
        ig = "–"
        if c.ig_username:
            if c.ig_username in igs:
                ig = f"OK (id {igs[c.ig_username]['instagram_business_account']['id']})"
                sample_ig = sample_ig or igs[c.ig_username]["instagram_business_account"]["id"]
            else:
                ig = "MISSING: the account is not a business account, is not linked to a page, or the page is not assigned"
                problems += 1
        row.update(fb=fb, ig=ig)
        rep["campaigns"].append(row)
        out(f"{c.name}\n   FB: {fb}\n   IG: {ig}")

    conn.execute("DELETE FROM metric_support")  # check from scratch
    rep["metrics"] = {}
    out("")
    out("== Facebook metrics (page, daily) ==")
    if sample_page:
        token = g.page_token(sample_page)
        params = {"period": "day", "since": (today - timedelta(days=4)).isoformat(), "until": today.isoformat()}
        rep["metrics"]["fb_page_day"] = _test_metrics(g, conn, "fb_page_day", sample_page,
                                                      s.metrics.get("fb_page_day") or [], params, token, out)
        rep["metrics"]["fb_page_day_breakdowns"] = _test_breakdowns(
            g, conn, "fb_page_day", sample_page, s.breakdowns.get("fb_page_day") or {}, params, token, out)

        out("== Facebook metrics (post) ==")
        posts = g.get(f"{sample_page}/posts", {"fields": "id,created_time", "limit": 3}, token=token).get("data") or []
        if posts:
            pid = posts[0]["id"]
            out(f"   (post {pid} from {posts[0]['created_time']})")
            rep["metrics"]["fb_post"] = _test_metrics(g, conn, "fb_post", pid, s.metrics.get("fb_post") or [], {}, token, out)
            rep["metrics"]["fb_post_breakdowns"] = _test_breakdowns(
                g, conn, "fb_post", pid, s.breakdowns.get("fb_post") or {}, {}, token, out)
        else:
            out("   No posts on the sample page.")
    else:
        out("   None of the configured pages is accessible, skipping.")

    out("")
    out("== Instagram metrics (account, daily) ==")
    if sample_ig:
        y = today - timedelta(days=1)
        params = {"period": "day", "metric_type": "total_value", "since": day_start_unix(y, s.tz), "until": day_start_unix(today, s.tz)}
        rep["metrics"]["ig_account_day"] = _test_metrics(g, conn, "ig_account_day", sample_ig,
                                                         s.metrics.get("ig_account_day") or [], params, None, out)
        rep["metrics"]["ig_account_series"] = _test_metrics(
            g, conn, "ig_account_series", sample_ig, ["follower_count"],
            {"period": "day", "since": day_start_unix(today - timedelta(days=7), s.tz), "until": day_start_unix(today, s.tz)}, None, out)

        out("== Instagram metrics (posts, by type) ==")
        media = g.get(f"{sample_ig}/media", {"fields": "id,media_type,media_product_type,timestamp", "limit": 25}).get("data") or []
        seen = set()
        for m in media:
            kind = m.get("media_product_type") or "FEED"
            if kind in seen:
                continue
            seen.add(kind)
            out(f"   [{kind} / {m.get('media_type')}] post {m['id']} from {m.get('timestamp')}")
            rep["metrics"][f"ig_media:{kind}"] = _test_metrics(g, conn, f"ig_media:{kind}", m["id"],
                                                                s.metrics.get("ig_media") or [], {}, None, out)
    else:
        out("   None of the configured IG accounts is accessible, skipping.")

    ensure_dir(s.data_dir)
    path = s.data_dir / f"probe-{datetime.now(s.tz):%Y%m%d-%H%M}.json"
    path.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    out("")
    out(f"API requests: {g.calls}. Full result: {path}")
    out("Problems to fix: " + (str(problems) if problems else "none"))
    conn.close()
    return 1 if problems else 0
