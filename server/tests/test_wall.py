import hashlib

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mahjong_core.config import DEFAULT_RULESET, RuleSet
from mahjong_core.tiles import TOTAL_PHYSICAL_TILES, Flower, all_tile_ids
from mahjong_core.wall import (
    Wall,
    deal_hands,
    draw_back,
    draw_front,
    new_wall,
    replace_flowers,
)


def _hand_seed(game_seed: int, hand_no: int) -> bytes:
    return hashlib.sha256(f"{game_seed}:{hand_no}".encode()).digest()


def _total_tiles(
    hands: tuple[tuple[object, ...], ...],
    wall: Wall,
    aside: tuple[tuple[object, ...], ...] = ((), (), (), ()),
) -> int:
    return sum(len(h) for h in hands) + len(wall.tiles) + sum(len(a) for a in aside)


def _tag(tile: int) -> tuple[str, int]:
    """Type-safe identity for a `WallTile`: `Flower` is an `IntEnum`, so `Flower.FLOWER_1 ==
    TileId(0)` is true under plain `==`/`in`/`set()` — tag by type before deduplicating."""
    return (type(tile).__name__, int(tile))


# --- shuffle -----------------------------------------------------------------


def test_new_wall_has_144_tiles_by_default() -> None:
    _, wall = new_wall(_hand_seed(1, 1), DEFAULT_RULESET)
    assert len(wall.tiles) == TOTAL_PHYSICAL_TILES == 144


def test_new_wall_has_136_tiles_when_flowers_disabled() -> None:
    ruleset = RuleSet(flowers_enabled=False)
    _, wall = new_wall(_hand_seed(1, 1), ruleset)
    assert len(wall.tiles) == 136
    assert not any(isinstance(t, Flower) for t in wall.tiles)


def test_new_wall_contains_every_tile_id_and_flower_exactly_once() -> None:
    _, wall = new_wall(_hand_seed(7, 3), DEFAULT_RULESET)
    assert sorted(wall.tiles, key=lambda t: (isinstance(t, Flower), int(t))) == sorted(
        [*all_tile_ids(), *Flower], key=lambda t: (isinstance(t, Flower), int(t))
    )


def test_deterministic_same_seed_same_dice_and_wall() -> None:
    seed = _hand_seed(42, 5)
    dice1, wall1 = new_wall(seed, DEFAULT_RULESET)
    dice2, wall2 = new_wall(seed, DEFAULT_RULESET)
    assert dice1 == dice2
    assert wall1 == wall2


def test_different_hand_no_gives_different_wall() -> None:
    _, wall_a = new_wall(_hand_seed(42, 1), DEFAULT_RULESET)
    _, wall_b = new_wall(_hand_seed(42, 2), DEFAULT_RULESET)
    assert wall_a != wall_b


@given(st.integers(min_value=1, max_value=6), st.integers(min_value=1, max_value=6))
def test_dice_always_in_range(game_seed: int, hand_no: int) -> None:
    dice, _ = new_wall(_hand_seed(game_seed, hand_no), DEFAULT_RULESET)
    assert 1 <= dice[0] <= 6
    assert 1 <= dice[1] <= 6


@given(st.integers(min_value=0, max_value=10_000))
def test_property_determinism_and_conservation(hand_no: int) -> None:
    seed = _hand_seed(999, hand_no)
    dice1, wall1 = new_wall(seed, DEFAULT_RULESET)
    dice2, wall2 = new_wall(seed, DEFAULT_RULESET)
    assert dice1 == dice2
    assert wall1 == wall2
    assert len(wall1.tiles) == TOTAL_PHYSICAL_TILES
    assert len({_tag(t) for t in wall1.tiles}) == TOTAL_PHYSICAL_TILES  # every tile unique


@given(st.integers(min_value=0, max_value=100_000))
def test_property_different_seeds_differ(hand_no: int) -> None:
    seed_a = _hand_seed(1, hand_no)
    seed_b = _hand_seed(2, hand_no)
    _, wall_a = new_wall(seed_a, DEFAULT_RULESET)
    _, wall_b = new_wall(seed_b, DEFAULT_RULESET)
    assert wall_a != wall_b


# --- draw front/back -----------------------------------------------------------


