import dataclasses

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mahjong_core.config import DEFAULT_RULESET, RuleSet
from mahjong_core.melds import Meld, MeldKind
from mahjong_core.state import (
    ClaimKind,
    ClaimOffer,
    ClaimWindow,
    GameState,
    Phase,
    SeatState,
    Wind,
    derive_hand_seed,
    new_game,
)
from mahjong_core.tiles import TOTAL_PHYSICAL_TILES, Flower, TileId


def _total_tiles(state: GameState) -> int:
    seat_tiles = sum(
        len(seat.concealed) + sum(len(m.tiles) for m in seat.melds) + len(seat.discards)
        for seat in state.seats
    )
    seat_flowers = sum(len(seat.flowers) for seat in state.seats)
    return seat_tiles + len(state.wall.tiles) + seat_flowers


def _tag(tile: object) -> tuple[str, int]:
    """Type-safe identity: `Flower` is an `IntEnum`, so `Flower.FLOWER_1 == TileId(0)` under
    plain `==` — tag by runtime type before deduplicating (mirrors test_wall.py's `_tag`)."""
    return (type(tile).__name__, int(tile))  # type: ignore[call-overload]


def _all_tiles(state: GameState) -> list[object]:
    tiles: list[object] = list(state.wall.tiles)
    for seat in state.seats:
        tiles.extend(seat.concealed)
        for meld in seat.melds:
            tiles.extend(meld.tiles)
        tiles.extend(seat.discards)
        tiles.extend(seat.flowers)
    return tiles


# --- new_game: composition / conservation -----------------------------------------------


def test_new_game_conserves_144_tiles() -> None:
    state = new_game(DEFAULT_RULESET, game_seed=1)
    assert _total_tiles(state) == TOTAL_PHYSICAL_TILES == 144


def test_new_game_every_tile_unique() -> None:
    state = new_game(DEFAULT_RULESET, game_seed=1)
    tiles = _all_tiles(state)
    assert len(tiles) == TOTAL_PHYSICAL_TILES
    assert len({_tag(t) for t in tiles}) == TOTAL_PHYSICAL_TILES


def test_new_game_conserves_136_tiles_when_flowers_disabled() -> None:
    ruleset = RuleSet(flowers_enabled=False)
    state = new_game(ruleset, game_seed=1)
    assert _total_tiles(state) == 136
    assert all(len(seat.flowers) == 0 for seat in state.seats)


@given(st.integers(min_value=0, max_value=100_000))
def test_property_new_game_conserves_tiles(game_seed: int) -> None:
    state = new_game(DEFAULT_RULESET, game_seed)
    assert _total_tiles(state) == TOTAL_PHYSICAL_TILES
    tiles = _all_tiles(state)
    assert len({_tag(t) for t in tiles}) == TOTAL_PHYSICAL_TILES


def test_new_game_no_flowers_remain_in_any_concealed_hand() -> None:
    state = new_game(DEFAULT_RULESET, game_seed=7)
    for seat in state.seats:
        assert all(isinstance(t, int) for t in seat.concealed)
        assert not any(isinstance(t, Flower) for t in seat.concealed)


def test_new_game_hand_sizes() -> None:
    state = new_game(DEFAULT_RULESET, game_seed=1)
    sizes = [len(seat.concealed) for seat in state.seats]
    assert sizes.count(13) == 3
    assert sizes.count(14) == 1
    assert sizes[state.dealer] == 14


def test_new_game_no_melds_or_discards_yet() -> None:
    state = new_game(DEFAULT_RULESET, game_seed=1)
    assert all(seat.melds == () for seat in state.seats)
    assert all(seat.discards == () for seat in state.seats)
    assert all(seat.score == 0 for seat in state.seats)


# --- new_game: starting phase/turn/dealer invariants -------------------------------------


def test_new_game_starting_dealer_is_seat_0() -> None:
    state = new_game(DEFAULT_RULESET, game_seed=1)
    assert state.dealer == 0


def test_new_game_starting_phase_is_await_action_not_await_draw() -> None:
    # the dealer's 14th tile from the deal stands in for the "draw" step (01-rules-spec.md
    # §4) -- hand 1 starts past AWAIT_DRAW, already waiting on the dealer's first discard.
    state = new_game(DEFAULT_RULESET, game_seed=1)
    assert state.phase == Phase.AWAIT_ACTION


def test_new_game_turn_is_the_dealer() -> None:
    state = new_game(DEFAULT_RULESET, game_seed=1)
    assert state.turn == state.dealer


def test_new_game_prevailing_wind_is_east() -> None:
    state = new_game(DEFAULT_RULESET, game_seed=1)
    assert state.prevailing == Wind.EAST


def test_new_game_hand_no_is_1() -> None:
    state = new_game(DEFAULT_RULESET, game_seed=1)
    assert state.hand_no == 1


def test_new_game_no_live_claim_window() -> None:
    state = new_game(DEFAULT_RULESET, game_seed=1)
    assert state.claim_window is None


def test_new_game_carries_ruleset_and_seeds() -> None:
    ruleset = RuleSet(min_faan=1)
    state = new_game(ruleset, game_seed=42)
    assert state.ruleset is ruleset
    assert state.game_seed == 42
    assert state.hand_seed == derive_hand_seed(42, 1)


# --- determinism --------------------------------------------------------------------------


def test_new_game_deterministic_same_seed() -> None:
    state1 = new_game(DEFAULT_RULESET, game_seed=123)
    state2 = new_game(DEFAULT_RULESET, game_seed=123)
    assert state1 == state2


def test_new_game_different_seeds_differ() -> None:
    state1 = new_game(DEFAULT_RULESET, game_seed=1)
    state2 = new_game(DEFAULT_RULESET, game_seed=2)
    assert state1 != state2


