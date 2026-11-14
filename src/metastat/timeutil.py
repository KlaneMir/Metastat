"""Time: Meta gives UTC, reports are in Europe/Warsaw."""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def parse_meta(s: str) -> datetime:
    """'2026-10-31T17:04:00+0000' → datetime in UTC."""
    s = re.sub(r"([+-]\d\d)(\d\d)$", r"\1:\2", s.strip())
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def iso_local(dt: datetime, tz: ZoneInfo) -> str:
    return dt.astimezone(tz).replace(microsecond=0, tzinfo=None).isoformat()


def local_date(dt: datetime, tz: ZoneInfo) -> date:
    return dt.astimezone(tz).date()


def day_start_unix(day: date, tz: ZoneInfo) -> int:
    """Start of the day in the local zone as a UNIX timestamp."""
    return int(datetime.combine(day, time(0), tzinfo=tz).timestamp())


def insights_day(end_time: str) -> date:
    """A daily insights value has end_time at the end of the day, so it belongs to the previous day.

    Note: days in FB page insights are counted in Meta time (Pacific), not Polish time.
    """
    return date.fromisoformat(end_time[:10]) - timedelta(days=1)


def days(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)
