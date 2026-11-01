"""Abandoned-table early termination (docs/architecture.md §8 "Every human gone",
docs/decisions/0024-end-abandoned-tables.md).

Driven like `tests/test_shutdown.py`: a bare `TableRegistry`/`Table` with `SeatBinding`s bound
directly and a never-resolving bot pool, so no real bot ever runs. `abandon_grace_seconds=0`
makes the abandonment deadline due the instant it's armed (the `disconnect_grace_seconds=0`
idiom); the reconnect case uses a long grace and fires the stale timer id by hand instead of
sleeping.
"""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import Executor, Future
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import ws
from app.main import app
from app.registry import TableRegistry
from app.table import Table
from app.table_types import BotResult, SeatBinding
from mahjong_core.config import DEFAULT_RULESET
from mahjong_core.ml import legal_mask


class _HangingExecutor(Executor):
    """`tests/test_table_turn_timeout.py`'s stand-in: every job hangs forever. Counts submits."""

    def __init__(self) -> None:
        self.submitted = 0

    def submit(self, fn: Any, /, *args: Any, **kwargs: Any) -> Future[Any]:
        self.submitted += 1
        return Future()


class _Recorder:
    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []
        self.closed = False

    def send(self, _seq: int, wire: dict[str, Any]) -> None:
        self.frames.append(wire)

    def close(self) -> None:
        self.closed = True


def _bind(table: Table, seat: int, *, status: str = "connected") -> _Recorder:
    rec = _Recorder()
    table.seat_bindings[seat] = SeatBinding(
        session_id=f"seat-{seat}",
        send=rec.send,
        name=f"Seat {seat}",
        status=status,  # type: ignore[arg-type]
    )
    return rec


async def _ticks(n: int = 50) -> None:
    for _ in range(n):
        await asyncio.sleep(0)


def _started_table(
    registry: TableRegistry, table_id: str, *, humans: int = 4
) -> tuple[Table, asyncio.Task[None]]:
    table = registry.get_or_create(table_id, DEFAULT_RULESET, seed=1, require_ready=False)
    for seat in range(4):
        _bind(table, seat, status="connected" if seat < humans else "bot")
    return table, registry._tasks[table_id]


async def test_all_humans_gone_ends_the_table_after_grace(caplog: pytest.LogCaptureFixture) -> None:
    registry = TableRegistry(bot_pool=_HangingExecutor(), abandon_grace_seconds=0)
    table, task = _started_table(registry, "abandon-all")
    spectator = _Recorder()
    table.register_spectator("spec-1", spectator.send, spectator.close)
    persisted: list[bool] = []

    async def _spy_persist() -> None:
        persisted.append(True)

    table._persist_game_record = _spy_persist  # type: ignore[method-assign]

    with caplog.at_level(logging.WARNING, logger="app.table"):
        for seat in range(4):
            table.mark_disconnected(seat, f"seat-{seat}")
        await asyncio.wait_for(task, timeout=1.0)

    assert table.closed
    assert not registry.is_running("abandon-all")
    assert registry.get("abandon-all") is None
    assert registry.is_closed("abandon-all")
    assert "abandon-all" not in [s.table_id for s in registry.list_tables()]
    assert persisted == []
    assert spectator.frames[-1] == {
        "t": "error",
        "code": "table_closed",
        "message": "table closed: every player left",
    }
    assert spectator.closed
    [line] = [r.getMessage() for r in caplog.records if "abandon-all" in r.getMessage()]
    assert "hand 1" in line and "abandoned" in line


