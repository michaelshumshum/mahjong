"""T1 `EfficiencyBot` (docs/04-bots.md §2/§3): shanten-minimising discard, ukeire tiebreak.

Never claims/declares kongs: a kong always contributes 3 tiles to the shanten count array
regardless of source, so doing so never changes shanten -- falls out of the shanten model, not a
special case.

All three chow variants score identically (only the claimed tile's type affects the count array,
not run position), so this evaluates once and returns whichever id the mask offers.
"""

from __future__ import annotations

from app.views import SeatView
from bots.features import is_closed, is_terminal_or_honor, own_hand34, seen34
from mahjong_core.shanten import shanten, ukeire
from mahjong_core.state import Phase
from mahjong_core.tiles import tile_id_type

__all__ = ["EfficiencyBot"]

_DISCARD_BASE = 0
_CONCEALED_KONG_BASE = 34
_ADDED_KONG_BASE = 68
_PASS = 102
_CHOW_LOW = 103
_CHOW_MIDDLE = 104
_CHOW_HIGH = 105
_CHOW_AIDS = (_CHOW_LOW, _CHOW_MIDDLE, _CHOW_HIGH)
_PUNG = 106
_KONG = 107
_WIN = 108


def _best_after_discard(hand34: list[int], *, closed: bool) -> int:
    """Best shanten after discarding one tile -- exposed so claim evaluation can compare against
    the best resulting hand, not just the meld's own shape."""
    best: int | None = None
    for t in range(34):
        if hand34[t] == 0:
            continue
        after = list(hand34)
        after[t] -= 1
        s = shanten(after, closed=closed)
        if best is None or s < best:
            best = s
    assert best is not None, "hand34 must hold at least one tile"
    return best


def _claimed_type(view: SeatView) -> int | None:
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


class EfficiencyBot:
    """T1: see module docstring. Never returns an id `mask` doesn't mark legal."""

    async def act(self, view: SeatView, mask: list[bool], deadline: float) -> int:
        del deadline  # no search budget; every decision is O(1)
        if mask[_WIN]:
            return _WIN
        if view.phase in (Phase.AWAIT_CLAIMS, Phase.AWAIT_KONG_ROB):
            return self._act_on_claim(view, mask)
        return self._act_on_turn(view, mask)

    def _act_on_claim(self, view: SeatView, mask: list[bool]) -> int:
        hand = own_hand34(view)
        closed = is_closed(view)
        best_aid = _PASS
        best_shanten = shanten(hand, closed=closed)

        claimed_type = _claimed_type(view)
        if claimed_type is not None:
            if mask[_PUNG]:
                candidate = list(hand)
                candidate[claimed_type] += 1
                s = _best_after_discard(candidate, closed=False)
                if s < best_shanten:
                    best_shanten, best_aid = s, _PUNG

            chow_aid = next((aid for aid in _CHOW_AIDS if mask[aid]), None)
            if chow_aid is not None:
                candidate = list(hand)
                candidate[claimed_type] += 1
                s = _best_after_discard(candidate, closed=False)
                if s < best_shanten:
                    best_shanten, best_aid = s, chow_aid

        # claiming an exposed kong never helps shanten (module docstring) -- skip it.
        return best_aid

    def _act_on_turn(self, view: SeatView, mask: list[bool]) -> int:
        hand = own_hand34(view)
        closed = is_closed(view)
        base = shanten(hand, closed=closed)

        best_kong_aid: int | None = None
        best_kong_shanten = base
        for kong_base in (_CONCEALED_KONG_BASE, _ADDED_KONG_BASE):
            for t in range(34):
                aid = kong_base + t
                if not mask[aid]:
                    continue
                candidate = list(hand)
                candidate[t] -= 1
                s = shanten(candidate, closed=False)
                if s < best_kong_shanten:
                    best_kong_shanten, best_kong_aid = s, aid
        if best_kong_aid is not None:
            return best_kong_aid

        return self._best_discard(hand, seen34(view), mask, closed=closed)

    def _best_discard(
        self, hand: list[int], seen: list[int], mask: list[bool], *, closed: bool
    ) -> int:
        accepts = ukeire(hand, seen, closed=closed)
        best_key: tuple[int, int, int, int] | None = None
        best_aid = -1
        for d in range(34):
            aid = _DISCARD_BASE + d
            if not mask[aid]:
                continue
            after = list(hand)
            after[d] -= 1
            result_shanten = shanten(after, closed=closed)
            kinds, tiles = accepts[d]
            terminal_rank = 0 if is_terminal_or_honor(d) else 1
            key = (result_shanten, -tiles, -kinds, terminal_rank)
            if best_key is None or key < best_key:
                best_key, best_aid = key, aid
        assert best_aid >= 0, "act() must not be called with an all-false discard mask"
        return best_aid
