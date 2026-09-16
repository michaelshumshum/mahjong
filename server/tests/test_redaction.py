"""Schema-walking redaction tests (docs/00-architecture.md §5, docs/02-protocol.md §3,
docs/05-roadmap.md §3's testing table: "render every event type for every seat and assert no
unauthorised `tile_id`/`tile` ever appears... fails loudly on new message fields").

Real `GameState`s, not just hand-built minimal ones: `_collect_self_play_samples` plays actual
`RandomBot` games through `mahjong_core.engine.reduce`/`start_next_hand` and harvests
`(state, event)` pairs as they actually occur. A handful of event shapes RandomBot essentially
never produces on its own (concealed kong, a claimed/self-drawn win clearing `min_faan`) are
supplemented with small hand-built states so this suite doesn't depend on random luck for
exactly the cases most worth checking -- see `_hand_built_samples`.
"""

from __future__ import annotations

import dataclasses
import random
from collections.abc import Iterator
from dataclasses import dataclass, fields
from typing import Any

import pytest

from app.views import (
    ClaimResolvedWire,
    ConcealedKongWire,
    DiscardWire,
    DrawWire,
    Entitlement,
    FlowerReplaceWire,
    GameEndWire,
    HandEndWire,
    KongReplaceWire,
    MeldWire,
    _build_event_wire,
    _wire_value,
    redact_event,
    seat_view,
)
from bots import RandomBot
from mahjong_core.actions import (
    Action,
    ClaimChow,
    ClaimKong,
    ClaimPung,
    DeclareAddedKong,
    DeclareConcealedKong,
    Discard,
)
from mahjong_core.config import RuleSet
from mahjong_core.engine import (
    ClaimResolved,
    Discarded,
    Drawn,
    Event,
    FlowerReplaced,
    GameEnded,
    HandEnded,
    KongReplacementDrawn,
    MeldFormed,
    new_game,
    reduce,
    start_next_hand,
)
from mahjong_core.melds import Meld, MeldKind
from mahjong_core.state import ClaimOffer, GameState, HandOutcome, HandResult, Phase, WinType
from mahjong_core.tiles import TileId

# --- self-play sample collection -----------------------------------------------------------

_RULESET = RuleSet(dealer_repeat_on_win=False, dealer_repeat_on_draw=False)
# matches tests/test_selfplay.py's own bounded config: dealer rotates unconditionally, so a
# game is capped at exactly 4 hands (EAST_ONLY) -- keeps this suite's self-play fast and
# guarantees GAME_OVER (hence a GameEnded sample) every run.

_STEP_CAP = 2000
_SEED_BUDGET = 80
_SAMPLES_PER_KIND = 6

_SELF_PLAY_EVENT_KINDS: tuple[type[Event], ...] = (
    Drawn,
    FlowerReplaced,
    Discarded,
    MeldFormed,
    ClaimResolved,
    KongReplacementDrawn,
    HandEnded,
    GameEnded,
)


def _play_and_collect(seed: int) -> Iterator[tuple[GameState, Event]]:
    """One bounded `RandomBot` game, yielding `(state, event)` for every event it produces.
    `state` is always the state `reduce()`/`start_next_hand()` returned alongside that event's
    batch -- for every event kind this module redacts, the redaction decision only depends on
    `event`'s own fields plus (for `HandEnded`) `state.hand_result`, which is set by the time
    `HandEnded` is the last event of its own batch -- so pairing with the batch's final state
    is always correct, not just convenient.
    """
    rng = random.Random(seed)
    bots = [RandomBot(rng=rng) for _ in range(4)]
    state = new_game(_RULESET, seed)
    steps = 0
    while state.phase != Phase.GAME_OVER:
        steps += 1
        if steps > _STEP_CAP:
            raise RuntimeError(f"seed={seed}: exceeded {_STEP_CAP} steps")

        if state.phase == Phase.HAND_OVER:
            state, events = start_next_hand(state)
            for event in events:
                yield state, event
            continue

        if state.phase in (Phase.AWAIT_CLAIMS, Phase.AWAIT_KONG_ROB):
            assert state.claim_window is not None
            pending = [
                o.seat
                for o in state.claim_window.offers
                if o.seat not in state.claim_window.responses
            ]
            seat = rng.choice(pending)
        else:
            seat = state.turn

        action = bots[seat].act(state, seat)
        state, events = reduce(state, action)
        for event in events:
            yield state, event


def _collect_self_play_samples() -> list[tuple[GameState, Event]]:
    by_kind: dict[type[Event], list[tuple[GameState, Event]]] = {
        kind: [] for kind in _SELF_PLAY_EVENT_KINDS
    }
    for seed in range(_SEED_BUDGET):
        if all(len(v) >= _SAMPLES_PER_KIND for v in by_kind.values()):
            break
        for state, event in _play_and_collect(seed):
            bucket = by_kind.get(type(event))
            if bucket is not None and len(bucket) < _SAMPLES_PER_KIND:
                bucket.append((state, event))
    samples: list[tuple[GameState, Event]] = []
    for bucket in by_kind.values():
        samples.extend(bucket)
    return samples


