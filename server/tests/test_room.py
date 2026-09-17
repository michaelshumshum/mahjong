"""`app/room.py`'s core dispatch loop (docs/05-roadmap.md M3 sub-task 2), driven purely through
`Room.submit()`/`process_one()` -- never `reduce()`/`start_next_hand()` directly, so these tests
actually exercise the Room's own dispatch, not the pure engine underneath it.

Same action-generation approach as `bots/selfplay.py`'s `play_game`/`tests/test_selfplay.py`
(seeded `RandomBot`s, `state.turn` on a live turn or a random pending claimant during a claim
window), wrapped through `Room` instead of calling `reduce`/`start_next_hand` directly. Ruleset
matches `tests/test_selfplay.py`'s bounded config (`dealer_repeat_on_win/draw=False`): a full
`EAST_ONLY` game is exactly 4 hands regardless of bot skill, so a real multi-hand game finishes
fast and deterministically.
"""

from __future__ import annotations

import random

from app.room import Room
from bots.random import random_action
from mahjong_core.actions import Discard
from mahjong_core.config import GameLength, RuleSet
from mahjong_core.state import Phase

_STEP_CAP = 8000  # matches bots/selfplay.py's _STEP_CAP for the same bounded ruleset
_BOUNDED_RULESET = RuleSet(
    dealer_repeat_on_win=False, dealer_repeat_on_draw=False, game_length=GameLength.EAST_ONLY
)


async def _drive_one_step(room: Room, rng: random.Random) -> None:
    """Pick the acting seat the same way `bots/selfplay.py`'s `play_game` does, then submit and
    process that seat's randomly-chosen action through the Room."""
    state = room.state
    if state.phase in (Phase.AWAIT_CLAIMS, Phase.AWAIT_KONG_ROB):
        assert state.claim_window is not None
        pending = [
            o.seat for o in state.claim_window.offers if o.seat not in state.claim_window.responses
        ]
        seat = rng.choice(pending)
    else:
        seat = state.turn
    action = random_action(state, seat, rng)
    room.submit(seat, action)
    await room.process_one()


async def test_full_game_through_room_progresses_and_publishes_gapless_redacted_frames() -> None:
    rng = random.Random(20260916)
    room = Room("room-1", _BOUNDED_RULESET, game_seed=20260916)

    seen_hand_numbers: set[int] = {room.state.hand_no}
    prev_event_id = room.event_id
    steps = 0
    while room.state.phase != Phase.GAME_OVER:
        steps += 1
        if steps > _STEP_CAP:
            raise RuntimeError(f"exceeded {_STEP_CAP} steps -- possible deadlock")
        await _drive_one_step(room, rng)
        seen_hand_numbers.add(room.state.hand_no)
        assert room.event_id >= prev_event_id  # never decreases
        prev_event_id = room.event_id

    # reduce()/start_next_hand() actually drove the game forward, not just one hand.
    assert room.state.phase == Phase.GAME_OVER
    assert room.state.hand_no == 4  # EAST_ONLY, no repeats -> exactly 4 hands (test_engine.py)
    assert seen_hand_numbers == {1, 2, 3, 4}
    assert room.event_id > 0

    # per-seat ring buffers: gapless seq even across `deque(maxlen=512)` eviction -- the tail
    # window's first seq must equal seat_seq minus the window's length, with no gap inside it.
    for seat in range(4):
        buf = list(room.ring[seat])
        assert buf, f"seat {seat} received no frames"
        expected_start = room.seat_seq[seat] - len(buf)
        assert [e.seq for e in buf] == list(range(expected_start, expected_start + len(buf)))

        # redaction spot-check: this Room seat's own tile draws are visible, every other
        # seat's concealed draws/kong-replacements/concealed-kong tiles are not (full schema
        # coverage is tests/test_redaction.py's job; this only confirms Room is actually
        # calling redact_event(), not skipping it).
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


async def test_illegal_command_is_rejected_without_corrupting_state() -> None:
    room = Room("room-2", _BOUNDED_RULESET, game_seed=4242)

    pre_state = room.state
    pre_event_id = room.event_id
    pre_seat_seq = list(room.seat_seq)
    pre_ring = {seat: list(room.ring[seat]) for seat in range(4)}

    # fresh game: turn belongs to the dealer (seat 0), phase AWAIT_ACTION. A discard "issued"
    # by a seat that isn't on turn is illegal regardless of which tile it names.
    off_turn_seat = (room.state.turn + 1) % 4
    illegal_tile = room.state.seats[off_turn_seat].concealed[0]
    room.submit(off_turn_seat, Discard(tile_id=illegal_tile))
    await room.process_one()

    assert room.state is pre_state  # reduce() never ran, no new GameState was built
    assert room.event_id == pre_event_id
    assert room.seat_seq == pre_seat_seq
    for seat in range(4):
        assert list(room.ring[seat]) == pre_ring[seat]

    # the room keeps working normally afterward -- a dropped command doesn't wedge it.
    legal_tile = room.state.seats[room.state.turn].concealed[0]
    room.submit(room.state.turn, Discard(tile_id=legal_tile))
    await room.process_one()
    assert room.state is not pre_state
    assert room.event_id == pre_event_id + 1
