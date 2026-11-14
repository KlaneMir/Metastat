"""One place for the program's configuration: data\\metastat.json.

The file holds the general settings and the list of connections. A connection is a Meta account (a system
user token) or a test account from the simulator, with its own campaign list and its own database in
data\\connections\\<id>. The active connection is switched in the program. Tokens are encrypted (secure.py, DPAPI).
"""
from __future__ import annotations

import copy
import json
import os
import re
import secrets
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

import yaml

from metastat import paths, secure

DEFAULT_SETTINGS = {
    "graph_api_version": "v24.0",
    "timezone": "Europe/Warsaw",
    "backfill_since": "2026-09-01",
    "snapshot_window_days": 90,
    "fresh_hours": 168,
    "flags": {"follower_jump_pct": 20, "follower_collapse_from": 100},
    "images": {"report_width": 800, "jpeg_quality": 85},
    "metrics": {
        "fb_page_day": ["page_follows", "page_daily_follows_unique", "page_daily_unfollows_unique", "page_media_view",
                        "page_total_media_view_unique", "page_post_engagements", "page_actions_post_reactions_total",
                        "page_video_views"],
        "fb_post": ["post_media_view", "post_total_media_view_unique", "post_reactions_by_type_total",
                    "post_clicks_by_type", "post_video_views"],
        "ig_account_day": ["views", "reach", "accounts_engaged", "total_interactions", "likes", "comments", "shares",
                           "saves", "follows_and_unfollows"],
        "ig_media": ["views", "reach", "saved", "shares", "total_interactions", "likes", "comments"],
    },
    "breakdowns": {"fb_page_day": {"page_media_view": "is_from_ads"}, "fb_post": {"post_media_view": "is_from_ads"}},
}
EDITABLE = {  # settings changed in the program: key → (type, min, max)
    "graph_api_version": (str, None, None),
    "backfill_since": (str, None, None),
    "snapshot_window_days": (int, 7, 400),
    "fresh_hours": (int, 0, 720),
    "flags.follower_jump_pct": (int, 1, 1000),
    "flags.follower_collapse_from": (int, 1, 1_000_000),
}
_LOCK = threading.Lock()


