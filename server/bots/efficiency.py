"""T1 `EfficiencyBot` (docs/bots.md §2/§3): shanten-minimising discard, ukeire tiebreak.

Shanten and ukeire parse the concealed tiles only, beside the exposed melds held fixed
(`melds=`, docs/bots.md §3), so a meld's tiles are never regrouped into a wait.

Never claims/declares kongs: removing a complete set from the concealed tiles never lowers
shanten, so doing so never helps -- falls out of the shanten model, not a special case.

Each offered chow variant locks different tiles, so each is scored; ties go to the first in
`CHOW_IDS` order.
"""

from __future__ import annotations

from app.views import SeatView
from bots.features import (
    after_claim34,
    claimed_tile_type,
    is_closed,
    is_terminal_or_honor,
    own_concealed34,
    own_meld_count,
    seen34,
)
from mahjong_core.config import HandSet
from mahjong_core.ml import (
    ADDED_KONG_BASE,
    CHOW_IDS,
    CONCEALED_KONG_BASE,
    DISCARD_BASE,
    PASS_ID,
    PUNG_ID,
    WIN_ID,
)
from mahjong_core.shanten import shanten, ukeire
from mahjong_core.state import Phase
from mahjong_core.tiles import COPIES_PER_TYPE, N_TILE_TYPES

__all__ = ["EfficiencyBot"]


def _best_after_discard(
    concealed34: list[int], *, melds: int, hand_sets: frozenset[HandSet]
) -> int:
    """Best shanten after discarding one concealed tile -- exposed so claim evaluation can
    compare against the best resulting hand, not just the meld's own shape."""
    best: int | None = None
    for t in range(N_TILE_TYPES):
        if concealed34[t] == 0:
            continue
        after = list(concealed34)
        after[t] -= 1
        s = shanten(after, closed=False, hand_sets=hand_sets, melds=melds)
        if best is None or s < best:
            best = s
    assert best is not None, "concealed34 must hold at least one tile"
    return best


class EfficiencyBot:
    """T1: see module docstring. Never returns an id `mask` doesn't mark legal."""

    async def act(self, view: SeatView, mask: list[bool], deadline: float) -> int:
        del deadline  # no search budget; every decision is O(1)
        if mask[WIN_ID]:
            return WIN_ID
        if view.phase in (Phase.AWAIT_CLAIMS, Phase.AWAIT_KONG_ROB):
            return self._act_on_claim(view, mask)
        return self._act_on_turn(view, mask)

    def _act_on_claim(self, view: SeatView, mask: list[bool]) -> int:
        concealed = own_concealed34(view)
        melds = own_meld_count(view)
        hand_sets = view.ruleset.hand_sets
        best_aid = PASS_ID
        best_shanten = shanten(concealed, closed=is_closed(view), hand_sets=hand_sets, melds=melds)

        claimed_type = claimed_tile_type(view)
        if claimed_type is not None:
            for aid in (PUNG_ID, *CHOW_IDS):
                if not mask[aid]:
                    continue
                candidate = after_claim34(concealed, claimed_type, aid)
                s = _best_after_discard(candidate, melds=melds + 1, hand_sets=hand_sets)
                if s < best_shanten:
                    best_shanten, best_aid = s, aid

        # claiming an exposed kong never helps shanten (module docstring) -- skip it.
        return best_aid

    def _act_on_turn(self, view: SeatView, mask: list[bool]) -> int:
        concealed = own_concealed34(view)
        melds = own_meld_count(view)
        closed = is_closed(view)
        hand_sets = view.ruleset.hand_sets
        base = shanten(concealed, closed=closed, hand_sets=hand_sets, melds=melds)

        best_kong_aid: int | None = None
        best_kong_shanten = base
        for kong_base, removed, new_melds in (
            (CONCEALED_KONG_BASE, COPIES_PER_TYPE, melds + 1),
            (ADDED_KONG_BASE, 1, melds),
        ):
            for t in range(N_TILE_TYPES):
                aid = kong_base + t
                if not mask[aid]:
                    continue
                candidate = list(concealed)
                candidate[t] -= removed
                s = shanten(candidate, closed=False, hand_sets=hand_sets, melds=new_melds)
                if s < best_kong_shanten:
                    best_kong_shanten, best_kong_aid = s, aid
        if best_kong_aid is not None:
            return best_kong_aid

        return self._best_discard(
            concealed, seen34(view), mask, closed=closed, melds=melds, hand_sets=hand_sets
        )

    def _best_discard(
        self,
        concealed: list[int],
        seen: list[int],
        mask: list[bool],
        *,
        closed: bool,
        melds: int,
        hand_sets: frozenset[HandSet],
    ) -> int:
        accepts = ukeire(concealed, seen, closed=closed, hand_sets=hand_sets, melds=melds)
        best_key: tuple[int, int, int, int] | None = None
        best_aid = -1
        for d in range(N_TILE_TYPES):
            aid = DISCARD_BASE + d
            if not mask[aid]:
                continue
            after = list(concealed)
            after[d] -= 1
            result_shanten = shanten(after, closed=closed, hand_sets=hand_sets, melds=melds)
            kinds, tiles = accepts[d]
            terminal_rank = 0 if is_terminal_or_honor(d) else 1
            key = (result_shanten, -tiles, -kinds, terminal_rank)
            if best_key is None or key < best_key:
                best_key, best_aid = key, aid
        assert best_aid >= 0, "act() must not be called with an all-false discard mask"
        return best_aid
