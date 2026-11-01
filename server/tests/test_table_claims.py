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

from app.frames import claim_offer_frame
from app.table import Table, TimerHeap
from mahjong_core.actions import ClaimPung, Discard, Pass, legal_actions
from mahjong_core.config import DEFAULT_RULESET, RuleSet
from mahjong_core.engine import new_game
from mahjong_core.melds import MeldKind
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


def _pre_discard_table(ruleset: RuleSet, *, game_seed: int = 1) -> Table:
    """A `Table` one command away from opening a claim window: seat 0 is on turn holding 5m
    plus junk, seat 1 can chow it, seat 2 can pung it, seat 3 holds nothing relevant."""
    table = Table("table-claims", ruleset, game_seed=game_seed)
    state = new_game(ruleset, game_seed=game_seed)
    state = dataclasses.replace(state, phase=Phase.AWAIT_ACTION, turn=0, claim_window=None)
    state = with_seat(state, 0, concealed=(*_JUNK_HAND, _MAN_5[0]), discards=())
    state = with_seat(state, 1, concealed=(_MAN_4[0], _MAN_6[0], *_JUNK_HAND[:11]))
    state = with_seat(state, 2, concealed=(_MAN_5[1], _MAN_5[2], *_JUNK_HAND[:11]))
    state = with_seat(state, 3, concealed=_JUNK_HAND)
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
    table.state = with_seat(table.state, 0, concealed=(*_JUNK_HAND, _SOU_8[2]), discards=())
    table.state = with_seat(table.state, 2, concealed=_JUNK_HAND)
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


async def test_second_answer_from_a_seat_that_already_responded_is_dropped() -> None:
    """Seat 2 passes, then submits a pung against the same window: one response per seat per
    window, so `_authorize` drops the pung and seat 2's Pass stands."""
    ruleset = dataclasses.replace(DEFAULT_RULESET, claim_seconds=999)
    table = await _open_claim_window(ruleset)

    pung_action = next(a for a in legal_actions(table.state, 2) if isinstance(a, ClaimPung))
    pass_action = next(a for a in legal_actions(table.state, 2) if isinstance(a, Pass))
    table.submit(2, pass_action)
    await table.process_one()
    assert table.state.claim_window is not None  # seat 1's chow still outstanding
    open_state = table.state

    table.submit(2, pung_action)
    await table.process_one()

    assert table.state is open_state
    assert table.state.claim_window is not None
    assert table.state.claim_window.responses == {2: pass_action}


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


# --- disconnect mid-claim-window: the offer stays open for a reconnect ------------------------


async def test_disconnect_mid_claim_window_keeps_the_offer_open() -> None:
    """docs/decisions/0004-claim-forfeit-on-disconnect.md: a disconnect leaves the seat's
    offer unanswered on its own deadline, and a reconnect inside the window can claim."""
    ruleset = dataclasses.replace(DEFAULT_RULESET, claim_seconds=999)
    table = await _open_claim_window(ruleset)
    window = table.state.claim_window
    assert window is not None
    sent: list[dict[str, object]] = []
    table.join("sess-2", lambda seq, wire: sent.append(wire), seat=2)
    secret = table.seat_bindings[2].reconnect_secret  # type: ignore[union-attr]

    table.mark_disconnected(2, "sess-2")
    await table.process_one()  # the _WakeUp _arm_disconnect_timer queued
    assert table.state.claim_window is window
    assert 2 not in window.responses

    sent.clear()
    table.reconnect(2, "sess-2b", lambda seq, wire: sent.append(wire), secret)
    table.resume(2, None)
    sync = next(w for w in sent if w["t"] == "state_sync")
    offer = sync["claim_offer"]
    assert isinstance(offer, dict)
    assert offer["window_id"] == window.window_id

    table.submit(2, next(a for a in legal_actions(table.state, 2) if isinstance(a, ClaimPung)))
    await table.process_one()  # the re-arm's _WakeUp
    await table.process_one()
    assert table.state.claim_window is None
    assert any(m.kind == MeldKind.PUNG for m in table.state.seats[2].melds)


async def test_only_the_first_resume_in_a_window_extends_the_deadline() -> None:
    """A reconnect loop can't hold a window open: a second resume keeps the first re-arm's
    deadline, though it still hands the offer back."""
    table = await _open_claim_window(DEFAULT_RULESET)
    window = table.state.claim_window
    assert window is not None
    key = (window.window_id, 1)
    sent: list[dict[str, object]] = []
    table.join("sess-1", lambda seq, wire: sent.append(wire), seat=1)

    table.resume(1, None)
    first_timer = table._active_seat_timer[key]
    sent.clear()
    table.resume(1, None)

    assert table._active_seat_timer[key] == first_timer
    sync = next(w for w in sent if w["t"] == "state_sync")
    assert isinstance(sync["claim_offer"], dict)
    assert sync["claim_offer"]["deadline_ts"] == table._claim_deadline_ms[key]