class StoreError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slug(text: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", text.replace("ł", "l").replace("Ł", "L")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:50] or "campaign"


class Store:
    def __init__(self, home: Path | None = None):
        self.home = home or paths.home()
        self.path = self.home / "metastat.json"
        self.backup = self.home / "metastat.json.bak"

    def _recover(self, error: Exception) -> dict:
        """Broken file (e.g. a power cut while copying, a manual edit): fall back to the backup copy,
        and the broken file stays next to it for inspection. Without a backup: a clear error with the path."""
        try:
            data = _parse(self.backup)
        except (OSError, ValueError):
            raise StoreError(f"The settings file {self.path} is corrupt ({error}) and there is no backup. "
                             f"Rename this file to let the program start over (you will have to add the "
                             f"connections again; the data in the connections folder stays).") from error
        broken = self.home / f"metastat-corrupt-{datetime.now():%Y%m%d-%H%M%S}.json"
        try:
            os.replace(self.path, broken)
        except OSError:
            pass
        self._write(data)
        import logging
        logging.getLogger(__name__).warning("The settings file was corrupt (%s); restored the backup, broken file: %s", error, broken)
        return data

    # ---------- file ----------

    def load(self) -> dict:
        with _LOCK:
            if not self.path.exists():
                data = self._initial()
                if self._write(data, create=True):
                    return data
                # another process (e.g. a second click) wrote the file first: take its version
            try:
                data = _parse(self.path)
            except (OSError, ValueError) as e:
                data = self._recover(e)
        merged = copy.deepcopy(DEFAULT_SETTINGS)
        merged.update(data.get("settings") or {})
        data["settings"] = merged
        data.setdefault("connections", [])
        return data

    def save(self, data: dict) -> None:
        with _LOCK:
            self._write(data)

    def _write(self, data: dict, create: bool = False) -> bool:
        """Atomic write (an interrupted write does not break the file). create=True: only when the file does not exist yet."""
        paths.ensure_dir(self.home)
        fd, tmp = tempfile.mkstemp(dir=self.home, prefix=".metastat-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        if not create:
            if self.path.exists():  # the previous version as a backup (restored when the file gets broken)
                try:
                    _parse(self.path)
                    shutil.copyfile(self.path, self.backup)  # a copy, not a move: the main file exists all the time
                except (OSError, ValueError):
                    pass
            os.replace(tmp, self.path)
            return True
        try:
            os.rename(tmp, self.path)  # on Windows rename does not overwrite an existing file
            return True
        except FileExistsError:
            os.unlink(tmp)
            return False

    def _initial(self) -> dict:
        """First start (empty data folder).

        - demo mode: nothing is taken over (demo.setup adds the demo accounts);
        - the old config/campaigns.yaml layout (+ token from .env): the campaigns move to a "Meta campaigns" connection;
        - only a token in .env (META_SYSTEM_USER_TOKEN): a "Meta" connection without campaigns (pages are picked in the program).
        The token goes into metastat.json encrypted right away (DPAPI); it can be removed from .env afterwards.
        """
        data = {"version": 1, "settings": copy.deepcopy(DEFAULT_SETTINGS), "connections": [], "active": None}
        if paths.demo():
            return data
        # from source: <project>\config; from an EXE in a folder next to the project: also <parent folder>\metastat\config
        candidates = [paths.app_dir() / "config", paths.app_dir().parent / "metastat" / "config"]
        legacy = next((c for c in candidates if (c / "campaigns.yaml").is_file()), candidates[0])
        if (legacy / "settings.yaml").is_file():
            s = yaml.safe_load((legacy / "settings.yaml").read_text(encoding="utf-8-sig")) or {}
            for k in DEFAULT_SETTINGS:
                if k in s and k not in ("metrics", "breakdowns"):
                    data["settings"][k] = s[k]
        token = _env_token(legacy.parent / ".env")
        camps = []
        if (legacy / "campaigns.yaml").is_file():
            camps = (yaml.safe_load((legacy / "campaigns.yaml").read_text(encoding="utf-8-sig")) or {}).get("campaigns") or []
        if camps or token:
            conn = self._new_conn("Meta campaigns" if camps else "Meta", "meta", token)
            conn["campaigns"] = clean_campaigns(camps)
            data["connections"].append(conn)
            data["active"] = conn["id"]
        return data

    # ---------- connections ----------

    def _new_conn(self, name: str, kind: str, token: str | None, **extra) -> dict:
        return {"id": f"{kind}-{secrets.token_hex(3)}", "name": name.strip() or "Connection", "kind": kind,
                "token": secure.encrypt(token) if token else None, "created_utc": _now(), "campaigns": [], **extra}

    def connections(self) -> list[dict]:
        return self.load()["connections"]

    def get(self, conn_id: str | None) -> dict | None:
        return next((c for c in self.connections() if c["id"] == conn_id), None)

    def active(self) -> dict | None:
        data = self.load()
        conn = next((c for c in data["connections"] if c["id"] == data.get("active")), None)
        return conn or (data["connections"][0] if data["connections"] else None)

    def set_active(self, conn_id: str) -> None:
        data = self.load()
        if not any(c["id"] == conn_id for c in data["connections"]):
            raise StoreError("No such connection.")
        data["active"] = conn_id
        self.save(data)

    def add(self, name: str, kind: str, token: str | None, campaigns: list | None = None, **extra) -> dict:
        data = self.load()
        conn = self._new_conn(name, kind, token, **extra)
        conn["campaigns"] = clean_campaigns(campaigns or [])
        data["connections"].append(conn)
        data["active"] = conn["id"]
        self.save(data)
        return conn

    def update(self, conn_id: str, **fields) -> dict:
        data = self.load()
        conn = next((c for c in data["connections"] if c["id"] == conn_id), None)
        if not conn:
            raise StoreError("No such connection.")
        if "token" in fields:
            fields["token"] = secure.encrypt(fields["token"]) if fields["token"] else None
        if "campaigns" in fields:
            fields["campaigns"] = clean_campaigns(fields["campaigns"])
        if "name" in fields:
            fields["name"] = str(fields["name"]).strip()[:80] or conn["name"]
        conn.update(fields)
        self.save(data)
        return conn

    def remove(self, conn_id: str) -> None:
        """Removes the connection from the list. Its data (database, images, reports) stays in the connection folder."""
        data = self.load()
        data["connections"] = [c for c in data["connections"] if c["id"] != conn_id]
        if data.get("active") == conn_id:
            data["active"] = data["connections"][0]["id"] if data["connections"] else None
        self.save(data)

    def token(self, conn: dict) -> str | None:
        return secure.decrypt(conn.get("token"))

    def conn_dir(self, conn_id: str) -> Path:
        return self.home / "connections" / re.sub(r"[^a-zA-Z0-9_-]", "_", conn_id)

    # ---------- settings ----------

    def update_settings(self, values: dict) -> dict:
        data = self.load()
        for key, raw in values.items():
            if key not in EDITABLE:
                continue
            typ, lo, hi = EDITABLE[key]
            try:
                v = typ(str(raw).strip())
            except ValueError as e:
                raise StoreError(f"Invalid value: {key}") from e
            if typ is int and not (lo <= v <= hi):
                raise StoreError(f"{key}: allowed {lo}–{hi}")
            if key == "graph_api_version" and not re.fullmatch(r"v\d{1,2}\.\d", v):
                raise StoreError("The Graph API version looks like v24.0")
            if key == "backfill_since":
                try:
                    day = datetime.strptime(v, "%Y-%m-%d").date()
                except ValueError:
                    raise StoreError("\"History from\": enter a real date as YYYY-MM-DD.") from None
                if not (2004 <= day.year and day <= datetime.now(timezone.utc).date()):
                    raise StoreError("\"History from\": the date must be in the past (2004 or later).")
            target = data["settings"]
            *parents, leaf = key.split(".")
            for p in parents:
                target = target.setdefault(p, {})
            target[leaf] = v
        self.save(data)
        return data["settings"]


def _env_token(env: Path) -> str | None:
    """META_SYSTEM_USER_TOKEN from the .env file (optional, only on the first start)."""
    if not env.is_file():
        return None
    from dotenv import dotenv_values
    token = "".join(str(dotenv_values(env).get("META_SYSTEM_USER_TOKEN") or "").split())
    return token if re.fullmatch(r"[A-Za-z0-9|._\-]{20,2048}", token) else None


def _parse(path: Path) -> dict:
    # utf-8-sig: a file saved in Notepad or PowerShell starts with a BOM; that is not corruption
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or not isinstance(data.get("connections", []), list):
        raise ValueError("unexpected content")
    return data


def clean_campaigns(items: list[dict]) -> list[dict]:
    """The campaign list after validation; repeated IDs get a -2, -3… suffix."""
    out, seen = [], set()
    for c in items:
        c = _clean_campaign(c)
        base, n = c["id"], 2
        while c["id"] in seen:
            c["id"] = f"{base}-{n}"
            n += 1
        seen.add(c["id"])
        out.append(c)
    return out


# the same limits as maxlength in the forms; enforced here too, because a browser limit is not a control
CAMPAIGN_NAME_MAX = 120
CAMPAIGN_LABEL_MAX = 20


def _clean_campaign(c: dict) -> dict:
    """A campaign from the config or a form: known fields only, ID as text, IG name without @."""
    name = str(c.get("name") or "").strip()[:CAMPAIGN_NAME_MAX].strip()
    if not name:
        raise StoreError("A campaign needs a name.")
    page = str(c.get("fb_page_id") or "").strip() or None
    if page and not page.isdigit():
        raise StoreError(f"A Facebook page ID is digits only (campaign \"{name}\").")
    ig = str(c.get("ig_username") or "").strip().lstrip("@").lower() or None
    if ig and not re.fullmatch(r"[a-z0-9._]{1,30}", ig):
        raise StoreError(f"Invalid IG account name (campaign \"{name}\").")
    cid = str(c.get("id") or "").strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", cid):  # the ID goes into page URLs and the database
        cid = slug(cid or name)
    return {
        "id": cid,
        "name": name,
        "label": (str(c["label"]).strip()[:CAMPAIGN_LABEL_MAX].strip() or None) if c.get("label") else None,
        "status": c.get("status") if c.get("status") in ("active", "ended") else "active",
        "fb_page_id": page,
        "ig_username": ig,
        "ig_skip": bool(c.get("ig_skip")),
    }
