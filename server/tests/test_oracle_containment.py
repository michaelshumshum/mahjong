"""Structural containment test for `app/views.py`'s `_omniscient_seat_view` -- the one
deliberate bypass of `seat_view()`'s `_check_reveal` guard (see that function's own docstring,
and `app/table.py`'s `_submit_bot_job`, for the full safety argument). AST-based, not a trust-me
comment: scans every *production* source file under `server/` (`app/`, `bots/`, `mahjong_core/`,
`ml/`, `alembic/`, `tools/` -- excluding `tests/` itself, caches, and `.venv`) for `Call` nodes
naming `_omniscient_seat_view` and asserts there is exactly one, inside `Table._submit_bot_job`
-- not `seat_view_wire`, not `state_sync_wire`, not any other WS/protocol-facing path, nowhere
else. `tests/` is excluded deliberately: `tests/test_oracle.py` legitimately constructs
omniscient views directly (via `app.views._omniscient_seat_view`) for white-box `"ORACLE"`-tier
tests -- that's expected, sanctioned test-only usage, not the dispatch path this test guards.
This guarantee is unaffected by which bot actually consumes the omniscient view -- it held for
the original rollout-based `OracleBot` and holds identically now that the tier is a plain
`FaanBot()` fed an omniscient view (docs/04-bots.md §10).
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

_SERVER_ROOT = Path(__file__).resolve().parents[1]  # server/
_TARGET = "_omniscient_seat_view"

# production packages only -- deliberately excludes tests/ (see module docstring), plus the
# usual caches/venvs.
_PRODUCTION_DIRS = ("app", "bots", "mahjong_core", "ml", "alembic", "tools")


def _iter_source_files() -> Iterator[Path]:
    for path in _SERVER_ROOT.rglob("*.py"):
        parts = path.relative_to(_SERVER_ROOT).parts
        if not parts:
            continue
        if parts[0] not in _PRODUCTION_DIRS:
            continue
        if any(p.startswith(".") or p == "__pycache__" for p in parts):
            continue
        yield path


class _CallCollector(ast.NodeVisitor):
    """Records `(enclosing "Class.func" qualname, lineno)` for every `Call` naming `_TARGET`."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []
        self._stack: list[str] = []

    def _visit_scope(self, node: ast.AST, name: str) -> None:
        self._stack.append(name)
        self.generic_visit(node)
        self._stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_scope(node, node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_scope(node, node.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_scope(node, node.name)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        name = None
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        if name == _TARGET:
            self.calls.append((".".join(self._stack) or "<module>", node.lineno))
        self.generic_visit(node)


def _find_calls(path: Path) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text(), filename=str(path))
    collector = _CallCollector()
    collector.visit(tree)
    return collector.calls


def test_omniscient_seat_view_has_exactly_one_call_site_in_the_whole_codebase() -> None:
    found: dict[Path, list[tuple[str, int]]] = {}
    for path in _iter_source_files():
        calls = _find_calls(path)
        if calls:
            found[path] = calls

    total = sum(len(v) for v in found.values())
    assert total == 1, (
        f"expected exactly 1 call site for {_TARGET} across server/, found {total}: "
        f"{ {str(p): c for p, c in found.items()} }"
    )

    ((path, calls),) = found.items()
    assert path.name == "table.py" and path.parent.name == "app", (
        f"{_TARGET} is called from {path}, expected server/app/table.py"
    )
    qualname, _lineno = calls[0]
    assert qualname == "Table._submit_bot_job", (
        f"{_TARGET} is called from {qualname!r} in {path}, expected 'Table._submit_bot_job'"
    )


def test_omniscient_seat_view_is_not_exported_from_views_module() -> None:
    """Not in `__all__` -- callers reaching for it have to import the private name explicitly,
    a small extra friction that keeps it from showing up in a casual `from app.views import *`
    or autocomplete sweep."""
    from app import views

    assert "_omniscient_seat_view" not in views.__all__


def test_wire_facing_functions_never_call_omniscient_seat_view() -> None:
    """Direct, redundant-by-design check on the specific functions a real WS client's traffic
    actually goes through -- `seat_view_wire`/`state_sync_wire`-shaped code -- on top of the
    whole-codebase sweep above. `Table.state_sync_wire` (`app/table.py`) and `app.views.
    seat_view_wire` must both be entirely free of `_TARGET`."""
    import inspect

    from app import views
    from app.table import Table

    for src in (inspect.getsource(views.seat_view_wire), inspect.getsource(Table.state_sync_wire)):
        assert _TARGET not in src
