"""T1 `EfficiencyBot` (docs/04-bots.md §2/§3): shanten-minimising discard, ukeire tiebreak, no
value-planning or safety model -- "Easy" difficulty, and the arena's shanten-only reference
point once T2 exists to compare against (docs/04-bots.md §7).

**Discard rule (§3, verbatim):** minimise shanten; tiebreak on `tiles_accepted` (more is
better); then `kinds_accepted` (more is better); then prefer discarding terminals/honors. Call
chow/pung only if it strictly reduces shanten.

**Claimed/self-declared kongs are never taken, by construction, not by special-casing.** A kong
always contributes exactly 3 tiles to the `mahjong_core.shanten` count array regardless of
source (`bots/features.py`'s `_add_meld`) -- claiming one leaves the array numerically
*identical* to not claiming it (the 3 concealed/claimed tiles that back the kong were already
contributing 3 to the array as a plain triplet), and self-declaring one only ever *drops* a
count from 4 to 3, which `mahjong_core.shanten._frontier` already treats identically to a
plain triplet in every case that matters for a real 13/14-tile hand (see that module's
"four-copies" divergence note for the one narrow case where it doesn't, which is also exactly
the case real kong-declaring resolves in the first place). So "only call if it strictly reduces
shanten" resolves to "never call" for every kong here, structurally -- not hand-coded, and this
module still runs the real comparison rather than skipping kongs outright, so a future change to
the shanten model would automatically be picked up here with no edit needed.

**All three chow options are numerically interchangeable for shanten purposes, and this module
only ever evaluates one.** Whichever two of a chow's three tile types come from this seat's own
concealed hand, they net to zero change in the count array (one concealed copy leaves, the
meld's own representation adds one back) -- only the claimed tile's type ever changes the array,
regardless of which of the three run positions it occupies. So `chow_low`/`chow_middle`/
`chow_high` always evaluate to the identical resulting shanten when any is legal; this module
computes it once and returns whichever specific id the mask actually offers.
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
    """The best shanten reachable from `hand34` by discarding exactly one tile -- the same
    "what's my base after this candidate action" step `mahjong_core.shanten.ukeire` computes
    per discard, exposed here so claim evaluation (which must compare against the *best*
    resulting hand, not just the meld's own shape) can reuse it."""
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
    """The tile type up for claim, derived without needing `state.claim_window.tile` (a bot
    never sees `GameState`): during a discard-triggered `AWAIT_CLAIMS` window, `view.turn`
    still names the discarder (`engine._apply_discard` opens the window without advancing
    `turn`), and that discard is exactly the last entry of their `discard_pools` -- it was just
    appended in the same `reduce()` call that opened the window. `None` outside a discard claim
    window (kong-rob offers are win-only, per `engine._kong_rob_offers` -- no meld to evaluate)
    or if that pool is somehow empty (defensive; should never happen when `AWAIT_CLAIMS` is
    live)."""
    if view.phase != Phase.AWAIT_CLAIMS:
        return None
    pool = view.discard_pools[view.turn]
    if not pool:
        return None
    return int(tile_id_type(pool[-1]))


class EfficiencyBot:
    """T1: see module docstring. Never returns an id `mask` doesn't mark legal."""

    async def act(self, view: SeatView, mask: list[bool], deadline: float) -> int:
        del deadline  # T1 has no search budget to spend; every decision is O(1) lookups
        if mask[_WIN]:
            return _WIN
        if view.phase in (Phase.AWAIT_CLAIMS, Phase.AWAIT_KONG_ROB):
            return self._act_on_claim(view, mask)
        return self._act_on_turn(view, mask)

    # --- claim window (discard-triggered chow/pung/kong, or a kong-rob window) -------------

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

        # mask[_KONG] (claiming an exposed kong) is deliberately not evaluated: see module
        # docstring -- it is numerically identical to not claiming, so it can never win here.
        return best_aid

    # --- own turn: self-declared kongs, then the discard rule -------------------------------

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
