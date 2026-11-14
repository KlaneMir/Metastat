"""Line charts as SVG rendered on the server (no JS libraries).

CSS sets the colours through classes (.s0, .s1, …), so a chart follows the program's palette.
"""
from __future__ import annotations

import math
from datetime import date
from html import escape

from metastat.fmt import dm


def fmt_num(v: float) -> str:
    v = round(v)
    return f"{v:,}"


def _nice_ticks(lo: float, hi: float, n: int = 4) -> list[float]:
    """Round ticks covering the whole range; the numbers are integers, so the step is at least 1."""
    if hi - lo < n:
        lo, hi = math.floor(lo) - (n - (hi - lo)) // 2, math.floor(lo) - (n - (hi - lo)) // 2 + n
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = max(1, next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw))
    if step != int(step):
        step = math.ceil(step)
    t = math.floor(lo / step) * step
    ticks = [t]
    while ticks[-1] < hi:  # the last tick is always above the maximum so the line stays inside the chart
        ticks.append(ticks[-1] + step)
    return ticks


def line_chart(series: list[dict], *, x_ticks: list[tuple[float, str]], width: int = 720, height: int = 260,
               x_log: bool = False, y_zero: bool = True, label: str = "") -> str:
    """series: [{'points': [(x, y)], 'cls': 's0', 'name': 'Ten post', 'dash': False, 'step': False}]"""
    pts_all = [pt for s in series for pt in s["points"]]
    if not pts_all:
        return ""
    left, right, top, bottom = 56, 16, 14, 30
    xs = [x for x, _ in pts_all] + [x for x, _ in x_ticks]
    ys = [y for _, y in pts_all]
    fx = (lambda v: math.log10(max(v, 1e-6))) if x_log else (lambda v: v)
    x0, x1 = fx(min(xs)), fx(max(xs))
    if x1 == x0:
        x1 = x0 + 1
    yt = _nice_ticks(0 if y_zero else min(ys), max(ys) or 1)
    y0, y1 = yt[0], yt[-1]

    def X(v):
        return left + (fx(v) - x0) / (x1 - x0) * (width - left - right)

    def Y(v):
        return top + (1 - (v - y0) / ((y1 - y0) or 1)) * (height - top - bottom)

    out = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(label)}">']
    for t in yt:
        out.append(f'<line class="grid" x1="{left}" x2="{width - right}" y1="{Y(t):.1f}" y2="{Y(t):.1f}"/>')
        out.append(f'<text class="ylab" x="{left - 8}" y="{Y(t) + 4:.1f}" text-anchor="end">{fmt_num(t)}</text>')
    for v, txt in x_ticks:
        out.append(f'<text class="xlab" x="{X(v):.1f}" y="{height - 8}" text-anchor="middle">{escape(txt)}</text>')
    for s in series:
        pts = s["points"]
        if not pts:
            continue
        path = " ".join(f"{'M' if i == 0 else 'L'}{X(x):.1f},{Y(y):.1f}" for i, (x, y) in enumerate(pts))
        dash = ' stroke-dasharray="5 5"' if s.get("dash") else ""
        out.append(f'<path class="line {s["cls"]}" d="{path}"{dash}/>')
        if len(pts) == 1:
            x, y = pts[0]
            out.append(f'<circle class="dot {s["cls"]}" cx="{X(x):.1f}" cy="{Y(y):.1f}" r="3"/>')
    out.append("</svg>")
    return "".join(out)


def hours_label(h: float) -> str:
    if h < 1:
        return f"{round(h * 60)} min"
    if h < 24:
        return f"{h:g} h"
    d, rest = divmod(round(h), 24)
    return f"{d} d" + (f" {rest} h" if rest else "") if d < 7 or rest else f"{d} days"


def post_curve_chart(curve: list[tuple[float, float]], typical: list[tuple[float, float]]) -> str:
    max_h = max([h for h, _ in curve + typical] + [168])
    ticks = [(h, hours_label(h)) for h in (0.25, 9, 30, 168, 720) if h <= max_h * 1.05]
    return line_chart([
        {"points": typical, "cls": "s1", "dash": True, "name": "Typical views of the profile's posts"},
        {"points": curve, "cls": "s0", "name": "Views of this post"},
    ], x_ticks=ticks, x_log=True, width=900, height=300, label="Post views over time since publication")


def followers_chart(points: list[tuple[date, float]], start: date, end: date, cls: str, label: str) -> str:
    """Followers day by day. FB and IG have separate charts because their scales differ."""
    days = (end - start).days or 1
    step = max(1, days // 4)
    ticks = [(i, dm(date.fromordinal(start.toordinal() + i))) for i in range(0, days + 1, step)]
    return line_chart([{"points": [((d - start).days, v) for d, v in points], "cls": cls, "name": label}],
                      x_ticks=ticks, y_zero=False, width=700, height=220, label=label)
