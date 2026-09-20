"""`app/table.py`'s per-seat `AWAIT_ACTION` turn-timeout timer (docs/00-architecture.md §3 D17,
§8 "Turn timeout" / "Bot raises / hangs"; docs/05-roadmap.md's M3 turn-timeout sub-task).

`turn_seconds=0` is this file's test-time-control knob for the turn-timeout deadline, matching
`tests/test_table_claims.py`'s `claim_seconds=0` and `tests/test_disconnect_bot_handover.py`'s
`disconnect_grace_seconds=0`: the deadline is due the instant it's armed, so the table's own
`_next()` pops it on the very next `process_one()` tick with no real sleep in the test.

Fixtures are white-box state rigs, same style `test_table_claims.py`/`test_disconnect_bot_handover.
py` already establish: seats hold disjoint tile types so a discard/draw this file exercises is
never accidentally contestable by another seat, unless the test is specifically about a claim
(the claimed-pung-then-timeout fixture).
"""

from __future__ import annotations

import dataclasses
from concurrent.futures import Executor, Future
from typing import Any

from app.table import SeatBinding, Table
from mahjong_core.actions import ClaimPung, Discard, legal_actions
from mahjong_core.config import DEFAULT_RULESET
from mahjong_core.engine import new_game
from mahjong_core.state import GameState, Phase
from mahjong_core.tiles import TileType, tile_ids_for_type

_MAN_1 = tile_ids_for_type(TileType.MAN_1)
_MAN_2 = tile_ids_for_type(TileType.MAN_2)
_MAN_3 = tile_ids_for_type(TileType.MAN_3)
_MAN_4 = tile_ids_for_type(TileType.MAN_4)
_MAN_5 = tile_ids_for_type(TileType.MAN_5)
_MAN_6 = tile_ids_for_type(TileType.MAN_6)
_MAN_7 = tile_ids_for_type(TileType.MAN_7)
_MAN_9 = tile_ids_for_type(TileType.MAN_9)
_PIN_1 = tile_ids_for_type(TileType.PIN_1)
_PIN_2 = tile_ids_for_type(TileType.PIN_2)
_PIN_3 = tile_ids_for_type(TileType.PIN_3)
_PIN_4 = tile_ids_for_type(TileType.PIN_4)
_PIN_5 = tile_ids_for_type(TileType.PIN_5)
_PIN_6 = tile_ids_for_type(TileType.PIN_6)
_PIN_7 = tile_ids_for_type(TileType.PIN_7)
_PIN_8 = tile_ids_for_type(TileType.PIN_8)
_SOU_1 = tile_ids_for_type(TileType.SOU_1)
_SOU_2 = tile_ids_for_type(TileType.SOU_2)
_SOU_3 = tile_ids_for_type(TileType.SOU_3)
_SOU_4 = tile_ids_for_type(TileType.SOU_4)
_SOU_5 = tile_ids_for_type(TileType.SOU_5)
_SOU_6 = tile_ids_for_type(TileType.SOU_6)
_SOU_7 = tile_ids_for_type(TileType.SOU_7)
_SOU_8 = tile_ids_for_type(TileType.SOU_8)
_SOU_9 = tile_ids_for_type(TileType.SOU_9)
_EAST = tile_ids_for_type(TileType.WIND_EAST)
_SOUTH = tile_ids_for_type(TileType.WIND_SOUTH)
_WEST = tile_ids_for_type(TileType.WIND_WEST)
_NORTH = tile_ids_for_type(TileType.WIND_NORTH)
_RED = tile_ids_for_type(TileType.DRAGON_RED)
_GREEN = tile_ids_for_type(TileType.DRAGON_GREEN)
_WHITE = tile_ids_for_type(TileType.DRAGON_WHITE)


