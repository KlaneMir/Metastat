"""XLSX report: the Summary, Posts – Facebook, Posts – Instagram and Notes sheets."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from metastat.fmt import dmy, dmyhm
from metastat.paths import ensure_dir
from metastat.reports.model import Report

INK, GREY, GREEN, RED = "141414", "4A4A46", "2E7D4F", "B8281F"
NUM = "#,##0"
DT = "d mmm yyyy hh:mm"
HEAD_FILL = PatternFill("solid", fgColor=INK)
TOTAL_FILL = PatternFill("solid", fgColor="F4F4F2")
HEAD_FONT = Font(bold=True, color="FFFFFF")
THIN = Side(style="thin", color="D6D6D0")

SOURCE = "Source: Meta Graph API (Facebook Page Insights, Instagram Insights), Metastat's own records."
DEFINITIONS = [
    ("Followers (end of month)", "State from the program's last record in the month (followers_count)."),
    ("Change in month", "Followers at the end of the month minus the state on the last day of the previous month."),
    ("Views", "All profile activity in the month, paid and organic, including older posts and ads (daily insights)."),
    ("Posts", "Posts published in the month. Profile and cover photo changes are in the post sheets but are not counted."),
    ("Likes (reactions)", "Sum of reactions (FB) or likes (IG) under posts published in the month."),
    ("Comments, Shares", "Sum under posts published in the month. A missing shares field in the API means 0."),
    ("Interactions", "All profile activity in the month according to Meta (FB: post engagements, IG: total interactions)."),
    ("Reactions, all page activity", "Reactions in the month under all of the page's content, older posts and ads included. "
                                     "This differs from the sum of reactions under the month's posts."),
    ("Post results", "State from the last reading before the end of the month (the \"As of\" column). When the program had "
                     "no reading then, the first later one."),
    ("Paid", "Post views from ads (the split from the Meta API, when available)."),
    ("\"–\"", "No data."),
]


def _header(ws, row: int, labels: list[str]) -> None:
    for i, label in enumerate(labels, 1):
        c = ws.cell(row=row, column=i, value=label)
        c.font, c.fill = HEAD_FONT, HEAD_FILL
        c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="left" if i <= 4 else "right")
    ws.row_dimensions[row].height = 32


def _val(ws, row: int, col: int, v, *, fmt: str = NUM, color: str | None = None, bold: bool = False):
    c = ws.cell(row=row, column=col, value="–" if v is None else v)
    if v is None:
        c.alignment = Alignment(horizontal="right")
        c.font = Font(color=GREY, bold=bold)
    else:
        c.number_format = fmt
        c.font = Font(color=color or INK, bold=bold)
    return c


def _post_link(ws, row: int, col: int, url: str) -> None:
    """Post link from the API: clickable only for https; any other URL stays plain text."""
    cell = ws.cell(row=row, column=col, value=url)
    if str(url).startswith("https://"):
        cell.hyperlink = url
        cell.font = Font(color="1F4E99", underline="single")


def _widths(ws, widths: list[int]) -> None:
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _local(iso: str | None) -> datetime | None:
    return datetime.fromisoformat(iso[:19]) if iso else None


def _taken_local(iso_utc: str | None, tz) -> datetime | None:
    return datetime.fromisoformat(iso_utc).astimezone(tz).replace(tzinfo=None) if iso_utc else None


def summary_sheet(wb: Workbook, rep: Report) -> None:
    ws = wb.active
    ws.title = "Summary"
    ws["A1"] = rep.title + (" (TEST DATA)" if rep.demo else "")
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = (f"Period: {rep.period.label()} · compared with: {rep.prev.label()} · "
                f"data fetched: {dmyhm(rep.generated)}")
    ws["A2"].font = Font(color=GREY)
    labels = ["Campaign", "Label", "Status", "Platform", "Followers (end of month)", "Change in month",
              "Views", "Posts", "Likes (reactions)", "Comments", "Shares", "Interactions",
              "Views, previous month", "Interactions, previous month",
              "Reactions, all page activity", "Views of the month's posts", "Notes"]
    _header(ws, 4, labels)
    row = 5
    for c in rep.campaigns:
        for pl in c.platforms():
            m, prev = c.metrics[pl], c.prev.get(pl) or {}
            ws.cell(row=row, column=1, value=c.campaign.name)
            ws.cell(row=row, column=2, value=c.campaign.label or "")
            ws.cell(row=row, column=3, value=c.campaign.status)
            ws.cell(row=row, column=4, value="Facebook" if pl == "fb" else "Instagram")
            if m is None:
                ws.cell(row=row, column=17, value="No data: the profile is not visible to the API or not synced yet.")
                for col in range(5, 17):
                    _val(ws, row, col, None)
            else:
                ch = m["followers_change"]
                _val(ws, row, 5, m["followers"])
                _val(ws, row, 6, ch, fmt="+#,##0;−#,##0;0", color=GREEN if (ch or 0) > 0 else RED if (ch or 0) < 0 else None)
                for col, key in ((7, "views"), (8, "posts"), (9, "likes"), (10, "comments"), (11, "shares"), (12, "interactions")):
                    _val(ws, row, col, m.get(key))
                _val(ws, row, 13, prev.get("views"))
                _val(ws, row, 14, prev.get("interactions"))
                _val(ws, row, 15, m.get("page_reactions") if pl == "fb" else None)
                _val(ws, row, 16, m.get("post_views"))
                notes = []
                if c.suspicious_change.get(pl):
                    notes.append("Check the follower change: a suspicious record at the start or end of the month.")
                profile_changes = sum(1 for p in c.posts.get(pl, []) if p["kind"] != "post")
                if profile_changes:
                    notes.append(f"Profile/cover photo changes: {profile_changes} (not counted as posts).")
                ws.cell(row=row, column=17, value=" ".join(notes))
            row += 1
    for pl, label in (("fb", "Facebook"), ("ig", "Instagram")):
        t, tp = rep.totals[pl], rep.totals_prev[pl]
        ws.cell(row=row, column=1, value="Total").font = Font(bold=True)
        ws.cell(row=row, column=4, value=label).font = Font(bold=True)
        for col, key in ((5, "followers"), (6, "followers_change"), (7, "views"), (8, "posts"), (9, "likes"),
                         (10, "comments"), (11, "shares"), (12, "interactions")):
            _val(ws, row, col, t.get(key), bold=True, fmt="+#,##0;−#,##0;0" if col == 6 else NUM)
        _val(ws, row, 13, tp.get("views"), bold=True)
        _val(ws, row, 14, tp.get("interactions"), bold=True)
        for col in range(1, 18):
            ws.cell(row=row, column=col).fill = TOTAL_FILL
        row += 1

    row += 1
    for line in [SOURCE, f"Period: {rep.period.label()}. Data fetched: {dmyhm(rep.generated)}.",
                 "Metric details: the \"Notes\" sheet."]:
        ws.cell(row=row, column=1, value=line).font = Font(color=GREY)
        row += 1
    ws.freeze_panes = "E5"
    ws.auto_filter.ref = f"A4:Q{4 + sum(len(c.platforms()) for c in rep.campaigns)}"
    _widths(ws, [34, 10, 12, 11, 14, 12, 13, 8, 12, 12, 13, 12, 14, 14, 15, 15, 60])
    for r in ws.iter_rows(min_row=5, max_row=row):
        for c in r:
            c.border = Border(bottom=THIN)


def posts_sheet(wb: Workbook, rep: Report, platform: str, tz) -> None:
    fb = platform == "fb"
    ws = wb.create_sheet("Posts – Facebook" if fb else "Posts – Instagram")
    labels = ["Date and time", "Campaign", "Type", "Counted in summary", "Text (start)", "Views"]
    labels += ["Paid", "Organic", "Viewers"] if fb else ["Reach"]
    labels += ["Likes (reactions)" if fb else "Likes", "Comments", "Shares"]
    labels += [] if fb else ["Saves", "Interactions"]
    labels += ["As of", "Link"]
    _header(ws, 1, labels)
    row = 2
    for c in rep.campaigns:
        for p in sorted(c.posts.get(platform, []), key=lambda x: x["created_utc"]):
            col = 1
            cell = ws.cell(row=row, column=col, value=_local(p["created_local"]))
            cell.number_format = DT
            ws.cell(row=row, column=2, value=c.campaign.name)
            ws.cell(row=row, column=3, value=p["type"])
            ws.cell(row=row, column=4, value="yes" if p["kind"] == "post" else "no (photo change)")
            text = (p["text"] or "").replace("\n", " ")
            ws.cell(row=row, column=5, value=text[:120] + ("…" if len(text) > 120 else ""))
            vals = [p["views"]] + ([p["paid"], p["organic"], p["reach"]] if fb else [p["reach"]])
            vals += [p["reactions"], p["comments"], p["shares"]]
            vals += [] if fb else [p["saves"], p["interactions_ig"]]
            for i, v in enumerate(vals):
                _val(ws, row, 6 + i, v)
            col = 6 + len(vals)
            t = ws.cell(row=row, column=col, value=_taken_local(p["taken_utc"], tz))
            t.number_format = DT
            if p["permalink"]:
                _post_link(ws, row, col + 1, p["permalink"])
            if p["kind"] != "post":
                for k in range(1, col + 1):
                    ws.cell(row=row, column=k).font = Font(italic=True, color=GREY)
            row += 1
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(labels))}{max(row - 1, 1)}"
    _widths(ws, [17, 30, 13, 14, 60] + [12] * (len(labels) - 7) + [17, 45])


def notes_sheet(wb: Workbook, rep: Report) -> None:
    ws = wb.create_sheet("Notes")
    ws["A1"] = "Notes"
    ws["A1"].font = Font(bold=True, size=13)
    r = 3
    for k, v in DEFINITIONS:
        ws.cell(row=r, column=1, value=k).font = Font(bold=True)
        ws.cell(row=r, column=2, value=v).alignment = Alignment(wrap_text=True, vertical="top")
        r += 1
    r += 1
    ws.cell(row=r, column=1, value="To check").font = Font(bold=True, size=12)
    r += 1
    flags = [(c.campaign.name, f) for c in rep.campaigns for f in c.flags]
    if not flags:
        ws.cell(row=r, column=1, value="No suspicious values this month.")
    for name, f in flags:
        ws.cell(row=r, column=1, value=name)
        ws.cell(row=r, column=2, value=f"{dmy(f['date'])}: {f['detail']}")
        r += 1
    r += 1
    ws.cell(row=r, column=1, value=SOURCE).font = Font(color=GREY)
    _widths(ws, [34, 110])


def write(rep: Report, path: Path, tz) -> Path:
    wb = Workbook()
    summary_sheet(wb, rep)
    posts_sheet(wb, rep, "fb", tz)
    posts_sheet(wb, rep, "ig", tz)
    notes_sheet(wb, rep)
    _no_formulas(wb)
    ensure_dir(path.parent)
    wb.save(path)
    return path


def _no_formulas(wb: Workbook) -> None:
    """Text from the data (post text, campaign name) that starts with "=" stays text, not an Excel formula.
    The workbook uses no formulas at all, so this applies to every cell."""
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if cell.data_type == "f":
                    cell.data_type = "s"
