"""Graceful shutdown drain (docs/architecture.md §8.1, docs/decisions/0018-milestone-plan.md M3).

`TableRegistry.begin_shutdown`/`Table.wait_for_shutdown_boundary` are driven directly (bare
`Table`/`TableRegistry`, no real WebSocket -- `tests/test_table.py`'s style: a `TableRegistry`'s
`get_or_create` already starts a real background `asyncio.Task` running `Table.run()`, so this
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
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.websockets import WebSocketDisconnect

from app import ws
from app.db.session import make_engine, make_session_factory
from app.main import app
from app.registry import TableRegistry
from app.table import SeatBinding, Table
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


# `_bind_fake_seats` binds real "connected" SeatBindings (not bot/autoplay), so the hand-end
# hold never auto-acks; `hand_end_seconds=0` is what lets it resolve (test_table.py's `_BOUNDED_RULESET` idiom).
_ZERO_HOLD_RULESET = dataclasses.replace(DEFAULT_RULESET, hand_end_seconds=0)


def _rig_uncontested_state(seed: int) -> GameState:
    """Seat 0 on turn, about to discard a lone WIND_EAST nobody else holds any of -- every
    other seat's junk is disjoint by tile type, so the discard is guaranteed uncontested
    (no chow/pung possible) regardless of which tile were chosen. Wall emptied so the
    uncontested discard ends the hand (exhaustive draw) immediately -- one action, one hand
    boundary, matching `Table.wait_for_shutdown_boundary`'s contract."""
    state = new_game(_ZERO_HOLD_RULESET, game_seed=seed)
    state = dataclasses.replace(state, phase=Phase.AWAIT_ACTION, turn=0, claim_window=None)
    state = _with_seat(state, 0, concealed=(*_SEAT0_JUNK, _SEAT0_DISCARD), discards=())
    state = _with_seat(state, 1, concealed=tuple(_SEAT1_JUNK))
    state = _with_seat(state, 2, concealed=tuple(_SEAT2_JUNK))
    state = _with_seat(state, 3, concealed=tuple(_SEAT3_JUNK))
    return dataclasses.replace(state, wall=dataclasses.replace(state.wall, tiles=()))


_NO_REPEAT_RULESET = dataclasses.replace(
    _ZERO_HOLD_RULESET, dealer_repeat_on_win=False, dealer_repeat_on_draw=False
)


def _rig_final_hand_state(seed: int) -> GameState:
    """`_rig_uncontested_state`, but on the last hand of a repeat-off `EAST_ONLY` game (seat 3
    deals), so the exhaustive draw that ends this hand ends the whole *game* -- the only thing
    that triggers `process_one()`'s `GAME_OVER` persist."""
    state = _rig_uncontested_state(seed)
    return dataclasses.replace(state, ruleset=_NO_REPEAT_RULESET, dealer=3, hand_no=4)


def _broken_session_factory() -> async_sessionmaker[AsyncSession]:
    """A real `async_sessionmaker` (not a bare stand-in callable, which fails the same type
    check `Table` enforces against the real one from `app/main.py`) against a schema-less
    in-memory SQLite DB -- no `Base.metadata.create_all`, so a write against it fails exactly
    like an unapplied migration would (no `games` table): the failure that actually bit."""
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    return make_session_factory(engine)


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


def _bind_fake_seats(table: Table) -> list[_FakeSocket]:
    sockets = [_FakeSocket() for _ in range(4)]
    for seat, sock in enumerate(sockets):
        table.seat_bindings[seat] = SeatBinding(
            session_id=f"seat-{seat}", send=sock.send, name=f"Seat {seat}"
        )
    return sockets


async def test_mid_hand_table_gets_server_shutdown_and_finishes_within_grace_window() -> None:
    registry = TableRegistry()
    table = registry.get_or_create("shutdown-finish", DEFAULT_RULESET, seed=1, require_ready=False)
    table.state = _rig_uncontested_state(seed=1)
    sockets = _bind_fake_seats(table)

    drain_task = asyncio.create_task(registry.begin_shutdown(grace_seconds=5.0))

    # every seat gets the broadcast immediately -- step 2, before the drain wait even resolves.
    for sock in sockets:
        frame = await asyncio.wait_for(sock.recv(), timeout=1.0)
        assert frame["t"] == "server_shutdown"
        assert isinstance(frame["deadline_ts"], int)

    assert registry.draining is True
    assert not drain_task.done()  # still waiting on this table's own hand boundary

    # finish the mid-hand discard for real -- Table's own background task processes it.
    table.submit(0, Discard(tile_id=_SEAT0_DISCARD))

    # drain resolves once the table reaches the hand boundary -- well under the 5s grace window,
    # proving this isn't just "waited out the timeout".
    await asyncio.wait_for(drain_task, timeout=1.0)
    assert table.state.hand_no == 2  # exhaustive draw -> next hand dealt: a real boundary


