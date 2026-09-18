"""A real `Room`/`RoomRegistry`-driven game over WS reaching `Phase.GAME_OVER` and persisting a
`GameRecord` (docs/06-ml.md §2, docs/00-architecture.md §6, docs/05-roadmap.md M3's "Postgres
persistence of finished games" -- the piece M1's `bots/selfplay.py` covered for bot-only games,
this covers for a real `Room`-driven one).

Same `TestClient` + `room.state = ...` white-box rig `tests/test_ws_gameplay.py` established,
plus one more trick: `dealer=3` with both dealer-repeat flags off makes *this* hand -- however it
ends -- the last hand of an `EAST_ONLY` game (`mahjong_core/engine.py`'s `start_next_hand`: once
`next_dealer` wraps back to seat 0 with no round left, the game ends), so a single uncontested
discard is enough to drive the whole game to `Phase.GAME_OVER` without needing to script a
multi-hand game end to end.

`DATABASE_URL` points at a tmp-file SQLite DB (`server/tests/test_game_record.py`'s pattern,
adapted: that file uses `:memory:` because everything happens through one already-open
`AsyncSession`; here the schema has to exist *before* `app.main`'s `lifespan` opens its own
engine against the same file, so a tmp file -- not `:memory:` -- is what lets two separate
engines see the same data, matching how a real deployment's migration step runs before the app
starts, not inside it)."""

from __future__ import annotations

import asyncio
import dataclasses
import itertools
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import Base, GameRecord
from app.db.session import make_engine, make_session_factory
from app.main import app
from app.ws import get_room
from mahjong_core.actions import action_from_dict
from mahjong_core.config import DEFAULT_RULESET, RuleSet
from mahjong_core.engine import ENGINE_VERSION, new_game
from mahjong_core.state import GameState, Phase
from mahjong_core.tiles import TileType, tile_ids_for_type

_id_gen = itertools.count(1)

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

_LAST_HAND_RULESET = dataclasses.replace(
    DEFAULT_RULESET, dealer_repeat_on_win=False, dealer_repeat_on_draw=False
)


def _ts() -> int:
    return time.time_ns() // 1_000_000


def _msg(t: str, d: dict[str, object], *, id_: str | None = None) -> dict[str, object]:
    frame: dict[str, object] = {"v": 1, "t": t, "ts": _ts(), "d": d}
    if id_ is not None:
        frame["id"] = id_
    return frame


def _next_id() -> str:
    return f"c-{next(_id_gen)}"


def _with_seat(state: GameState, seat: int, **overrides: object) -> GameState:
    seats = list(state.seats)
    seats[seat] = dataclasses.replace(seats[seat], **overrides)  # type: ignore[arg-type]
    return dataclasses.replace(state, seats=tuple(seats))  # type: ignore[arg-type]


def _rig_last_hand_state(seed: int) -> GameState:
    """Seat 0 on turn, dealer set to seat 3 (so this hand ending -- win or draw -- always wraps
    the deal back to seat 0 with no round left under `EAST_ONLY`, i.e. `Phase.GAME_OVER`).
    Otherwise identical to `tests/test_shutdown.py`'s uncontested-discard fixture: every seat's
    junk is a disjoint tile type, so seat 0's one discard is guaranteed unclaimed."""
    state = new_game(_LAST_HAND_RULESET, game_seed=seed)
    state = dataclasses.replace(
        state, phase=Phase.AWAIT_ACTION, turn=0, dealer=3, claim_window=None
    )
    state = _with_seat(state, 0, concealed=(*_SEAT0_JUNK, _SEAT0_DISCARD), discards=())
    state = _with_seat(state, 1, concealed=tuple(_SEAT1_JUNK))
    state = _with_seat(state, 2, concealed=tuple(_SEAT2_JUNK))
    state = _with_seat(state, 3, concealed=tuple(_SEAT3_JUNK))
    return dataclasses.replace(state, wall=dataclasses.replace(state.wall, tiles=()))


