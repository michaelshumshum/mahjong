#!/usr/bin/env python3
"""fails if a comment block spans more than 2 lines.

covers: python `#` comments, js/ts/svelte/css/scss `//` and `/* */` comments.
consecutive line-comments (including a trailing comment continued on the
next line) are treated as one block. block comments are checked directly.

heuristic, not a real parser: template-literal expressions (`${...}`) are
treated as opaque string content, so a `//`/`/* */` inside one won't be seen.
that only under-detects, never flags something that isn't a comment.
"""

from __future__ import annotations

import subprocess
import sys
import tokenize
from pathlib import Path

MAX_LINES = 2

EXCLUDE = {
    "web/src/lib/net/protocol.d.ts",
    "web/src/lib/net/protocol.assertNever.ts",
}

C_LIKE_EXTS = {".js", ".ts", ".svelte", ".css", ".scss"}


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "--", "*.py", "*.js", "*.ts", "*.svelte", "*.css", "*.scss"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [f for f in out.splitlines() if f not in EXCLUDE]


def group_runs(spans: list[tuple[int, int, str]]) -> list[tuple[int, int]]:
    """merge adjacent single-line spans into runs; block spans stand alone."""
    runs: list[tuple[int, int]] = []
    run_start = run_end = None
    for start, end, kind in spans:
        if kind == "block":
            if run_start is not None:
                runs.append((run_start, run_end))
                run_start = run_end = None
            runs.append((start, end))
            continue
        if run_start is not None and start == run_end + 1:
            run_end = end
        else:
            if run_start is not None:
                runs.append((run_start, run_end))
            run_start, run_end = start, end
    if run_start is not None:
        runs.append((run_start, run_end))
    return runs


def scan_python(path: Path) -> list[tuple[int, int, str]]:
    spans = []
    with path.open("rb") as f:
        try:
            for tok in tokenize.tokenize(f.readline):
                if tok.type == tokenize.COMMENT:
                    row = tok.start[0]
                    spans.append((row, row, "line"))
        except tokenize.TokenizeError:
            pass
    return spans


def scan_c_like(text: str) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    state = "code"
    quote = ""
    line = 1
    start_line = 1
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if state == "code":
            if c == "\n":
                line += 1
                i += 1
            elif text[i : i + 2] == "//":
                state, start_line = "line", line
                i += 2
            elif text[i : i + 2] == "/*":
                state, start_line = "block", line
                i += 2
            elif c in ("'", '"', "`"):
                state, quote = "string", c
                i += 1
            else:
                i += 1
        elif state == "string":
            if c == "\\":
                i += 2
            elif c == quote:
                state = "code"
                i += 1
            elif c == "\n":
                line += 1
                i += 1
            else:
                i += 1
        elif state == "line":
            if c == "\n":
                spans.append((start_line, line, "line"))
                state = "code"
                line += 1
                i += 1
            else:
                i += 1
        elif state == "block":
            if text[i : i + 2] == "*/":
                spans.append((start_line, line, "block"))
                state = "code"
                i += 2
            elif c == "\n":
                line += 1
                i += 1
            else:
                i += 1
    if state == "line":
        spans.append((start_line, line, "line"))
    elif state == "block":
        spans.append((start_line, line, "block"))
    return spans


def check_file(rel_path: str) -> list[str]:
    path = Path(rel_path)
    if path.suffix == ".py":
        spans = scan_python(path)
    elif path.suffix in C_LIKE_EXTS:
        spans = scan_c_like(path.read_text())
    else:
        return []

    violations = []
    for start, end in group_runs(spans):
        length = end - start + 1
        if length > MAX_LINES:
            violations.append(f"{rel_path}:{start}-{end}: comment spans {length} lines (max {MAX_LINES})")
    return violations


def main() -> int:
    violations = [v for f in tracked_files() for v in check_file(f)]
    if violations:
        print("\n".join(violations), file=sys.stderr)
        print(f"\n{len(violations)} comment block(s) exceed {MAX_LINES} lines", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
