"""T2 `FaanBot` (docs/04-bots.md §2/§4/§5): T1's shanten/ukeire plus value-planning and a
defence model, implementing docs/04-bots.md §4's `score(discard) = w_speed*speed + w_value*
E[faan] - w_safety*risk + w_flex*optionality`. `_speed_term` folds shanten+ukeire into one
scalar (not T1's lexicographic key) so `w_value` can trade off against it in the same sum.

Reads `view.ruleset.min_faan` for the claim guard (`_should_claim`) -- the table's real
minimum, not a hardcoded default (docs/04-bots.md §9 Tier 1).
"""

from __future__ import annotations

from app.views import SeatView
from bots.features import is_closed, is_terminal_or_honor, own_hand34, seen34
from bots.safety import opponent_threat_level, tile_risk
from bots.valuation import estimate_best_faan, pattern_optionality, route_faan_for
from mahjong_core.config import HandSet, RuleSet
from mahjong_core.shanten import shanten, ukeire
from mahjong_core.state import Phase
from mahjong_core.tiles import tile_id_type
from mahjong_core.wall import max_turns_per_seat

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

_SHANTEN_UNIT = 5.0
"""Cost, in composite-score units, of one extra shanten -- sized so a large value gain (6+ faan
route) can outweigh one shanten step once `w_value` ramps up, without disturbing routine 1-2 faan
differences. Tuned by hand against `tests/test_faanbot.py` and arena runs (see `_weights_for_turn`).
"""
_UKEIRE_SCALE = 8.0
"""Puts the speed term's ukeire component on the same scale as `_SHANTEN_UNIT`/`w_value*E[faan]`.
Measured: 8 is the smallest divisor letting a strong value signal (Full Flush) still win a
discard, while a weak one (Voided Suit vs Half Flush) still correctly loses to ukeire."""

_FOLD_SHANTEN = 3
_THREAT_THRESHOLD = 0.3
"""One exposed meld alone (0.3 on `opponent_threat_level`'s scale) counts as "threatening" --
fold logic already gates on lateness and shanten too, so this doesn't need to be conservative
alone."""

_REFERENCE_MAX_TURN = max_turns_per_seat(RuleSet())
"""`mahjong_core.wall.max_turns_per_seat` at the default ruleset: 144 total tiles
(`flowers_enabled`) - 53 dealt (13*4 + 1 dealer extra) - 0 `wall_reserve` = 91 available draws,
// 4 seats = 22. `_weights_for_turn`'s turn-6/turn-12 schedule (docs/04-bots.md §4/§8) was
hand-tuned against exactly this regime -- every shipped preset (`mahjong_core/presets.py`)
leaves `wall_reserve`/`flowers_enabled` at their defaults, so `_turn_breakpoints` must reproduce
6 and 12 exactly there (docs/04-bots.md §9's `wall_reserve` row)."""
_EARLY_TURN_AT_REFERENCE = 6
_LATE_TURN_AT_REFERENCE = 12


def _turn_breakpoints(ruleset: RuleSet) -> tuple[int, int]:
    """`(early, late)` turn numbers for `_weights_for_turn`'s speed/value/safety schedule and
    fold-mode's lateness gate -- `_EARLY_TURN_AT_REFERENCE`/`_LATE_TURN_AT_REFERENCE` scaled by
    this ruleset's own `max_turns_per_seat` relative to `_REFERENCE_MAX_TURN`, so a ruleset with
    a shorter real turn budget (`wall_reserve` up, or `flowers_enabled` off) shifts into value
    and then safety weighting proportionally earlier. Calibration: at the default ruleset,
    `max_turns_per_seat(ruleset) == _REFERENCE_MAX_TURN` by construction, so
    `early == round(6 * 22 / 22) == 6` and `late == round(12 * 22 / 22) == 12` exactly -- the
    same fixed breakpoints `_weights_for_turn` was tuned against, for every ruleset every shipped
    preset uses."""
    max_turn = max_turns_per_seat(ruleset)
    if max_turn <= 0:
        return (0, 0)
    early = round(_EARLY_TURN_AT_REFERENCE * max_turn / _REFERENCE_MAX_TURN)
    late = round(_LATE_TURN_AT_REFERENCE * max_turn / _REFERENCE_MAX_TURN)
    return early, late


def _weights_for_turn(
    turn: int, early_turn: int, late_turn: int
) -> tuple[float, float, float, float]:
    """`(w_speed, w_value, w_safety, w_flex)` per docs/04-bots.md §4's "speed early -> value mid
    -> safety late" schedule, at the `early_turn`/`late_turn` breakpoints `_turn_breakpoints`
    derives (6/12 at the default ruleset). Hand-tuned and retuned twice against arena runs vs
    `EfficiencyBot` (1000 duplicate sets, at those default breakpoints): mean paired difference
    moved -2.420 -> -0.908 -> +0.591 pts/game, but the 95% CI still includes zero -- not yet a
    clean win. `w_safety` has moved the needle most so far; trimming it further is the natural
    next step."""
    if turn <= early_turn:
        return (1.0, 0.2, 0.15, 0.15)
    if turn <= late_turn:
        return (0.7, 0.9, 0.3, 0.2)
    return (0.4, 0.4, 0.9, 0.15)