# --- state_sync resumes the window and the turn on its own (docs/protocol.md §3) ---------------


async def test_state_sync_mid_window_carries_each_seats_own_claim_offer() -> None:
    """The same payload, window id and deadline as that seat's `claim_offer` frame; nothing
    for a seat with no offer, and nothing once a seat has answered."""
    ruleset = dataclasses.replace(DEFAULT_RULESET, claim_seconds=999)
    table = await _open_claim_window(ruleset)
    window = table.state.claim_window
    assert window is not None

    for seat in (1, 2):
        deadline = table._claim_deadline_ms[(window.window_id, seat)]
        frame = claim_offer_frame(table.state, seat, deadline_ts=deadline)
        assert frame is not None
        sync = table.state_sync_wire(seat)
        assert sync["claim_offer"] == {k: v for k, v in frame.items() if k != "t"}
        assert sync["claim_offer"]["window_id"] == window.window_id
        assert sync["drawn_tile"] is None
        assert sync["last_discard"] == {"seat": 0, "tile_id": _MAN_5[0]}
    assert {o["kind"] for o in table.state_sync_wire(1)["claim_offer"]["options"]} == {
        "chow",
        "pass",
    }
    for seat in (0, 3, None):
        assert table.state_sync_wire(seat)["claim_offer"] is None

    table.submit(2, Pass(window_id=window.window_id, seat=2))
    await table.process_one()
    assert table.state.claim_window is not None  # seat 1's chow is still outstanding
    assert table.state_sync_wire(2)["claim_offer"] is None
    assert table.state_sync_wire(1)["claim_offer"] is not None


async def test_resync_mid_window_without_a_disconnect_hands_back_a_claimable_offer() -> None:
    """A gap resync on the live socket (`hello{last_seq}` past the ring) or a backpressure
    collapse lands mid-window with the offer still live. Its `state_sync` must carry a window id
    and options the client can answer, with the fresh deadline `resume()` re-armed."""
    ruleset = dataclasses.replace(DEFAULT_RULESET, claim_seconds=999)
    table = await _open_claim_window(ruleset)
    window = table.state.claim_window
    assert window is not None
    sent: list[dict[str, object]] = []
    table.join("sess-1", lambda seq, wire: sent.append(wire), seat=1)
    sent.clear()

    table.resume(1, None)

    syncs = [w for w in sent if w["t"] == "state_sync"]
    assert len(syncs) == 1
    offer = syncs[0]["claim_offer"]
    assert isinstance(offer, dict)
    assert offer["window_id"] == window.window_id
    assert offer["deadline_ts"] == table._claim_deadline_ms[(window.window_id, 1)]
    assert offer["options"][-1] == {"kind": "pass"}
    chow = next(o for o in offer["options"] if o["kind"] == "chow")
    assert sorted(chow["tiles"]) == sorted([_MAN_4[0], _MAN_6[0]])


async def test_state_sync_after_a_claim_holds_no_drawn_tile() -> None:
    """A pung's turn starts with no draw: the claimer's hand has no tile held apart, and the
    claimed discard left the pool."""
    ruleset = dataclasses.replace(DEFAULT_RULESET, claim_seconds=999)
    table = await _open_claim_window(ruleset)
    pung = next(a for a in legal_actions(table.state, 2) if isinstance(a, ClaimPung))
    table.submit(2, pung)
    await table.process_one()
    assert table.state.phase == Phase.AWAIT_ACTION
    assert table.state.turn == 2

    sync = table.state_sync_wire(2)
    assert sync["drawn_tile"] is None
    assert sync["claim_offer"] is None
    assert sync["last_discard"] is None
    assert any(a["kind"] == "discard" for a in sync["legal_actions"])


async def test_state_sync_after_a_draw_names_the_drawn_tile_to_its_seat_only() -> None:
    ruleset = dataclasses.replace(DEFAULT_RULESET, claim_seconds=5)
    table = _pre_discard_table(ruleset)
    table.state = with_seat(table.state, 0, concealed=(*_JUNK_HAND, _SOU_8[2]), discards=())
    table.state = with_seat(table.state, 2, concealed=_JUNK_HAND)
    table.submit(0, Discard(tile_id=_SOU_8[2]))
    await table.process_one()
    assert table.state.phase == Phase.AWAIT_ACTION
    assert table.state.turn == 1

    drawn = table.state.seats[1].concealed[-1]
    assert drawn == table._turn_draw_tile
    assert table.state_sync_wire(1)["drawn_tile"] == drawn
    for viewer in (0, 2, 3, None):
        assert table.state_sync_wire(viewer)["drawn_tile"] is None
        assert table.state_sync_wire(viewer)["last_discard"] == {"seat": 0, "tile_id": _SOU_8[2]}


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
