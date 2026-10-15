"""`SeatView` -> `mahjong_core.shanten`'s 34-count-array contract (docs/bots.md §3), shared by
every heuristic bot tier. Lives in `bots/`, not `mahjong_core/`, since it reads `SeatView`/
`ClaimOffer` -- `app/`-layer types `mahjong_core` must never depend on.

`own_hand34`/`seen34` only read tiles this seat is entitled to: own concealed hand, every seat's
melds (concealed kongs included -- they're played face-up), public discard pools. `seen34` is the
one exception: when `view.hands` is populated (the `"ORACLE"` tier's omniscient view,
docs/bots.md §9) it also counts every opponent's real concealed tiles -- see its own docstring.
"""

from __future__ import annotations

from app.views import SeatView
from mahjong_core.melds import Meld
from mahjong_core.state import Phase
from mahjong_core.tiles import N_SUITED_TYPES, RANKS_PER_SUIT, new_count_array, tile_id_type

__all__ = [
    "add_meld",
    "claimed_tile_type",
    "is_closed",
    "is_terminal_or_honor",
    "own_hand34",
    "seen34",
]


def add_meld(counts: list[int], meld: Meld) -> None:
    """Adds one meld to a 34-count array; a kong contributes 3, per mahjong_core.shanten's
    contract."""
    tiles = meld.tiles[:3] if meld.is_kong else meld.tiles
    for t in tiles:
        counts[int(tile_id_type(t))] += 1


def claimed_tile_type(view: SeatView) -> int | None:
    """Tile type up for claim, without `state.claim_window.tile` (a bot never sees `GameState`):
    `view.turn` still names the discarder during `AWAIT_CLAIMS`, so their last discard is the
    claimed tile. `None` outside a discard claim window (kong-rob is win-only) or on a
    defensively-empty pool."""
    if view.phase != Phase.AWAIT_CLAIMS:
        return None
    pool = view.discard_pools[view.turn]
    if not pool:
        return None
    return int(tile_id_type(pool[-1]))


def own_hand34(view: SeatView) -> list[int]:
    """This seat's full hand as a 34-array: concealed tiles plus own melds (including own
    concealed kongs, fully visible to yourself unlike everyone else's)."""
    if view.seat is None:
        raise ValueError("own_hand34 needs a seated view, not a spectator's")
    counts = new_count_array()
    for t in view.own_hand:
        counts[int(tile_id_type(t))] += 1
    for meld in view.melds[view.seat]:
        add_meld(counts, meld)
    return counts


def is_closed(view: SeatView) -> bool:
    """Whether this seat holds zero melds of any kind, including own concealed kongs -- matches
    `hand_is_winning_shape`'s `not seat.melds` rule for Seven Pairs/Thirteen Orphans eligibility."""
    if view.seat is None:
        raise ValueError("is_closed needs a seated view, not a spectator's")
    return not view.melds[view.seat]


def seen34(view: SeatView) -> list[int]:
    """Every tile type publicly visible plus this seat's own concealed hand (docs/bots.md §3's
    ukeire contract) -- never the wall.

    Hands-aware when `view.hands` is populated (the `"ORACLE"` tier's omniscient view,
    docs/bots.md §9): every opponent's real concealed tiles count as seen too, since they're
    genuinely known rather than merely inferred -- otherwise `ukeire`'s live-tile count
    (`4 - seen34[t]`) would treat tiles actually sitting in an opponent's hand as still drawable
    from the wall. `view.hands is None` (every other tier) is untouched, byte-for-byte.
    """
    if view.seat is None:
        raise ValueError("seen34 needs a seated view, not a spectator's")
    counts = own_hand34(view)
    for s, seat_melds in enumerate(view.melds):
        if s == view.seat:
            continue
        for meld in seat_melds:
            add_meld(counts, meld)
    if view.hands is not None:
        for s, hand in enumerate(view.hands):
            if s == view.seat:
                continue
            for t in hand:
                counts[int(tile_id_type(t))] += 1
    for pool in view.discard_pools:
        for t in pool:
            counts[int(tile_id_type(t))] += 1
    return counts


def is_terminal_or_honor(tile_type: int) -> bool:
    """1/9 of a suit, or any wind/dragon -- T1's discard tiebreak prefers these."""
    if tile_type >= N_SUITED_TYPES:
        return True
    rank = tile_type % RANKS_PER_SUIT
    return rank == 0 or rank == 8
