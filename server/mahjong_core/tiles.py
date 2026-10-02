"""Tile identity, the 34-array index scheme, and string parsing.

No shuffling, no wall, no melds here — just the canonical, pre-shuffle 0..135 <-> TileType
mapping that wall.py's shuffle permutes.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import IntEnum
from typing import NewType

TileId = NewType("TileId", int)
"""Opaque physical-tile identifier, 0..135. Never assume it encodes wall position."""

_COPIES_PER_TYPE = 4
_TILE_TYPE_COUNT = 34
_TILE_ID_COUNT = _COPIES_PER_TYPE * _TILE_TYPE_COUNT  # 136, §1 "Playable subtotal"
_FLOWER_COUNT = 8
TOTAL_PHYSICAL_TILES = _TILE_ID_COUNT + _FLOWER_COUNT  # 144, §1 "Total"

_SUITS = "mps"


class TileType(IntEnum):
    """The 34 playable tile types. Value doubles as the 34-array slot (§1)."""

    MAN_1 = 0
    MAN_2 = 1
    MAN_3 = 2
    MAN_4 = 3
    MAN_5 = 4
    MAN_6 = 5
    MAN_7 = 6
    MAN_8 = 7
    MAN_9 = 8
    PIN_1 = 9
    PIN_2 = 10
    PIN_3 = 11
    PIN_4 = 12
    PIN_5 = 13
    PIN_6 = 14
    PIN_7 = 15
    PIN_8 = 16
    PIN_9 = 17
    SOU_1 = 18
    SOU_2 = 19
    SOU_3 = 20
    SOU_4 = 21
    SOU_5 = 22
    SOU_6 = 23
    SOU_7 = 24
    SOU_8 = 25
    SOU_9 = 26
    WIND_EAST = 27
    WIND_SOUTH = 28
    WIND_WEST = 29
    WIND_NORTH = 30
    DRAGON_RED = 31
    DRAGON_GREEN = 32
    DRAGON_WHITE = 33


class Flower(IntEnum):
    """Flowers f1-f4 and seasons f5-f8, one copy each (§1). Don't form melds or sequences,
    so they sit outside the 34-array/TileType scheme entirely."""

    FLOWER_1 = 0
    FLOWER_2 = 1
    FLOWER_3 = 2
    FLOWER_4 = 3
    SEASON_1 = 4
    SEASON_2 = 5
    SEASON_3 = 6
    SEASON_4 = 7


Tile = TileType | Flower

_TILE_ID_TYPES: tuple[TileType, ...] = tuple(
    TileType(i // _COPIES_PER_TYPE) for i in range(_TILE_ID_COUNT)
)


def tile_code(tile: Tile) -> str:
    """Render a `TileType`/`Flower` to its wire string, matching
    web/src/lib/table/tile-code.ts's `TileCode` scheme: '1m'..'9s', 'z1'..'z7', 'f1'..'f8'."""
    if isinstance(tile, Flower):
        return f"f{int(tile) + 1}"
    value = int(tile)
    if value < 27:
        suit = _SUITS[value // 9]
        rank = value % 9 + 1
        return f"{rank}{suit}"
    return f"z{value - 26}"


def parse_tile(code: str) -> Tile:
    """Parse a wire string into a `TileType` or `Flower`. Raises `ValueError` on anything
    that isn't exactly one of the 42 valid codes."""
    if len(code) == 2 and code[0] in "123456789" and code[1] in _SUITS:
        rank = int(code[0]) - 1
        return TileType(_SUITS.index(code[1]) * 9 + rank)
    if len(code) == 2 and code[0] == "z" and code[1] in "1234567":
        return TileType(26 + int(code[1]))
    if len(code) == 2 and code[0] == "f" and code[1] in "12345678":
        return Flower(int(code[1]) - 1)
    raise ValueError(f"invalid tile code: {code!r}")


def tile_id_type(tile_id: TileId) -> TileType:
    """The `TileType` a physical `TileId` belongs to, under the canonical pre-shuffle
    numbering (4 consecutive ids per type, in `TileType` order)."""
    if not 0 <= tile_id < _TILE_ID_COUNT:
        raise ValueError(f"tile_id out of range 0..{_TILE_ID_COUNT - 1}: {tile_id}")
    return _TILE_ID_TYPES[tile_id]


def tile_ids_for_type(tile_type: TileType) -> tuple[TileId, ...]:
    """The 4 canonical `TileId`s for a given `TileType`."""
    base = int(tile_type) * _COPIES_PER_TYPE
    return tuple(TileId(i) for i in range(base, base + _COPIES_PER_TYPE))


def all_tile_ids() -> tuple[TileId, ...]:
    """All 136 playable `TileId`s in a physical set (excludes flowers/seasons)."""
    return tuple(TileId(i) for i in range(_TILE_ID_COUNT))


def all_flowers() -> tuple[Flower, ...]:
    """All 8 flowers/seasons in a physical set (one copy each)."""
    return tuple(Flower)


def new_count_array() -> list[int]:
    """A zeroed 34-array, indexed by `TileType` value."""
    return [0] * _TILE_TYPE_COUNT


def count_array_from_types(tile_types: Iterable[TileType]) -> list[int]:
    """Build a 34-array counting occurrences of each `TileType`."""
    counts = new_count_array()
    for tile_type in tile_types:
        counts[int(tile_type)] += 1
    return counts