async def test_wait_for_shutdown_boundary_waits_out_an_in_flight_game_over_persist() -> None:
    """Regression for the race `Table.wait_for_shutdown_boundary`'s own docstring now documents:
    `begin_shutdown` only ever calls this on a table whose background task is still running, so a
    table already at `Phase.GAME_OVER` here is, by construction, one whose final `process_one()`
    tick is still suspended inside `_persist_game_record()` -- `state.phase` and `self._persisted`
    both flip synchronously, before that write even starts. Two bugs used to lose this race:
    fast-pathing on `state.phase` alone returned instantly, before the write started; and once
    that was fixed, falling through to the normal `timeout`-bounded wait still lost, since
    `server/tests/conftest.py` pins `grace_seconds` to `0` for the whole test session and
    `asyncio.wait_for` with a non-positive timeout never gives the awaited event a single
    scheduling turn. Both are exercised directly (no real DB, no full hand) by rigging exactly
    the state `process_one()`'s own tail would have produced mid-persist."""
    registry = TableRegistry()
    table = registry.get_or_create(
        "shutdown-persist-race", DEFAULT_RULESET, seed=6, require_ready=False
    )
    table.state = dataclasses.replace(table.state, phase=Phase.GAME_OVER)
    table._persisted = True  # process_one()'s tail sets this before the write starts, not after

    async def _finish_persist_soon() -> None:
        await asyncio.sleep(0.05)
        table._game_over_persisted = True
        if table._shutdown_boundary is not None:
            table._shutdown_boundary.set()

    finisher = asyncio.create_task(_finish_persist_soon())

    # grace_seconds=0, exactly this codebase's session-wide test pin -- must not abandon a
    # persist that's genuinely about to finish just because there's no grace window to spare.
    reached = await asyncio.wait_for(table.wait_for_shutdown_boundary(0.0), timeout=1.0)
    assert reached is True
    # the load-bearing assertion: proves this genuinely waited for the write, not just for the
    # phase flip (bug 1) or for `timeout=0` to elapse regardless (bug 2).
    assert table._game_over_persisted is True
    await finisher


async def test_failed_game_over_persist_is_logged_and_still_ends_the_drain_window(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Regression: a `GAME_OVER` write that *raises* used to propagate straight out of
    `process_one()` -> `Table.run()`, killing the table task with `_game_over_persisted` still
    `False` and the boundary event never set -- precisely the state
    `wait_for_shutdown_boundary` waits on *unbounded*, so every later drain (and the process,
    or the `TestClient` context, waiting on it) hung forever. Found for real: docker-compose
    sets `DATABASE_URL`, the dev database had no `games` table (migrations never applied), and
    `make test-server` wedged on the first test that finishes a game.

    Driven through `process_one()` directly rather than a background task so the failing tick
    is observed, not raced: under the old code this call itself raises.
    """
    table = Table(
        "shutdown-persist-fails",
        _NO_REPEAT_RULESET,
        game_seed=7,
        session_factory=_broken_session_factory(),
    )
    table.state = _rig_final_hand_state(seed=7)
    _bind_fake_seats(table)
    table.submit(0, Discard(tile_id=_SEAT0_DISCARD))

    with caplog.at_level(logging.ERROR):
        # first tick: discard lands HAND_OVER, arms the hand_end_seconds=0 timer (no seat here
        # is bot/autoplay, so nothing pre-acks). Second tick: timer expired -- advances to GAME_OVER.
        await asyncio.wait_for(table.process_one(), timeout=2.0)
        assert table.state.phase == Phase.HAND_OVER
        await asyncio.wait_for(table.process_one(), timeout=2.0)

    # mypy doesn't see the second process_one() reassigns table.state to a new GameState, so
    # it flags this phase check as unreachable -- it's real and correct.
    assert table.state.phase == Phase.GAME_OVER
    assert table._game_over_persisted is True
    assert any("persist failed" in r.message for r in caplog.records)

    # and the drain that used to hang on it now resolves immediately, without abandoning it.
    assert await asyncio.wait_for(table.wait_for_shutdown_boundary(0.0), timeout=1.0) is True


async def test_table_never_reaching_boundary_is_abandoned_not_hung(
    caplog: pytest.LogCaptureFixture,
) -> None:
    registry = TableRegistry()
    table = registry.get_or_create("shutdown-timeout", DEFAULT_RULESET, seed=2, require_ready=False)
    table.state = _rig_uncontested_state(seed=2)
    _bind_fake_seats(table)

    # nobody ever submits the finishing discard -- the table sits mid-hand forever. The drain
    # must still return promptly, bounded by grace_seconds, not hang.
    with caplog.at_level(logging.WARNING):
        await asyncio.wait_for(registry.begin_shutdown(grace_seconds=0.05), timeout=2.0)

    assert table.state.phase != Phase.GAME_OVER  # genuinely never finished
    assert any(
        "shutdown-timeout" in r.message and "abandoning" in r.message for r in caplog.records
    )


async def test_begin_shutdown_is_a_noop_when_no_table_has_any_seat_bound() -> None:
    registry = TableRegistry()
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
    table_id = f"draining-{uuid.uuid4()}"
    with TestClient(app) as client:
        ws.registry().draining = True
        with pytest.raises(WebSocketDisconnect), client.websocket_connect(f"/ws?table={table_id}"):
            pass
