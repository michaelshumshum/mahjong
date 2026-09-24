#!/usr/bin/env python3
"""Render a flat shields.io-style coverage badge as a standalone SVG.

Self-rendered rather than shields.io's own /badge endpoint: this repo is private, and
raw.githubusercontent.com (what an endpoint badge would point at) 401s for third-party
fetchers like shields.io on a private repo. An SVG committed to the repo and referenced by
a relative path in README.md renders for any authenticated viewer with no external fetch.

Usage: coverage_badge.py <server|web> <label> <report-path> <out-path>
"""

import sys
from xml.sax.saxutils import escape

# shields.io's own flat-badge palette, so this matches what a public shields.io badge would
# have looked like.
_COLOR_HEX = {
    "brightgreen": "#4c1",
    "green": "#97ca00",
    "yellowgreen": "#a4a61d",
    "yellow": "#dfb317",
    "orange": "#fe7d37",
    "red": "#e05d44",
}


def color_for(pct: float) -> str:
    if pct >= 90:
        return "brightgreen"
    if pct >= 80:
        return "green"
    if pct >= 70:
        return "yellowgreen"
    if pct >= 60:
        return "yellow"
    if pct >= 50:
        return "orange"
    return "red"


def pct_from(kind: str, path: str) -> float:
    import json

    data = json.load(open(path))
    if kind == "server":  # pytest-cov --cov-report=json
        return data["totals"]["percent_covered"]
    if kind == "web":  # vitest --coverage.reporter=json-summary
        return data["total"]["lines"]["pct"]
    raise ValueError(f"unknown report kind: {kind}")


def _text_width(text: str) -> int:
    # shields.io's own approximation for 11px Verdana.
    return round(len(text) * 6.9) + 10


def render_svg(label: str, message: str, color: str) -> str:
    label_w = _text_width(label)
    msg_w = _text_width(message)
    total_w = label_w + msg_w
    hex_color = _COLOR_HEX[color]
    label, message = escape(label), escape(message)
    return f"""\
<svg xmlns="http://www.w3.org/2000/svg" width="{total_w}" height="20" role="img" aria-label="{label}: {message}">
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="r"><rect width="{total_w}" height="20" rx="3" fill="#fff"/></clipPath>
  <g clip-path="url(#r)">
    <rect width="{label_w}" height="20" fill="#555"/>
    <rect x="{label_w}" width="{msg_w}" height="20" fill="{hex_color}"/>
    <rect width="{total_w}" height="20" fill="url(#s)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,sans-serif" font-size="11">
    <text x="{label_w / 2:.1f}" y="14">{label}</text>
    <text x="{label_w + msg_w / 2:.1f}" y="14">{message}</text>
  </g>
</svg>
"""


def main() -> None:
    kind, label, in_path, out_path = sys.argv[1:5]
    pct = pct_from(kind, in_path)
    svg = render_svg(label, f"{pct:.1f}%", color_for(pct))
    with open(out_path, "w") as f:
        f.write(svg)


if __name__ == "__main__":
    main()
