"""T2 `FaanBot` (docs/04-bots.md §2/§4/§5): T1's shanten/ukeire plus value-planning and a
defence model, implementing docs/04-bots.md §4's `score(discard) = w_speed*speed + w_value*
E[faan] - w_safety*risk + w_flex*optionality`. `_speed_term` folds shanten+ukeire into one
scalar (not T1's lexicographic key) so `w_value` can trade off against it in the same sum.

Assumes `min_faan = 3` rather than reading a live ruleset: `SeatView` carries no ruleset field,
and a bot never sees `GameState`, only `SeatView`.
"""

from __future__ import annotations

from app.views import SeatView
from bots.features import is_closed, is_terminal_or_honor, own_hand34, seen34
from bots.safety import opponent_threat_level, tile_risk
from bots.valuation import estimate_best_faan, pattern_optionality
from mahjong_core.shanten import shanten, ukeire
from mahjong_core.state import Phase
from mahjong_core.tiles import tile_id_type

__all__ = ["FaanBot"]

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

_ASSUMED_MIN_FAAN = 3
"""See module docstring's "Assumed min_faan" note."""

_SHANTEN_UNIT = 5.0
"""Cost, in composite-score units, of one extra shanten -- sized so a large value gain (6+ faan
route) can outweigh one shanten step once `w_value` ramps up, without disturbing routine 1-2 faan
differences. Tuned by hand against `tests/test_faanbot.py` and arena runs (see `_weights_for_turn`).
"""
_UKEIRE_SCALE = 8.0
"""Puts the speed term's ukeire component on the same scale as `_SHANTEN_UNIT`/`w_value*E[faan]`.
Measured: 8 is the smallest divisor letting a strong value signal (Full Flush) still win a
discard, while a weak one (Voided Suit vs Half Flush) still correctly loses to ukeire."""

_LATE_TURN = 12
"""`turn` = this seat's own discard count this hand -- the closest proxy to docs/04-bots.md §4's
turn-number language available from a `SeatView` alone."""
_FOLD_SHANTEN = 3
_THREAT_THRESHOLD = 0.3
"""One exposed meld alone (0.3 on `opponent_threat_level`'s scale) counts as "threatening" --
fold logic already gates on lateness and shanten too, so this doesn't need to be conservative
alone."""


def _weights_for_turn(turn: int) -> tuple[float, float, float, float]:
    """`(w_speed, w_value, w_safety, w_flex)` per docs/04-bots.md §4's "speed early -> value mid
    -> safety late" schedule. Hand-tuned and retuned twice against arena runs vs `EfficiencyBot`
    (1000 duplicate sets): mean paired difference moved -2.420 -> -0.908 -> +0.591 pts/game, but
    the 95% CI still includes zero -- not yet a clean win. `w_safety` has moved the needle most
    so far; trimming it further is the natural next step."""
    if turn <= 6:
        return (1.0, 0.2, 0.15, 0.15)
    if turn <= 12:
        return (0.7, 0.9, 0.3, 0.2)
    return (0.4, 0.4, 0.9, 0.15)


def _opponents(seat: int) -> tuple[int, ...]:
    return tuple(s for s in range(4) if s != seat)


def _best_after_discard(hand34: list[int], *, closed: bool) -> tuple[int, list[int]]:
    """`(best_shanten, resulting_hand34)` after discarding one tile -- lets `_should_claim` check
    the real post-discard shape. Duplicated from `bots/efficiency.py`'s same-named helper (T1/T2
    stay independently editable) but also returns the hand."""
    best_shanten: int | None = None
    best_hand: list[int] | None = None
    for t in range(34):
        if hand34[t] == 0:
            continue
        after = list(hand34)
        after[t] -= 1
        s = shanten(after, closed=closed)
        if best_shanten is None or s < best_shanten:
            best_shanten, best_hand = s, after
    assert best_shanten is not None and best_hand is not None, "hand34 must hold at least one tile"
    return best_shanten, best_hand


def _claimed_type(view: SeatView) -> int | None:
    """Same derivation as `bots/efficiency.py`'s identical helper; duplicated for independence."""
    if view.phase != Phase.AWAIT_CLAIMS:
        return None
    pool = view.discard_pools[view.turn]
    if not pool:
        return None
    return int(tile_id_type(pool[-1]))


