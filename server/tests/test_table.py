"""`app/table.py`'s core dispatch loop (docs/decisions/0018-milestone-plan.md M3 sub-task 2), driven purely through
`Table.submit()`/`process_one()` -- never `reduce()`/`start_next_hand()` directly, so these tests
actually exercise the Table's own dispatch, not the pure engine underneath it.

Same action-generation approach as `bots/selfplay.py`'s `play_game`/`tests/test_selfplay.py`
(seeded `RandomBot`s, `state.turn` on a live turn or a random pending claimant during a claim
window), wrapped through `Table` instead of calling `reduce`/`start_next_hand` directly. Ruleset
matches `tests/test_selfplay.py`'s bounded config (`dealer_repeat_on_win/draw=False`): a full
`EAST_ONLY` game is exactly 4 hands regardless of bot skill, so a real multi-hand game finishes
fast and deterministically.
"""

from __future__ import annotations

import dataclasses
import random
from concurrent.futures import Executor, Future
from typing import Any

import pytest

from app.table import SeatBinding, Table
from bots.random import random_action
from mahjong_core.actions import Discard
from mahjong_core.config import GameLength, RuleSet
from mahjong_core.state import Phase

_STEP_CAP = 8000  # matches bots/selfplay.py's _STEP_CAP for the same bounded ruleset
_BOUNDED_RULESET = RuleSet(
    dealer_repeat_on_win=False,
    dealer_repeat_on_draw=False,
    game_length=GameLength.EAST_ONLY,
    # bare Table() has no seat_bindings to ack the hand-end hold -- 0 resolves every hold on
    # the next process_one() tick, same idiom as claim_seconds=0/turn_seconds=0 elsewhere.
    hand_end_seconds=0,
)


async def _drive_one_step(table: Table, rng: random.Random) -> None:
    """Pick the acting seat the same way `bots/selfplay.py`'s `play_game` does, then submit and
    process that seat's randomly-chosen action through the Table. `HAND_OVER` has no seat
    decision at all (`legal_actions` is `()` for every seat in that phase) -- just process the
    tick so the `hand_end_seconds=0` timer (armed the moment the hand ended) closes the hold."""
    state = table.state
    if state.phase == Phase.HAND_OVER:
        await table.process_one()
        return
    if state.phase in (Phase.AWAIT_CLAIMS, Phase.AWAIT_KONG_ROB):
        assert state.claim_window is not None
        pending = [
            o.seat for o in state.claim_window.offers if o.seat not in state.claim_window.responses
        ]
        seat = rng.choice(pending)
    else:
        seat = state.turn
    action = random_action(state, seat, rng)
    table.submit(seat, action)
    await table.process_one()


async def test_full_game_through_table_progresses_and_publishes_gapless_redacted_frames() -> None:
    rng = random.Random(20260916)
    table = Table("table-1", _BOUNDED_RULESET, game_seed=20260916)

    seen_hand_numbers: set[int] = {table.state.hand_no}
    prev_event_id = table.event_id
    steps = 0
    while table.state.phase != Phase.GAME_OVER:
        steps += 1
        if steps > _STEP_CAP:
            raise RuntimeError(f"exceeded {_STEP_CAP} steps -- possible deadlock")
        await _drive_one_step(table, rng)
        seen_hand_numbers.add(table.state.hand_no)
        assert table.event_id >= prev_event_id  # never decreases
        prev_event_id = table.event_id

    # reduce()/start_next_hand() actually drove the game forward, not just one hand.
    assert table.state.phase == Phase.GAME_OVER
    assert table.state.hand_no == 4  # EAST_ONLY, no repeats -> exactly 4 hands (test_engine.py)
    assert seen_hand_numbers == {1, 2, 3, 4}
    assert table.event_id > 0

    # per-seat ring buffers: gapless seq even across `deque(maxlen=512)` eviction -- the tail
    # window's first seq must equal seat_seq minus the window's length, with no gap inside it.
    for seat in range(4):
        buf = list(table.ring[seat])
        assert buf, f"seat {seat} received no frames"
        expected_start = table.seat_seq[seat] - len(buf)
        assert [e.seq for e in buf] == list(range(expected_start, expected_start + len(buf)))

        # redaction spot-check: own draws visible, other seats' concealed tiles are not --
        # full coverage is test_redaction.py's job; this only confirms redact_event() actually runs.
        for envelope in buf:
            wire = envelope.event
            if wire["t"] in ("draw", "kong_replace"):
                if wire["seat"] == seat:
                    continue
                assert wire["tile_id"] is None
            elif wire["t"] == "meld" and wire.get("meld_kind") == "concealed_kong":
                if wire["seat"] == seat:
                    continue
                assert wire["tiles"] is None
                assert wire["count"] is not None