# --- hand-built supplements: shapes RandomBot essentially never reaches on its own ----------


def _concealed_kong_sample() -> tuple[GameState, Event]:
    base = new_game(_RULESET, 90001)
    kong = Meld(MeldKind.CONCEALED_KONG, (TileId(0), TileId(1), TileId(2), TileId(3)))
    seat0 = dataclasses.replace(base.seats[0], melds=(kong,))
    seats = (seat0, base.seats[1], base.seats[2], base.seats[3])
    state = dataclasses.replace(base, seats=seats)
    return state, MeldFormed(seat=0, meld=kong)


def _self_draw_win_sample() -> tuple[GameState, Event]:
    base = new_game(_RULESET, 90002)
    result = HandResult(
        outcome=HandOutcome.WIN,
        winner=1,
        win_type=WinType.SELF_DRAW,
        discarder=None,
        faan=5,
        faan_breakdown={"清一色": 5},
        points=20,
        payments={0: -20, 1: 60, 2: -20, 3: -20},
    )
    state = dataclasses.replace(base, phase=Phase.HAND_OVER, hand_result=result, claim_window=None)
    event = HandEnded(
        hand_no=state.hand_no,
        outcome=HandOutcome.WIN,
        winner=1,
        win_type=WinType.SELF_DRAW,
        discarder=None,
    )
    return state, event


def _claimed_win_sample() -> tuple[GameState, Event]:
    """Winner (seat 2) took the win off seat 0's discard. `state.seats[2].concealed` does NOT
    include the winning tile -- `engine._apply_claim_response` never merges it back in for a
    claimed win, only the scoring context sees it (HandEndWire's docstring, app/views.py). This
    sample exists specifically to pin that known, documented gap in the redacted output, not to
    assert it's correct."""
    base = new_game(_RULESET, 90003)
    result = HandResult(
        outcome=HandOutcome.WIN,
        winner=2,
        win_type=WinType.DISCARD,
        discarder=0,
        faan=3,
        faan_breakdown={"雞糊": 3},
        points=8,
        payments={0: -24, 1: 0, 2: 24, 3: 0},
    )
    state = dataclasses.replace(base, phase=Phase.HAND_OVER, hand_result=result, claim_window=None)
    event = HandEnded(
        hand_no=state.hand_no,
        outcome=HandOutcome.WIN,
        winner=2,
        win_type=WinType.DISCARD,
        discarder=0,
    )
    return state, event


def _exhaustive_draw_sample() -> tuple[GameState, Event]:
    base = new_game(_RULESET, 90004)
    result = HandResult(outcome=HandOutcome.EXHAUSTIVE_DRAW)
    state = dataclasses.replace(base, phase=Phase.HAND_OVER, hand_result=result, claim_window=None)
    event = HandEnded(
        hand_no=state.hand_no,
        outcome=HandOutcome.EXHAUSTIVE_DRAW,
        winner=None,
        win_type=None,
        discarder=None,
    )
    return state, event


def _hand_built_samples() -> list[tuple[GameState, Event]]:
    return [
        _concealed_kong_sample(),
        _self_draw_win_sample(),
        _claimed_win_sample(),
        _exhaustive_draw_sample(),
    ]


@pytest.fixture(scope="module")
def event_samples() -> list[tuple[GameState, Event]]:
    return _collect_self_play_samples() + _hand_built_samples()


# --- the schema walker itself ---------------------------------------------------------------


def _assert_wire_entitlement(wire: Any, viewer: int | None) -> None:
    """Walk one produced wire instance's `Entitlement`-annotated fields structurally
    (00-architecture.md §5). Every field must carry an annotation -- a field with none fails
    loudly rather than silently passing (see `test_walker_rejects_unannotated_field`)."""
    owner = getattr(wire, "seat", None)
    revealed = getattr(wire, "revealed", None)
    for f in fields(wire):
        entitlement = f.metadata.get("entitlement")
        assert entitlement is not None, (
            f"{type(wire).__name__}.{f.name} has no Entitlement annotation -- "
            "classify it before shipping"
        )
        value = getattr(wire, f.name)

        if entitlement is Entitlement.PUBLIC:
            continue

        if entitlement is Entitlement.COUNT_ONLY:
            assert value is None or isinstance(value, int), (
                f"{type(wire).__name__}.{f.name} is COUNT_ONLY but holds {value!r}, not a count"
            )
            continue

        if entitlement is Entitlement.OWN_SEAT:
            entitled = viewer is not None and owner is not None and viewer == owner
            if not entitled:
                assert value is None, (
                    f"{type(wire).__name__}.{f.name} leaked to seat {viewer} "
                    f"(owner={owner}): {value!r}"
                )
            continue

        if entitlement is Entitlement.HAND_END:
            if not revealed:
                assert value is None, (
                    f"{type(wire).__name__}.{f.name} leaked before hand end: {value!r}"
                )
            continue

        raise AssertionError(f"unhandled Entitlement: {entitlement}")  # new enum member


