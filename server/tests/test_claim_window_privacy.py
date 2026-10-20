"""A seat or spectator without a claim offer must not learn, from messages or timing, whether
anyone could claim a discard (docs/architecture.md §4 "Claim hold", docs/protocol.md §3)."""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Any

from app.table import Table
from mahjong_core.actions import Discard, Pass
from mahjong_core.config import DEFAULT_RULESET
from mahjong_core.engine import new_game
from mahjong_core.state import Phase
from mahjong_core.tiles import TileType, tile_ids_for_type
from tests.game_state import with_seat

_MAN_4 = tile_ids_for_type(TileType.MAN_4)
_MAN_5 = tile_ids_for_type(TileType.MAN_5)
_MAN_6 = tile_ids_for_type(TileType.MAN_6)
_SOU_2 = tile_ids_for_type(TileType.SOU_2)
_SOU_4 = tile_ids_for_type(TileType.SOU_4)
_SOU_6 = tile_ids_for_type(TileType.SOU_6)
_SOU_8 = tile_ids_for_type(TileType.SOU_8)
_SOUTH = tile_ids_for_type(TileType.WIND_SOUTH)
_WEST = tile_ids_for_type(TileType.WIND_WEST)
_NORTH = tile_ids_for_type(TileType.WIND_NORTH)
_RED = tile_ids_for_type(TileType.DRAGON_RED)
_GREEN = tile_ids_for_type(TileType.DRAGON_GREEN)
_WHITE = tile_ids_for_type(TileType.DRAGON_WHITE)

_JUNK_HAND = (
    _SOU_2[0],
    _SOU_4[0],
    _SOU_6[0],
    _SOU_8[0],
    _SOU_2[1],
    _SOU_4[1],
    _SOU_6[1],
    _SOUTH[0],
    _WEST[0],
    _NORTH[0],
    _RED[0],
    _GREEN[0],
    _WHITE[0],
)

_HOLD = 0.2
_SPECTATOR = "spec"

Frame = tuple[float, dict[str, Any]]


def _discard_table(*, claimable: bool, hold: float) -> tuple[Table, list[Frame]]:
    """Seat 0 is about to discard 5m. `claimable`: seat 1 can chow it and seat 2 pung it;
    otherwise nobody can. Seat 3 is never offered anything. Returns the table and the frames
    a spectator receives, stamped with loop time."""
    ruleset = DEFAULT_RULESET
    table = Table("t-privacy", ruleset, game_seed=1, claim_hold_seconds=hold)
    state = new_game(ruleset, game_seed=1)
    state = dataclasses.replace(state, phase=Phase.AWAIT_ACTION, turn=0, claim_window=None)
    state = with_seat(state, 0, concealed=(*_JUNK_HAND, _MAN_5[0]), discards=())
    if claimable:
        state = with_seat(state, 1, concealed=(_MAN_4[0], _MAN_6[0], *_JUNK_HAND[:11]))
        state = with_seat(state, 2, concealed=(_MAN_5[1], _MAN_5[2], *_JUNK_HAND[:11]))
    else:
        state = with_seat(state, 1, concealed=_JUNK_HAND)
        state = with_seat(state, 2, concealed=_JUNK_HAND)
    state = with_seat(state, 3, concealed=_JUNK_HAND)
    table.state = state

    frames: list[Frame] = []
    loop = asyncio.get_running_loop()
    table.register_spectator(_SPECTATOR, lambda _seq, wire: frames.append((loop.time(), wire)))
    frames.clear()  # drop the registration state_sync
    return table, frames


def _seat_types(table: Table, seat: int, *, after: int) -> list[str]:
    return [env.event["t"] for env in table.ring[seat] if env.seq >= after]


async def _run_until_turn(table: Table, frames: list[Frame]) -> None:
    async def drive() -> None:
        while not any(w["t"] == "turn" for _, w in frames):
            await table.process_one()

    await asyncio.wait_for(drive(), timeout=5)


async def _play_discard(*, claimable: bool, hold: float) -> tuple[Table, list[Frame], int]:
    table, frames = _discard_table(claimable=claimable, hold=hold)
    seat3_head = table.seat_seq[3]
    table.submit(0, Discard(tile_id=_MAN_5[0]))
    await table.process_one()
    window = table.state.claim_window
    assert (window is not None) == claimable
    if window is not None:
        for seat in (1, 2):
            table.submit(seat, Pass(window_id=window.window_id, seat=seat))
    await _run_until_turn(table, frames)
    return table, frames, seat3_head


async def test_passed_discard_window_is_not_broadcast_to_non_offered_recipients() -> None:
    table, frames, seat3_head = await _play_discard(claimable=True, hold=0)

    assert "claim_resolved" not in _seat_types(table, 3, after=seat3_head)
    assert "claim_resolved" not in _seat_types(table, 0, after=0)
    assert not any(w["t"] == "claim_resolved" for _, w in frames)
    for seat in (1, 2):
        resolved = [e.event for e in table.ring[seat] if e.event["t"] == "claim_resolved"]
        assert len(resolved) == 1 and resolved[0]["seat"] is None


async def test_non_offered_stream_is_identical_with_or_without_a_discard_window() -> None:
    open_table, open_frames, open_head = await _play_discard(claimable=True, hold=0)
    none_table, none_frames, none_head = await _play_discard(claimable=False, hold=0)

    assert _seat_types(open_table, 3, after=open_head) == _seat_types(
        none_table, 3, after=none_head
    )
    assert [w["t"] for _, w in open_frames] == [w["t"] for _, w in none_frames]


def _gap(frames: list[Frame], first: str, then: str) -> float:
    t_first = next(t for t, w in frames if w["t"] == first)
    t_then = next(t for t, w in frames if w["t"] == then)
    return t_then - t_first


async def test_discard_to_draw_gap_is_the_same_hold_with_or_without_a_window() -> None:
    _, open_frames, _ = await _play_discard(claimable=True, hold=_HOLD)
    _, none_frames, _ = await _play_discard(claimable=False, hold=_HOLD)

    open_gap = _gap(open_frames, "discard", "draw")
    none_gap = _gap(none_frames, "discard", "draw")
    assert open_gap >= _HOLD
    assert none_gap >= _HOLD
    assert abs(open_gap - none_gap) < _HOLD / 2


async def test_next_seat_cannot_act_before_its_held_draw_is_published() -> None:
    table, frames = _discard_table(claimable=False, hold=_HOLD)
    table.submit(0, Discard(tile_id=_MAN_5[0]))
    await table.process_one()
    assert table.state.phase == Phase.AWAIT_ACTION and table.state.turn == 1
    assert [w["t"] for _, w in frames] == ["discard"]

    tile = table.state.seats[1].concealed[0]
    pre = table.state
    table.submit(1, Discard(tile_id=tile))
    await table.process_one()
    assert table.state is pre

    await _run_until_turn(table, frames)
    types = [w["t"] for _, w in frames]
    assert types[0] == "discard" and "draw" in types and types[-1] == "turn"


async def test_state_sync_during_a_hold_is_deferred_to_its_release() -> None:
    table, frames = _discard_table(claimable=False, hold=_HOLD)
    table.submit(0, Discard(tile_id=_MAN_5[0]))
    await table.process_one()

    late: list[dict[str, Any]] = []
    table.register_spectator("late", lambda _seq, wire: late.append(wire))
    assert late == []

    await _run_until_turn(table, frames)
    assert [w["t"] for w in late][:1] == ["state_sync"]
    assert "draw" not in [w["t"] for w in late]
