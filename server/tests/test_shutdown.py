"""Graceful shutdown drain (docs/00-architecture.md §8.1, docs/05-roadmap.md M3).

`RoomRegistry.begin_shutdown`/`Room.wait_for_shutdown_boundary` are driven directly (bare
`Room`/`RoomRegistry`, no real WebSocket -- `tests/test_room.py`'s style: a `RoomRegistry`'s
`get_or_create` already starts a real background `asyncio.Task` running `Room.run()`, so this
still exercises the real dispatch loop, just without a socket in front of it) since the grace
window itself needs fine-grained async control (a concurrent drain-wait racing real inbox
processing) that `fastapi.testclient`'s blocking `receive_json()` API doesn't give a clean way to
assert on. `test_ws.py`'s `WebSocketDisconnect`-on-close and `/healthz`'s draining reflection are
still exercised end to end over the real app below, where that's the more direct test.

Every test here pins `SHUTDOWN_GRACE_SECONDS` implicitly via `server/tests/conftest.py`'s
session-wide default (0) or passes `grace_seconds` explicitly to `begin_shutdown` -- never a
real multi-second sleep.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import uuid

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import ws
from app.main import app
from app.registry import RoomRegistry
from app.room import Room, SeatBinding
from mahjong_core.actions import Discard
from mahjong_core.config import DEFAULT_RULESET
from mahjong_core.engine import new_game
from mahjong_core.state import GameState, Phase
from mahjong_core.tiles import TileType, tile_ids_for_type

_SEAT0_JUNK = tile_ids_for_type(TileType.PIN_2)[:4] + tile_ids_for_type(TileType.PIN_4)[:4]
_SEAT0_JUNK += tile_ids_for_type(TileType.PIN_6)[:4] + tile_ids_for_type(TileType.PIN_8)[:1]
_SEAT0_DISCARD = tile_ids_for_type(TileType.WIND_EAST)[0]
_SEAT1_JUNK = tile_ids_for_type(TileType.SOU_1)[:4] + tile_ids_for_type(TileType.SOU_3)[:4]
_SEAT1_JUNK += tile_ids_for_type(TileType.SOU_5)[:4] + tile_ids_for_type(TileType.SOU_7)[:1]
_SEAT2_JUNK = (
    tile_ids_for_type(TileType.WIND_SOUTH)[:4]
    + tile_ids_for_type(TileType.WIND_WEST)[:4]
    + tile_ids_for_type(TileType.WIND_NORTH)[:4]
    + tile_ids_for_type(TileType.DRAGON_RED)[:1]
)
_SEAT3_JUNK = (
    tile_ids_for_type(TileType.DRAGON_GREEN)[:4]
    + tile_ids_for_type(TileType.DRAGON_WHITE)[:4]
    + tile_ids_for_type(TileType.MAN_2)[:4]
    + tile_ids_for_type(TileType.MAN_4)[:1]
)


def _with_seat(state: GameState, seat: int, **overrides: object) -> GameState:
    seats = list(state.seats)
    seats[seat] = dataclasses.replace(seats[seat], **overrides)  # type: ignore[arg-type]
    return dataclasses.replace(state, seats=tuple(seats))  # type: ignore[arg-type]


def _rig_uncontested_state(seed: int) -> GameState:
    """Seat 0 on turn, about to discard a lone WIND_EAST nobody else holds any of -- every
    other seat's junk is disjoint by tile type, so the discard is guaranteed uncontested
    (no chow/pung possible) regardless of which tile were chosen. Wall emptied so the
    uncontested discard ends the hand (exhaustive draw) immediately -- one action, one hand
    boundary, matching `Room.wait_for_shutdown_boundary`'s contract."""
    state = new_game(DEFAULT_RULESET, game_seed=seed)
    state = dataclasses.replace(state, phase=Phase.AWAIT_ACTION, turn=0, claim_window=None)
    state = _with_seat(state, 0, concealed=(*_SEAT0_JUNK, _SEAT0_DISCARD), discards=())
    state = _with_seat(state, 1, concealed=tuple(_SEAT1_JUNK))
    state = _with_seat(state, 2, concealed=tuple(_SEAT2_JUNK))
    state = _with_seat(state, 3, concealed=tuple(_SEAT3_JUNK))
    return dataclasses.replace(state, wall=dataclasses.replace(state.wall, tiles=()))


