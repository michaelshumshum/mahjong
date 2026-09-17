"""`SeatView` -> `mahjong_core.shanten`'s 34-count-array contract (docs/04-bots.md §3), shared by
every heuristic bot tier (T1 today; T2 later). Lives in `bots/`, not `mahjong_core/`, because it
reads `SeatView`/`ClaimOffer` -- `app/`-layer, wire-adjacent types -- which `mahjong_core` must
never depend on (see `bots/base.py`'s module docstring on the layering rule this respects).

**Redaction note.** `own_hand34`/`seen34` only ever read tiles this seat is actually entitled to:
its own concealed hand, every seat's *non*-concealed melds (chow/pung/exposed_kong/added_kong --
`Meld.concealed` is only ever true for `concealed_kong`), and public discard pools. Another
seat's concealed kong contributes nothing here, on purpose -- a human in this seat wouldn't know
its tile type either, and `mahjong_core` never redacts (`melds.py`'s `Meld.tiles` docstring), so
this module is where that boundary has to be drawn for bots.
"""

from __future__ import annotations

from app.views import SeatView
from mahjong_core.melds import Meld
from mahjong_core.tiles import new_count_array, tile_id_type

__all__ = ["is_closed", "is_terminal_or_honor", "own_hand34", "seen34"]


def _add_meld(counts: list[int], meld: Meld) -> None:
    """Add one meld's contribution to a 34-count array under `mahjong_core.shanten`'s "melds
    included, kongs contribute 3" contract -- see that module's docstring."""
    tiles = meld.tiles[:3] if meld.is_kong else meld.tiles
    for t in tiles:
        counts[int(tile_id_type(t))] += 1


def own_hand34(view: SeatView) -> list[int]:
    """This seat's full hand as a `mahjong_core.shanten`-shaped 34-array: concealed tiles plus
    this seat's own exposed melds (including its own concealed kongs -- fully visible to
    yourself, unlike everyone else's)."""
    if view.seat is None:
        raise ValueError("own_hand34 needs a seated view, not a spectator's")
    counts = new_count_array()
    for t in view.own_hand:
        counts[int(tile_id_type(t))] += 1
    for meld in view.melds[view.seat]:
        _add_meld(counts, meld)
    return counts


def is_closed(view: SeatView) -> bool:
    """Whether this seat holds zero exposed melds of any kind -- including its own concealed
    kongs, which still count as "a meld" for Seven Pairs/Thirteen Orphans eligibility
    (`mahjong_core.actions.hand_is_winning_shape`'s same rule: `not seat.melds`, no kind
    exception)."""
    if view.seat is None:
        raise ValueError("is_closed needs a seated view, not a spectator's")
    return not view.melds[view.seat]


def seen34(view: SeatView) -> list[int]:
    """Every tile type publicly visible plus this seat's own concealed hand -- docs/04-bots.md
    §3's ukeire contract ("your hand, all melds on the table, all discards... never the wall").
    """
    if view.seat is None:
        raise ValueError("seen34 needs a seated view, not a spectator's")
    counts = own_hand34(view)
    for s, seat_melds in enumerate(view.melds):
        if s == view.seat:
            continue
        for meld in seat_melds:
            if meld.concealed:
                continue  # another seat's concealed kong -- not visible, see module docstring
            _add_meld(counts, meld)
    for pool in view.discard_pools:
        for t in pool:
            counts[int(tile_id_type(t))] += 1
    return counts


def is_terminal_or_honor(tile_type: int) -> bool:
    """1/9 of a suit, or any wind/dragon -- T1's discard tiebreak prefers these
    (docs/04-bots.md §3)."""
    if tile_type >= 27:
        return True
    rank = tile_type % 9
    return rank == 0 or rank == 8
