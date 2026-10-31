"""T2 `FaanBot` (docs/bots.md §2/§4/§5): T1's shanten/ukeire plus value-planning and a
defence model, implementing docs/bots.md §4's `score(discard) = w_speed*speed + w_value*
E[faan] - w_safety*risk + w_flex*optionality`. `_speed_term` folds shanten+ukeire into one
scalar (not T1's lexicographic key) so `w_value` can trade off against it in the same sum.

Reads `view.ruleset.min_faan` for the claim guard (`_should_claim`) -- the table's real
minimum, not a hardcoded default (docs/bots.md §8 Tier 1).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.views import SeatView
from bots.features import (
    after_claim34,
    claimed_tile_type,
    is_closed,
    is_terminal_or_honor,
    own_concealed34,
    own_hand34,
    own_meld_count,
    seen34,
)
from bots.labels import meld_counts34, winning_tile_types
from bots.safety import kong_rob_risk, opponent_threat_level, ron_credit, tile_risk
from bots.valuation import (
    estimate_best_faan,
    exact_wait_value,
    pattern_optionality,
    route_faan_for,
)
from mahjong_core.config import HandSet, RuleSet
from mahjong_core.melds import MeldKind
from mahjong_core.ml import (
    ADDED_KONG_BASE,
    CHOW_IDS,
    CHOW_LOW_ID,
    CONCEALED_KONG_BASE,
    DISCARD_BASE,
    PASS_ID,
    PUNG_ID,
    WIN_ID,
)
from mahjong_core.shanten import shanten, ukeire
from mahjong_core.state import Phase
from mahjong_core.tiles import COPIES_PER_TYPE, N_TILE_TYPES, TileId, new_count_array, tile_id_type
from mahjong_core.wall import max_turns_per_seat

__all__ = ["AGGRESSIVE", "BASELINE", "DEFENSIVE", "FLUSH_CHASING", "FaanBot", "WeightProfile"]

_SHANTEN_UNIT = 5.0
"""Cost, in composite-score units, of one extra shanten -- sized so a large value gain (6+ faan
route) can outweigh one shanten step once `w_value` ramps up, without disturbing routine 1-2 faan
differences. Tuned by hand against `tests/test_faanbot.py` and arena runs (see `_weights_for_turn`).
"""
_UKEIRE_SCALE = 8.0
"""Puts the speed term's ukeire component on the same scale as `_SHANTEN_UNIT`/`w_value*E[faan]`.
Measured: 8 is the smallest divisor letting a strong value signal (Full Flush) still win a
discard, while a weak one (Voided Suit vs Half Flush) still correctly loses to ukeire."""

_CLAIM_MIN_ACCEPTANCE = 1.0
_CLAIM_VALUE_MARGIN = 1
"""`ORACLE` claims into a tenpai only if its exact value reaches `min_faan` + this. Margin 0 won
more but cheaper hands and failed the points gate; 1 passed, 2 and 3 were null (ADR 0019 §12)."""

_FOLD_SHANTEN = 3
_THREAT_THRESHOLD = 0.3
"""One exposed meld alone (0.3 on `opponent_threat_level`'s scale) counts as "threatening" --
fold logic already gates on lateness and shanten too, so this doesn't need to be conservative
alone."""

_REFERENCE_MAX_TURN = max_turns_per_seat(RuleSet())
"""`mahjong_core.wall.max_turns_per_seat` at the default ruleset: 144 total tiles
(`flowers_enabled`) - 53 dealt (13*4 + 1 dealer extra) - 0 `wall_reserve` = 91 available draws,
// 4 seats = 22. `_weights_for_turn`'s turn-6/turn-12 schedule (docs/bots.md §4/§7) was
hand-tuned against exactly this regime -- every shipped preset (`mahjong_core/presets.py`)
leaves `wall_reserve`/`flowers_enabled` at their defaults, so `_turn_breakpoints` must reproduce
6 and 12 exactly there (docs/bots.md §8's `wall_reserve` row)."""
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
    """`(w_speed, w_value, w_safety, w_flex)` per docs/bots.md §4's "speed early -> value mid
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
    concealed34: list[int], *, melds: int, hand_sets: frozenset[HandSet]
) -> tuple[int, int]:
    """`(best_shanten, discard_type)` after discarding one concealed tile -- lets `_should_claim`
    check the real post-discard shape. Duplicated from `bots/efficiency.py`'s same-named helper
    (T1/T2 stay independently editable) but also returns the discard."""
    best: tuple[int, int] | None = None
    for t in range(N_TILE_TYPES):
        if concealed34[t] == 0:
            continue
        after = list(concealed34)
        after[t] -= 1
        s = shanten(after, closed=False, hand_sets=hand_sets, melds=melds)
        if best is None or s < best[0]:
            best = (s, t)
    assert best is not None, "concealed34 must hold at least one tile"
    return best


def _without_one(tiles: tuple[TileId, ...], tile_type: int) -> tuple[TileId, ...]:
    for i, t in enumerate(tiles):
        if int(tile_id_type(t)) == tile_type:
            return tiles[:i] + tiles[i + 1 :]
    raise ValueError(f"no tile of type {tile_type} in hand")


def _speed_term(result_shanten: int, tiles_accepted: float) -> float:
    """One scalar (not T1's lexicographic key) so `w_value` can trade off against it in the same
    weighted sum; lower shanten always wins, ukeire breaks ties within a shanten level."""
    return -_SHANTEN_UNIT * result_shanten + tiles_accepted / _UKEIRE_SCALE


@dataclass(frozen=True)
class WeightProfile:
    """Multipliers on `_weights_for_turn`'s `(w_speed, w_value, w_safety, w_flex)` schedule --
    personas for docs/ml.md §12's mixed-table evaluation and the danger dataset's opponent
    variety. `BASELINE`'s all-1.0 multipliers reproduce the shipped, arena-tuned weights exactly
    (docs/bots.md §7's numbers are measured against `BASELINE` specifically) -- every other
    profile is a deliberate, unvalidated-by-arena departure from that tuning, meant to vary the
    opponents a learned model is trained or evaluated against, not to compete with `BASELINE`."""

    w_speed: float = 1.0
    w_value: float = 1.0
    w_safety: float = 1.0
    w_flex: float = 1.0


BASELINE = WeightProfile()
AGGRESSIVE = WeightProfile(w_value=1.3, w_safety=0.5)
"""Chases points and discounts danger relative to the shipped tuning."""
DEFENSIVE = WeightProfile(w_value=0.7, w_safety=1.6)
"""Folds earlier and more readily than the shipped tuning."""
FLUSH_CHASING = WeightProfile(w_value=1.3, w_flex=0.3)
"""Commits to its single best route instead of hedging across several -- `w_flex`
(`pattern_optionality`) rewards keeping multiple routes open, which is exactly what a
flush-chaser gives up in exchange for committing harder to the biggest one."""


class FaanBot:
    """T2: see module docstring. Never returns an id `mask` doesn't mark legal."""

    def __init__(self, *, weight_profile: WeightProfile = BASELINE) -> None:
        self._weight_profile = weight_profile

    async def act(self, view: SeatView, mask: list[bool], deadline: float) -> int:
        del deadline  # no search budget; O(1)-ish per candidate
        if mask[WIN_ID]:
            return WIN_ID
        if view.phase in (Phase.AWAIT_CLAIMS, Phase.AWAIT_KONG_ROB):
            return self._act_on_claim(view, mask)
        return self._act_on_turn(view, mask)

    def _act_on_claim(self, view: SeatView, mask: list[bool]) -> int:
        hand = own_hand34(view)
        concealed = own_concealed34(view)
        melds = own_meld_count(view)
        closed = is_closed(view)
        hand_sets = view.ruleset.hand_sets
        route_faan = route_faan_for(view.ruleset.faan_overrides)
        before_shanten = shanten(concealed, closed=closed, hand_sets=hand_sets, melds=melds)
        before_value, _ = estimate_best_faan(hand, closed=closed, route_faan=route_faan)

        best_aid = PASS_ID
        best_shanten = before_shanten

        min_faan = view.ruleset.min_faan
        claimed_type = claimed_tile_type(view)
        if claimed_type is not None:
            for aid in (PUNG_ID, *CHOW_IDS):
                if not mask[aid]:
                    continue
                candidate = after_claim34(concealed, claimed_type, aid)
                s, discard = _best_after_discard(candidate, melds=melds + 1, hand_sets=hand_sets)
                resulting_hand = list(hand)
                resulting_hand[claimed_type] += 1
                resulting_hand[discard] -= 1
                if s < best_shanten and self._should_claim(
                    before_value, resulting_hand, min_faan, route_faan
                ):
                    best_shanten, best_aid = s, aid

        # claiming an exposed kong never helps shanten (same reason as bots/efficiency.py) -- skip.
        # ORACLE-only: the proxy claim guard passed, but the exact post-claim tenpai may be worth it.
        if (
            best_aid == PASS_ID
            and view.hands is not None
            and claimed_type is not None
            and before_shanten >= 1
        ):
            return self._claim_into_clearing_tenpai(view, mask)
        return best_aid

    def _claim_into_clearing_tenpai(self, view: SeatView, mask: list[bool]) -> int:
        """The pung/chow whose best safe post-claim discard leaves a tenpai with the highest
        `exact_wait_value` acceptance × value, if one clears the thresholds above; else pass."""
        assert view.seat is not None
        hand_sets = view.ruleset.hand_sets
        claimed_id = view.discard_pools[view.turn][-1]
        claimed_type = int(tile_id_type(claimed_id))
        seen = seen34(view)
        best = (0.0, PASS_ID)
        for offer in view.claim_options:
            for meld in offer.melds:
                if meld.kind == MeldKind.PUNG:
                    aid = PUNG_ID
                elif meld.kind == MeldKind.CHOW:
                    aid = CHOW_LOW_ID + claimed_type - int(meld.tile_type)
                else:
                    continue
                if not mask[aid]:
                    continue
                concealed = list(view.own_hand)
                for t in meld.tiles:
                    if t != claimed_id:
                        concealed.remove(t)
                melds = (*view.melds[view.seat], meld)
                melds34 = meld_counts34(melds)
                concealed34 = new_count_array()
                for t in concealed:
                    concealed34[int(tile_id_type(t))] += 1
                for d in sorted({int(tile_id_type(t)) for t in concealed}):
                    if tile_risk(view, d) > 0.0:
                        continue
                    after = list(concealed34)
                    after[d] -= 1
                    if shanten(after, closed=False, hand_sets=hand_sets, melds=len(melds)) != 0:
                        continue
                    waits = winning_tile_types(
                        [a + m for a, m in zip(after, melds34, strict=True)],
                        closed=False,
                        hand_sets=hand_sets,
                        melds34=melds34,
                    )
                    acc, val = exact_wait_value(
                        view,
                        _without_one(tuple(concealed), d),
                        waits,
                        seen,
                        ron_credit(view, waits),
                        melds=melds,
                    )
                    if (
                        acc >= _CLAIM_MIN_ACCEPTANCE
                        and val >= view.ruleset.min_faan + _CLAIM_VALUE_MARGIN
                        and acc * val > best[0]
                    ):
                        best = (acc * val, aid)
        return best[1]

    def _should_claim(
        self,
        before_value: int,
        resulting_hand: list[int],
        min_faan: int,
        route_faan: dict[str, int],
    ) -> bool:
        """Refuses to claim into a hand that drops below `min_faan` when it wasn't already
        sub-minimum -- deliberately no "unless it reaches tenpai" exception (docs/bots.md §4's
        point is that sub-minimum tenpai is the failure mode to avoid). Already-sub-minimum hands
        claim freely."""
        after_value, _ = estimate_best_faan(resulting_hand, closed=False, route_faan=route_faan)
        return not (before_value >= min_faan > after_value)

    def _act_on_turn(self, view: SeatView, mask: list[bool]) -> int:
        hand = own_hand34(view)
        concealed = own_concealed34(view)
        melds = own_meld_count(view)
        closed = is_closed(view)
        hand_sets = view.ruleset.hand_sets
        base = shanten(concealed, closed=closed, hand_sets=hand_sets, melds=melds)

        best_kong_aid: int | None = None
        best_kong_shanten = base
        for kong_base, is_concealed, removed, new_melds in (
            (CONCEALED_KONG_BASE, True, COPIES_PER_TYPE, melds + 1),
            (ADDED_KONG_BASE, False, 1, melds),
        ):
            for t in range(N_TILE_TYPES):
                aid = kong_base + t
                if not mask[aid]:
                    continue
                # ORACLE-only: skip a kong outright if it hands an opponent an immediate 搶槓 win,
                # regardless of shanten gain -- other tiers can't see this (view.hands is None).
                if view.hands is not None and kong_rob_risk(view, t, concealed=is_concealed) > 0.0:
                    continue
                candidate = list(concealed)
                candidate[t] -= removed
                s = shanten(candidate, closed=False, hand_sets=hand_sets, melds=new_melds)
                if s < best_kong_shanten:
                    best_kong_shanten, best_kong_aid = s, aid
        if best_kong_aid is not None:
            return best_kong_aid

        assert view.seat is not None
        # this seat's own discard count -- closest proxy to docs/bots.md §4's turn-number
        # language available from a SeatView alone.
        turn = len(view.discard_pools[view.seat])
        return self._best_discard(
            view, hand, concealed, seen34(view), mask, closed=closed, melds=melds, turn=turn
        )

    def _best_discard(
        self,
        view: SeatView,
        hand: list[int],
        concealed: list[int],
        seen: list[int],
        mask: list[bool],
        *,
        closed: bool,
        melds: int,
        turn: int,
    ) -> int:
        """`hand` (whole, melds included) feeds the value proxies; `concealed` beside `melds`
        fixed feeds shanten/ukeire (docs/bots.md §3)."""
        assert view.seat is not None
        hand_sets = view.ruleset.hand_sets
        route_faan = route_faan_for(view.ruleset.faan_overrides)
        base_shanten = shanten(concealed, closed=closed, hand_sets=hand_sets, melds=melds)
        threatening = any(
            opponent_threat_level(view, opp) >= _THREAT_THRESHOLD for opp in _opponents(view.seat)
        )
        early_turn, late_turn = _turn_breakpoints(view.ruleset)
        fold_mode = turn >= late_turn and base_shanten >= _FOLD_SHANTEN and threatening

        w_speed, w_value, w_safety, w_flex = _weights_for_turn(turn, early_turn, late_turn)
        profile = self._weight_profile
        w_speed *= profile.w_speed
        w_value *= profile.w_value
        w_safety *= profile.w_safety
        w_flex *= profile.w_flex
        accepts = ukeire(concealed, seen, closed=closed, hand_sets=hand_sets, melds=melds)
        melds34 = [h - c for h, c in zip(hand, concealed, strict=True)]

        risks = {d: tile_risk(view, d) for d in range(N_TILE_TYPES) if mask[DISCARD_BASE + d]}
        candidates = list(risks)
        if view.hands is not None:
            # exact risk is a certain deal-in, not a likelihood: never pay it while a safe tile exists
            safe = [d for d, r in risks.items() if r == 0.0]
            if safe:
                candidates = safe

        best_key: tuple[float, int, int] | None = None
        best_aid = -1
        for d in candidates:
            aid = DISCARD_BASE + d
            after = list(hand)
            after[d] -= 1
            concealed_after = list(concealed)
            concealed_after[d] -= 1
            result_shanten = shanten(
                concealed_after, closed=closed, hand_sets=hand_sets, melds=melds
            )
            kinds, tiles = accepts[d]
            exact_tenpai: tuple[float, float] | None = None
            if view.hands is not None and result_shanten == 0:
                waits = winning_tile_types(
                    after, closed=closed, hand_sets=hand_sets, melds34=melds34
                )
                exact_tenpai = exact_wait_value(
                    view, _without_one(view.own_hand, d), waits, seen, ron_credit(view, waits)
                )
                tiles = exact_tenpai[0]
            risk = risks[d]
            terminal_rank = 0 if is_terminal_or_honor(d) else 1

            if fold_mode:
                # pure defence: minimise deal-in risk, tie-break like T1.
                key = (risk, -tiles, terminal_rank)
            else:
                if exact_tenpai is not None:
                    value_est = exact_tenpai[1]
                else:
                    value_est, _route = estimate_best_faan(
                        after, closed=closed, route_faan=route_faan
                    )
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