class _FakeSocket:
    """Stands in for `SeatBinding.send` -- pushes onto an `asyncio.Queue` instead of a real WS
    write, so a test can `await queue.get()` for a specific frame exactly like
    `fastapi.testclient`'s `receive_json()` does, without a real socket."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()

    def send(self, _seq: int, wire: dict[str, object]) -> None:
        self.queue.put_nowait(wire)

    async def recv(self) -> dict[str, object]:
        return await self.queue.get()


def _bind_fake_seats(room: Room) -> list[_FakeSocket]:
    sockets = [_FakeSocket() for _ in range(4)]
    for seat, sock in enumerate(sockets):
        room.seat_bindings[seat] = SeatBinding(session_id=f"seat-{seat}", send=sock.send)
    return sockets


async def test_mid_hand_room_gets_server_shutdown_and_finishes_within_grace_window() -> None:
    registry = RoomRegistry()
    room = registry.get_or_create("shutdown-finish", DEFAULT_RULESET, seed=1, require_ready=False)
    room.state = _rig_uncontested_state(seed=1)
    sockets = _bind_fake_seats(room)

    drain_task = asyncio.create_task(registry.begin_shutdown(grace_seconds=5.0))

    # every seat gets the broadcast immediately -- step 2, before the drain wait even resolves.
    for sock in sockets:
        frame = await asyncio.wait_for(sock.recv(), timeout=1.0)
        assert frame["t"] == "server_shutdown"
        assert isinstance(frame["deadline_ts"], int)

    assert registry.draining is True
    assert not drain_task.done()  # still waiting on this room's own hand boundary

    # finish the mid-hand discard for real -- Room's own background task processes it.
    room.submit(0, Discard(tile_id=_SEAT0_DISCARD))

    # drain resolves once the room reaches the hand boundary -- well under the 5s grace window,
    # proving this isn't just "waited out the timeout".
    await asyncio.wait_for(drain_task, timeout=1.0)
    assert room.state.hand_no == 2  # exhaustive draw -> next hand dealt: a real boundary


async def test_wait_for_shutdown_boundary_waits_out_an_in_flight_game_over_persist() -> None:
    """Regression for the race `Room.wait_for_shutdown_boundary`'s own docstring now documents:
    `begin_shutdown` only ever calls this on a room whose background task is still running, so a
    room already at `Phase.GAME_OVER` here is, by construction, one whose final `process_one()`
    tick is still suspended inside `_persist_game_record()` -- `state.phase` and `self._persisted`
    both flip synchronously, before that write even starts. Two bugs used to lose this race:
    fast-pathing on `state.phase` alone returned instantly, before the write started; and once
    that was fixed, falling through to the normal `timeout`-bounded wait still lost, since
    `server/tests/conftest.py` pins `grace_seconds` to `0` for the whole test session and
    `asyncio.wait_for` with a non-positive timeout never gives the awaited event a single
    scheduling turn. Both are exercised directly (no real DB, no full hand) by rigging exactly
    the state `process_one()`'s own tail would have produced mid-persist."""
    registry = RoomRegistry()
    room = registry.get_or_create(
        "shutdown-persist-race", DEFAULT_RULESET, seed=6, require_ready=False
    )
    room.state = dataclasses.replace(room.state, phase=Phase.GAME_OVER)
    room._persisted = True  # process_one()'s tail sets this before the write starts, not after

    async def _finish_persist_soon() -> None:
        await asyncio.sleep(0.05)
        room._game_over_persisted = True
        if room._shutdown_boundary is not None:
            room._shutdown_boundary.set()

    finisher = asyncio.create_task(_finish_persist_soon())

    # grace_seconds=0, exactly this codebase's session-wide test pin -- must not abandon a
    # persist that's genuinely about to finish just because there's no grace window to spare.
    reached = await asyncio.wait_for(room.wait_for_shutdown_boundary(0.0), timeout=1.0)
    assert reached is True
    # the load-bearing assertion: proves this genuinely waited for the write, not just for the
    # phase flip (bug 1) or for `timeout=0` to elapse regardless (bug 2).
    assert room._game_over_persisted is True
    await finisher


async def test_room_never_reaching_boundary_is_abandoned_not_hung(
    caplog: pytest.LogCaptureFixture,
) -> None:
    registry = RoomRegistry()
    room = registry.get_or_create("shutdown-timeout", DEFAULT_RULESET, seed=2, require_ready=False)
    room.state = _rig_uncontested_state(seed=2)
    _bind_fake_seats(room)

    # nobody ever submits the finishing discard -- the room sits mid-hand forever. The drain
    # must still return promptly, bounded by grace_seconds, not hang.
    with caplog.at_level(logging.WARNING):
        await asyncio.wait_for(registry.begin_shutdown(grace_seconds=0.05), timeout=2.0)

    assert room.state.phase != Phase.GAME_OVER  # genuinely never finished
    assert any(
        "shutdown-timeout" in r.message and "abandoning" in r.message for r in caplog.records
    )


async def test_begin_shutdown_is_a_noop_when_no_room_has_any_seat_bound() -> None:
    registry = RoomRegistry()
    registry.get_or_create("shutdown-empty", DEFAULT_RULESET, seed=3, require_ready=False)
    # no seat_bindings at all -- nothing to warn, nothing to wait on.
    await asyncio.wait_for(registry.begin_shutdown(grace_seconds=90.0), timeout=1.0)
    assert registry.draining is True


def test_healthz_reflects_draining_state() -> None:
    with TestClient(app) as client:
        ok = client.get("/healthz")
        assert ok.status_code == 200
        assert ok.json() == {"status": "ok"}

        ws.registry().draining = True
        draining = client.get("/healthz")
        assert draining.status_code == 503
        assert draining.json() == {"status": "draining"}


def test_new_connections_rejected_while_draining() -> None:
    room_id = f"draining-{uuid.uuid4()}"
    with TestClient(app) as client:
        ws.registry().draining = True
        with pytest.raises(WebSocketDisconnect), client.websocket_connect(f"/ws?room={room_id}"):
            pass
