"""Raw, entitlement-safe values read off a `SeatView` for the danger model (docs/ml.md §5).

Pure Python, no numpy -- shared by dataset generation (`ml/generate_dataset.py`) and the encoder
(`ml/encode.py`) so both see the same table a human at the seat sees. Every seat's melds,
concealed kongs included, are public (docs/rules.md, docs/protocol.md §3).
"""

from __future__ import annotations

from app.views import SeatView
from bots.features import own_hand34
from bots.labels import discard_counts34
from mahjong_core.melds import Meld
from mahjong_core.scoring.patterns import seat_wind_for
from mahjong_core.tiles import new_count_array, tile_id_type

__all__ = ["concealed_kong_counts", "raw_row", "relative_seats", "visible_meld_counts34"]


def relative_seats(seat: int) -> tuple[int, int, int, int]:
    """(self, next, across, previous) as absolute seat indices."""
    return (seat, (seat + 1) % 4, (seat + 2) % 4, (seat + 3) % 4)


def visible_meld_counts34(view: SeatView, seat: int) -> list[int]:
    """34-count array of `seat`'s melds, concealed kongs included (they're played face-up). A
    kong contributes 3 tiles, matching `mahjong_core.shanten`'s convention."""
    counts = new_count_array()
    for meld in view.melds[seat]:
        _add_meld(counts, meld)
    return counts


def concealed_kong_counts(view: SeatView) -> list[int]:
    """Concealed kongs per absolute seat -- still scored as concealed, so kept apart."""
    return [sum(1 for meld in seat_melds if meld.concealed) for seat_melds in view.melds]


def raw_row(view: SeatView) -> dict[str, object]:
    """Every model input a seated view supports, in relative-seat order (self first): per-tile
    counts, per-seat discard order (tile types, oldest first), concealed-kong and flower counts,
    and table context."""
    if view.seat is None:
        raise ValueError("raw_row needs a seated view, not a spectator's")
    order = relative_seats(view.seat)
    kongs = concealed_kong_counts(view)
    return {
        "hand_counts": own_hand34(view),
        "meld_counts": [visible_meld_counts34(view, s) for s in order],
        "discard_counts": [discard_counts34(view.discard_pools[s]) for s in order],
        "discard_seq": [[int(tile_id_type(t)) for t in view.discard_pools[s]] for s in order],
        "concealed_counts": [view.concealed_counts[s] for s in order],
        "concealed_kongs": [kongs[s] for s in order],
        "flowers": [len(view.flowers[s]) for s in order],
        "dealer_idx": order.index(view.dealer),
        "prevailing_wind": int(view.prevailing),
        "seat_wind": int(seat_wind_for(view.seat, view.dealer)),
        "wall_remaining": view.wall_remaining,
    }


def _add_meld(counts: list[int], meld: Meld) -> None:
    tiles = meld.tiles[:3] if meld.is_kong else meld.tiles
    for t in tiles:
        counts[int(tile_id_type(t))] += 1
