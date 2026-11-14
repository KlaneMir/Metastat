"""Number and date formatting (program and reports): 10,896, 31 Oct 2026, 31 Oct 2026 14:05, "–" = no data.

Month names come from fixed lists, never from the system locale, so a Windows set to another language
does not change the output.
"""
from __future__ import annotations

from datetime import datetime

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]
MONTHS_SHORT = [m[:3] for m in MONTHS]


def num(v, decimals: int = 0) -> str:
    if v is None:
        return "–"
    return f"{v:,.{decimals}f}"


def signed(v) -> str:
    if v is None:
        return "–"
    return ("+" if v > 0 else "−" if v < 0 else "±") + num(abs(v))


def dm(v) -> str:
    """'2026-10-31' (or a date) → '31 Oct'."""
    if not v:
        return "–"
    s = str(v)
    return f"{int(s[8:10])} {MONTHS_SHORT[int(s[5:7]) - 1]}"


def dmy(v) -> str:
    """'2026-10-31' (or a date) → '31 Oct 2026'."""
    if not v:
        return "–"
    s = str(v)
    return f"{dm(s)} {s[0:4]}"


def dmyhm(v) -> str:
    """'2026-10-31T14:05' (or a datetime) → '31 Oct 2026 14:05'."""
    if not v:
        return "–"
    s = str(v)
    return f"{dmy(s)} {s[11:16]}"


def date_range(start, end) -> str:
    """'1 Oct – 31 Oct 2026'; the year is repeated only when it differs."""
    a, b = str(start), str(end)
    return f"{dm(a) if a[:4] == b[:4] else dmy(a)} – {dmy(b)}"


def make_localtime(tz):
    def localtime(v) -> str:
        if not v:
            return "–"
        return dmyhm(datetime.fromisoformat(str(v)).astimezone(tz).isoformat())
    return localtime


def pct_change(cur, prev) -> str:
    if cur is None or prev is None or not prev:
        return ""
    p = (cur - prev) / prev * 100
    if abs(p) < 1:
        return ""
    return f"{'+' if p > 0 else '−'}{abs(p):.0f}%"
