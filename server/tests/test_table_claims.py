"""`app/table.py`'s claim-window timer heap, D17 race fix, and early exit/timeout wiring
(docs/architecture.md §3 D17, §4; docs/decisions/0018-milestone-plan.md M3 sub-task 3).

Fixtures mirror `tests/test_engine.py`'s `_claims_window_state()`: seat 0 discards 5m, seat 1
can chow it (holding 4m/6m), seat 2 can pung it (holding two more 5m) -- injected straight into
a `Table` (bypassing `new_game`'s random deal) via the same white-box style `test_ws.py` already
uses on `table.ring`/`table.seat_seq`.
"""

from __future__ import annotations

import asyncio
import dataclasses

from app.table import Table, TimerHeap
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


def _pre_discard_table(ruleset: RuleSet, *, game_seed: int = 1) -> Table:
    """A `Table` one command away from opening a claim window: seat 0 is on turn holding 5m
    plus junk, seat 1 can chow it, seat 2 can pung it, seat 3 holds nothing relevant."""
    table = Table("table-claims", ruleset, game_seed=game_seed)
    state = new_game(ruleset, game_seed=game_seed)
    state = dataclasses.replace(state, phase=Phase.AWAIT_ACTION, turn=0, claim_window=None)
    state = _with_seat(state, 0, concealed=(*_JUNK_HAND, _MAN_5[0]), discards=())
    state = _with_seat(state, 1, concealed=(_MAN_4[0], _MAN_6[0], *_JUNK_HAND[:11]))
    state = _with_seat(state, 2, concealed=(_MAN_5[1], _MAN_5[2], *_JUNK_HAND[:11]))
    state = _with_seat(state, 3, concealed=_JUNK_HAND)
    table.state = state
    return table


async def _open_claim_window(ruleset: RuleSet, *, game_seed: int = 1) -> Table:
    table = _pre_discard_table(ruleset, game_seed=game_seed)
    table.submit(0, Discard(tile_id=_MAN_5[0]))
    await table.process_one()
    assert table.state.phase == Phase.AWAIT_CLAIMS
    assert table.state.claim_window is not None
    return table


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
    table = await _open_claim_window(ruleset)

    loop = asyncio.get_running_loop()
    deadline = table.deadlines.peek()
    assert deadline is not None
    assert loop.time() < deadline <= loop.time() + ruleset.claim_seconds + 1


async def test_no_claim_deadline_armed_when_a_discard_draws_no_claims() -> None:
    """No claim-window deadline gets armed when a discard draws no claims -- it cascades
    straight to the next player's draw+`AWAIT_ACTION` instead (architecture.md §4). The
    heap is no longer empty afterward, though: landing in `AWAIT_ACTION` now arms that seat's
    own turn-timeout deadline too (architecture.md §8 "Turn timeout", the turn-timeout
    sub-task) -- this asserts the *claim* side specifically (no armed window, no per-seat claim
    timer entries), not "the heap has nothing in it at all"."""
    ruleset = dataclasses.replace(DEFAULT_RULESET, claim_seconds=5)
    table = _pre_discard_table(ruleset)
    # nobody can claim a tile nobody holds a match for
    table.state = _with_seat(table.state, 0, concealed=(*_JUNK_HAND, _SOU_8[2]), discards=())
    table.state = _with_seat(table.state, 2, concealed=_JUNK_HAND)
    table.submit(0, Discard(tile_id=_SOU_8[2]))
    await table.process_one()

    assert table.state.claim_window is None
    assert table._armed_window_id is None
    assert table._timer_seat == {}
    # the turn timer for seat 1 (now on turn) is the only thing left in the heap
    assert table.state.phase == Phase.AWAIT_ACTION
    assert table.state.turn == 1
    assert table._active_turn_timer.keys() == {1}


# --- early exit: resolves as soon as the best pending claim can't beat what's already in ------


