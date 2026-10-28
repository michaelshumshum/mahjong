import pytest
from hypothesis import given
from hypothesis import strategies as st

from mahjong_core.tiles import (
    TOTAL_PHYSICAL_TILES,
    Flower,
    TileId,
    TileType,
    all_flowers,
    all_tile_ids,
    assign_tile_ids,
    count_array_from_types,
    new_count_array,
    parse_tile,
    parse_tiles,
    tile_code,
    tile_id_type,
    tile_ids_for_type,
)

ALL_TILE_TYPE_CODES = [
    ("1m", TileType.MAN_1),
    ("2m", TileType.MAN_2),
    ("3m", TileType.MAN_3),
    ("4m", TileType.MAN_4),
    ("5m", TileType.MAN_5),
    ("6m", TileType.MAN_6),
    ("7m", TileType.MAN_7),
    ("8m", TileType.MAN_8),
    ("9m", TileType.MAN_9),
    ("1p", TileType.PIN_1),
    ("2p", TileType.PIN_2),
    ("3p", TileType.PIN_3),
    ("4p", TileType.PIN_4),
    ("5p", TileType.PIN_5),
    ("6p", TileType.PIN_6),
    ("7p", TileType.PIN_7),
    ("8p", TileType.PIN_8),
    ("9p", TileType.PIN_9),
    ("1s", TileType.SOU_1),
    ("2s", TileType.SOU_2),
    ("3s", TileType.SOU_3),
    ("4s", TileType.SOU_4),
    ("5s", TileType.SOU_5),
    ("6s", TileType.SOU_6),
    ("7s", TileType.SOU_7),
    ("8s", TileType.SOU_8),
    ("9s", TileType.SOU_9),
    ("z1", TileType.WIND_EAST),
    ("z2", TileType.WIND_SOUTH),
    ("z3", TileType.WIND_WEST),
    ("z4", TileType.WIND_NORTH),
    ("z5", TileType.DRAGON_RED),
    ("z6", TileType.DRAGON_GREEN),
    ("z7", TileType.DRAGON_WHITE),
]

ALL_FLOWER_CODES = [
    ("f1", Flower.FLOWER_1),
    ("f2", Flower.FLOWER_2),
    ("f3", Flower.FLOWER_3),
    ("f4", Flower.FLOWER_4),
    ("f5", Flower.SEASON_1),
    ("f6", Flower.SEASON_2),
    ("f7", Flower.SEASON_3),
    ("f8", Flower.SEASON_4),
]

INVALID_CODES = [
    "",
    "0m",
    "10m",
    "1",
    "m1",
    "1x",
    "z0",
    "z8",
    "zz",
    "f0",
    "f9",
    "ff",
    "5",
    "5mm",
    " 5m",
    "5m ",
    "5M",
]


@pytest.mark.parametrize(("code", "expected"), ALL_TILE_TYPE_CODES)
def test_parse_tile_type_round_trip(code: str, expected: TileType) -> None:
    parsed = parse_tile(code)
    assert parsed == expected
    assert tile_code(parsed) == code


@pytest.mark.parametrize(("code", "expected"), ALL_FLOWER_CODES)
def test_parse_flower_round_trip(code: str, expected: Flower) -> None:
    parsed = parse_tile(code)
    assert parsed == expected
    assert tile_code(parsed) == code


def test_all_tile_types_covered_by_round_trip_table() -> None:
    assert {t for _, t in ALL_TILE_TYPE_CODES} == set(TileType)


def test_all_flowers_covered_by_round_trip_table() -> None:
    assert {f for _, f in ALL_FLOWER_CODES} == set(Flower)


@pytest.mark.parametrize("code", INVALID_CODES)
def test_parse_tile_rejects_invalid_codes(code: str) -> None:
    with pytest.raises(ValueError, match="invalid tile code"):
        parse_tile(code)


@given(st.text(alphabet="0123456789mpszfMPSZF", min_size=0, max_size=4))
def test_parse_tile_property_round_trips_or_rejects(code: str) -> None:
    try:
        parsed = parse_tile(code)
    except ValueError:
        return
    assert tile_code(parsed) == code


def test_tile_type_count_is_34() -> None:
    assert len(TileType) == 34


def test_flower_count_is_8() -> None:
    assert len(Flower) == 8