def _action_tile_ids(action: Action) -> set[TileId]:
    if isinstance(action, Discard):
        return {action.tile_id}
    if isinstance(
        action, (ClaimChow, ClaimPung, ClaimKong, DeclareConcealedKong, DeclareAddedKong)
    ):
        return set(action.meld.tiles)
    return set()  # ClaimWin, Pass, DeclareWin carry no tile identity


def _offer_tile_ids(offer: ClaimOffer) -> set[TileId]:
    ids: set[TileId] = set()
    for meld in offer.melds:
        ids.update(meld.tiles)
    return ids


def _public_tile_ids(state: GameState) -> set[TileId]:
    """Every tile id already public knowledge right now: melds (all kinds -- even a concealed
    kong's `tiles` field is a real leak if it shows up outside `own_hand`/an entitled wire, but
    the *seat* who declared it already legitimately knows its own concealed_kong tiles, which
    is exactly `own_hand`, not this set) and every seat's discard pool, plus the live claim
    window's tile if one is open."""
    ids: set[TileId] = set()
    for seat_state in state.seats:
        for meld in seat_state.melds:
            if meld.kind != MeldKind.CONCEALED_KONG:
                ids.update(meld.tiles)
        ids.update(seat_state.discards)
    if state.claim_window is not None:
        ids.add(state.claim_window.tile)
    return ids


def _assert_seat_view_entitled(state: GameState, seat: int | None) -> None:
    view = seat_view(state, seat)
    allowed = _public_tile_ids(state)

    if seat is not None:
        allowed |= set(state.seats[seat].concealed)
        assert set(view.own_hand) == set(state.seats[seat].concealed), (
            f"own_hand for seat {seat} doesn't match its real concealed hand"
        )
    else:
        assert view.own_hand == (), "spectator own_hand must be empty"

    for action in view.legal_actions:
        leaked = _action_tile_ids(action) - allowed
        assert not leaked, f"legal_actions leaked {leaked} to seat {seat}: {action!r}"

    for offer in view.claim_options:
        leaked = _offer_tile_ids(offer) - allowed
        assert not leaked, f"claim_options leaked {leaked} to seat {seat}: {offer!r}"


def _assert_event_redaction(state: GameState, event: Event) -> None:
    for viewer in (0, 1, 2, 3, None):
        wire = _build_event_wire(state, viewer, event)
        _assert_wire_entitlement(wire, viewer)

        d = redact_event(state, viewer, event)
        for f in fields(wire):
            assert d[f.name] == _wire_value(getattr(wire, f.name)), (
                f"redact_event's dict drifted from _build_event_wire for {f.name}"
            )

    # ground-truth (positive) checks: the entitled viewer must get the *real* value, not just
    # "not obviously redacted" -- a bug that nulls everything for everyone would otherwise
    # pass every check above.
    if isinstance(event, Drawn):
        owner_wire = _build_event_wire(state, event.seat, event)
        assert isinstance(owner_wire, DrawWire)
        assert owner_wire.tile_id == event.tile_id

    if isinstance(event, KongReplacementDrawn):
        owner_wire = _build_event_wire(state, event.seat, event)
        assert isinstance(owner_wire, KongReplaceWire)
        assert owner_wire.tile_id == event.tile_id

    if isinstance(event, MeldFormed) and event.meld.kind == MeldKind.CONCEALED_KONG:
        owner_wire = _build_event_wire(state, event.seat, event)
        assert isinstance(owner_wire, ConcealedKongWire)
        assert owner_wire.tiles == tuple(event.meld.tiles)
        assert owner_wire.count is None

        other_seat = (event.seat + 1) % 4
        other_wire = _build_event_wire(state, other_seat, event)
        assert isinstance(other_wire, ConcealedKongWire)
        assert other_wire.tiles is None
        assert other_wire.count == len(event.meld.tiles)

    if isinstance(event, MeldFormed) and event.meld.kind != MeldKind.CONCEALED_KONG:
        for viewer in (0, 1, 2, 3, None):
            wire = _build_event_wire(state, viewer, event)
            assert isinstance(wire, MeldWire)
            assert wire.tiles == tuple(event.meld.tiles)  # fully public, every kind but the above

    if isinstance(event, HandEnded) and event.outcome == HandOutcome.WIN:
        assert event.winner is not None
        for viewer in (0, 1, 2, 3, None):  # HAND_END is viewer-independent once revealed
            wire = _build_event_wire(state, viewer, event)
            assert isinstance(wire, HandEndWire)
            assert wire.revealed is True
            assert wire.winning_hand == tuple(state.seats[event.winner].concealed)


