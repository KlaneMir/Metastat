"""`metastat report --month 2026-10 [--campaign ID]`: XLSX, PDF and a ZIP with post cards."""
from __future__ import annotations

import logging
import re
import shutil
import tempfile
import zipfile
from html import escape
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from metastat import db, fmt
from metastat.config import Settings
from metastat.paths import ensure_dir
from metastat.reports import model, render, xlsx

log = logging.getLogger(__name__)
TEMPLATES = Path(__file__).parent / "templates"


def _env(s: Settings) -> Environment:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]))
    env.filters.update(num=fmt.num, signed=fmt.signed, dm=fmt.dm, dmy=fmt.dmy, dmyhm=fmt.dmyhm)
    env.globals.update(pct=fmt.pct_change, months=fmt.MONTHS)
    return env


_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


# characters forbidden in Windows file names, control characters (0x00-0x1F) and text direction overrides
# (written in ASCII, without literal invisible characters in the code)
_UNSAFE = re.compile("[" + re.escape('<>:"/\\|?*') + chr(0) + "-" + chr(0x1F) + chr(0x202A) + "-" + chr(0x202E)
                     + chr(0x2066) + "-" + chr(0x2069) + "]")


def _safe(name: str) -> str:
    """Folder name in the ZIP and on disk: no characters forbidden in Windows, not empty, not reserved (CON, NUL…)."""
    s = _UNSAFE.sub("_", name).strip(" .")[:80].strip(" .")
    if not s or s.split(".")[0].lower() in _RESERVED:
        s = f"campaign_{s}" if s else "campaign"
    return s


def resolve_campaign(s: Settings, value: str) -> str:
    """--campaign accepts an id from campaigns.yaml or a campaign name (case-insensitive)."""
    for c in s.campaigns:
        if value in (c.id, c.name) or value.lower() == c.name.lower():
            return c.id
    raise ValueError(f"There is no campaign \"{value}\". Available ids: " + ", ".join(c.id for c in s.campaigns))


def generate(s: Settings, year: int, month: int, *, only: list[str] | None = None, demo: bool = False,
             out_dir: Path | None = None, progress=log.info) -> dict[str, Path]:
    conn = db.connect(s.db_path)
    rep = model.build(conn, s, year, month, only=only, demo=demo or s.fake)
    conn.close()
    out_dir = out_dir or s.data_dir / "reports" / f"{year}-{month:02d}"
    ensure_dir(out_dir)
    suffix = ("_" + "_".join(only)) if only else ""
    stem = f"FB_IG_stats_{rep.file_stem}{suffix}"
    paths = {"xlsx": out_dir / f"{stem}.xlsx", "pdf": out_dir / f"{stem}.pdf",
             "zip": out_dir / f"Post_cards_{rep.file_stem}{suffix}.zip"}

    progress("Writing the XLSX…")
    xlsx.write(rep, paths["xlsx"], s.tz)

    env = _env(s)
    css = (TEMPLATES / "report.css").read_text(encoding="utf-8")

    def img(p) -> str | None:
        f = s.data_dir / p["image"] if p.get("image") else None
        return f.as_uri() if f and f.exists() else None

    work = Path(tempfile.mkdtemp(prefix="metastat-report-"))
    try:
        cards: list[tuple[Path, Path, str]] = []
        used: set[str] = set()
        for c in rep.campaigns:
            for pl in c.platforms():
                for p in c.posts.get(pl, []):
                    t = p["created_local"]
                    arc = f"{_safe(c.campaign.name)}/{'Facebook' if pl == 'fb' else 'Instagram'}/{t[:10]}_{t[11:13]}{t[14:16]}"
                    n, base = 2, arc
                    while arc in used:
                        arc, n = f"{base}_{n}", n + 1
                    used.add(arc)
                    jpg = (work / "jpg" / f"{arc}.jpg").resolve()
                    if work.resolve() not in jpg.parents:  # second barrier: a card always stays in the work folder
                        raise ValueError(f"Invalid campaign name for a file: {c.campaign.name!r}")
                    html = work / "cards" / f"{len(cards):05d}.html"
                    ensure_dir(html.parent)
                    html.write_text(env.get_template("card.html").render(css=css, p=p, profile=c.profiles[pl], img_uri=img(p)),
                                    encoding="utf-8")
                    cards.append((html, jpg, arc + ".jpg"))

        report_html = work / "report.html"
        report_html.write_text(env.get_template("report.html").render(r=rep, css=css, img=img), encoding="utf-8")

        with render.browser() as b:
            progress(f"Creating post cards ({len(cards)})…")
            render.card_jpgs(b, [(h, j) for h, j, _ in cards])
            progress("Creating the PDF…")
            render.pdf(b, report_html, paths["pdf"], escape(f"{rep.title} · data fetched {fmt.dmy(rep.generated)}"))

        with zipfile.ZipFile(paths["zip"], "w", zipfile.ZIP_DEFLATED) as z:
            for _, jpg, arc in cards:
                z.write(jpg, arc)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    progress(f"Done: {out_dir}")
    return paths
