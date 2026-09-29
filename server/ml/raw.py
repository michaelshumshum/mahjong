"""Raw, entitlement-safe values read off a `SeatView` for the danger model (docs/06-ml.md §6.2).

Pure Python, no numpy -- shared by dataset generation (`ml/generate_dataset.py`) and the encoder
(`ml/encode.py`) so both see the same table a human at the seat sees. `SeatView.melds` holds the
full `Meld` for every seat (only the wire path redacts it), so anything reading it directly would
learn the tile type of another seat's concealed kong.
"""

from __future__ import annotations

from app.views import SeatView
from mahjong_core.melds import Meld
from mahjong_core.tiles import new_count_array, tile_id_type

__all__ = ["concealed_kong_counts", "visible_meld_counts34"]


def visible_meld_counts34(view: SeatView, seat: int) -> list[int]:
    """34-count array of `seat`'s melds as `view.seat` may see them: another seat's concealed
    kong is skipped (its tile type is hidden), the observer's own is kept. A kong contributes 3
    tiles, matching `mahjong_core.shanten`'s convention."""
    counts = new_count_array()
    for meld in view.melds[seat]:
        if meld.concealed and seat != view.seat:
            continue
        _add_meld(counts, meld)
    return counts


def concealed_kong_counts(view: SeatView) -> list[int]:
    """Concealed kongs per absolute seat -- face-down but public, so the count is visible."""
    return [sum(1 for meld in seat_melds if meld.concealed) for seat_melds in view.melds]


def _add_meld(counts: list[int], meld: Meld) -> None:
    tiles = meld.tiles[:3] if meld.is_kong else meld.tiles
    for t in tiles:
        counts[int(tile_id_type(t))] += 1