def _with_seat(state: GameState, seat: int, **overrides: object) -> GameState:
    seats = list(state.seats)
    seats[seat] = dataclasses.replace(seats[seat], **overrides)  # type: ignore[arg-type]
    return dataclasses.replace(state, seats=tuple(seats))  # type: ignore[arg-type]


def _bind(table: Table, seat: int, *, status: str = "connected") -> None:
    table.seat_bindings[seat] = SeatBinding(
        session_id=f"seat-{seat}",
        send=lambda seq, wire: None,
        name=f"Seat {seat}",
        status=status,  # type: ignore[arg-type]
    )


# --- fixture: an uncontested draw, so a timeout must tsumogiri the freshly-drawn tile ----------


def _rig_uncontested_draw_state(seed: int, *, turn_seconds: int) -> GameState:
    """Seat 0 discards an uncontested `WIND_EAST`, cascading straight to seat 1's draw (a 14th,
    otherwise-irrelevant `MAN_9`) and `AWAIT_ACTION` -- no seat anywhere holds a tile that makes
    any of this contestable (disjoint suits/types throughout), same partitioning
    `tests/test_disconnect_bot_handover.py`'s `_rig_disconnect_state` already establishes."""
    ruleset = dataclasses.replace(DEFAULT_RULESET, turn_seconds=turn_seconds)
    state = new_game(ruleset, game_seed=seed)
    state = dataclasses.replace(state, phase=Phase.AWAIT_ACTION, turn=0, claim_window=None)

    seat0 = (
        *_PIN_2[:3],
        *_PIN_4[:3],
        *_PIN_6[:3],
        *_PIN_8[:3],
        _EAST[0],
    )
    seat1 = (
        _SOUTH[0],
        _WEST[0],
        _NORTH[0],
        _RED[0],
        _GREEN[0],
        _WHITE[0],
        _MAN_1[0],
        _MAN_2[0],
        _MAN_3[0],
        _MAN_4[0],
        _MAN_5[0],
        _MAN_6[0],
        _MAN_7[0],
    )
    seat2 = (*_SOU_1[:3], *_SOU_3[:3], *_SOU_5[:3], _SOU_7[0])
    seat3 = (*_PIN_1[:3], *_PIN_3[:3], *_PIN_5[:3], _PIN_7[0])

    state = _with_seat(state, 0, concealed=seat0, discards=())
    state = _with_seat(state, 1, concealed=seat1)
    state = _with_seat(state, 2, concealed=seat2)
    state = _with_seat(state, 3, concealed=seat3)

    draw_tile = _MAN_9[0]
    wall = state.wall
    state = dataclasses.replace(
        state, wall=dataclasses.replace(wall, tiles=(draw_tile, *wall.tiles[1:]))
    )
    return state


async def test_turn_timeout_tsumogiris_the_freshly_drawn_tile() -> None:
    table = Table("table-turn-timeout-draw", DEFAULT_RULESET, game_seed=1)
    _bind(table, 1)
    table.state = _rig_uncontested_draw_state(seed=1, turn_seconds=0)

    table.submit(0, Discard(tile_id=_EAST[0]))
    await table.process_one()  # seat 0 discards, cascades to seat 1's draw + AWAIT_ACTION

    assert table.state.phase == Phase.AWAIT_ACTION
    assert table.state.turn == 1
    assert _MAN_9[0] in table.state.seats[1].concealed
    assert table._active_turn_timer.keys() == {1}  # a real deadline is armed, not merely advisory

    await table.process_one()  # turn_seconds=0 -- the deadline is already due, pops this tick

    assert (
        table.state.seats[1].discards[-1] == _MAN_9[0]
    )  # tsumogiri: the drawn tile, not any other
    assert _MAN_9[0] not in table.state.seats[1].concealed
    assert table.seat_bindings[1] is not None
    assert table.seat_bindings[1].turn_timeout_strikes == 1


# --- fixture: a claimed pung with nothing drawn, so a timeout must discard the lowest tile_id --