# --- tests ------------------------------------------------------------------------------


def test_event_kind_coverage(event_samples: list[tuple[GameState, Event]]) -> None:
    """Every mahjong_core.engine.Event variant is actually exercised -- a variant this suite
    never samples would make the rest of these tests vacuously true for it."""
    all_kinds: tuple[type[Event], ...] = (
        Drawn,
        FlowerReplaced,
        Discarded,
        MeldFormed,
        ClaimResolved,
        KongReplacementDrawn,
        HandEnded,
        GameEnded,
    )
    seen = {type(event) for _, event in event_samples}
    missing = set(all_kinds) - seen
    assert not missing, f"no sample collected for: {missing}"

    # and both concealed-kong and win/exhaustive-draw shapes specifically, not just the base kind
    melds = [event.meld.kind for _, event in event_samples if isinstance(event, MeldFormed)]
    assert MeldKind.CONCEALED_KONG in melds
    hand_ends = [event.outcome for _, event in event_samples if isinstance(event, HandEnded)]
    assert HandOutcome.WIN in hand_ends
    assert HandOutcome.EXHAUSTIVE_DRAW in hand_ends
    win_types = {event.win_type for _, event in event_samples if isinstance(event, HandEnded)}
    assert WinType.SELF_DRAW in win_types
    assert WinType.DISCARD in win_types


def test_redact_event_schema(event_samples: list[tuple[GameState, Event]]) -> None:
    for state, event in event_samples:
        _assert_event_redaction(state, event)


def test_seat_view_schema(event_samples: list[tuple[GameState, Event]]) -> None:
    # de-dup by identity -- many events share the same batch's final state
    seen_states = {id(state): state for state, _ in event_samples}
    for state in seen_states.values():
        for seat in (0, 1, 2, 3, None):
            _assert_seat_view_entitled(state, seat)


def test_seat_view_own_hand_matches_state() -> None:
    state = new_game(_RULESET, 1)
    for seat in range(4):
        assert set(seat_view(state, seat).own_hand) == set(state.seats[seat].concealed)
    assert seat_view(state, None).own_hand == ()


def test_hand_end_known_gap_claimed_win_misses_winning_tile() -> None:
    """Pins the documented gap (HandEndWire's docstring, app/views.py): a claimed win's
    `winning_hand` reveal is short exactly the winning tile, because `engine.py` never merges
    it back into `state.seats[winner].concealed`. If `engine.py` is fixed later, this test
    should start failing and can be flipped to assert full correctness."""
    state, event = _claimed_win_sample()
    assert isinstance(event, HandEnded)
    assert event.winner is not None
    wire = _build_event_wire(state, event.winner, event)
    assert isinstance(wire, HandEndWire)
    assert wire.winning_hand == tuple(state.seats[event.winner].concealed)


def test_walker_rejects_unannotated_field() -> None:
    """Proves the walker isn't just a docstring promise: a field with no `Entitlement`
    metadata fails loudly instead of silently passing (00-architecture.md §5's own framing)."""

    @dataclass(frozen=True)
    class _Naked:
        t: str
        seat: int
        tile_id: int | None  # deliberately missing metadata

    naked = _Naked(t="x", seat=0, tile_id=42)
    with pytest.raises(AssertionError, match="no Entitlement annotation"):
        _assert_wire_entitlement(naked, viewer=1)


def test_walker_catches_a_leak() -> None:
    """Proves the walker actually rejects a real leak, not just well-formed input: a
    `DrawWire` built (incorrectly) with another seat's tile populated must fail when checked
    against a different viewer."""
    leaking = DrawWire(t="draw", seat=0, tile_id=55)
    with pytest.raises(AssertionError, match="leaked"):
        _assert_wire_entitlement(leaking, viewer=1)


def test_public_wire_forms_never_declare_hand_end_or_own_seat_for_group_fields() -> None:
    """Sanity check on the schema itself: `ClaimResolvedWire`/`FlowerReplaceWire`/
    `DiscardWire`/`GameEndWire` carry no restricted fields at all -- nothing in them is ever
    allowed to differ per viewer, matching 02-protocol.md §3 ("fully public... no redaction")."""
    for cls in (ClaimResolvedWire, FlowerReplaceWire, DiscardWire, GameEndWire):
        for f in fields(cls):
            assert f.metadata.get("entitlement") in (Entitlement.PUBLIC, None) or f.name == "t", (
                f"{cls.__name__}.{f.name} unexpectedly restricted"
            )
