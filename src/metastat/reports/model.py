"""Monthly report data, shared by the XLSX, the PDF and the cards (one source of numbers = matching totals)."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from metastat import analytics as an
from metastat.config import Campaign, Settings
from metastat.fmt import MONTHS

FLAG_KINDS = {"jump": "follower jump", "collapse": "followers dropped to a handful",
              "negative_value": "negative follower count", "ig_not_found": "IG account not visible to the API"}


@dataclass
class CampaignReport:
    campaign: Campaign
    metrics: dict          # {'fb': dict|None, 'ig': dict|None}; None = configured, but no data
    prev: dict             # the same metrics for the previous month
    posts: dict            # {'fb': [...], 'ig': [...]} all posts of the month, photo changes included
    flags: list = field(default_factory=list)
    suspicious_change: dict = field(default_factory=dict)  # {'fb': True} when the follower change has a flag
    profiles: dict = field(default_factory=dict)           # {'fb': page name, 'ig': '@account'}

    def platforms(self) -> list[str]:
        return [p for p in ("fb", "ig") if p in self.metrics]


@dataclass
class Report:
    period: an.Period
    prev: an.Period
    generated: datetime
    campaigns: list[CampaignReport]
    totals: dict
    totals_prev: dict
    demo: bool = False

    @property
    def month_name(self) -> str:
        return MONTHS[self.period.start.month - 1]

    @property
    def title(self) -> str:
        return f"Campaign statistics, {self.month_name} {self.period.start.year}"

    @property
    def range_label(self) -> str:
        p = self.period
        return f"1–{p.end.day} {MONTHS[p.start.month - 1]} {p.start.year}"

    @property
    def file_stem(self) -> str:
        return f"{self.period.start.year}-{self.period.start.month:02d}"

    def all_posts(self, platform: str) -> list[dict]:
        return [p for c in self.campaigns for p in c.posts.get(platform, [])]

    def lead(self) -> str:
        """One or two summary sentences for page 1, computed from the same data as the table."""
        from metastat.fmt import num, signed
        fb, ig = self.totals["fb"], self.totals["ig"]
        parts = []
        if fb.get("views") is not None:
            s = f"On Facebook the campaign pages got {num(fb['views'])} views"
            if fb.get("interactions") is not None:
                s += f" and {num(fb['interactions'])} interactions"
            if fb.get("followers_change") is not None:
                s += f", with a follower change of {signed(fb['followers_change'])}"
            parts.append(s + ".")
        if ig.get("posts"):
            parts.append(f"On Instagram {num(ig['posts'])} posts were published, with {num(ig.get('likes'))} likes in total.")
        return " ".join(parts)


def _suspicious(flags, owner: str | None, period: an.Period) -> bool:
    """A follower flag at the start or end of the month undermines the "change in the month"."""
    edges = {(period.start - timedelta(days=1)).isoformat(), period.start.isoformat(),
             period.end.isoformat(), (period.end + timedelta(days=1)).isoformat()}
    return any(f["object_id"] == owner and f["kind"] in ("jump", "collapse", "negative_value") and f["date"] in edges
               for f in flags)


def build(conn: sqlite3.Connection, s: Settings, year: int, month: int, *, only: list[str] | None = None,
          demo: bool = False) -> Report:
    period = an.Period.month(year, month)
    prev = period.previous_month()
    campaigns = [c for c in s.campaigns if not only or c.id in only]
    rows = an.summary(conn, s, period, prev, campaigns)
    out = []
    flag_period = an.Period(period.start - timedelta(days=1), period.end + timedelta(days=1))
    for r in rows:
        camp = r["campaign"]
        owners = an.owner_ids(conn, camp)
        flags = an.flags(conn, s, camp, flag_period)
        cr = CampaignReport(
            campaign=camp, metrics=r["platforms"], prev=r["prev"],
            posts={pl: an.posts(conn, s, camp, pl, period) for pl in r["platforms"]},
            flags=[f for f in flags if f["kind"] in FLAG_KINDS])
        cr.suspicious_change = {pl: _suspicious(flags, owners[pl], period) for pl in r["platforms"]}
        page = conn.execute("SELECT name FROM fb_pages WHERE page_id = ?", (owners["fb"],)).fetchone() if owners["fb"] else None
        cr.profiles = {"fb": page[0] if page and page[0] else camp.name, "ig": f"@{camp.ig_username}" if camp.ig_username else ""}
        out.append(cr)
    totals = {pl: an.totals(rows, pl) for pl in ("fb", "ig")}
    prev_rows = [{"platforms": r["prev"]} for r in rows]
    totals_prev = {pl: an.totals(prev_rows, pl) for pl in ("fb", "ig")}
    return Report(period=period, prev=prev, generated=datetime.now(timezone.utc).astimezone(s.tz),
                  campaigns=out, totals=totals, totals_prev=totals_prev, demo=demo)