async def test_early_exit_resolves_without_waiting_on_every_offer() -> None:
    ruleset = dataclasses.replace(DEFAULT_RULESET, claim_seconds=999)
    table = await _open_claim_window(ruleset)

    pung_action = next(a for a in legal_actions(table.state, 2) if isinstance(a, ClaimPung))
    table.submit(2, pung_action)
    await table.process_one()

    # seat 1's chow is strictly weaker than seat 2's submitted pung and never responded -- the
    # window must close immediately (can_close_early), not wait for seat 1 or a 999s timer.
    assert table.state.phase == Phase.AWAIT_ACTION
    assert table.state.claim_window is None
    assert any(m.kind == MeldKind.PUNG for m in table.state.seats[2].melds)


# --- timeout: absentees default to Pass --------------------------------------------------------


async def test_claim_timeout_defaults_every_absent_seat_to_pass() -> None:
    ruleset = dataclasses.replace(DEFAULT_RULESET, claim_seconds=0)
    table = await _open_claim_window(ruleset)
    assert table.state.phase == Phase.AWAIT_CLAIMS

    # claim_seconds=0 -> the deadline armed above is already due; nobody has responded, so the
    # next tick must pop the timer and resolve via default Pass for both offered seats.
    await table.process_one()

    assert table.state.claim_window is None
    # mypy doesn't see process_one() reassigns table.state to a new GameState, so it flags this
    # phase comparison as unreachable -- it's real and correct.
    assert table.state.phase == Phase.AWAIT_ACTION
    assert table.state.turn == 1  # nobody claimed -> play continues past the discarder
    assert not any(m.kind == MeldKind.PUNG for m in table.state.seats[2].melds)
    assert not any(m.kind == MeldKind.CHOW for m in table.state.seats[1].melds)


async def test_claim_timeout_only_defaults_seats_that_never_responded() -> None:
    """A partial response before the deadline is preserved -- only the still-silent seat gets
    a synthesized Pass; can_close_early then resolves it inline, same path as a real Pass."""
    ruleset = dataclasses.replace(DEFAULT_RULESET, claim_seconds=0)
    table = await _open_claim_window(ruleset)

    chow_pass = next(a for a in legal_actions(table.state, 1) if isinstance(a, Pass))
    table.submit(1, chow_pass)
    await table.process_one()
    assert table.state.claim_window is not None  # seat 2's pung is still outstanding
    assert table.state.claim_window.responses == {1: chow_pass}

    await table.process_one()  # timer pops for the same window_id -> defaults seat 2 to Pass

    assert table.state.claim_window is None
    assert table.state.phase == Phase.AWAIT_ACTION
    assert not any(m.kind == MeldKind.PUNG for m in table.state.seats[2].melds)


# --- stale timer: a window resolved early must ignore its own leftover deadline ----------------


async def test_stale_timer_after_early_exit_is_a_noop() -> None:
    ruleset = dataclasses.replace(DEFAULT_RULESET, claim_seconds=0)
    table = await _open_claim_window(ruleset)

    pung_action = next(a for a in legal_actions(table.state, 2) if isinstance(a, ClaimPung))
    table.submit(2, pung_action)
    await table.process_one()  # early exit resolves the window before its own deadline pops

    resolved_state = table.state
    assert resolved_state.claim_window is None

    # claim_seconds=0's deadline is still in the heap (lazy deletion) -- drive one more tick so
    # it fires and prove it's a no-op: no crash, no second resolution, no state mutation.
    await table.process_one()
    assert table.state is resolved_state


# --- disconnect mid-claim-window: forfeit immediately, don't wait for reconnect ----------------