async def test_hand_history_accumulates_across_full_game_and_reconciles_with_final_scores() -> None:
    """`state_sync.hand_history` (docs/protocol.md §3) exists so a client with no live memory
    of earlier hands can still reconstruct the full scoresheet -- same reconciliation check
    `web/src/lib/ui/ScoreSheet.svelte`'s `historyComplete` runs client-side: summed per-hand
    `payments` must reach the same totals `state.seats[*].score` already holds."""
    rng = random.Random(20260917)
    table = Table("table-hand-history-full", _BOUNDED_RULESET, game_seed=20260917)

    steps = 0
    while table.state.phase != Phase.GAME_OVER:
        steps += 1
        if steps > _STEP_CAP:
            raise RuntimeError(f"exceeded {_STEP_CAP} steps -- possible deadlock")
        await _drive_one_step(table, rng)

    history = table.state_sync_wire(None)["hand_history"]
    assert [h["hand_no"] for h in history] == [1, 2, 3, 4]

    running = [0, 0, 0, 0]
    for hand in history:
        for seat, delta in (hand["payments"] or {}).items():
            running[seat] += delta
    assert running == [table.state.seats[s].score for s in range(4)]

    # identical on every seat's own state_sync too -- HandEndWire's fields are all
    # PUBLIC/HAND_END, never owner-gated, so there's nothing seat-specific to differ here.
    for seat in range(4):
        assert table.state_sync_wire(seat)["hand_history"] == history


async def test_spectator_joining_mid_game_sees_completed_hand_history() -> None:
    """The actual bug `hand_history` exists to fix: a spectator that only ever gets a fresh
    `state_sync` (never having been connected for any earlier `hand_end`) must still see every
    hand already played, not just whatever's in progress when it joins."""
    rng = random.Random(20260918)
    table = Table("table-spectator-history", _BOUNDED_RULESET, game_seed=20260918)

    starting_hand_no = table.state.hand_no
    while table.state.hand_no == starting_hand_no and table.state.phase != Phase.GAME_OVER:
        await _drive_one_step(table, rng)
    assert table.state.hand_no != starting_hand_no  # hand 1 has genuinely closed

    received: list[dict[str, object]] = []
    table.register_spectator("spec-1", lambda seq, wire: received.append(wire))

    assert len(received) == 1
    sync = received[0]
    assert sync["t"] == "state_sync"
    history = sync["hand_history"]
    assert [h["hand_no"] for h in history] == [starting_hand_no]


async def test_illegal_command_is_rejected_without_corrupting_state() -> None:
    table = Table("table-2", _BOUNDED_RULESET, game_seed=4242)

    pre_state = table.state
    pre_event_id = table.event_id
    pre_seat_seq = list(table.seat_seq)
    pre_ring = {seat: list(table.ring[seat]) for seat in range(4)}

    # fresh game: turn belongs to the dealer (seat 0), phase AWAIT_ACTION. A discard "issued"
    # by a seat that isn't on turn is illegal regardless of which tile it names.
    off_turn_seat = (table.state.turn + 1) % 4
    illegal_tile = table.state.seats[off_turn_seat].concealed[0]
    table.submit(off_turn_seat, Discard(tile_id=illegal_tile))
    await table.process_one()

    assert table.state is pre_state  # reduce() never ran, no new GameState was built
    assert table.event_id == pre_event_id
    assert table.seat_seq == pre_seat_seq
    for seat in range(4):
        assert list(table.ring[seat]) == pre_ring[seat]

    # the table keeps working normally afterward -- a dropped command doesn't wedge it.
    legal_tile = table.state.seats[table.state.turn].concealed[0]
    table.submit(table.state.turn, Discard(tile_id=legal_tile))
    await table.process_one()
    assert table.state is not pre_state
    assert table.event_id == pre_event_id + 1


