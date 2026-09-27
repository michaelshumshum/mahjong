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

from app.table import Table
from app.views import (
    ClaimResolvedWire,
    ConcealedKongWire,
    DiscardWire,
    DrawWire,
    Entitlement,
    FlowerReplaceWire,
    GameEndWire,
    HandEndWire,
    HandHistoryRecord,
    KongReplaceWire,
    MeldWire,
    _build_event_wire,
    _wire_value,
    hand_history_wire,
    redact_event,
    seat_view,
    seat_view_wire,
)
from bots.random import random_action
from bots.worker import BOT_TIERS
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
# matches test_selfplay.py's bounded config: dealer rotates unconditionally, capping the game
# at 4 hands (EAST_ONLY) -- keeps this suite fast and guarantees a GameEnded sample.

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

        action = random_action(state, seat, rng)
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
    """Winner (seat 2) took the win off seat 0's discard. `state.seats[2].concealed` is the
    real post-win shape `engine._apply_claim_response` now produces: the claimed tile folded
    in, 14 tiles total -- not just the 13 seat 2 held while waiting on the claim."""
    base = new_game(_RULESET, 90003)
    winner_state = base.seats[2]
    claimed_tile = TileId(0) if TileId(0) not in winner_state.concealed else TileId(4)
    winner_state = dataclasses.replace(
        winner_state, concealed=(*winner_state.concealed, claimed_tile)
    )
    seats = (base.seats[0], base.seats[1], winner_state, base.seats[3])
    base = dataclasses.replace(base, seats=seats)
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


