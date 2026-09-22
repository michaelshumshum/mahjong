"""`app/registry.py`'s `TableRegistry` -- table lookup/creation/cleanup (M3 sub-task 6).

`get_or_create`/`get` are exercised directly against a bare `TableRegistry()` (no WS layer) --
`app/ws.py`'s own module-level `_registry` is exactly this class, already covered indirectly by
every WS-integration test (`tests/test_ws_gameplay.py`, `tests/test_reconnect.py`,
`tests/test_disconnect_bot_handover.py`). This file's own job is the registry's *own* behavior:
dedup on repeated `get_or_create`, `get` on an unknown id, the task-cleanup-on-`GAME_OVER`
lifecycle `app/registry.py`'s module docstring documents, and the lobby's `list_tables`.
"""

from __future__ import annotations

import asyncio
import dataclasses

from app.registry import TableRegistry
from mahjong_core.actions import Pass
from mahjong_core.config import DEFAULT_RULESET
from mahjong_core.state import Phase


async def _wait_until_stopped(
    registry: TableRegistry, table_id: str, *, timeout: float = 2.0
) -> None:
    async def _poll() -> None:
        while registry.is_running(table_id):
            await asyncio.sleep(0.01)

    await asyncio.wait_for(_poll(), timeout=timeout)


def test_get_unknown_table_returns_none() -> None:
    registry = TableRegistry()
    assert registry.get("no-such-table") is None
    assert len(registry) == 0


async def test_get_or_create_is_idempotent_per_table_id() -> None:
    registry = TableRegistry()
    table1 = registry.get_or_create("table-a", DEFAULT_RULESET, seed=1)
    table2 = registry.get_or_create("table-a", DEFAULT_RULESET, seed=999)  # seed ignored on reuse
    assert table1 is table2
    assert registry.get("table-a") is table1
    assert len(registry) == 1

    table_b = registry.get_or_create("table-b", DEFAULT_RULESET, seed=1)
    assert table_b is not table1
    assert len(registry) == 2


async def test_get_or_create_passes_through_require_ready_and_seed() -> None:
    registry = TableRegistry()
    table = registry.get_or_create("table-c", DEFAULT_RULESET, seed=42, require_ready=False)
    assert table.require_ready is False
    assert table.started is True  # require_ready=False tables start immediately (Table.__init__)


async def test_table_task_stops_and_is_cleaned_up_on_game_over() -> None:
    """`Table.run()` (see its own docstring) returns once `state.phase == Phase.GAME_OVER`;
    `TableRegistry._run` wraps that so `_tasks` drops the entry the moment it does -- the `Table`
    object itself stays in `_tables` (see `app/registry.py`'s module docstring on why)."""
    registry = TableRegistry()
    table = registry.get_or_create("table-gameover", DEFAULT_RULESET, seed=1, require_ready=False)
    assert registry.is_running("table-gameover")

    # force GAME_OVER directly (white-box, same style tests/test_reconnect.py's `table.state = ...`
    # rigging already established) and nudge the table's own background task awake with a command
    # it will drop as illegal (GAME_OVER has no legal_actions for any seat) -- process_one() only
    # re-checks phase after handling *something*, per Table.run()'s own loop.
    table.state = dataclasses.replace(table.state, phase=Phase.GAME_OVER, claim_window=None)
    table.submit(0, Pass(window_id=0, seat=0))

    await _wait_until_stopped(registry, "table-gameover")
    assert not registry.is_running("table-gameover")
    assert registry.get("table-gameover") is table  # the Table itself is retained, not evicted

    # get_or_create on the same (finished) table id returns the same, now-task-less Table --
    # a table id names one particular game, not a recyclable lobby slot.
    same_table = registry.get_or_create("table-gameover", DEFAULT_RULESET, seed=2)
    assert same_table is table
    assert not registry.is_running("table-gameover")


def _noop_send(_seq: int, _frame: dict[str, object]) -> None:
    pass


async def test_list_tables_skips_tables_nobody_has_joined() -> None:
    registry = TableRegistry()
    registry.get_or_create("visited-only", DEFAULT_RULESET, seed=1, require_ready=True)
    registry.get_or_create("practice", DEFAULT_RULESET, seed=1, require_ready=True, practice=True)
    assert registry.list_tables() == []


async def test_list_tables_reports_open_then_in_progress() -> None:
    registry = TableRegistry()
    table = registry.get_or_create("lobby-a", DEFAULT_RULESET, seed=1, require_ready=True)
    table.join("s-alice", _noop_send, seat=2, name="Alice")

    [summary] = registry.list_tables()
    assert summary.table_id == "lobby-a"
    assert summary.status == "open"
    assert summary.hand_no == 1
    assert summary.seat_status == ("empty", "empty", "connected", "empty")
    assert summary.names == (None, None, "Alice", None)

    table.start_with_bots(2)
    [summary] = registry.list_tables()
    assert summary.status == "in_progress"
    assert summary.seat_status.count("bot") == 3


async def test_disconnect_pre_start_frees_seat_after_grace_period() -> None:
    """A seat still disconnected once its grace period elapses, on a table that hasn't started,
    frees back to empty instead of flipping to `AUTOPLAY` (`Table._handle_disconnect_timeout`) --
    there's no hand for a bot to play pre-start, so an abandoned waiting-room seat would otherwise
    sit `autoplay` forever and keep the table listed to the lobby as taken with nobody actually
    there. `disconnect_grace_seconds=0` is the same test-time-control pattern
    `tests/test_disconnect_bot_handover.py` uses -- the deadline is due the instant it's armed."""
    ruleset = dataclasses.replace(DEFAULT_RULESET, disconnect_grace_seconds=0)
    registry = TableRegistry()
    table = registry.get_or_create("lobby-abandoned", ruleset, seed=1, require_ready=True)
    table.join("s-carol", _noop_send, seat=1, name="Carol")
    assert table.host_seat == 1
    assert registry.list_tables() != []

    table.mark_disconnected(1, "s-carol")
    assert table.seat_bindings[1] is not None
    assert table.seat_bindings[1].status == "disconnected"

    async def _poll() -> None:
        while table.seat_bindings[1] is not None:
            await asyncio.sleep(0.01)

    await asyncio.wait_for(_poll(), timeout=2.0)

    assert table.host_seat is None
    assert registry.list_tables() == []


async def test_list_tables_drops_finished_games() -> None:
    registry = TableRegistry()
    table = registry.get_or_create("lobby-done", DEFAULT_RULESET, seed=1, require_ready=False)
    table.join("s-bob", _noop_send, seat=0, name="Bob")
    assert [t.table_id for t in registry.list_tables()] == ["lobby-done"]

    table.state = dataclasses.replace(table.state, phase=Phase.GAME_OVER, claim_window=None)
    table.submit(0, Pass(window_id=0, seat=0))
    await _wait_until_stopped(registry, "lobby-done")
    assert registry.list_tables() == []
