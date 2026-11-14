"""Hand-built tile ids, melds and filler hands for scoring/bot/table tests."""

from mahjong_core.melds import Meld, MeldKind
from mahjong_core.tiles import TileId, TileType, tile_ids_for_type


def tile_ids(*types: TileType) -> tuple[TileId, ...]:
    """One tile id per `TileType` given, in order -- a repeated type draws the next physical copy
    (up to 4)."""
    seen: dict[TileType, int] = {}
    ids = []
    for t in types:
        n = seen.get(t, 0)
        ids.append(tile_ids_for_type(t)[n])
        seen[t] = n + 1
    return tuple(ids)


def pung(tile_type: TileType, from_seat: int | None = None) -> Meld:
    return Meld(MeldKind.PUNG, tile_ids_for_type(tile_type)[:3], from_seat=from_seat)


def concealed_kong(tile_type: TileType) -> Meld:
    return Meld(MeldKind.CONCEALED_KONG, tile_ids_for_type(tile_type))


# sou evens + honours: never duplicates the man or pin tile a test discards or claims
JUNK_HAND = tile_ids(
    TileType.SOU_2,
    TileType.SOU_4,
    TileType.SOU_6,
    TileType.SOU_8,
    TileType.SOU_2,
    TileType.SOU_4,
    TileType.SOU_6,
    TileType.WIND_SOUTH,
    TileType.WIND_WEST,
    TileType.WIND_NORTH,
    TileType.DRAGON_RED,
    TileType.DRAGON_GREEN,
    TileType.DRAGON_WHITE,
)


def _three_quads_and_one(a: TileType, b: TileType, c: TileType, d: TileType) -> tuple[TileId, ...]:
    return tile_ids(a, a, a, a, b, b, b, b, c, c, c, c, d)


# per seat, disjoint by tile type and from `UNCONTESTED_DISCARD`: seat 0's discard of it is
# never claimable
UNCONTESTED_JUNK = (
    _three_quads_and_one(TileType.PIN_2, TileType.PIN_4, TileType.PIN_6, TileType.PIN_8),
    _three_quads_and_one(TileType.SOU_1, TileType.SOU_3, TileType.SOU_5, TileType.SOU_7),
    _three_quads_and_one(
        TileType.WIND_SOUTH, TileType.WIND_WEST, TileType.WIND_NORTH, TileType.DRAGON_RED
    ),
    _three_quads_and_one(
        TileType.DRAGON_GREEN, TileType.DRAGON_WHITE, TileType.MAN_2, TileType.MAN_4
    ),
)
UNCONTESTED_DISCARD = tile_ids_for_type(TileType.WIND_EAST)[0]
