"""Hand-built tile ids and melds for scoring/bot tests."""

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