# --- M5 guest display name normalization (docs/protocol.md §2 join.name) --------------------


def test_join_name_is_trimmed_and_stored() -> None:
    table = Table("table-name-1", _BOUNDED_RULESET, game_seed=1)
    seat = table.join("sess-0", lambda seq, wire: None, seat=0, name="  Alice  ")
    binding = table.seat_bindings[seat]
    assert binding is not None
    assert binding.name == "Alice"


def test_join_name_empty_or_omitted_falls_back_to_a_per_seat_default() -> None:
    table = Table("table-name-2", _BOUNDED_RULESET, game_seed=2)
    table.join("sess-0", lambda seq, wire: None, seat=0, name="   ")
    table.join("sess-1", lambda seq, wire: None, seat=1, name=None)
    assert table.seat_bindings[0] is not None and table.seat_bindings[0].name == "Guest 1"
    assert table.seat_bindings[1] is not None and table.seat_bindings[1].name == "Guest 2"


def test_join_name_over_length_is_truncated_not_rejected() -> None:
    table = Table("table-name-3", _BOUNDED_RULESET, game_seed=3)
    long_name = "x" * 100
    seat = table.join("sess-0", lambda seq, wire: None, seat=0, name=long_name)
    binding = table.seat_bindings[seat]
    assert binding is not None
    assert binding.name == "x" * 24
    assert len(binding.name) == 24


# --- hand-end hold (docs/architecture.md §3, "Hand-end hold") ------------------------------
# holds the table at HAND_OVER until every non-bot/autoplay seat acks or hand_end_seconds elapses; these drive a bare Table() to the first landing and exercise the hold directly.


async def _drive_to_first_hand_over(table: Table, rng: random.Random) -> None:
    while table.state.phase != Phase.HAND_OVER:
        await _drive_one_step(table, rng)


async def test_hand_end_hold_advances_immediately_once_all_seats_ack() -> None:
    ruleset = dataclasses.replace(_BOUNDED_RULESET, hand_end_seconds=999)
    table = Table("table-hold-ack-all", ruleset, game_seed=101)
    for seat in range(4):
        table.join(f"sess-{seat}", lambda seq, wire: None, seat=seat)

    await _drive_to_first_hand_over(table, random.Random(101))
    hand_no = table.state.hand_no

    table.mark_hand_end_ack(0)
    table.mark_hand_end_ack(1)
    table.mark_hand_end_ack(2)
    assert table.state.phase == Phase.HAND_OVER  # seat 3 hasn't acked yet -- still held

    table.mark_hand_end_ack(3)
    # the last ack closes the hold immediately, without waiting for the (here, deliberately
    # huge) hand_end_seconds timeout.
    assert table.state.phase != Phase.HAND_OVER
    assert table.state.hand_no != hand_no or table.state.phase == Phase.GAME_OVER


async def test_hand_end_hold_times_out_with_only_partial_acks() -> None:
    ruleset = dataclasses.replace(_BOUNDED_RULESET, hand_end_seconds=0)
    table = Table("table-hold-timeout", ruleset, game_seed=102)
    for seat in range(4):
        table.join(f"sess-{seat}", lambda seq, wire: None, seat=seat)

    await _drive_to_first_hand_over(table, random.Random(102))

    table.mark_hand_end_ack(0)
    table.mark_hand_end_ack(2)
    assert table.state.phase == Phase.HAND_OVER  # only 2 of 4 -- still held

    # hand_end_seconds=0 -- the very next tick's timer closes it despite the missing acks.
    await table.process_one()
    assert table.state.phase != Phase.HAND_OVER