def _rig_pre_pung_state(seed: int, *, claim_seconds: int = 999) -> GameState:
    """Seat 0 is one command away from discarding `MAN_5`, which only seat 2 (holding two more
    copies) can claim -- a pung, the only live offer (seat 1/seat 3 hold disjoint suits, so
    neither can chow or compete for the pung)."""
    ruleset = dataclasses.replace(DEFAULT_RULESET, claim_seconds=claim_seconds)
    state = new_game(ruleset, game_seed=seed)
    state = dataclasses.replace(state, phase=Phase.AWAIT_ACTION, turn=0, claim_window=None)

    seat0 = (*_PIN_1[:3], *_PIN_3[:3], *_PIN_5[:3], *_PIN_7[:3], _MAN_5[0])
    seat1 = (*_SOU_1[:3], *_SOU_3[:3], *_SOU_5[:3], *_SOU_7[:3], _EAST[0])
    seat2 = (
        _MAN_5[1],
        _MAN_5[2],
        _SOUTH[0],
        _WEST[0],
        _NORTH[0],
        _RED[0],
        _GREEN[0],
        _WHITE[0],
        _SOU_2[0],
        _SOU_4[0],
        _SOU_6[0],
        _SOU_8[0],
        _SOU_9[0],
    )
    seat3 = (*_PIN_2[:3], *_PIN_4[:3], *_PIN_6[:3], *_PIN_8[:3], _MAN_1[0])

    state = _with_seat(state, 0, concealed=seat0, discards=())
    state = _with_seat(state, 1, concealed=seat1)
    state = _with_seat(state, 2, concealed=seat2)
    state = _with_seat(state, 3, concealed=seat3)
    return state


async def test_turn_timeout_after_claimed_pung_discards_lowest_tile_id() -> None:
    table = Table("table-turn-timeout-pung", DEFAULT_RULESET, game_seed=2)
    _bind(table, 2)
    table.state = _rig_pre_pung_state(seed=2)

    table.submit(0, Discard(tile_id=_MAN_5[0]))
    await table.process_one()
    phase_after_discard = table.state.phase
    assert phase_after_discard == Phase.AWAIT_CLAIMS

    pung = next(a for a in legal_actions(table.state, 2) if isinstance(a, ClaimPung))
    table.submit(2, pung)
    await table.process_one()  # seat 2's pung is the only offer -- resolves immediately

    assert table.state.phase == Phase.AWAIT_ACTION
    assert table.state.turn == 2
    concealed_after_claim = table.state.seats[2].concealed
    expected_tile = min(concealed_after_claim)  # nothing drawn -- lowest tile_id is the default

    # re-arm with turn_seconds=0 for the timeout half of this test (can't set it on the ruleset
    # before the claim above without also collapsing claim_seconds -- rearm directly instead).
    table.state = dataclasses.replace(
        table.state, ruleset=dataclasses.replace(table.state.ruleset, turn_seconds=0)
    )
    table._publish_turn_if_active()  # re-arm now that turn_seconds=0 -- see _arm_turn_timer

    await table.process_one()  # the just-armed deadline is already due -- pops this tick

    assert table.state.seats[2].discards[-1] == expected_tile
    assert expected_tile not in table.state.seats[2].concealed
    assert table.seat_bindings[2] is not None
    assert table.seat_bindings[2].turn_timeout_strikes == 1


# --- three strikes -> AUTOPLAY, and the count survives a hand-boundary change -------------------


async def test_three_turn_timeouts_flip_seat_to_autoplay() -> None:
    table = Table("table-turn-timeout-strikes", DEFAULT_RULESET, game_seed=3)
    _bind(table, 0)

    for _ in range(2):
        table.state = _rig_uncontested_draw_state(seed=3, turn_seconds=0)
        table.state = dataclasses.replace(table.state, turn=0, phase=Phase.AWAIT_ACTION)
        table._publish_turn_if_active()
        await table.process_one()

    assert table.seat_bindings[0] is not None
    assert table.seat_bindings[0].turn_timeout_strikes == 2
    assert table.seat_bindings[0].status == "connected"  # not flipped yet -- only 2 strikes