def _assert_wire_entitlement(wire: Any, viewer: int | None, *, reveal_hands: bool = False) -> None:
    """Walk one produced wire instance's `Entitlement`-annotated fields structurally
    (00-architecture.md §5). Every field must carry an annotation -- a field with none fails
    loudly rather than silently passing (see `test_walker_rejects_unannotated_field`).
    `reveal_hands` walks it as the open-hands spectator (`app/views.py`'s module docstring)."""
    open_spectator = reveal_hands and viewer is None
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
            entitled = open_spectator or (
                viewer is not None and owner is not None and viewer == owner
            )
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

        if entitlement is Entitlement.OPEN_HANDS:
            if not open_spectator:
                assert value is None, (
                    f"{type(wire).__name__}.{f.name} leaked to non-open viewer {viewer}: {value!r}"
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
    assert view.hands is None, f"hands populated without reveal_hands for seat {seat}"
    assert seat_view_wire(view)["hands"] is None

    for action in view.legal_actions:
        leaked = _action_tile_ids(action) - allowed
        assert not leaked, f"legal_actions leaked {leaked} to seat {seat}: {action!r}"

    for offer in view.claim_options:
        leaked = _offer_tile_ids(offer) - allowed
        assert not leaked, f"claim_options leaked {leaked} to seat {seat}: {offer!r}"

    # `melds` has hand-rolled serialization (`_meld_wire`), not the schema walker above -- its
    # aggregate PUBLIC annotation is wrong specifically for a concealed kong's tiles (00-architecture.md §5).
    wire = seat_view_wire(view)
    for owner_seat, seat_melds in enumerate(view.melds):
        wire_melds = wire["melds"][owner_seat]
        for meld, wire_meld in zip(seat_melds, wire_melds, strict=True):
            if meld.kind != MeldKind.CONCEALED_KONG:
                assert wire_meld["tiles"] == list(meld.tiles), (
                    f"public meld tiles altered for seat {seat}: {wire_meld!r}"
                )
                continue
            if seat == owner_seat:
                # ground truth: the declaring seat must get its real tiles, not just "not
                # obviously leaked" -- else a bug nulling tiles for everyone passes vacuously.
                assert wire_meld["tiles"] == list(meld.tiles), (
                    "concealed_kong tiles hidden from the declaring seat itself"
                )
                assert wire_meld["count"] is None
            else:
                assert wire_meld["tiles"] is None, (
                    f"concealed_kong tiles leaked to seat {seat} (owner={owner_seat}): "
                    f"{wire_meld!r}"
                )
                assert wire_meld["count"] == len(meld.tiles)


def _assert_event_redaction(state: GameState, event: Event) -> None:
    for viewer in (0, 1, 2, 3, None):
        wire = _build_event_wire(state, viewer, event)
        _assert_wire_entitlement(wire, viewer)

        d = redact_event(state, viewer, event)
        for f in fields(wire):
            assert d[f.name] == _wire_value(getattr(wire, f.name)), (
                f"redact_event's dict drifted from _build_event_wire for {f.name}"
            )

    # ground truth: the entitled viewer must get the *real* value, not just "not obviously
    # redacted" -- else a bug nulling everything for everyone would pass every check above.
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


def test_hand_end_reveals_full_winning_hand_for_claimed_win() -> None:
    """A claimed win's `winning_hand` reveal includes the claimed tile -- 14 tiles, not the 13
    the winner held while waiting on the claim (`engine._apply_claim_response` merges it into
    `state.seats[winner].concealed` before scoring; see `test_engine.py`'s
    `test_claim_win_off_discard_merges_winning_tile_into_concealed` for the engine-level pin)."""
    state, event = _claimed_win_sample()
    assert isinstance(event, HandEnded)
    assert event.winner is not None
    wire = _build_event_wire(state, event.winner, event)
    assert isinstance(wire, HandEndWire)
    assert wire.winning_hand == tuple(state.seats[event.winner].concealed)
    assert wire.winning_hand is not None
    assert len(wire.winning_hand) == 14


def _concealed_kong_history_record() -> HandHistoryRecord:
    """A completed hand won with a concealed kong in the winner's melds -- `hand_history_wire`'s
    one genuinely per-viewer-redacted field (`HandHistoryRecord`'s own docstring)."""
    kong = Meld(MeldKind.CONCEALED_KONG, (TileId(0), TileId(1), TileId(2), TileId(3)))
    return HandHistoryRecord(
        hand_no=1,
        outcome="win",
        winner=0,
        win_type="self_draw",
        discarder=None,
        faan=5,
        faan_breakdown={"kong": 1},
        points=32,
        payments={1: -32, 2: -32, 3: -32},
        revealed=True,
        winning_hand=[10, 11, 12],
        dealer=0,
        prevailing="EAST",
        winner_melds=(kong,),
    )


def test_hand_history_wire_hides_winner_concealed_kong_from_non_owners() -> None:
    """A hand ending doesn't retroactively make its winner's concealed-kong tile identity
    public -- a non-owning viewer still only ever gets `count`, matching what a live `meld`
    event would have shown them for the same meld while the hand was in progress."""
    record = _concealed_kong_history_record()

    owner_view = hand_history_wire([record], viewer=0)[0]
    assert owner_view["winner_melds"][0]["tiles"] == [0, 1, 2, 3]
    assert owner_view["winner_melds"][0]["count"] is None

    other_seat_view = hand_history_wire([record], viewer=1)[0]
    assert other_seat_view["winner_melds"][0]["tiles"] is None
    assert other_seat_view["winner_melds"][0]["count"] == 4

    plain_spectator_view = hand_history_wire([record], viewer=None)[0]
    assert plain_spectator_view["winner_melds"][0]["tiles"] is None

    open_hands_spectator_view = hand_history_wire([record], viewer=None, reveal_hands=True)[0]
    assert open_hands_spectator_view["winner_melds"][0]["tiles"] == [0, 1, 2, 3]


def test_hand_history_wire_omits_winner_melds_for_exhaustive_draw() -> None:
    record = dataclasses.replace(
        _concealed_kong_history_record(),
        outcome="exhaustive_draw",
        winner=None,
        win_type=None,
        revealed=False,
        winning_hand=None,
        winner_melds=None,
    )
    wire = hand_history_wire([record], viewer=None)[0]
    assert wire["winner_melds"] is None
    assert wire["winner"] is None


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


# --- open-hands spectator (`reveal_hands`) --------------------------------------------------


def test_open_hands_spectator_event_redaction(
    event_samples: list[tuple[GameState, Event]],
) -> None:
    for state, event in event_samples:
        wire = _build_event_wire(state, None, event, reveal_hands=True)
        _assert_wire_entitlement(wire, None, reveal_hands=True)
        d = redact_event(state, None, event, reveal_hands=True)
        assert d == {f.name: _wire_value(getattr(wire, f.name)) for f in fields(wire)}

        if isinstance(event, Drawn):
            assert isinstance(wire, DrawWire)
            assert wire.tile_id == event.tile_id
        if isinstance(event, KongReplacementDrawn):
            assert isinstance(wire, KongReplaceWire)
            assert wire.tile_id == event.tile_id
        if isinstance(event, MeldFormed) and event.meld.kind == MeldKind.CONCEALED_KONG:
            assert isinstance(wire, ConcealedKongWire)
            assert wire.tiles == tuple(event.meld.tiles)
            assert wire.count is None


def test_open_hands_spectator_seat_view(event_samples: list[tuple[GameState, Event]]) -> None:
    seen_states = {id(state): state for state, _ in event_samples}
    for state in seen_states.values():
        view = seat_view(state, None, reveal_hands=True)
        assert view.hands == tuple(s.concealed for s in state.seats)
        assert view.own_hand == ()
        assert view.legal_actions == ()
        assert view.claim_options == ()

        wire = seat_view_wire(view)
        assert wire["hands"] == [list(s.concealed) for s in state.seats]
        for owner_seat, seat_state in enumerate(state.seats):
            for meld, wire_meld in zip(seat_state.melds, wire["melds"][owner_seat], strict=True):
                assert wire_meld["tiles"] == list(meld.tiles)


def test_reveal_hands_is_spectator_only() -> None:
    state, event = _concealed_kong_sample()
    for seat in range(4):
        with pytest.raises(ValueError, match="spectator-only"):
            seat_view(state, seat, reveal_hands=True)
        with pytest.raises(ValueError, match="spectator-only"):
            redact_event(state, seat, event, reveal_hands=True)


# --- ORACLE tier containment (docs/04-bots.md §10): a real seat's own wire traffic never gets hands


@pytest.mark.parametrize("bot_tier", BOT_TIERS)
@pytest.mark.parametrize("seat", range(4))
def test_state_sync_wire_never_populates_hands_for_a_real_seat_regardless_of_bot_tier(
    seat: int, bot_tier: str
) -> None:
    """Regression, `ORACLE`-tier-specific: `app/views.py`'s `_omniscient_seat_view` is a
    deliberate, narrowly-scoped exception to "a real seat's `.hands` is never populated" -- it
    exists purely to feed `app/table.py`'s `_submit_bot_job` (which drives the `"ORACLE"` tier's
    plain `FaanBot()` with an omniscient view), and must never leak into what a real WS client
    actually receives. `state_sync_wire` is exactly that path (`app/ws.py` calls it on
    join/reconnect/backpressure-collapse) -- confirm it's completely unaffected by which
    `bot_tier` a table happens to be configured with, `ORACLE` included: a real seat's own
    `state_sync` never carries another seat's tiles, no matter what bot is driving other seats
    at this table.
    """
    table = Table("table-redaction-bot-tier", RuleSet(), game_seed=1, bot_tier=bot_tier)
    wire = table.state_sync_wire(seat)
    assert wire["hands"] is None


def test_walker_catches_open_hands_leak() -> None:
    @dataclass(frozen=True)
    class _Snapshot:
        seat: int | None = dataclasses.field(metadata={"entitlement": Entitlement.PUBLIC})
        hands: tuple[tuple[int, ...], ...] | None = dataclasses.field(
            metadata={"entitlement": Entitlement.OPEN_HANDS}
        )

    snapshot = _Snapshot(seat=None, hands=((1, 2), (3,), (), ()))
    _assert_wire_entitlement(snapshot, None, reveal_hands=True)
    with pytest.raises(AssertionError, match="leaked to non-open viewer"):
        _assert_wire_entitlement(snapshot, None)
    with pytest.raises(AssertionError, match="leaked to non-open viewer"):
        _assert_wire_entitlement(dataclasses.replace(snapshot, seat=0), 0)
