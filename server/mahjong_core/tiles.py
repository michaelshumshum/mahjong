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

COPIES_PER_TYPE = 4
N_TILE_TYPES = 34
N_SUITED_TYPES = 27  # types 0-26 are suited (m/p/s); 27-33 are winds/dragons
RANKS_PER_SUIT = 9
_TILE_ID_COUNT = COPIES_PER_TYPE * N_TILE_TYPES  # 136, §1 "Playable subtotal"
N_FLOWERS = 8
TOTAL_PHYSICAL_TILES = _TILE_ID_COUNT + N_FLOWERS  # 144, §1 "Total"

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

WIND_TYPES = frozenset(
    {TileType.WIND_EAST, TileType.WIND_SOUTH, TileType.WIND_WEST, TileType.WIND_NORTH}
)
DRAGON_TYPES = frozenset({TileType.DRAGON_RED, TileType.DRAGON_GREEN, TileType.DRAGON_WHITE})
ORPHAN_TYPES = frozenset(
    {
        TileType.MAN_1,
        TileType.MAN_9,
        TileType.PIN_1,
        TileType.PIN_9,
        TileType.SOU_1,
        TileType.SOU_9,
        *WIND_TYPES,
        *DRAGON_TYPES,
    }
)
"""Terminals and honors: the 13 types of Thirteen Orphans."""
ORPHAN_INDICES = tuple(sorted(int(t) for t in ORPHAN_TYPES))

_TILE_ID_TYPES: tuple[TileType, ...] = tuple(
    TileType(i // COPIES_PER_TYPE) for i in range(_TILE_ID_COUNT)
)


def tile_code(tile: Tile) -> str:
    """Render a `TileType`/`Flower` to its wire string, matching
    web/src/lib/table/tile-code.ts's `TileCode` scheme: '1m'..'9s', 'z1'..'z7', 'f1'..'f8'."""
    if isinstance(tile, Flower):
        return f"f{int(tile) + 1}"
    value = int(tile)
    if value < N_SUITED_TYPES:
        suit = _SUITS[value // RANKS_PER_SUIT]
        rank = value % RANKS_PER_SUIT + 1
        return f"{rank}{suit}"
    return f"z{value - 26}"


def parse_tile(code: str) -> Tile:
    """Parse a wire string into a `TileType` or `Flower`. Raises `ValueError` on anything
    that isn't exactly one of the 42 valid codes."""
    if len(code) == 2 and code[0] in "123456789" and code[1] in _SUITS:
        rank = int(code[0]) - 1
        return TileType(_SUITS.index(code[1]) * RANKS_PER_SUIT + rank)
    if len(code) == 2 and code[0] == "z" and code[1] in "1234567":
        return TileType(26 + int(code[1]))
    if len(code) == 2 and code[0] == "f" and code[1] in "12345678":
        return Flower(int(code[1]) - 1)
    raise ValueError(f"invalid tile code: {code!r}")


def parse_tiles(spec: str) -> list[Tile]:
    """Parse compact notation, runs of ranks closed by a suit letter: `"123m11z5f"` is
    1m 2m 3m z1 z1 f5. Each tile goes through `parse_tile`, so `z`/`f` take the same ranks
    their codes do. Raises `ValueError` on anything else."""
    tiles: list[Tile] = []
    ranks = ""
    for ch in spec:
        if ch.isdigit():
            ranks += ch
            continue
        if not ranks:
            raise ValueError(f"suit {ch!r} with no ranks in {spec!r}")
        for rank in ranks:
            tiles.append(parse_tile(rank + ch if ch in _SUITS else ch + rank))
        ranks = ""
    if ranks:
        raise ValueError(f"ranks {ranks!r} with no suit in {spec!r}")
    return tiles


def assign_tile_ids(groups: Iterable[Iterable[TileType]]) -> list[list[TileId]]:
    """Give every tile a distinct physical `TileId`, copy numbers shared across all `groups`
    (one per seat, wall, ...). Raises `ValueError` on a fifth copy."""
    used = [0] * N_TILE_TYPES
    out: list[list[TileId]] = []
    for group in groups:
        ids: list[TileId] = []
        for tile in group:
            n = used[tile]
            if n >= COPIES_PER_TYPE:
                raise ValueError(f"more than {COPIES_PER_TYPE} copies of {tile_code(tile)}")
            used[tile] = n + 1
            ids.append(tile_ids_for_type(tile)[n])
        out.append(ids)
    return out


def tile_id_type(tile_id: TileId) -> TileType:
    """The `TileType` a physical `TileId` belongs to, under the canonical pre-shuffle
    numbering (4 consecutive ids per type, in `TileType` order)."""
    if not 0 <= tile_id < _TILE_ID_COUNT:
        raise ValueError(f"tile_id out of range 0..{_TILE_ID_COUNT - 1}: {tile_id}")
    return _TILE_ID_TYPES[tile_id]


def tile_ids_for_type(tile_type: TileType) -> tuple[TileId, ...]:
    """The 4 canonical `TileId`s for a given `TileType`."""
    base = int(tile_type) * COPIES_PER_TYPE
    return tuple(TileId(i) for i in range(base, base + COPIES_PER_TYPE))


def all_tile_ids() -> tuple[TileId, ...]:
    """All 136 playable `TileId`s in a physical set (excludes flowers/seasons)."""
    return tuple(TileId(i) for i in range(_TILE_ID_COUNT))


def all_flowers() -> tuple[Flower, ...]:
    """All 8 flowers/seasons in a physical set (one copy each)."""
    return tuple(Flower)


def new_count_array() -> list[int]:
    """A zeroed 34-array, indexed by `TileType` value."""
    return [0] * N_TILE_TYPES


def count_array_from_types(tile_types: Iterable[TileType]) -> list[int]:
    """Build a 34-array counting occurrences of each `TileType`."""
    counts = new_count_array()
    for tile_type in tile_types:
        counts[int(tile_type)] += 1
    return counts
