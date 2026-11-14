"""Shared state of a single sync run."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime

from metastat.config import Settings
from metastat.graph import Graph
from metastat.images import ImageStore
from metastat.timeutil import iso_utc, local_date


@dataclass
class Ctx:
    s: Settings
    graph: Graph
    conn: sqlite3.Connection
    images: ImageStore
    now: datetime
    _ig_directory: dict | None = field(default=None, repr=False)

    @property
    def taken_utc(self) -> str:
        return iso_utc(self.now)

    @property
    def today(self) -> date:
        return local_date(self.now, self.s.tz)

    def ig_directory(self) -> dict[str, dict]:
        """username → {id, username, page_id} for IG accounts linked to pages assigned to the token."""
        if self._ig_directory is None:
            out = {}
            for p in self.graph.paginate("me/accounts", {"fields": "id,name,instagram_business_account{id,username}", "limit": 100}):
                iba = p.get("instagram_business_account")
                if iba and iba.get("username"):
                    out[iba["username"].lower()] = {"id": iba["id"], "username": iba["username"], "page_id": p["id"]}
            self._ig_directory = out
        return self._ig_directory
