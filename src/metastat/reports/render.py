"""HTML → JPG (post cards) and HTML → PDF through a browser driven by Playwright.

Uses the installed Microsoft Edge by default, so no separate browser has to be downloaded.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from metastat.paths import ensure_dir


class RenderError(Exception):
    pass


@contextmanager
def browser():
    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError as e:
        raise RenderError("The Playwright library is missing. Install it: .venv\\Scripts\\python -m pip install playwright") from e
    with sync_playwright() as p:
        b = None
        for kw in ({"channel": "msedge"}, {"channel": "chrome"}, {}):
            try:
                b = p.chromium.launch(**kw)
                break
            except Error:
                continue
        if b is None:
            raise RenderError("No browser found for creating the PDF and cards. Install Microsoft Edge "
                              "or run: .venv\\Scripts\\python -m playwright install chromium")
        try:
            yield b
        finally:
            b.close()


def card_jpgs(b, items: list[tuple[Path, Path]]) -> None:
    """items: (card HTML file, target JPG). A screenshot of the card alone, 800 px wide."""
    page = b.new_page(viewport={"width": 800, "height": 1000})
    try:
        for html, out in items:
            page.goto(html.as_uri(), wait_until="load")
            ensure_dir(out.parent)
            page.locator(".card").screenshot(path=str(out), type="jpeg", quality=90)
    finally:
        page.close()


def pdf(b, html: Path, out: Path, footer_left: str) -> None:
    page = b.new_page()
    try:
        page.goto(html.as_uri(), wait_until="load")
        footer = ('<div style="font-family:Segoe UI,Arial,sans-serif;font-size:7px;color:#4A4A46;width:100%;'
                  'padding:0 12mm;display:flex;justify-content:space-between">'
                  f'<span>{footer_left}</span><span>page <span class="pageNumber"></span> of '
                  '<span class="totalPages"></span></span></div>')
        page.pdf(path=str(out), format="A4", print_background=True, display_header_footer=True,
                 header_template="<span></span>", footer_template=footer,
                 margin={"top": "14mm", "bottom": "16mm", "left": "12mm", "right": "12mm"})
    finally:
        page.close()