async def test_disconnect_mid_claim_window_forfeits_seats_own_offer_only() -> None:
    """A seat that disconnects while its own claim offer is still live forfeits it right away --
    `mark_disconnected` enqueues `SeatDisconnected`, and the next `process_one()` tick applies a
    synthesized `Pass` for it, the same `_apply()` path a claim-window timeout uses. Why not wait
    for reconnect to re-arm a fresh window instead (the previous design): a reconnect's own
    `state_sync` has no `window_id` to offer a dialog against (`app/protocol.py`'s
    `StateSyncPayload.claim_options` carries only `{kind, tiles?}`), so the seat would come back
    to a table that looked paused with nothing to act on. Forfeiting up front means there is
    nothing left for a reconnect to hand back. Seat 2's own pung offer, untouched throughout,
    proves this is seat-scoped, not a window-wide cancellation."""
    table = await _open_claim_window(DEFAULT_RULESET, game_seed=1)
    window = table.state.claim_window
    assert window is not None
    window_id = window.window_id
    table.join("sess-1", lambda seq, wire: None, seat=1)

    table.mark_disconnected(1, "sess-1")
    # `mark_disconnected` queues _WakeUp then SeatDisconnected -- this single-step driver needs
    # two ticks (unlike Table.run()'s while loop) to reach the one that forfeits the offer.
    await table.process_one()
    await table.process_one()

    window = table.state.claim_window
    assert window is not None  # seat 2's pung offer is still outstanding
    assert window.window_id == window_id
    assert isinstance(window.responses.get(1), Pass)
    assert 2 not in window.responses


async def test_disconnect_with_no_live_claim_offer_is_a_noop() -> None:
    """A seat with nothing to forfeit (no offer of its own in the live window, or it already
    responded) just gets the normal disconnect bookkeeping -- `_handle_seat_disconnected` is a
    silent no-op, not an error, the same staleness discipline every other synthesized action
    here uses (`_handle_claim_timeout`'s docstring)."""
    table = await _open_claim_window(DEFAULT_RULESET, game_seed=1)
    table.join("sess-3", lambda seq, wire: None, seat=3)  # seat 3 was never offered anything

    table.mark_disconnected(3, "sess-3")
    pre_state = table.state
    await table.process_one()  # the _WakeUp _arm_disconnect_timer queued: no-op
    await table.process_one()  # SeatDisconnected(seat=3): nothing to forfeit, no-op

    assert table.state is pre_state
    window = table.state.claim_window
    assert window is not None
    assert 3 not in window.responses


# --- D17: a command arriving the same tick a deadline expires must not be silently dropped -----


async def test_command_same_tick_as_deadline_expiry_is_not_dropped() -> None:
    """The exact bug class D17 exists to prevent: a naive `asyncio.wait_for(inbox.get(), ...)`
    (or an `asyncio.wait` that cancels the getter on the timer branch) can lose a command
    that's already queued at the moment a deadline is also due, because the getter can be
    cancelled before it hands back an item that's genuinely ready. `Table._next()` never
    cancels `_inbox_getter()`, so a queued command must always win: the real response gets
    applied, not silently replaced by the timeout-default resolution.

    Repeated: which of two zero-delay futures (`inbox.get()` on an already-nonempty queue vs.
    `asyncio.sleep(0)`) a given asyncio implementation reports first isn't a documented
    guarantee, so one iteration proves too little either way.
    """
    ruleset = dataclasses.replace(DEFAULT_RULESET, claim_seconds=0)
    for _ in range(25):
        table = await _open_claim_window(ruleset)
        # the claim_seconds=0 deadline armed above is already due by the time we get here.
        pass_action = next(a for a in legal_actions(table.state, 1) if isinstance(a, Pass))
        table.submit(1, pass_action)  # queued before _next() ever peeks the heap

        await table.process_one()

        window = table.state.claim_window
        # a bug that defaults every offered seat to Pass via the timer would close the window
        # too -- seat 2's still-silent, higher-priority pung keeps can_close_early from firing, so the window must still be open here.
        assert window is not None, "seat 1's real Pass must not have been swallowed by the timer"
        assert window.responses == {1: pass_action}
