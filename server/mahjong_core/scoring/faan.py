"""Top-level faan scoring.

`patterns.py` scores one candidate decomposition at a time (`score_hand`); this module
maximizes across every candidate, and applies `hand_sets` filtering, `faan_overrides`,
limit-hand non-stacking, `faan_cap`, Chicken Hand, and the `min_faan` gate.

Candidate hands are `melds + one decompose() split`, plus `melds` alone as an extra
candidate -- that extra one lets a raw-shape/context-only pattern (七對子/十三么/九蓮寶燈, or a
win-timing pattern that only reads `ctx`) win the maximisation even when `decompose()` finds
nothing to attach to it.

`score_hand` returns `occurrences * pattern.faan` -- the base value, before `hand_sets`
filtering or `faan_overrides`. `pattern.faan` is always >= 1, so `occurrences` is recoverable
as `value // pattern.faan`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from mahjong_core.config import RuleSet
from mahjong_core.melds import Meld, decompose
from mahjong_core.scoring.patterns import (
    PATTERNS,
    Pattern,
    ScoringContext,
    apply_supersedes,
    score_hand,
)
from mahjong_core.tiles import TileId

_PATTERNS_BY_NAME: dict[str, Pattern] = {p.name: p for p in PATTERNS}

CHICKEN_HAND_NAME = "雞糊"
CHICKEN_HAND_FAAN = 0
"""Chicken Hand (雞糊): a win with every other pattern scoring zero, worth 0 faan. Not a
`Pattern` -- its condition needs this module's own maximisation loop to already have run, so
it can't be a `DetectorFn`."""


@dataclass(frozen=True)
class FaanResult:
    """`score_winning_hand`'s result. `total_faan` is the final, capped/collapsed value a
    payout calculation should use; `breakdown` is `{pattern_name: faan_awarded}` for the
    winning candidate hand (a single entry for a chicken hand or a collapsed limit hand).
    `clears_min_faan` is the `min_faan` gate -- callers check this field directly.
    """

    total_faan: int
    breakdown: dict[str, int]
    clears_min_faan: bool


def _candidate_breakdown(
    hand: tuple[Meld, ...], ctx: ScoringContext, ruleset: RuleSet
) -> dict[str, int]:
    """One candidate hand's per-pattern faan after `hand_sets` filtering and `faan_overrides`
    -- everything `score_hand` itself deliberately leaves undone. A pattern from a disabled
    `hand_set` contributes nothing; an override replaces its per-occurrence value (0 disables
    it outright).
    """
    raw = score_hand(hand, ctx, supersede=False)
    breakdown: dict[str, int] = {}
    for name, value in raw.items():
        pattern = _PATTERNS_BY_NAME[name]
        if pattern.hand_set not in ruleset.hand_sets:
            continue
        occurrences = value // pattern.faan
        awarded_per_occurrence = ruleset.faan_overrides.get(name, pattern.faan)
        awarded = occurrences * awarded_per_occurrence
        if awarded:
            breakdown[name] = awarded
    return apply_supersedes(breakdown)


def _score_candidate(
    hand: tuple[Meld, ...], ctx: ScoringContext, ruleset: RuleSet
) -> tuple[int, dict[str, int]]:
    """`(total, breakdown)` for one candidate hand, applying the two rules that apply
    per-hand rather than across the whole maximisation: limit-hand non-stacking and the
    `faan_cap` clamp.

    Limit hands don't stack with anything, including each other: if any matched pattern is
    `is_limit`, every non-limit pattern on this candidate is discarded, and only the single
    highest-paying limit pattern survives, worth `min(its tier, ruleset.faan_cap)`.
    """
    raw = _candidate_breakdown(hand, ctx, ruleset)
    limit_names = [name for name in raw if _PATTERNS_BY_NAME[name].is_limit]
    if limit_names:
        best = max(limit_names, key=lambda name: min(raw[name], ruleset.faan_cap))
        paid = min(raw[best], ruleset.faan_cap)
        return paid, {best: paid}
    total = sum(raw.values())
    return min(total, ruleset.faan_cap), raw


def seven_pairs_enabled(ruleset: RuleSet) -> bool:
    """Whether 七對子 scores under `ruleset`. When it doesn't, a seven-pairs hand isn't a win at
    all -- otherwise the raw-shape candidate would still pass on 自摸/無花 alone."""
    pattern = _PATTERNS_BY_NAME["七對子"]
    return (
        pattern.hand_set in ruleset.hand_sets
        and ruleset.faan_overrides.get(pattern.name, pattern.faan) != 0
    )


def _chicken_hand_allowed(ruleset: RuleSet) -> bool:
    """雞糊 is only reachable at `min_faan == 0` -- at any higher minimum a zero-faan hand can
    never win, so evaluating it would be dead config."""
    return ruleset.min_faan == 0


def score_winning_hand(
    concealed_tiles: Sequence[TileId],
    melds: Sequence[Meld],
    ctx: ScoringContext,
    ruleset: RuleSet,
) -> FaanResult:
    """Score a complete winning hand: `melds` (already-formed claimed/self-declared melds)
    plus `concealed_tiles` (the remaining concealed tiles at the moment of the win). Runs
    every candidate decomposition, plus the raw-shape/context-only fallback, through
    `_score_candidate`, and keeps the highest-`total` one -- scoring must maximize over all
    valid decompositions, not the first found.

    `ctx.concealed_tiles` is overwritten with `concealed_tiles` regardless of what the caller
    set it to, so the raw-shape detectors always see the same tiles this function's own
    decomposition step does.
    """
    effective_ctx = replace(ctx, concealed_tiles=tuple(concealed_tiles))
    melds_t = tuple(melds)
    candidates = [melds_t + split for split in decompose(concealed_tiles)]
    candidates.append(melds_t)

    best_total = -1
    best_breakdown: dict[str, int] = {}
    for hand in candidates:
        total, breakdown = _score_candidate(hand, effective_ctx, ruleset)
        if total > best_total:
            best_total = total
            best_breakdown = breakdown

    if best_total <= 0 and _chicken_hand_allowed(ruleset):
        chicken_faan = ruleset.faan_overrides.get(CHICKEN_HAND_NAME, CHICKEN_HAND_FAAN)
        best_total = chicken_faan
        best_breakdown = {CHICKEN_HAND_NAME: chicken_faan}

    return FaanResult(
        total_faan=max(best_total, 0),
        breakdown=best_breakdown,
        clears_min_faan=max(best_total, 0) >= ruleset.min_faan,
    )
