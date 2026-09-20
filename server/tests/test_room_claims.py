"""`app/room.py`'s claim-window timer heap, D17 race fix, and early exit/timeout wiring
(docs/00-architecture.md §3 D17, §4; docs/05-roadmap.md M3 sub-task 3).

Fixtures mirror `tests/test_engine.py`'s `_claims_window_state()`: seat 0 discards 5m, seat 1
can chow it (holding 4m/6m), seat 2 can pung it (holding two more 5m) -- injected straight into
a `Room` (bypassing `new_game`'s random deal) via the same white-box style `test_ws.py` already
uses on `room.ring`/`room.seat_seq`.
"""

from __future__ import annotations

import asyncio
import dataclasses

from app.room import Room, TimerHeap
from mahjong_core.actions import ClaimPung, Discard, Pass, legal_actions
from mahjong_core.config import DEFAULT_RULESET, RuleSet
from mahjong_core.engine import new_game
from mahjong_core.melds import MeldKind
from mahjong_core.state import GameState, Phase
from mahjong_core.tiles import TileType, tile_ids_for_type

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

# 13 junk tiles, confined to sou-evens + honors so they never collide with the man4/5/6 tiles
# every test below discards/claims -- same fixture test_engine.py's `_claims_window_state` uses.
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


def _with_seat(state: GameState, seat: int, **overrides: object) -> GameState:
    seats = list(state.seats)
    seats[seat] = dataclasses.replace(seats[seat], **overrides)  # type: ignore[arg-type]
    return dataclasses.replace(state, seats=tuple(seats))  # type: ignore[arg-type]


def _pre_discard_room(ruleset: RuleSet, *, game_seed: int = 1) -> Room:
    """A `Room` one command away from opening a claim window: seat 0 is on turn holding 5m
    plus junk, seat 1 can chow it, seat 2 can pung it, seat 3 holds nothing relevant."""
    room = Room("room-claims", ruleset, game_seed=game_seed)
    state = new_game(ruleset, game_seed=game_seed)
    state = dataclasses.replace(state, phase=Phase.AWAIT_ACTION, turn=0, claim_window=None)
    state = _with_seat(state, 0, concealed=(*_JUNK_HAND, _MAN_5[0]), discards=())
    state = _with_seat(state, 1, concealed=(_MAN_4[0], _MAN_6[0], *_JUNK_HAND[:11]))
    state = _with_seat(state, 2, concealed=(_MAN_5[1], _MAN_5[2], *_JUNK_HAND[:11]))
    state = _with_seat(state, 3, concealed=_JUNK_HAND)
    room.state = state
    return room


async def _open_claim_window(ruleset: RuleSet, *, game_seed: int = 1) -> Room:
    room = _pre_discard_room(ruleset, game_seed=game_seed)
    room.submit(0, Discard(tile_id=_MAN_5[0]))
    await room.process_one()
    assert room.state.phase == Phase.AWAIT_CLAIMS
    assert room.state.claim_window is not None
    return room


# --- TimerHeap: pure data structure -----------------------------------------------------------


def test_timer_heap_peek_and_pop_expired_in_deadline_order() -> None:
    heap = TimerHeap()
    assert heap.peek() is None
    assert heap.pop_expired(1_000.0) == []

    heap.add(5.0, 1)
    heap.add(2.0, 2)
    heap.add(8.0, 3)

    assert heap.peek() == 2.0
    assert heap.pop_expired(2.0) == [2]
    assert heap.peek() == 5.0
    assert heap.pop_expired(6.0) == [1]
    assert heap.peek() == 8.0
    assert heap.pop_expired(100.0) == [3]
    assert heap.peek() is None


def test_timer_heap_pop_expired_returns_nothing_before_the_deadline() -> None:
    heap = TimerHeap()
    heap.add(10.0, 1)
    assert heap.pop_expired(9.0) == []
    assert heap.peek() == 10.0


# --- arming: a discard that opens a claim window gets a real deadline -------------------------


async def test_discard_opening_claim_window_arms_a_deadline() -> None:
    ruleset = dataclasses.replace(DEFAULT_RULESET, claim_seconds=5)
    room = await _open_claim_window(ruleset)

    loop = asyncio.get_running_loop()
    deadline = room.deadlines.peek()
    assert deadline is not None
    assert loop.time() < deadline <= loop.time() + ruleset.claim_seconds + 1


async def test_no_claim_deadline_armed_when_a_discard_draws_no_claims() -> None:
    """No claim-window deadline gets armed when a discard draws no claims -- it cascades
    straight to the next player's draw+`AWAIT_ACTION` instead (00-architecture.md §4). The
    heap is no longer empty afterward, though: landing in `AWAIT_ACTION` now arms that seat's
    own turn-timeout deadline too (00-architecture.md §8 "Turn timeout", the turn-timeout
    sub-task) -- this asserts the *claim* side specifically (no armed window, no per-seat claim
    timer entries), not "the heap has nothing in it at all"."""
    ruleset = dataclasses.replace(DEFAULT_RULESET, claim_seconds=5)
    room = _pre_discard_room(ruleset)
    # nobody can claim a tile nobody holds a match for
    room.state = _with_seat(room.state, 0, concealed=(*_JUNK_HAND, _SOU_8[2]), discards=())
    room.state = _with_seat(room.state, 2, concealed=_JUNK_HAND)
    room.submit(0, Discard(tile_id=_SOU_8[2]))
    await room.process_one()

    assert room.state.claim_window is None
    assert room._armed_window_id is None
    assert room._timer_seat == {}
    # the turn timer for seat 1 (now on turn) is the only thing left in the heap
    assert room.state.phase == Phase.AWAIT_ACTION
    assert room.state.turn == 1
    assert room._active_turn_timer.keys() == {1}