def test_draw_front_takes_first_tile() -> None:
    _, wall = new_wall(_hand_seed(1, 1), DEFAULT_RULESET)
    first = wall.tiles[0]
    drawn, rest = draw_front(wall)
    assert drawn == first
    assert rest.tiles == wall.tiles[1:]


def test_draw_back_takes_last_tile() -> None:
    _, wall = new_wall(_hand_seed(1, 1), DEFAULT_RULESET)
    last = wall.tiles[-1]
    drawn, rest = draw_back(wall)
    assert drawn == last
    assert rest.tiles == wall.tiles[:-1]


def test_draw_front_conserves_count() -> None:
    _, wall = new_wall(_hand_seed(1, 1), DEFAULT_RULESET)
    _, rest = draw_front(wall)
    assert len(rest.tiles) == len(wall.tiles) - 1


def test_draw_back_conserves_count() -> None:
    _, wall = new_wall(_hand_seed(1, 1), DEFAULT_RULESET)
    _, rest = draw_back(wall)
    assert len(rest.tiles) == len(wall.tiles) - 1


def test_draw_front_empty_wall_raises() -> None:
    with pytest.raises(ValueError):
        draw_front(Wall(()))


def test_draw_back_empty_wall_raises() -> None:
    with pytest.raises(ValueError):
        draw_back(Wall(()))


# --- dealing ---------------------------------------------------------------------


def test_deal_hands_sizes() -> None:
    _, wall = new_wall(_hand_seed(1, 1), DEFAULT_RULESET)
    hands, _ = deal_hands(wall, dealer_seat=0)
    sizes = [len(h) for h in hands]
    assert sizes.count(13) == 3
    assert sizes.count(14) == 1
    assert sizes[0] == 14  # dealer_seat=0 is East, gets the extra tile


def test_deal_hands_dealer_seat_gets_extra_tile() -> None:
    _, wall = new_wall(_hand_seed(1, 1), DEFAULT_RULESET)
    hands, _ = deal_hands(wall, dealer_seat=2)
    assert len(hands[2]) == 14
    for seat in (0, 1, 3):
        assert len(hands[seat]) == 13


def test_deal_hands_conserves_tiles() -> None:
    _, wall = new_wall(_hand_seed(3, 9), DEFAULT_RULESET)
    hands, remaining = deal_hands(wall, dealer_seat=1)
    assert _total_tiles(hands, remaining) == TOTAL_PHYSICAL_TILES


def test_deal_hands_invalid_dealer_seat_raises() -> None:
    _, wall = new_wall(_hand_seed(1, 1), DEFAULT_RULESET)
    with pytest.raises(ValueError):
        deal_hands(wall, dealer_seat=4)


def test_deal_hands_deterministic() -> None:
    _, wall = new_wall(_hand_seed(5, 5), DEFAULT_RULESET)
    hands1, remaining1 = deal_hands(wall, dealer_seat=0)
    hands2, remaining2 = deal_hands(wall, dealer_seat=0)
    assert hands1 == hands2
    assert remaining1 == remaining2


@given(st.integers(min_value=0, max_value=5_000), st.integers(min_value=0, max_value=3))
def test_property_deal_conserves_tiles(hand_no: int, dealer_seat: int) -> None:
    _, wall = new_wall(_hand_seed(123, hand_no), DEFAULT_RULESET)
    hands, remaining = deal_hands(wall, dealer_seat)
    assert _total_tiles(hands, remaining) == TOTAL_PHYSICAL_TILES
    all_tiles = {_tag(t) for seat in hands for t in seat} | {_tag(t) for t in remaining.tiles}
    assert len(all_tiles) == TOTAL_PHYSICAL_TILES


# --- flower replacement -----------------------------------------------------------


def test_replace_flowers_no_flowers_in_hand_is_noop() -> None:
    from mahjong_core.tiles import TileId

    hands = (
        tuple(TileId(i) for i in range(13)),
        tuple(TileId(i) for i in range(13, 26)),
        tuple(TileId(i) for i in range(26, 39)),
        tuple(TileId(i) for i in range(39, 53)),
    )
    wall = Wall(tuple(TileId(i) for i in range(53, 136)))
    new_hands, new_wall_, aside = replace_flowers(hands, wall, dealer_seat=0)
    assert new_hands == hands
    assert new_wall_ == wall
    assert aside == ((), (), (), ())