async def test_hand_end_hold_pre_acks_bot_and_autoplay_seats() -> None:
    """M4.5 practice-mode bot seats (and any already-`autoplay` seat) have no human to click
    dismiss -- pre-seeded into the ack set the instant the hold opens (mirrors
    `_send_claim_offers`'s `no_calls`/`auto_pass_chow` pre-resolution), so only the one real
    seat here has to actually ack."""
    ruleset = dataclasses.replace(_BOUNDED_RULESET, hand_end_seconds=999)
    table = Table("table-hold-bots", ruleset, game_seed=103, practice=True)
    table.join("sess-0", lambda seq, wire: None, seat=0)

    await _drive_to_first_hand_over(table, random.Random(103))

    assert table._hand_end_acked == {1, 2, 3}  # every bot seat, pre-seeded
    table.mark_hand_end_ack(0)
    assert table.state.phase != Phase.HAND_OVER  # the one real seat closes it out


async def test_stray_hand_end_ack_for_an_already_resolved_hand_is_a_no_op() -> None:
    ruleset = dataclasses.replace(_BOUNDED_RULESET, hand_end_seconds=0)
    table = Table("table-hold-stray-ack", ruleset, game_seed=104)
    for seat in range(4):
        table.join(f"sess-{seat}", lambda seq, wire: None, seat=seat)

    await _drive_to_first_hand_over(table, random.Random(104))
    await table.process_one()  # timeout closes it (hand_end_seconds=0)
    assert table.state.phase != Phase.HAND_OVER

    state_before = table.state
    table.mark_hand_end_ack(0)  # stray ack for the hand that already resolved -- a no-op
    assert table.state is state_before


async def test_state_sync_carries_the_hand_end_deadline_while_the_hold_is_open() -> None:
    ruleset = dataclasses.replace(_BOUNDED_RULESET, hand_end_seconds=999)
    table = Table("table-hold-state-sync", ruleset, game_seed=105)
    for seat in range(4):
        table.join(f"sess-{seat}", lambda seq, wire: None, seat=seat)

    await _drive_to_first_hand_over(table, random.Random(105))

    wire = table.state_sync_wire(0)
    assert wire["phase"] == "HAND_OVER"
    assert isinstance(wire["deadline_ts"], int)


# --- bot job pool routing (app/table.py's _shared_bot_pool) ------------------------------------


class _RecordingExecutor(Executor):
    """Minimal `Executor` stand-in, same convention as `tests/test_table_turn_timeout.py`'s
    `_HangingExecutor` -- `loop.run_in_executor` only needs `submit(fn, *args, **kwargs)`.
    Resolves immediately with a harmless action id (0, DISCARD tile_type 0) since these tests
    only care about *which* pool a job lands on, never the decoded result."""

    def __init__(self) -> None:
        self.submissions: list[tuple[Any, ...]] = []

    def submit(self, fn: Any, /, *args: Any, **kwargs: Any) -> Future[Any]:
        self.submissions.append((fn, args, kwargs))
        future: Future[Any] = Future()
        future.set_result(0)
        return future


async def test_t2_bot_jobs_route_to_the_default_pool_only() -> None:
    default_pool = _RecordingExecutor()
    table = Table(
        "table-pool-t2",
        RuleSet(),
        game_seed=1,
        bot_tier="T2",
        bot_pool=default_pool,
        all_bots=True,
    )
    table._poke_bots()  # seat 0 (dealer) is AWAIT_ACTION right after new_game(); 1 job submitted
    assert len(default_pool.submissions) == 1


# --- per-seat bot tier override (practice mode's difficulty picker, docs/frontend.md) -------


def test_seat_bot_tiers_overrides_bot_tier_per_seat_falling_back_for_seats_it_omits() -> None:
    table = Table(
        "table-seat-tiers",
        RuleSet(),
        game_seed=1,
        bot_tier="T2",
        seat_bot_tiers={1: "T1", 3: "ORACLE"},
        practice=True,
    )
    assert table._effective_bot_tier(1) == "T1"
    assert table._effective_bot_tier(2) == "T2"  # not in the mapping -- falls back to bot_tier
    assert table._effective_bot_tier(3) == "ORACLE"