# --- early exit: resolves as soon as the best pending claim can't beat what's already in ------


async def test_early_exit_resolves_without_waiting_on_every_offer() -> None:
    ruleset = dataclasses.replace(DEFAULT_RULESET, claim_seconds=999)
    room = await _open_claim_window(ruleset)

    pung_action = next(a for a in legal_actions(room.state, 2) if isinstance(a, ClaimPung))
    room.submit(2, pung_action)
    await room.process_one()

    # seat 1's chow is strictly weaker than seat 2's already-submitted pung and never responded
    # -- the window must close immediately (can_close_early, inside reduce()'s
    # _apply_claim_response), not stay open waiting for seat 1 or a 999s timer.
    assert room.state.phase == Phase.AWAIT_ACTION
    assert room.state.claim_window is None
    assert any(m.kind == MeldKind.PUNG for m in room.state.seats[2].melds)


# --- timeout: absentees default to Pass --------------------------------------------------------


async def test_claim_timeout_defaults_every_absent_seat_to_pass() -> None:
    ruleset = dataclasses.replace(DEFAULT_RULESET, claim_seconds=0)
    room = await _open_claim_window(ruleset)
    assert room.state.phase == Phase.AWAIT_CLAIMS

    # claim_seconds=0 -> the deadline armed above is already due; nobody has responded, so the
    # next tick must pop the timer and resolve via default Pass for both offered seats.
    await room.process_one()

    assert room.state.claim_window is None
    # mypy narrows room.state.phase to Literal[AWAIT_CLAIMS] from the assert above and doesn't
    # see that `await room.process_one()` reassigns `room.state` to a new GameState in between --
    # flags this as a non-overlapping/unreachable comparison, but it's real and correct.
    assert room.state.phase == Phase.AWAIT_ACTION
    assert room.state.turn == 1  # nobody claimed -> play continues past the discarder
    assert not any(m.kind == MeldKind.PUNG for m in room.state.seats[2].melds)
    assert not any(m.kind == MeldKind.CHOW for m in room.state.seats[1].melds)


async def test_claim_timeout_only_defaults_seats_that_never_responded() -> None:
    """A partial response before the deadline is preserved -- only the still-silent seat gets
    a synthesized Pass; can_close_early then resolves it inline, same path as a real Pass."""
    ruleset = dataclasses.replace(DEFAULT_RULESET, claim_seconds=0)
    room = await _open_claim_window(ruleset)

    chow_pass = next(a for a in legal_actions(room.state, 1) if isinstance(a, Pass))
    room.submit(1, chow_pass)
    await room.process_one()
    assert room.state.claim_window is not None  # seat 2's pung is still outstanding
    assert room.state.claim_window.responses == {1: chow_pass}

    await room.process_one()  # timer pops for the same window_id -> defaults seat 2 to Pass

    assert room.state.claim_window is None
    assert room.state.phase == Phase.AWAIT_ACTION
    assert not any(m.kind == MeldKind.PUNG for m in room.state.seats[2].melds)


# --- stale timer: a window resolved early must ignore its own leftover deadline ----------------


async def test_stale_timer_after_early_exit_is_a_noop() -> None:
    ruleset = dataclasses.replace(DEFAULT_RULESET, claim_seconds=0)
    room = await _open_claim_window(ruleset)

    pung_action = next(a for a in legal_actions(room.state, 2) if isinstance(a, ClaimPung))
    room.submit(2, pung_action)
    await room.process_one()  # early exit resolves the window before its own deadline pops

    resolved_state = room.state
    assert resolved_state.claim_window is None

    # the claim_seconds=0 deadline armed when the window opened is still sitting in the heap
    # (TimerHeap does lazy deletion) -- drive one more tick so it actually fires and prove it's
    # a no-op: no crash, no second resolution, no state mutation.
    await room.process_one()
    assert room.state is resolved_state


# --- D17: a command arriving the same tick a deadline expires must not be silently dropped -----


async def test_command_same_tick_as_deadline_expiry_is_not_dropped() -> None:
    """The exact bug class D17 exists to prevent: a naive `asyncio.wait_for(inbox.get(), ...)`
    (or an `asyncio.wait` that cancels the getter on the timer branch) can lose a command
    that's already queued at the moment a deadline is also due, because the getter can be
    cancelled before it hands back an item that's genuinely ready. `Room._next()` never
    cancels `_inbox_getter()`, so a queued command must always win: the real response gets
    applied, not silently replaced by the timeout-default resolution.

    Repeated: which of two zero-delay futures (`inbox.get()` on an already-nonempty queue vs.
    `asyncio.sleep(0)`) a given asyncio implementation reports first isn't a documented
    guarantee, so one iteration proves too little either way.
    """
    ruleset = dataclasses.replace(DEFAULT_RULESET, claim_seconds=0)
    for _ in range(25):
        room = await _open_claim_window(ruleset)
        # the claim_seconds=0 deadline armed above is already due by the time we get here.
        pass_action = next(a for a in legal_actions(room.state, 1) if isinstance(a, Pass))
        room.submit(1, pass_action)  # queued before _next() ever peeks the heap

        await room.process_one()

        window = room.state.claim_window
        # a buggy implementation that drops the queued Pass in favour of the timer would
        # default *every* offered seat (1 and 2) to Pass in this same tick, closing the
        # window entirely and losing the fact that seat 1's Pass was a real, specific command
        # (as opposed to a synthesized one) -- indistinguishable from the correct outcome by
        # its *effect* on the window, but distinguishable by timing: the window must still be
        # open afterward, since seat 2 (pung, higher priority, still silent) keeps
        # can_close_early from firing on a lone Pass.
        assert window is not None, "seat 1's real Pass must not have been swallowed by the timer"
        assert window.responses == {1: pass_action}
