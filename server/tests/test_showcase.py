"""The always-on all-bot showcase table (`app/registry.py`'s `TableRegistry.start_showcase`) and
the open-hands spectator setting it runs with (`app/table.py`'s `TableSettings`)."""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.errors import SeatTakenError, TableFullError
from app.main import app
from app.registry import TableRegistry
from app.table import Table
from app.table_types import TableSettings
from mahjong_core.actions import Pass
from mahjong_core.config import DEFAULT_RULESET
from mahjong_core.state import Phase

_FAST = dataclasses.replace(DEFAULT_RULESET, hand_end_seconds=0)


class _Capture:
    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []
        self.closed = False

    def send(self, _seq: int, wire: dict[str, Any]) -> None:
        self.frames.append(wire)

    def close(self) -> None:
        self.closed = True


async def _until(pred: Callable[[], bool], *, timeout: float = 5.0) -> None:
    async def _poll() -> None:
        while not pred():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(_poll(), timeout=timeout)


def _showcase(registry: TableRegistry) -> Table:
    table = registry.get("BOTS")
    assert table is not None
    return table


def _end_game(table: Table) -> None:
    table.state = dataclasses.replace(table.state, phase=Phase.GAME_OVER, claim_window=None)
    table.submit(0, Pass(window_id=0, seat=0))  # dropped as illegal; just wakes the loop


async def _shutdown(registry: TableRegistry) -> None:
    task = registry._showcase_task
    await asyncio.wait_for(registry.begin_shutdown(grace_seconds=30), timeout=2)
    assert task is not None
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def test_showcase_plays_itself_and_shows_spectators_every_hand() -> None:
    registry = TableRegistry()
    registry.start_showcase("BOTS", _FAST, restart_delay=0)
    table = _showcase(registry)
    assert table.seat_status_tuple() == ("bot", "bot", "bot", "bot")

    spectator = _Capture()
    table.register_spectator("spec-1", spectator.send, spectator.close)
    sync = spectator.frames[0]
    assert sync["t"] == "state_sync"
    assert sync["seat"] is None
    assert sync["hands"] == [list(s.concealed) for s in table.state.seats]

    # nobody readies an all-bot table -- it deals and plays on its own
    await _until(lambda: any(f["t"] == "draw" for f in spectator.frames))
    assert table.started
    draw = next(f for f in spectator.frames if f["t"] == "draw")
    assert draw["tile_id"] is not None

    # spectators get no `deal` -- each hand_start is followed by a snapshot with the new hands
    kinds = [f["t"] for f in spectator.frames]
    after_deal = spectator.frames[kinds.index("hand_start") + 1]
    assert after_deal["t"] == "state_sync"
    assert all(len(hand) >= 13 for hand in after_deal["hands"])

    await _shutdown(registry)


async def test_showcase_draws_each_seats_level_per_game() -> None:
    registry = TableRegistry()
    registry.start_showcase("BOTS", _FAST, restart_delay=0, bot_tiers=("T1", "T2"))
    levels: set[tuple[str | None, ...]] = set()
    for _ in range(8):
        table = _showcase(registry)
        spectator = _Capture()
        table.register_spectator("spec-1", spectator.send, spectator.close)
        sync_levels = spectator.frames[0]["bot_levels"]
        assert sync_levels == [table._effective_bot_tier(seat) for seat in range(4)]
        assert set(sync_levels) <= {"T1", "T2"}
        levels.add(tuple(sync_levels))
        _end_game(table)
        await _until(lambda t=table: registry.get("BOTS") is not t)
    assert len(levels) > 1

    await _shutdown(registry)


def test_bot_levels_only_name_bot_seats() -> None:
    table = Table(
        "t-practice", DEFAULT_RULESET, 1, practice=True, seat_bot_tiers={1: "T1", 3: "ORACLE"}
    )
    player = _Capture()
    table.join("s-alice", player.send, seat=0, name="Alice")
    sync = next(f for f in player.frames if f["t"] == "state_sync")
    assert sync["bot_levels"] == [None, "T1", "T2", "ORACLE"]


async def test_showcase_restarts_under_same_id_and_closes_old_spectators() -> None:
    registry = TableRegistry()
    registry.start_showcase("BOTS", _FAST, restart_delay=0)
    first = _showcase(registry)
    spectator = _Capture()
    first.register_spectator("spec-1", spectator.send, spectator.close)

    _end_game(first)
    await _until(lambda: registry.get("BOTS") is not first)

    assert spectator.closed
    second = _showcase(registry)
    assert registry.is_running("BOTS")
    assert second.all_bots
    assert second.settings.spectators_see_hands

    await _shutdown(registry)


async def test_showcase_stays_listed_between_games() -> None:
    registry = TableRegistry()
    registry.start_showcase("BOTS", _FAST, restart_delay=60)
    table = _showcase(registry)
    await _until(lambda: table.started)

    [summary] = registry.list_tables()
    assert summary.table_id == "BOTS"
    assert summary.status == "in_progress"
    assert summary.seat_status == ("bot", "bot", "bot", "bot")

    _end_game(table)
    await _until(lambda: not registry.is_running("BOTS"))
    assert [t.table_id for t in registry.list_tables()] == ["BOTS"]

    await _shutdown(registry)  # cancels the supervisor mid-restart-delay