def _speed_term(result_shanten: int, tiles_accepted: int) -> float:
    """One scalar (not T1's lexicographic key) so `w_value` can trade off against it in the same
    weighted sum; lower shanten always wins, ukeire breaks ties within a shanten level."""
    return -_SHANTEN_UNIT * result_shanten + tiles_accepted / _UKEIRE_SCALE


class FaanBot:
    """T2: see module docstring. Never returns an id `mask` doesn't mark legal."""

    async def act(self, view: SeatView, mask: list[bool], deadline: float) -> int:
        del deadline  # no search budget; O(1)-ish per candidate
        if mask[_WIN]:
            return _WIN
        if view.phase in (Phase.AWAIT_CLAIMS, Phase.AWAIT_KONG_ROB):
            return self._act_on_claim(view, mask)
        return self._act_on_turn(view, mask)

    def _act_on_claim(self, view: SeatView, mask: list[bool]) -> int:
        hand = own_hand34(view)
        closed = is_closed(view)
        before_shanten = shanten(hand, closed=closed)
        before_value, _ = estimate_best_faan(hand, closed=closed)

        best_aid = _PASS
        best_shanten = before_shanten

        claimed_type = _claimed_type(view)
        if claimed_type is not None:
            if mask[_PUNG]:
                candidate = list(hand)
                candidate[claimed_type] += 1
                s, resulting_hand = _best_after_discard(candidate, closed=False)
                if s < best_shanten and self._should_claim(before_value, resulting_hand):
                    best_shanten, best_aid = s, _PUNG

            chow_aid = next((aid for aid in _CHOW_AIDS if mask[aid]), None)
            if chow_aid is not None:
                candidate = list(hand)
                candidate[claimed_type] += 1
                s, resulting_hand = _best_after_discard(candidate, closed=False)
                if s < best_shanten and self._should_claim(before_value, resulting_hand):
                    best_shanten, best_aid = s, chow_aid

        # claiming an exposed kong never helps shanten (same reason as bots/efficiency.py) -- skip.
        return best_aid

    def _should_claim(self, before_value: int, resulting_hand: list[int]) -> bool:
        """Refuses to claim into a hand that drops below `min_faan` when it wasn't already
        sub-minimum -- deliberately no "unless it reaches tenpai" exception (docs/04-bots.md §4's
        point is that sub-minimum tenpai is the failure mode to avoid). Already-sub-minimum hands
        claim freely."""
        after_value, _ = estimate_best_faan(resulting_hand, closed=False)
        return not (before_value >= _ASSUMED_MIN_FAAN > after_value)

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

        assert view.seat is not None
        turn = len(view.discard_pools[view.seat])
        return self._best_discard(view, hand, seen34(view), mask, closed=closed, turn=turn)

    def _best_discard(
        self,
        view: SeatView,
        hand: list[int],
        seen: list[int],
        mask: list[bool],
        *,
        closed: bool,
        turn: int,
    ) -> int:
        assert view.seat is not None
        base_shanten = shanten(hand, closed=closed)
        threatening = any(
            opponent_threat_level(view, opp) >= _THREAT_THRESHOLD for opp in _opponents(view.seat)
        )
        fold_mode = turn >= _LATE_TURN and base_shanten >= _FOLD_SHANTEN and threatening

        w_speed, w_value, w_safety, w_flex = _weights_for_turn(turn)
        accepts = ukeire(hand, seen, closed=closed)

        best_key: tuple[float, int, int] | None = None
        best_aid = -1
        for d in range(34):
            aid = _DISCARD_BASE + d
            if not mask[aid]:
                continue
            after = list(hand)
            after[d] -= 1
            result_shanten = shanten(after, closed=closed)
            kinds, tiles = accepts[d]
            risk = tile_risk(view, d)
            terminal_rank = 0 if is_terminal_or_honor(d) else 1

            if fold_mode:
                # pure defence: minimise deal-in risk, tie-break like T1.
                key = (risk, -tiles, terminal_rank)
            else:
                value_est, _route = estimate_best_faan(after, closed=closed)
                optionality = pattern_optionality(after, closed=closed)
                score = (
                    w_speed * _speed_term(result_shanten, tiles)
                    + w_value * value_est
                    - w_safety * risk
                    + w_flex * optionality
                )
                # negate score (higher-better) to sort ascending like every other key here.
                key = (-score, -kinds, terminal_rank)
            if best_key is None or key < best_key:
                best_key, best_aid = key, aid
        assert best_aid >= 0, "act() must not be called with an all-false discard mask"
        return best_aid