def _opponents(seat: int) -> tuple[int, ...]:
    return tuple(s for s in range(4) if s != seat)


def _best_after_discard(
    hand34: list[int], *, closed: bool, hand_sets: frozenset[HandSet]
) -> tuple[int, list[int]]:
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
        s = shanten(after, closed=closed, hand_sets=hand_sets)
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
        hand_sets = view.ruleset.hand_sets
        route_faan = route_faan_for(view.ruleset.faan_overrides)
        before_shanten = shanten(hand, closed=closed, hand_sets=hand_sets)
        before_value, _ = estimate_best_faan(hand, closed=closed, route_faan=route_faan)

        best_aid = _PASS
        best_shanten = before_shanten

        min_faan = view.ruleset.min_faan
        claimed_type = _claimed_type(view)
        if claimed_type is not None:
            if mask[_PUNG]:
                candidate = list(hand)
                candidate[claimed_type] += 1
                s, resulting_hand = _best_after_discard(
                    candidate, closed=False, hand_sets=hand_sets
                )
                if s < best_shanten and self._should_claim(
                    before_value, resulting_hand, min_faan, route_faan
                ):
                    best_shanten, best_aid = s, _PUNG

            chow_aid = next((aid for aid in _CHOW_AIDS if mask[aid]), None)
            if chow_aid is not None:
                candidate = list(hand)
                candidate[claimed_type] += 1
                s, resulting_hand = _best_after_discard(
                    candidate, closed=False, hand_sets=hand_sets
                )
                if s < best_shanten and self._should_claim(
                    before_value, resulting_hand, min_faan, route_faan
                ):
                    best_shanten, best_aid = s, chow_aid

        # claiming an exposed kong never helps shanten (same reason as bots/efficiency.py) -- skip.
        return best_aid

    def _should_claim(
        self,
        before_value: int,
        resulting_hand: list[int],
        min_faan: int,
        route_faan: dict[str, int],
    ) -> bool:
        """Refuses to claim into a hand that drops below `min_faan` when it wasn't already
        sub-minimum -- deliberately no "unless it reaches tenpai" exception (docs/04-bots.md §4's
        point is that sub-minimum tenpai is the failure mode to avoid). Already-sub-minimum hands
        claim freely."""
        after_value, _ = estimate_best_faan(resulting_hand, closed=False, route_faan=route_faan)
        return not (before_value >= min_faan > after_value)

    def _act_on_turn(self, view: SeatView, mask: list[bool]) -> int:
        hand = own_hand34(view)
        closed = is_closed(view)
        hand_sets = view.ruleset.hand_sets
        base = shanten(hand, closed=closed, hand_sets=hand_sets)

        best_kong_aid: int | None = None
        best_kong_shanten = base
        for kong_base in (_CONCEALED_KONG_BASE, _ADDED_KONG_BASE):
            for t in range(34):
                aid = kong_base + t
                if not mask[aid]:
                    continue
                candidate = list(hand)
                candidate[t] -= 1
                s = shanten(candidate, closed=False, hand_sets=hand_sets)
                if s < best_kong_shanten:
                    best_kong_shanten, best_kong_aid = s, aid
        if best_kong_aid is not None:
            return best_kong_aid

        assert view.seat is not None
        # this seat's own discard count -- closest proxy to docs/04-bots.md §4's turn-number
        # language available from a SeatView alone.
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
        hand_sets = view.ruleset.hand_sets
        route_faan = route_faan_for(view.ruleset.faan_overrides)
        base_shanten = shanten(hand, closed=closed, hand_sets=hand_sets)
        threatening = any(
            opponent_threat_level(view, opp) >= _THREAT_THRESHOLD for opp in _opponents(view.seat)
        )
        early_turn, late_turn = _turn_breakpoints(view.ruleset)
        fold_mode = turn >= late_turn and base_shanten >= _FOLD_SHANTEN and threatening

        w_speed, w_value, w_safety, w_flex = _weights_for_turn(turn, early_turn, late_turn)
        accepts = ukeire(hand, seen, closed=closed, hand_sets=hand_sets)

        best_key: tuple[float, int, int] | None = None
        best_aid = -1
        for d in range(34):
            aid = _DISCARD_BASE + d
            if not mask[aid]:
                continue
            after = list(hand)
            after[d] -= 1
            result_shanten = shanten(after, closed=closed, hand_sets=hand_sets)
            kinds, tiles = accepts[d]
            risk = tile_risk(view, d)
            terminal_rank = 0 if is_terminal_or_honor(d) else 1

            if fold_mode:
                # pure defence: minimise deal-in risk, tie-break like T1.
                key = (risk, -tiles, terminal_rank)
            else:
                value_est, _route = estimate_best_faan(after, closed=closed, route_faan=route_faan)
                optionality = pattern_optionality(after, closed=closed, route_faan=route_faan)
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
