"""Checks a Meta token pasted into the program and lists the pages to import as campaigns."""
from __future__ import annotations

import re

import httpx

from metastat.graph import Graph, GraphError, TokenError

# The same permissions that the check in probe.py requires.
REQUIRED = ["pages_show_list", "pages_read_engagement", "read_insights", "instagram_basic",
            "instagram_manage_insights", "business_management"]
TOKEN_RE = re.compile(r"[A-Za-z0-9|._\-]{20,2048}")


class ConnectError(Exception):
    pass


def clean_token(raw: str) -> str:
    token = "".join(str(raw or "").split())  # a pasted token is sometimes broken over several lines
    if not TOKEN_RE.fullmatch(token):
        raise ConnectError("This does not look like a Meta token. Copy the whole token (it usually starts with \"EAA\").")
    return token


def _graph(token: str, version: str, base: str | None) -> Graph:
    return Graph(token, version, base=base, max_tries=2, sleep=lambda _s: None)


def check(token: str, version: str, base: str | None = None) -> dict:
    """Token owner, missing permissions and pages. Raises ConnectError with a readable description."""
    g = _graph(token, version, base)
    try:
        me = g.get("me", {"fields": "id,name"})
        try:
            perms = {p["permission"]: p["status"] for p in g.get("me/permissions").get("data", [])}
        except GraphError:
            perms = {}  # a page token has no /me/permissions; missing permissions will show up with the pages
        found = pages(g)
    except TokenError as e:
        raise ConnectError(f"Meta rejected the token: {e}") from e
    except GraphError as e:
        raise ConnectError(f"Meta returned an error: {e}") from e
    except httpx.HTTPError as e:
        raise ConnectError("Could not connect to Meta. Check your internet connection and try again.") from e
    return {"name": me.get("name") or me.get("id"), "id": me.get("id"),
            "missing": [p for p in REQUIRED if perms and perms.get(p) != "granted"], "pages": found}


def pages(g: Graph) -> list[dict]:
    out = []
    for p in g.paginate("me/accounts", {"fields": "id,name,instagram_business_account{id,username}", "limit": 100}):
        ig = (p.get("instagram_business_account") or {}).get("username")
        out.append({"id": str(p["id"]), "name": p.get("name") or str(p["id"]), "ig": ig.lower() if ig else None})
    return sorted(out, key=lambda p: p["name"].lower())


def list_pages(token: str, version: str, base: str | None = None) -> list[dict]:
    try:
        return pages(_graph(token, version, base))
    except TokenError as e:
        raise ConnectError(f"Meta rejected the token: {e}") from e
    except GraphError as e:
        raise ConnectError(f"Meta returned an error: {e}") from e
    except httpx.HTTPError as e:
        raise ConnectError("Could not connect to Meta. Check your internet connection and try again.") from e
