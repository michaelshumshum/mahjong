#!/usr/bin/env python3
"""Write a shields.io endpoint-badge JSON file from a coverage report.

Usage: coverage_badge.py <server|web> <label> <report-path> <out-path>
"""

import json
import sys


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
    data = json.load(open(path))
    if kind == "server":  # pytest-cov --cov-report=json
        return data["totals"]["percent_covered"]
    if kind == "web":  # vitest --coverage.reporter=json-summary
        return data["total"]["lines"]["pct"]
    raise ValueError(f"unknown report kind: {kind}")


def main() -> None:
    kind, label, in_path, out_path = sys.argv[1:5]
    pct = pct_from(kind, in_path)
    badge = {
        "schemaVersion": 1,
        "label": label,
        "message": f"{pct:.1f}%",
        "color": color_for(pct),
    }
    with open(out_path, "w") as f:
        json.dump(badge, f)
        f.write("\n")


if __name__ == "__main__":
    main()
