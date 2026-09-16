"""Top-level faan scoring (docs/01-rules-spec.md §7; docs/05-roadmap.md §2, sixth sub-task).

`patterns.py` scores one candidate decomposition at a time (`score_hand`) and says so
explicitly in its own docstring: maximising across every candidate, `hand_sets` filtering,
`faan_overrides`, the limit-hand non-stacking rule, `faan_cap`, Chicken Hand, and the
`min_faan` gate are all deferred here. This module is that "here."

**Candidate hands.** `melds.decompose(concealed_tiles)` only ever produces the
groups-plus-pair shape (chows/pungs/a pair) -- it returns `()` for Seven Pairs, Thirteen
Orphans, and Nine Gates, none of which decompose that way at all (see patterns.py's "Raw-hand
access" note). Rather than branching on hand shape here, every candidate hand this module
scores is `melds + one decompose() split`, *plus* one more candidate, `melds` alone (no
concealed groups attached). That extra candidate is what lets a raw-shape/context-only
pattern (七對子/十三么/九蓮寶燈, or a win-timing pattern like 天糊 that only reads `ctx`) win
the maximisation even when `decompose()` finds nothing to attach to it -- `score_hand` already
degrades gracefully on it (every group-shaped detector's `_groups_and_pair` guard returns 0
for a hand with no pair), so this never inflates a normal hand's score, only rescues the
shapes `decompose()` can't reach.

**Why `score_hand` isn't the final per-pattern faan.** `score_hand` returns
`occurrences * pattern.faan` -- the *base* value, before `RuleSet.hand_sets` filtering or
`RuleSet.faan_overrides` (config.py documents overrides as applying "after hand_sets
selection, before stacking/caps", i.e. exactly at this layer). `pattern.faan` is always >= 1,
so `occurrences` is recoverable as `value // pattern.faan` -- cheaper than threading a second
occurrence-returning path through `score_hand` for a value this module already has.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from mahjong_core.config import HandSet, RuleSet
from mahjong_core.melds import Meld, decompose
from mahjong_core.scoring.patterns import PATTERNS, Pattern, ScoringContext, score_hand
from mahjong_core.tiles import TileId

_PATTERNS_BY_NAME: dict[str, Pattern] = {p.name: p for p in PATTERNS}

CHICKEN_HAND_NAME = "雞糊"
CHICKEN_HAND_FAAN = 1
"""§7 New 6 table: "1 | Chicken Hand (zero other faan) | 雞糊". Not a `Pattern` -- its
condition ("every other pattern scored zero, across every decomposition") needs this
module's own maximisation loop to already have run, so it can't be a `DetectorFn` (see
patterns.py's "What doesn't fit here" note)."""


@dataclass(frozen=True)
class FaanResult:
    """`score_winning_hand`'s result. `total_faan` is the final, capped/collapsed value a
    payout calculation should use; `breakdown` is `{pattern_name: faan_awarded}` for the
    winning candidate hand (a single `{CHICKEN_HAND_NAME: ...}` entry for a chicken hand, or a
    single `{limit_pattern_name: ruleset.faan_cap}` entry once a limit hand collapses --
    see `_score_candidate`). `clears_min_faan` is the gate itself, not yet wired into
    `actions.py` (that's sub-task 8) -- callers check this field directly for now.
    """

    total_faan: int
    breakdown: dict[str, int]
    clears_min_faan: bool


def _candidate_breakdown(
    hand: tuple[Meld, ...], ctx: ScoringContext, ruleset: RuleSet
) -> dict[str, int]:
    """One candidate hand's per-pattern faan after `hand_sets` filtering and
    `faan_overrides` -- everything `score_hand` itself deliberately leaves undone (its own
    docstring). A pattern from a disabled `hand_set` contributes nothing; an override
    replaces its per-occurrence value (0 disables it outright, same "contributes nothing"
    effect, just reached through a different config knob).
    """
    raw = score_hand(hand, ctx)
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
    return breakdown


def _score_candidate(
    hand: tuple[Meld, ...], ctx: ScoringContext, ruleset: RuleSet
) -> tuple[int, dict[str, int]]:
    """`(total, breakdown)` for one candidate hand, with the two rules that apply per-hand
    rather than across the whole maximisation: limit-hand non-stacking and the `faan_cap`
    clamp (01-rules-spec.md §7 "Stacking and caps").

    **Limit hands don't stack with anything, including each other.** If any matched pattern
    is `is_limit`, every non-limit pattern on this candidate (自摸, 門前清, 無花, wind/dragon
    faan, ...) is discarded, and only the single highest-scoring limit pattern survives --
    resolved against `ruleset.faan_cap`, not `patterns.py`'s `LIMIT_FAAN` placeholder (that
    placeholder exists specifically so this module can be the one to replace it, per its own
    docstring).
    """
    raw = _candidate_breakdown(hand, ctx, ruleset)
    limit_names = [name for name in raw if _PATTERNS_BY_NAME[name].is_limit]
    if limit_names:
        best = max(limit_names, key=lambda name: raw[name])
        return ruleset.faan_cap, {best: ruleset.faan_cap}
    total = sum(raw.values())
    return min(total, ruleset.faan_cap), raw


def _chicken_hand_allowed(ruleset: RuleSet) -> bool:
    """01-rules-spec.md §7 note ¹: 雞糊 is only reachable at `min_faan == 0` -- at any higher
    minimum a zero-faan hand can never win in the first place, so evaluating it would be dead
    config. It's tabled under New 6, so it's additionally gated on that `hand_set` like every
    other pattern in that table, consistent with how `_candidate_breakdown` gates the rest.
    """
    return ruleset.min_faan == 0 and HandSet.NEW_6 in ruleset.hand_sets


def score_winning_hand(
    concealed_tiles: Sequence[TileId],
    melds: Sequence[Meld],
    ctx: ScoringContext,
    ruleset: RuleSet,
) -> FaanResult:
    """Score a complete winning hand: `melds` (already-formed claimed/self-declared melds)
    plus `concealed_tiles` (the remaining concealed tiles at the moment of the win). Runs
    every candidate decomposition, plus the raw-shape/context-only fallback (see the module
    docstring), through `_score_candidate`, and keeps the highest-`total` one --
    01-rules-spec.md §11 edge case 9: "scoring must maximize over *all* valid decompositions,
    not the first found."

    `ctx.concealed_tiles` is overwritten with `concealed_tiles` regardless of what the caller
    set it to, so the raw-shape detectors (七對子/十三么/九蓮寶燈, patterns.py's "Raw-hand
    access" note) always see the same tiles this function's own decomposition step does --
    one source of truth rather than two fields that could silently disagree.
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
        if chicken_faan:
            best_total = chicken_faan
            best_breakdown = {CHICKEN_HAND_NAME: chicken_faan}

    return FaanResult(
        total_faan=max(best_total, 0),
        breakdown=best_breakdown,
        clears_min_faan=max(best_total, 0) >= ruleset.min_faan,
    )