def test_tile_type_values_are_bijection_0_to_33() -> None:
    assert {int(t) for t in TileType} == set(range(34))


def test_flower_values_are_bijection_0_to_7() -> None:
    assert {int(f) for f in Flower} == set(range(8))


def test_all_tile_ids_count_is_136() -> None:
    assert len(all_tile_ids()) == 136
    assert len(set(all_tile_ids())) == 136


def test_all_flowers_count_is_8() -> None:
    assert len(all_flowers()) == 8
    assert len(set(all_flowers())) == 8


def test_total_physical_tile_count_matches_doc() -> None:
    # docs/rules.md §1: 136 playable + 8 flowers/seasons = 144.
    assert TOTAL_PHYSICAL_TILES == 144
    assert len(all_tile_ids()) + len(all_flowers()) == TOTAL_PHYSICAL_TILES


def test_tile_id_to_type_is_bijection_no_collisions() -> None:
    seen: dict[TileType, list[TileId]] = {t: [] for t in TileType}
    for tile_id in all_tile_ids():
        seen[tile_id_type(tile_id)].append(tile_id)
    for tile_type, ids in seen.items():
        assert len(ids) == 4, f"{tile_type} has {len(ids)} tile ids, expected 4"
        assert len(set(ids)) == 4


def test_tile_ids_for_type_round_trips_with_tile_id_type() -> None:
    for tile_type in TileType:
        ids = tile_ids_for_type(tile_type)
        assert len(ids) == 4
        for tile_id in ids:
            assert tile_id_type(tile_id) == tile_type


def test_tile_ids_for_type_covers_all_tile_ids_exactly_once() -> None:
    covered = [tile_id for tile_type in TileType for tile_id in tile_ids_for_type(tile_type)]
    assert sorted(covered) == sorted(all_tile_ids())


def _reference_tile_id_type(tile_id: int) -> TileType:
    if not 0 <= tile_id < 136:
        raise ValueError(f"tile_id out of range 0..135: {tile_id}")
    return TileType(tile_id // 4)


@pytest.mark.parametrize("tile_id", range(-8, 144))
def test_tile_id_type_table_equals_reference(tile_id: int) -> None:
    try:
        expected = _reference_tile_id_type(tile_id)
    except ValueError:
        with pytest.raises(ValueError, match="tile_id out of range"):
            tile_id_type(TileId(tile_id))
        return
    got = tile_id_type(TileId(tile_id))
    assert got is expected
    assert type(got) is TileType


@pytest.mark.parametrize("bad_id", [-1, 136, 137, 1000])
def test_tile_id_type_rejects_out_of_range(bad_id: int) -> None:
    with pytest.raises(ValueError, match="tile_id out of range"):
        tile_id_type(TileId(bad_id))


def test_new_count_array_is_34_zeros() -> None:
    arr = new_count_array()
    assert arr == [0] * 34


def test_count_array_from_types_counts_occurrences() -> None:
    arr = count_array_from_types([TileType.MAN_1, TileType.MAN_1, TileType.DRAGON_WHITE])
    assert arr[TileType.MAN_1] == 2
    assert arr[TileType.DRAGON_WHITE] == 1
    assert sum(arr) == 3


def test_count_array_from_types_empty_is_all_zero() -> None:
    assert count_array_from_types([]) == new_count_array()


def test_parse_tiles_compact_notation() -> None:
    assert parse_tiles("12m9p5s17z28f") == [
        TileType.MAN_1,
        TileType.MAN_2,
        TileType.PIN_9,
        TileType.SOU_5,
        TileType.WIND_EAST,
        TileType.DRAGON_WHITE,
        Flower.FLOWER_2,
        Flower.SEASON_4,
    ]
    assert parse_tiles("") == []


@pytest.mark.parametrize("spec", ["12", "m", "1x", "8z", "9f", "1 m"])
def test_parse_tiles_rejects_malformed(spec: str) -> None:
    with pytest.raises(ValueError):
        parse_tiles(spec)


def test_assign_tile_ids_shares_copies_across_groups() -> None:
    a, b = assign_tile_ids([[TileType.MAN_1, TileType.MAN_1], [TileType.MAN_1]])
    assert a + b == list(tile_ids_for_type(TileType.MAN_1)[:3])
    with pytest.raises(ValueError):
        assign_tile_ids([[TileType.MAN_1] * 3, [TileType.MAN_1] * 2])
