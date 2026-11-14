"""Program settings: from data\\metastat.json (store.py) or from the old config/*.yaml + .env layout."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from dotenv import dotenv_values


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Campaign:
    id: str
    name: str
    label: str | None
    status: str
    fb_page_id: str | None
    ig_username: str | None
    ig_skip: bool = False   # known problem with the IG account: sync skips it and reports no error


@dataclass
class Settings:
    root: Path
    graph_api_version: str
    graph_base_url: str
    tz: ZoneInfo
    data_dir: Path
    log_dir: Path
    backfill_since: str
    snapshot_window_days: int
    fresh_hours: int
    flags: dict
    images: dict
    metrics: dict
    breakdowns: dict
    campaigns: list[Campaign]
    token: str | None
    connection: dict | None = None   # active connection (single-program mode); None in old YAML folders
    home: Path | None = None         # the program's data folder (data\)

    @property
    def fake(self) -> bool:
        return self.graph_base_url == "fake"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "metastat.sqlite"

    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"


def find_root(start: Path | None = None) -> Path:
    """Project folder: METASTAT_HOME or the first folder upwards that has config/settings.yaml."""
    env = os.environ.get("METASTAT_HOME")
    if env:
        return Path(env).resolve()
    here = (start or Path.cwd()).resolve()
    for p in [here, *here.parents]:
        if (p / "config" / "settings.yaml").is_file():
            return p
    raise ConfigError("config/settings.yaml not found. Run the program from the project folder or set METASTAT_HOME.")


def _read_yaml(path: Path) -> dict:
    if not path.is_file():
        raise ConfigError(f"File not found: {path}")
    with path.open(encoding="utf-8-sig") as f:  # BOM from Notepad
        return yaml.safe_load(f) or {}


def load(root: Path | None = None, connection: str | None = None) -> Settings:
    """Settings of the active connection from data\\metastat.json.

    The old config/*.yaml layout (test folders, tests) is still supported: when `root`
    or the METASTAT_HOME variable is given.
    """
    if root is None and not os.environ.get("METASTAT_HOME"):
        return load_store(connection)
    return load_legacy(root)


def _campaign(raw: dict) -> Campaign:
    return Campaign(id=raw["id"], name=raw["name"], label=raw.get("label"), status=raw.get("status") or "active",
                    fb_page_id=raw.get("fb_page_id"), ig_username=raw.get("ig_username"), ig_skip=bool(raw.get("ig_skip")))


def load_store(connection: str | None = None, home: Path | None = None) -> Settings:
    from metastat import paths, secure, store
    st = store.Store(home)
    data = st.load()
    conn = st.get(connection) if connection else st.active()
    if connection and not conn:
        raise ConfigError(f"There is no connection {connection}.")
    s = {**data["settings"], **((conn or {}).get("settings") or {})}  # a connection can override e.g. backfill_since
    token = None
    if conn:
        try:
            token = st.token(conn)
        except secure.SecureError:
            token = None  # the program shows in Settings that the token has to be pasted again
    data_dir = st.conn_dir(conn["id"]) if conn else st.home / "connections" / "_none"
    d = store.DEFAULT_SETTINGS

    def num(key: str) -> int:  # a value broken by hand in the file: the default instead of a crash
        try:
            return int(s.get(key))
        except (TypeError, ValueError):
            return int(d[key])

    def section(key: str) -> dict:
        return s[key] if isinstance(s.get(key), dict) else d[key]

    try:
        tz = ZoneInfo(str(s.get("timezone") or d["timezone"]))
    except (KeyError, ValueError, OSError):  # unknown zone (ZoneInfoNotFoundError is a KeyError) or a bad name
        tz = ZoneInfo(d["timezone"])
    return Settings(
        root=paths.app_dir(),
        graph_api_version=str(s.get("graph_api_version") or d["graph_api_version"]),
        graph_base_url="fake" if conn and conn.get("kind") == "fake" else "https://graph.facebook.com/",
        tz=tz,
        data_dir=data_dir,
        log_dir=st.home / "logs",
        backfill_since=str(s.get("backfill_since") or ""),
        snapshot_window_days=num("snapshot_window_days"),
        fresh_hours=num("fresh_hours"),
        flags=section("flags"),
        images=section("images"),
        metrics=section("metrics"),
        breakdowns=section("breakdowns"),
        campaigns=[_campaign(c) for c in (conn or {}).get("campaigns", [])],
        token=token,
        connection=conn,
        home=st.home,
    )


def load_legacy(root: Path | None = None) -> Settings:
    root = root or find_root()
    # .env from the project folder takes precedence (test folders have their own tokens); os.environ is not changed
    env = {**os.environ, **{k: v for k, v in dotenv_values(root / ".env").items() if v}}
    s = _read_yaml(root / "config" / "settings.yaml")
    c = _read_yaml(root / "config" / "campaigns.yaml")

    campaigns = []
    seen = set()
    for i, raw in enumerate(c.get("campaigns") or []):
        if not raw.get("id") or not raw.get("name"):
            raise ConfigError(f"campaigns.yaml: campaign no. {i + 1} has no id or name")
        if raw["id"] in seen:
            raise ConfigError(f"campaigns.yaml: duplicate id {raw['id']}")
        seen.add(raw["id"])
        page = raw.get("fb_page_id")
        ig = raw.get("ig_username")
        campaigns.append(Campaign(
            id=raw["id"],
            name=raw["name"],
            label=raw.get("label"),
            status=raw.get("status") or "active",
            fb_page_id=str(page) if page else None,
            ig_username=str(ig).lstrip("@").lower() if ig else None,
            ig_skip=bool(raw.get("ig_skip")),
        ))

    def path(key: str, default: str) -> Path:
        p = Path(s.get(key) or default)
        return p if p.is_absolute() else root / p

    return Settings(
        root=root,
        graph_api_version=str(s.get("graph_api_version") or "v24.0"),
        graph_base_url=str(s.get("graph_base_url") or "https://graph.facebook.com/"),  # "fake" = simulator for tests
        tz=ZoneInfo(s.get("timezone") or "Europe/Warsaw"),
        data_dir=path("data_dir", "data"),
        log_dir=path("log_dir", "logs"),
        backfill_since=str(s.get("backfill_since") or ""),
        snapshot_window_days=int(s.get("snapshot_window_days") or 90),
        fresh_hours=int(s.get("fresh_hours") or 168),
        flags=s.get("flags") or {},
        images=s.get("images") or {},
        metrics=s.get("metrics") or {},
        breakdowns=s.get("breakdowns") or {},
        campaigns=campaigns,
        token=env.get("META_SYSTEM_USER_TOKEN") or None,
    )