async def test_human_reconnecting_within_grace_keeps_the_game() -> None:
    registry = TableRegistry(bot_pool=_HangingExecutor(), abandon_grace_seconds=60)
    table, _task = _started_table(registry, "abandon-reconnect")
    for seat in range(4):
        table.mark_disconnected(seat, f"seat-{seat}")
    await _ticks()
    stale_id = table._abandon_timer_id
    assert stale_id is not None

    binding = table.seat_bindings[0]
    assert binding is not None
    table.reconnect(0, "seat-0-again", lambda seq, wire: None, binding.reconnect_secret)
    table._wake()
    await _ticks()
    assert table._abandon_timer_id is None

    table._dispatch_expired_timer(stale_id)  # the old deadline popping late is a no-op
    assert not table.closed
    assert registry.is_running("abandon-reconnect")
    await registry.begin_shutdown(grace_seconds=0)


async def test_one_human_still_connected_keeps_the_game() -> None:
    registry = TableRegistry(bot_pool=_HangingExecutor(), abandon_grace_seconds=0)
    table, task = _started_table(registry, "abandon-partial", humans=2)
    table.mark_disconnected(0, "seat-0")
    await _ticks()
    assert table._abandon_timer_id is None
    assert not table.closed
    assert registry.is_running("abandon-partial")

    # bot seats never count as someone watching
    table.mark_disconnected(1, "seat-1")
    await asyncio.wait_for(task, timeout=1.0)
    assert table.closed


async def test_showcase_table_is_exempt() -> None:
    registry = TableRegistry(bot_pool=_HangingExecutor(), abandon_grace_seconds=0)
    registry.start_showcase("BOTS", DEFAULT_RULESET)
    await _ticks()
    table = registry.get("BOTS")
    assert table is not None
    assert not table.closed
    assert table._abandon_timer_id is None
    assert registry.is_running("BOTS")
    await registry.begin_shutdown(grace_seconds=0)


async def test_late_bot_result_after_end_is_dropped() -> None:
    pool = _HangingExecutor()
    table = Table("abandon-late-bot", DEFAULT_RULESET, game_seed=1, bot_pool=pool)
    table.abandon_grace_seconds = 0
    _bind(table, 0, status="bot")  # dealer, on turn: a bot job goes out
    _bind(table, 1)
    table._poke_bots()
    tag = table._pending_bot[0]
    submitted = pool.submitted

    table.mark_disconnected(1, "seat-1")
    # _WakeUp, then the deadline armed at the first tick's tail pops
    for _ in range(2):
        await table.process_one()
    assert table.closed
    assert table._pending_bot == {}

    state = table.state
    aid = legal_mask(state, 0).index(True)
    table._handle_bot_result(BotResult(seat=0, tag=tag, aid=aid))
    table._poke_bots()
    assert table.state is state
    assert table.actions == []
    assert pool.submitted == submitted


def test_ended_table_refuses_connections_and_leaves_the_lobby(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ABANDONED_TABLE_GRACE_SECONDS", "0")
    with TestClient(app) as client:
        table_id = client.post("/tables", json={"practice": True}).json()["table_id"]
        with client.websocket_connect(f"/ws?table={table_id}") as conn:
            conn.send_json({"v": 1, "t": "hello", "ts": 0, "d": {"client_version": "test"}})
            conn.send_json({"v": 1, "t": "join", "id": "j", "ts": 0, "d": {"seat": 0}})
            conn.send_json({"v": 1, "t": "ready", "id": "r", "ts": 0, "d": {}})
            table = ws.registry().get(table_id)
            assert table is not None
            deadline = time.monotonic() + 2.0
            while not table.started:
                assert time.monotonic() < deadline
                time.sleep(0.01)
        deadline = time.monotonic() + 2.0
        while not ws.registry().is_closed(table_id):
            assert time.monotonic() < deadline
            time.sleep(0.01)

        listed = [t["id"] for t in client.get("/tables").json()["tables"]]
        assert table_id not in listed

        with client.websocket_connect(f"/ws?table={table_id}") as late:
            frame = late.receive_json()
            assert frame["t"] == "error"
            assert frame["d"]["code"] == "table_closed"
            with pytest.raises(WebSocketDisconnect):
                late.receive_json()
        assert ws.registry().get(table_id) is None  # the late connect didn't recreate it
