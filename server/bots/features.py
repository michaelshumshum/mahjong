"""`SeatView` -> `mahjong_core.shanten`'s 34-count-array contract (docs/04-bots.md §3), shared by
every heuristic bot tier. Lives in `bots/`, not `mahjong_core/`, since it reads `SeatView`/
`ClaimOffer` -- `app/`-layer types `mahjong_core` must never depend on.

`own_hand34`/`seen34` only read tiles this seat is entitled to: own concealed hand, every seat's
non-concealed melds, public discard pools. Another seat's concealed kong is deliberately excluded
-- a human wouldn't see its tile type either, and `mahjong_core` never redacts, so this module is
where that boundary is drawn. `seen34` is the one exception: when `view.hands` is populated (the
`"ORACLE"` tier's omniscient view, docs/04-bots.md §10) it also counts every opponent's real
concealed tiles, including concealed kongs -- see its own docstring.
"""

from __future__ import annotations

from app.views import SeatView
from mahjong_core.melds import Meld
from mahjong_core.tiles import new_count_array, tile_id_type

__all__ = ["is_closed", "is_terminal_or_honor", "own_hand34", "seen34"]


def _add_meld(counts: list[int], meld: Meld) -> None:
    """Adds one meld to a 34-count array; a kong contributes 3, per mahjong_core.shanten's
    contract."""
    tiles = meld.tiles[:3] if meld.is_kong else meld.tiles
    for t in tiles:
        counts[int(tile_id_type(t))] += 1


def own_hand34(view: SeatView) -> list[int]:
    """This seat's full hand as a 34-array: concealed tiles plus own melds (including own
    concealed kongs, fully visible to yourself unlike everyone else's)."""
    if view.seat is None:
        raise ValueError("own_hand34 needs a seated view, not a spectator's")
    counts = new_count_array()
    for t in view.own_hand:
        counts[int(tile_id_type(t))] += 1
    for meld in view.melds[view.seat]:
        _add_meld(counts, meld)
    return counts


def is_closed(view: SeatView) -> bool:
    """Whether this seat holds zero melds of any kind, including own concealed kongs -- matches
    `hand_is_winning_shape`'s `not seat.melds` rule for Seven Pairs/Thirteen Orphans eligibility."""
    if view.seat is None:
        raise ValueError("is_closed needs a seated view, not a spectator's")
    return not view.melds[view.seat]


def seen34(view: SeatView) -> list[int]:
    """Every tile type publicly visible plus this seat's own concealed hand (docs/04-bots.md §3's
    ukeire contract) -- never the wall.

    Hands-aware when `view.hands` is populated (the `"ORACLE"` tier's omniscient view,
    docs/04-bots.md §10): every opponent's real concealed tiles count as seen too, since they're
    genuinely known rather than merely inferred -- otherwise `ukeire`'s live-tile count
    (`4 - seen34[t]`) would treat tiles actually sitting in an opponent's hand as still drawable
    from the wall. `view.hands is None` (every other tier) is untouched, byte-for-byte.

    A concealed kong is the one case that flips direction under `view.hands`: its 4 tiles are
    removed from `SeatState.concealed` the moment it's declared
    (`mahjong_core.engine._apply_self_kong`), so they are *not* already counted via
    `view.hands[opponent]` -- unlike the probabilistic branch, which must skip it because a real
    human genuinely can't see it, the omniscient view knows exactly what it is and must add it
    from `view.melds` instead, or those tiles would silently vanish from the count entirely.
    """
    if view.seat is None:
        raise ValueError("seen34 needs a seated view, not a spectator's")
    counts = own_hand34(view)
    for s, seat_melds in enumerate(view.melds):
        if s == view.seat:
            continue
        for meld in seat_melds:
            if meld.concealed and view.hands is None:
                continue  # another seat's concealed kong -- not visible probabilistically
            _add_meld(counts, meld)
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
    if tile_type >= 27:
        return True
    rank = tile_type % 9
    return rank == 0 or rank == 8