async def test_shutdown_cancels_showcase_without_waiting_for_a_hand_boundary() -> None:
    registry = TableRegistry()
    registry.start_showcase("BOTS", DEFAULT_RULESET)
    table = _showcase(registry)
    await _until(lambda: table.started)

    await _shutdown(registry)
    await _until(lambda: not registry.is_running("BOTS"))


async def test_all_bot_table_holds_hand_end_for_spectators() -> None:
    """Every seat is a bot, so the hold's ack set is full immediately -- a normal table would
    advance the same tick, an all-bot one rides out `hand_end_seconds` instead."""
    all_bots = Table("t-all", DEFAULT_RULESET, 1, require_ready=True, all_bots=True)
    assert all_bots._open_hand_end_window() is False

    practice = Table("t-practice", DEFAULT_RULESET, 1, require_ready=True, practice=True)
    practice._bind_bot_seat(0)
    assert practice._open_hand_end_window() is True


def test_update_settings_resyncs_spectators_only_when_reveal_changes() -> None:
    table = Table("t-settings", DEFAULT_RULESET, 1, all_bots=True)
    spectator = _Capture()
    table.register_spectator("spec-1", spectator.send)
    assert spectator.frames[-1]["hands"] is None

    table.update_settings(TableSettings(spectators_see_hands=True))
    assert spectator.frames[-1]["t"] == "state_sync"
    assert spectator.frames[-1]["hands"] == [list(s.concealed) for s in table.state.seats]

    count = len(spectator.frames)
    table.update_settings(TableSettings(spectators_see_hands=True))
    assert len(spectator.frames) == count


def test_seats_never_see_other_hands_on_an_open_hands_table() -> None:
    table = Table(
        "t-open",
        DEFAULT_RULESET,
        1,
        all_bots=True,
        settings=TableSettings(spectators_see_hands=True),
    )
    sync = table.state_sync_wire(0)
    assert sync["hands"] is None
    assert sync["own_hand"] == list(table.state.seats[0].concealed)


@pytest.mark.parametrize("mode", [{}, {"practice": True}, {"require_ready": True}])
def test_open_hands_rejected_at_construction_unless_all_bots(mode: dict[str, bool]) -> None:
    with pytest.raises(ValueError, match="all-bot"):
        Table(
            "t-open", DEFAULT_RULESET, 1, settings=TableSettings(spectators_see_hands=True), **mode
        )


def test_update_settings_rejects_open_hands_on_a_table_with_human_seats() -> None:
    table = Table("t-practice", DEFAULT_RULESET, 1, practice=True)
    player = _Capture()
    table.join("s-alice", player.send, seat=0, name="Alice")
    spectator = _Capture()
    table.register_spectator("spec-1", spectator.send)
    count = len(spectator.frames)

    with pytest.raises(ValueError, match="all-bot"):
        table.update_settings(TableSettings(spectators_see_hands=True))
    assert not table.settings.spectators_see_hands
    assert len(spectator.frames) == count
    assert table.state_sync_wire(None)["hands"] is None

    table.update_settings(TableSettings(spectators_see_hands=False))


def test_no_human_can_take_a_seat_on_an_open_hands_table() -> None:
    table = Table(
        "t-open",
        DEFAULT_RULESET,
        1,
        all_bots=True,
        settings=TableSettings(spectators_see_hands=True),
    )
    player = _Capture()
    with pytest.raises(TableFullError):
        table.join("s-alice", player.send)
    with pytest.raises(TableFullError):
        table.join("s-alice", player.send, seat=0)
    with pytest.raises(SeatTakenError):
        table.reconnect(0, "s-alice", player.send, None)

    # refused on all_bots itself, not on seat occupancy: a freed bot seat stays closed
    table.seat_bindings[0] = None
    with pytest.raises(TableFullError):
        table.join("s-alice", player.send)
    with pytest.raises(TableFullError):
        table.join("s-alice", player.send, seat=0)
    assert player.frames == []


def test_lifespan_starts_showcase_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHOWCASE_TABLE_ID", "BOTS")
    with (
        TestClient(app) as client,
        client.websocket_connect("/ws?table=BOTS&spectate=true") as ws,
    ):
        sync = ws.receive_json()
        assert sync["t"] == "state_sync"
        assert sync["d"]["seat_status"] == ["bot", "bot", "bot", "bot"]
        assert set(sync["d"]["bot_levels"]) <= {"T1", "T2", "T4", "ORACLE"}
        assert [len(hand) for hand in sync["d"]["hands"]] == sync["d"]["concealed_counts"]

        tables = client.get("/tables").json()["tables"]
        assert [t["id"] for t in tables] == ["BOTS"]