@given(st.integers(min_value=0, max_value=50_000))
def test_property_new_game_deterministic(game_seed: int) -> None:
    assert new_game(DEFAULT_RULESET, game_seed) == new_game(DEFAULT_RULESET, game_seed)


def test_derive_hand_seed_deterministic() -> None:
    assert derive_hand_seed(1, 1) == derive_hand_seed(1, 1)


def test_derive_hand_seed_differs_by_hand_no() -> None:
    assert derive_hand_seed(1, 1) != derive_hand_seed(1, 2)


def test_derive_hand_seed_differs_by_game_seed() -> None:
    assert derive_hand_seed(1, 1) != derive_hand_seed(2, 1)


# --- immutability ---------------------------------------------------------------------------


def test_game_state_is_frozen() -> None:
    state = new_game(DEFAULT_RULESET, game_seed=1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.turn = 2  # type: ignore[misc]


def test_seat_state_is_frozen() -> None:
    state = new_game(DEFAULT_RULESET, game_seed=1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.seats[0].score = 100  # type: ignore[misc]


def test_game_state_seats_tuple_rejects_item_assignment() -> None:
    state = new_game(DEFAULT_RULESET, game_seed=1)
    with pytest.raises(TypeError):
        state.seats[0] = state.seats[1]  # type: ignore[index]


def test_claim_window_is_frozen() -> None:
    window = ClaimWindow(
        window_id=0,
        kind=ClaimKind.DISCARD,
        source_seat=0,
        tile=TileId(0),
        offers=(ClaimOffer(seat=1, can_win=False, melds=(_pung(),)),),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        window.window_id = 1  # type: ignore[misc]


# --- GameState / SeatState structural validation --------------------------------------------


def test_game_state_rejects_out_of_range_turn() -> None:
    base = new_game(DEFAULT_RULESET, game_seed=1)
    with pytest.raises(ValueError):
        dataclasses.replace(base, turn=4)


def test_game_state_rejects_out_of_range_dealer() -> None:
    base = new_game(DEFAULT_RULESET, game_seed=1)
    with pytest.raises(ValueError):
        dataclasses.replace(base, dealer=-1)


def test_game_state_rejects_hand_no_below_1() -> None:
    base = new_game(DEFAULT_RULESET, game_seed=1)
    with pytest.raises(ValueError):
        dataclasses.replace(base, hand_no=0)


def test_game_state_await_claims_requires_claim_window() -> None:
    base = new_game(DEFAULT_RULESET, game_seed=1)
    with pytest.raises(ValueError):
        dataclasses.replace(base, phase=Phase.AWAIT_CLAIMS)


def test_game_state_non_claims_phase_rejects_claim_window() -> None:
    base = new_game(DEFAULT_RULESET, game_seed=1)
    window = ClaimWindow(
        window_id=0,
        kind=ClaimKind.DISCARD,
        source_seat=0,
        tile=TileId(0),
        offers=(ClaimOffer(seat=1, can_win=True),),
    )
    with pytest.raises(ValueError):
        dataclasses.replace(base, claim_window=window)


def test_game_state_await_kong_rob_requires_kong_rob_window() -> None:
    base = new_game(DEFAULT_RULESET, game_seed=1)
    window = ClaimWindow(
        window_id=0,
        kind=ClaimKind.DISCARD,
        source_seat=0,
        tile=TileId(0),
        offers=(ClaimOffer(seat=1, can_win=True),),
    )
    with pytest.raises(ValueError):
        dataclasses.replace(base, phase=Phase.AWAIT_KONG_ROB, claim_window=window)


def test_game_state_accepts_matching_await_claims_window() -> None:
    base = new_game(DEFAULT_RULESET, game_seed=1)
    window = ClaimWindow(
        window_id=0,
        kind=ClaimKind.DISCARD,
        source_seat=0,
        tile=TileId(0),
        offers=(ClaimOffer(seat=1, can_win=True),),
    )
    state = dataclasses.replace(base, phase=Phase.AWAIT_CLAIMS, claim_window=window)
    assert state.claim_window is window


def _pung() -> Meld:
    return Meld(MeldKind.PUNG, (TileId(0), TileId(1), TileId(2)))


def test_claim_offer_requires_win_or_meld() -> None:
    with pytest.raises(ValueError):
        ClaimOffer(seat=0, can_win=False, melds=())


def test_claim_offer_rejects_bad_seat() -> None:
    with pytest.raises(ValueError):
        ClaimOffer(seat=4, can_win=True)


def test_claim_window_rejects_empty_offers() -> None:
    with pytest.raises(ValueError):
        ClaimWindow(window_id=0, kind=ClaimKind.DISCARD, source_seat=0, tile=TileId(0), offers=())


def test_claim_window_rejects_duplicate_offer_seats() -> None:
    with pytest.raises(ValueError):
        ClaimWindow(
            window_id=0,
            kind=ClaimKind.DISCARD,
            source_seat=0,
            tile=TileId(0),
            offers=(ClaimOffer(seat=1, can_win=True), ClaimOffer(seat=1, can_win=True)),
        )


def test_claim_window_rejects_offer_from_source_seat() -> None:
    with pytest.raises(ValueError):
        ClaimWindow(
            window_id=0,
            kind=ClaimKind.DISCARD,
            source_seat=0,
            tile=TileId(0),
            offers=(ClaimOffer(seat=0, can_win=True),),
        )


def test_seat_state_defaults() -> None:
    seat = SeatState(concealed=(TileId(0), TileId(1)))
    assert seat.melds == ()
    assert seat.discards == ()
    assert seat.flowers == ()
    assert seat.score == 0