async def test_seat_bot_tiers_still_forces_t2_for_disconnect_handover() -> None:
    """A per-seat override of `ORACLE` only ever applies to a `bot`-status seat (practice mode) --
    a real human's seat gone `autoplay` must still never be driven by `ORACLE`, same invariant as
    `test_disconnect_handover_always_uses_t2_even_when_table_bot_tier_is_oracle` pins for the
    table-wide `bot_tier`."""
    table = Table(
        "table-seat-tiers-disconnect",
        RuleSet(),
        game_seed=1,
        bot_tier="T2",
        seat_bot_tiers={0: "ORACLE"},
    )
    table.seat_bindings[0] = SeatBinding(
        session_id="sess-0",
        send=lambda seq, wire: None,
        name="Guest 1",
        status="autoplay",
    )
    assert table._effective_bot_tier(0) == "T2"


def test_seat_bot_tiers_rejects_an_unknown_tier() -> None:
    with pytest.raises(ValueError, match="unknown bot tier"):
        Table("table-bad-tier", RuleSet(), game_seed=1, seat_bot_tiers={1: "not_a_real_tier"})


def test_seat_bot_tiers_rejects_a_seat_out_of_range() -> None:
    with pytest.raises(ValueError, match="seat must be 0..3"):
        Table("table-bad-seat", RuleSet(), game_seed=1, seat_bot_tiers={4: "T1"})


# --- ORACLE dispatch + disconnect-handover pinning (docs/bots.md §9) -----------------------
# "ORACLE" is a plain FaanBot() fed an omniscient view -- no dedicated pool, so only the view-building special case and disconnect-handover (never for a human's seat) need pinning here.


async def test_oracle_bot_job_view_has_hands_populated_for_a_practice_bot_seat() -> None:
    """A practice-mode `bot` seat (`all_bots=True`, never a real human -- `_bind_bot_seat`) on
    an `ORACLE` table gets the omniscient view built by `_omniscient_seat_view` -- the whole
    point of the tier, and the one case where `_submit_bot_job` is allowed to build one. Routes
    through the ordinary default pool, same as `T2` -- a `FaanBot`-cost decision needs no
    isolation from other tables' `T1`/`T2` jobs."""
    default_pool = _RecordingExecutor()
    table = Table(
        "table-pool-oracle-view",
        RuleSet(),
        game_seed=1,
        bot_tier="ORACLE",
        bot_pool=default_pool,
        all_bots=True,
    )
    table._poke_bots()
    assert len(default_pool.submissions) == 1
    _fn, args, _kwargs = default_pool.submissions[0]
    view, _mask, _seed, tier, _deadline = args
    assert tier == "ORACLE"
    assert view.hands is not None
    assert view.hands == tuple(s.concealed for s in table.state.seats)


async def test_disconnect_handover_always_uses_t2_even_when_table_bot_tier_is_oracle() -> None:
    """The one explicit product requirement behind the `ORACLE` tier's live-dispatch wiring
    (docs/bots.md): a real human's seat gone quiet (`autoplay`) must never be driven by the
    table's own `bot_tier` when that tier is `ORACLE` -- a human never opted into a bot that
    sees every other seat's concealed tiles. Verified: the view built for that job is an
    ordinary `seat_view` (`.hands is None`), never the omniscient one -- both tiers already share
    the same pool, so there's no separate pool-routing fact left to pin here.
    """
    default_pool = _RecordingExecutor()
    table = Table(
        "table-disconnect-oracle",
        RuleSet(),
        game_seed=1,
        bot_tier="ORACLE",
        bot_pool=default_pool,
    )
    # seat 0 (dealer, AWAIT_ACTION right after new_game()) is a real human's seat that went
    # quiet, not a practice-mode bot seat -- `status` is "autoplay", never "bot".
    table.seat_bindings[0] = SeatBinding(
        session_id="sess-0",
        send=lambda seq, wire: None,
        name="Guest 1",
        status="autoplay",
    )
    table._poke_bots()

    assert len(default_pool.submissions) == 1
    _fn, args, _kwargs = default_pool.submissions[0]
    view, _mask, _seed, tier, _deadline = args
    assert tier == "T2"
    assert view.hands is None
