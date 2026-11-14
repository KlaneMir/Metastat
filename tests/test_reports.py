from __future__ import annotations

import io
import zipfile

import pytest
from openpyxl import load_workbook
from PIL import Image

from metastat import db
from metastat.reports import build, model, xlsx
from metastat.reports.render import RenderError


def test_xlsx_summary_matches_post_sheets(sim, tmp_path):
    """Acceptance criterion: the totals in the Summary sheet = the totals from the post sheets (posts counted in the summary)."""
    conn = db.connect(sim.db_path)
    rep = model.build(conn, sim, 2026, 10, demo=True)
    path = xlsx.write(rep, tmp_path / "r.xlsx", sim.tz)
    wb = load_workbook(path)
    summ, sheets = wb["Summary"], {"Facebook": wb["Posts – Facebook"], "Instagram": wb["Posts – Instagram"]}
    assert "(TEST DATA)" in summ["A1"].value

    def col(ws, name):
        for c in ws[1 if ws.title != "Summary" else 4]:
            if c.value == name:
                return c.column - 1
        raise KeyError(name)

    sums: dict = {}
    for plat, ws in sheets.items():
        likes = col(ws, "Likes (reactions)" if plat == "Facebook" else "Likes")
        for row in ws.iter_rows(min_row=2, values_only=True):
            if row[0] is None or row[col(ws, "Counted in summary")] != "yes":
                continue
            k = (row[1], plat)
            agg = sums.setdefault(k, {"posts": 0, "likes": 0, "comments": 0, "shares": 0})
            agg["posts"] += 1
            agg["likes"] += row[likes] if isinstance(row[likes], (int, float)) else 0
            agg["comments"] += row[col(ws, "Comments")] or 0
            agg["shares"] += row[col(ws, "Shares")] or 0
    checked = 0
    for row in summ.iter_rows(min_row=5, values_only=True):
        if not row[0] or row[0] == "Total" or not isinstance(row[7], (int, float)):
            continue
        got = sums.get((row[0], row[3]), {"posts": 0, "likes": 0, "comments": 0, "shares": 0})
        assert (row[7], row[8], row[9], row[10]) == (got["posts"], got["likes"], got["comments"], got["shares"]), row[:4]
        checked += 1
    assert checked >= 6
    fb = sheets["Facebook"]
    assert fb.freeze_panes == "A2" and fb.auto_filter.ref


def test_month_period_and_names():
    from metastat.analytics import Period
    p = Period.month(2026, 10)
    assert (p.start.isoformat(), p.end.isoformat()) == ("2026-10-01", "2026-10-31")
    assert p.previous_month().label() == "1 Sep – 30 Sep 2026"
    assert Period.month(2026, 1).previous_month().start.isoformat() == "2025-12-01"


def test_resolve_campaign(sim):
    camp = sim.campaigns[0]
    assert build.resolve_campaign(sim, camp.name) == camp.id
    assert build.resolve_campaign(sim, camp.name.upper()) == camp.id
    assert build.resolve_campaign(sim, camp.id) == camp.id
    with pytest.raises(ValueError):
        build.resolve_campaign(sim, "no such campaign")


def test_full_report_pdf_zip(sim, tmp_path):
    camp = next(c for c in sim.campaigns if c.fb_page_id and c.ig_username and not c.ig_skip)
    try:
        paths = build.generate(sim, 2026, 10, only=[camp.id], demo=True, out_dir=tmp_path)
    except RenderError as e:
        pytest.skip(f"no browser for the PDF: {e}")
    assert paths["pdf"].read_bytes()[:4] == b"%PDF"
    with zipfile.ZipFile(paths["zip"]) as z:
        names = z.namelist()
        folder = build._safe(camp.name) + "/"
        assert names and all(n.startswith(folder) for n in names)
        assert any("/Facebook/2026-10-" in n for n in names)
        with Image.open(io.BytesIO(z.read(names[0]))) as im:
            assert im.width == 800 and im.format == "JPEG"
    assert paths["xlsx"].exists()