def test_replace_flowers_single_flower_replaced_from_back() -> None:
    from mahjong_core.tiles import TileId

    back_tile = TileId(999)
    hands = (
        (Flower.FLOWER_1,) + tuple(TileId(i) for i in range(12)),
        tuple(TileId(i) for i in range(12, 25)),
        tuple(TileId(i) for i in range(25, 38)),
        tuple(TileId(i) for i in range(38, 52)),
    )
    wall = Wall(tuple(TileId(i) for i in range(52, 100)) + (back_tile,))
    new_hands, new_wall_, aside = replace_flowers(hands, wall, dealer_seat=0)
    assert aside[0] == (Flower.FLOWER_1,)
    assert back_tile in new_hands[0]
    assert not any(isinstance(t, Flower) for t in new_hands[0])
    assert len(new_hands[0]) == 13
    assert back_tile not in new_wall_.tiles


def test_replace_flowers_cascade_terminates_and_conserves() -> None:
    from mahjong_core.tiles import TileId

    # seat 0 holds one flower; the back of the wall is itself two flowers deep, forcing a
    # chain: draw_back -> flower -> draw_back again -> flower -> draw_back again -> tile.
    hands = (
        (Flower.FLOWER_1,) + tuple(TileId(i) for i in range(12)),
        tuple(TileId(i) for i in range(12, 25)),
        tuple(TileId(i) for i in range(25, 38)),
        tuple(TileId(i) for i in range(38, 52)),
    )
    wall = Wall(
        tuple(TileId(i) for i in range(52, 129)) + (TileId(129), Flower.FLOWER_3, Flower.SEASON_1)
    )
    new_hands, new_wall_, aside = replace_flowers(hands, wall, dealer_seat=0)
    assert aside[0] == (Flower.FLOWER_1, Flower.SEASON_1, Flower.FLOWER_3)
    assert TileId(129) in new_hands[0]
    assert not any(isinstance(t, Flower) for t in new_hands[0])
    assert len(new_hands[0]) == 13
    assert _total_tiles(new_hands, new_wall_, aside) == _total_tiles(hands, wall)


def test_replace_flowers_seat_order_starts_from_dealer() -> None:
    from mahjong_core.tiles import TileId

    hands = (
        (Flower.FLOWER_1,) + tuple(TileId(i) for i in range(12)),
        (Flower.FLOWER_2,) + tuple(TileId(i) for i in range(12, 24)),
        tuple(TileId(i) for i in range(24, 37)),
        tuple(TileId(i) for i in range(37, 51)),
    )
    # back-to-front pop order: seat resolved first gets TileId(101), next gets TileId(100).
    wall = Wall(tuple(TileId(i) for i in range(51, 100)) + (TileId(100), TileId(101)))
    new_hands, _, aside = replace_flowers(hands, wall, dealer_seat=1)
    assert aside[1] == (Flower.FLOWER_2,)
    assert aside[0] == (Flower.FLOWER_1,)
    assert TileId(101) in new_hands[1]  # dealer_seat=1 resolves first, gets the last tile
    assert TileId(100) in new_hands[0]


def test_replace_flowers_invalid_dealer_seat_raises() -> None:
    hands = ((), (), (), ())
    with pytest.raises(ValueError):
        replace_flowers(hands, Wall(()), dealer_seat=-1)


@given(st.integers(min_value=0, max_value=3_000))
def test_property_full_deal_and_replacement_conserves_144(hand_no: int) -> None:
    _, wall = new_wall(_hand_seed(77, hand_no), DEFAULT_RULESET)
    hands, remaining = deal_hands(wall, dealer_seat=hand_no % 4)
    new_hands, new_remaining, aside = replace_flowers(hands, remaining, dealer_seat=hand_no % 4)
    assert _total_tiles(new_hands, new_remaining, aside) == TOTAL_PHYSICAL_TILES
    for hand in new_hands:
        assert not any(isinstance(t, Flower) for t in hand)


@given(st.integers(min_value=0, max_value=3_000))
def test_property_flower_replacement_terminates(hand_no: int) -> None:
    # regression guard: replace_flowers must always return (it can't infinite-loop even
    # in the worst case where every flower a seat draws is another flower).
    _, wall = new_wall(_hand_seed(31337, hand_no), DEFAULT_RULESET)
    hands, remaining = deal_hands(wall, dealer_seat=0)
    replace_flowers(hands, remaining, dealer_seat=0)