async def test_third_turn_timeout_flips_to_autoplay_even_across_a_hand_boundary() -> None:
    """`SeatBinding.turn_timeout_strikes` accumulates for "the rest of the game" (00-architecture.
    md §8), not per hand -- the chosen reading is that a hand boundary must NOT reset the count.
    Two strikes land in one `hand_no`, then `hand_no` changes (simulating a new hand dealt) before
    the third -- proving the count survived that change, not merely three timeouts in a row within
    a single hand (which the *other* plausible "resets each hand" interpretation would also pass)."""
    table = Table("table-turn-timeout-strikes-cross-hand", DEFAULT_RULESET, game_seed=4)
    _bind(table, 0)

    for _ in range(2):
        table.state = _rig_uncontested_draw_state(seed=4, turn_seconds=0)
        table.state = dataclasses.replace(table.state, turn=0, phase=Phase.AWAIT_ACTION, hand_no=1)
        table._publish_turn_if_active()
        await table.process_one()
    binding = table.seat_bindings[0]
    assert binding is not None
    assert binding.turn_timeout_strikes == 2
    status_after_two = binding.status
    assert status_after_two == "connected"

    # a new hand -- hand_no changes. A "resets each hand" implementation would zero the strike
    # count here; this file's chosen semantics (never reset) must not.
    table.state = _rig_uncontested_draw_state(seed=4, turn_seconds=0)
    table.state = dataclasses.replace(table.state, turn=0, phase=Phase.AWAIT_ACTION, hand_no=2)
    table._publish_turn_if_active()
    await table.process_one()

    assert binding.turn_timeout_strikes == 3
    status_after_three = binding.status
    assert status_after_three == "autoplay"


# --- a hung/crashed bot job doesn't stall the turn timer ----------------------------------------


class _HangingExecutor(Executor):
    """Simulates a bot worker that crashed or never returns: `submit()` hands back a bare
    `concurrent.futures.Future` that's never resolved. `loop.run_in_executor` only needs a
    `submit(fn, *args, **kwargs)` method, so this is a minimal `Executor` stand-in, matching
    `Table.__init__`'s `bot_pool: Executor | None` injection point tests already use
    (`tests/test_shutdown.py`'s `SeatBinding` direct-construction convention, applied here to
    `Executor` instead)."""

    def submit(self, fn: Any, /, *args: Any, **kwargs: Any) -> Future[Any]:
        return Future()  # never marked done -- the table must not wait on it


async def test_hung_bot_job_still_times_out_via_the_turn_timer() -> None:
    table = Table(
        "table-turn-timeout-hung-bot",
        DEFAULT_RULESET,
        game_seed=5,
        bot_pool=_HangingExecutor(),
    )
    _bind(table, 1, status="autoplay")  # seat 1 is bot-driven -- see _rig_uncontested_draw_state
    table.state = _rig_uncontested_draw_state(seed=5, turn_seconds=0)

    table.submit(0, Discard(tile_id=_EAST[0]))
    await table.process_one()  # seat 0 discards -> seat 1 draws, AWAIT_ACTION, _poke_bots submits

    assert table.state.phase == Phase.AWAIT_ACTION
    assert table.state.turn == 1
    assert 1 in table._pending_bot  # the (hung) job is genuinely in flight

    await table.process_one()  # turn_seconds=0 -- the turn timer fires regardless of the hung job

    assert table.state.seats[1].discards[-1] == _MAN_9[0]  # same deterministic default as a human
    assert 1 not in table._pending_bot  # the stale job tag was cleared, not left dangling
    assert table.seat_bindings[1] is not None
    assert table.seat_bindings[1].turn_timeout_strikes == 1