def _fetch_latest_record(database_url: str) -> GameRecord | None:
    async def _run() -> GameRecord | None:
        engine = make_engine(database_url)
        try:
            factory = make_session_factory(engine)
            async with factory() as session:
                result = await session.execute(select(GameRecord).order_by(GameRecord.id.desc()))
                return result.scalars().first()
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def test_full_game_via_ws_persists_a_game_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "game_record_ws.db"
    database_url = f"sqlite+aiosqlite:///{db_path}"

    async def _create_schema() -> None:
        engine = make_engine(database_url)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        finally:
            await engine.dispose()

    asyncio.run(_create_schema())
    monkeypatch.setenv("DATABASE_URL", database_url)

    room_id = f"persist-{uuid.uuid4()}"
    seed = 20260917

    with (
        TestClient(app) as client,
        client.websocket_connect(f"/ws?room={room_id}") as ws0,
        client.websocket_connect(f"/ws?room={room_id}") as ws1,
        client.websocket_connect(f"/ws?room={room_id}") as ws2,
        client.websocket_connect(f"/ws?room={room_id}") as ws3,
    ):
        room = get_room(room_id)
        assert room is not None
        room.state = _rig_last_hand_state(seed=seed)

        wss = [ws0, ws1, ws2, ws3]
        names = {seat: f"Player {seat}" for seat in range(4)}
        for seat, sock in enumerate(wss):
            sock.send_json(_msg("hello", {"client_version": "test"}))
            sock.send_json(_msg("join", {"seat": seat, "name": names[seat]}, id_=_next_id()))
            for s in range(seat + 1):
                frame = wss[s].receive_json()
                assert frame["t"] == "seat_state"
            sync = sock.receive_json()
            assert sync["t"] == "state_sync"
            ack = sock.receive_json()
            assert ack["t"] == "ack" and ack["d"]["ok"] is True

        assert room is not None
        for seat in range(4):
            binding = room.seat_bindings[seat]
            assert binding is not None
            assert binding.name == names[seat]

        for seat in range(3):
            wss[seat].send_json(_msg("ready", {}, id_=_next_id()))
            ack = wss[seat].receive_json()
            assert ack["t"] == "ack" and ack["d"]["ok"] is True
        wss[3].send_json(_msg("ready", {}, id_=_next_id()))
        for seat in range(4):
            hand_start = wss[seat].receive_json()
            assert hand_start["t"] == "hand_start"
            deal = wss[seat].receive_json()
            assert deal["t"] == "deal"
            turn = wss[seat].receive_json()
            assert turn["t"] == "turn"
        ack3 = wss[3].receive_json()
        assert ack3["t"] == "ack"

        # one uncontested discard -- unclaimed, wall already empty -> exhaustive draw -> (dealer
        # wraps to seat 0, no round left under EAST_ONLY) -> Phase.GAME_OVER, all in this tick.
        discard_id = _next_id()
        wss[0].send_json(_msg("discard", {"tile_id": _SEAT0_DISCARD}, id_=discard_id))
        ack_d0 = wss[0].receive_json()
        assert ack_d0["d"] == {"id": discard_id, "ok": True}

        expected_types = ["discard", "hand_end", "score", "game_end"]
        for _ in expected_types:
            for ws_conn in wss:
                frame = ws_conn.receive_json()
                assert frame["t"] in expected_types

        assert room.state.phase == Phase.GAME_OVER

    # the room's background task has to actually finish (and its GAME_OVER persist with it)
    # before we can trust the DB row exists -- Room.run() returns only after that, and
    # RoomRegistry's own task-cleanup already proves this timing (tests/test_registry.py).
    record = _fetch_latest_record(database_url)
    assert record is not None
    assert record.engine_version == ENGINE_VERSION
    assert record.seed == seed
    assert RuleSet.from_dict(record.ruleset) == _LAST_HAND_RULESET
    assert record.result["hand_count"] == room.state.hand_no
    assert record.result["final_scores"] == [s.score for s in room.state.seats]
    assert record.players == [names[s] for s in range(4)]
    assert len(record.action_log) == len(room.actions)
    assert [action_from_dict(d) for d in record.action_log] == room.actions
