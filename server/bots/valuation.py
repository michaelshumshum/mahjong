"""Hand-value estimation for T2 `FaanBot` (docs/04-bots.md §4): a fast structural proxy for
"what faan does the best reachable pattern from this hand shape score", used to rank candidate
discards by value, not just speed.

**Why a proxy, not the real scorer, per discard.** `mahjong_core.scoring.faan.score_winning_hand`
is the ground truth, but it only scores a *complete* 14-tile winning hand -- there is no
"partial credit" API, and a discard decision has to compare ~14 candidate discards against a
hand that is (usually) several tiles away from complete. Calling the real scorer would mean
hypothesizing a full completion for every candidate, which needs a wait-tile enumeration and a
tile-id assignment per candidate (the arena's `_tenpai_can_reach_min_faan` does exactly this,
but only for one already-tenpai hand at hand-end, not for ~14 mid-hand candidates on every
decision). This module instead reads the *shape* directly off the 34-count array -- which suits
are in play, how many pair/pung blocks exist, how many dragon pairs, etc. -- against the
threshold table in docs/04-bots.md §4, no decomposition or completion needed.

**Validated against the real scorer, not assumed correct** (same "measure it, don't assume"
precedent as `mahjong_core/shanten.py`'s frontier-table tradeoff). `tests/test_valuation.py`
checks two things: (1) a handful of scripted hand shapes for each route, each one's expected
route/faan confirmed directly against `score_hand` on a real hand of that shape before being
pinned as this module's expected output; (2) `tests/test_valuation_selfplay.py` (marked `slow`)
runs an organic sample -- winning hands produced by real (`RandomBot`) self-play games --
comparing this module's estimate (taken at the winning seat's pre-win, already-tenpai shape)
against the actual awarded faan from `state.hand_result`.

**Measured**: mean absolute error 2.46 faan, only 9% of samples within 1 faan, over 67
`RandomBot` self-play wins (1500 games; wins are rare by pure chance, see that test's own
sizing note). That gap is larger than a first guess would suggest, and the reason is concrete,
not vague imprecision: `RandomBot`'s real wins very often pick up situational/win-timing faan
this module does not model at all -- 箭刻 (1 faan *per* dragon pung, no pair needed, unlike
`small_three_dragons`'s 2-pair threshold), 座位花 (flowers), 全求人 (every group claimed, win
off a discard), and the New-6 win-timing set (海底/河底/槓上/搶槓) -- because a policy with no
value model discards and claims with no regard for hand shape, so these shape-independent
bonuses show up disproportionately often relative to the routes in `ROUTE_FAAN`. Modeling them
would mean threading claim/flower/win-timing history through this module, which needs
information (whose discard was claimed and when, flower draws, wall-exhaustion timing) that
isn't part of a 34-count hand shape at all -- a real scope expansion, not a threshold tweak, and
deliberately left out: this module only ever prices the *hand-shape* routes docs/04-bots.md §4
names.

**Why this is still safe to rank discards with, despite the gap.** The systematic bias
documented above is close to *shape-independent* -- 箭刻/座位花/全求人/win-timing faan don't
depend on which tile T2 discards this turn, they depend on claim history and luck that a
same-decision comparison across candidate discards shares equally. A constant-ish additive
term omitted from every candidate's estimate shifts every candidate's score by roughly the same
amount and so barely disturbs their *relative order* -- the property `bots/faanbot.py`'s
discard ranking actually needs (module docstring's "acceptable... only needs to get the
relative order of candidates right"). What this estimator is not safe to use for is an absolute
faan prediction in isolation; nothing in this codebase does that with it.

**What this module deliberately does not do**, beyond the win-timing/situational gap above: it
does not weight by *probability* of actually completing a route (that's `mahjong_core.shanten`'s
job, combined by `bots/faanbot.py`'s own scoring formula, not fused into this estimate) and it
does not model interactions between routes (e.g. Half Flush + a dragon pung stacking to 4-5
faan, docs/04-bots.md §4's table) beyond the flat `+2` self-draw/concealed bonus.
"""

from __future__ import annotations

from collections.abc import Sequence

from mahjong_core.tiles import TileType

__all__ = [
    "ROUTE_FAAN",
    "estimate_best_faan",
    "pattern_optionality",
    "reachable_routes",
]

_HONOR_START = 27
_RANKS_PER_SUIT = 9
_DRAGON_TYPES = (int(TileType.DRAGON_RED), int(TileType.DRAGON_GREEN), int(TileType.DRAGON_WHITE))

# docs/04-bots.md §4's "realistic 3-faan routes" table, base faan per route (before the closed
# bonus). Not every table row is modeled: "Half Flush + dragon/wind pung" is the natural sum of
# two routes already covered (half_flush + a dragon block bumping small_three_dragons), so it
# doesn't need its own entry.
ROUTE_FAAN: dict[str, int] = {
    "full_flush": 6,
    "half_flush": 3,
    "all_pungs": 3,
    "small_three_dragons": 3,
    "seven_pairs": 4,
    "voided_suit": 2,
    "all_sequences": 1,  # 平糊 -- the floor every hand can reach, T1's whole failure mode
}

_HALF_FLUSH_MIN_TILES = 7
"""docs/04-bots.md §4: "≥7 tiles in one suit + honors by turn 6"."""
_FULL_FLUSH_MIN_TILES = 9
"""docs/04-bots.md §4: "≥9 tiles in one suit by turn 5"."""
_ALL_PUNGS_MIN_BLOCKS = 2
"""docs/04-bots.md §4: "≥2 pairs/triplets early, few sequence shapes"."""
_ALL_PUNGS_MAX_SEQUENCE_POTENTIAL = 1
_SMALL_DRAGONS_MIN_PAIRS = 2
"""docs/04-bots.md §4: "two dragon pairs"."""
_SEVEN_PAIRS_MIN_PAIRS = 4
"""docs/04-bots.md §4: "≥4 pairs by turn 5, honors-heavy" -- the "honors-heavy" qualifier isn't
separately checked: a hand with 4+ pair-types already, of any kind, is the actual shanten-
relevant signal (`mahjong_core.shanten.seven_pairs_shanten`), and restricting to honors-heavy
hands only would miss plenty of real all-suit seven-pairs hands."""
_SELF_DRAW_CONCEALED_BONUS = 2
"""docs/04-bots.md §4: "Self-draw + concealed: +2 if closed" -- additive, not its own route,
since it always requires staying closed regardless of which other route is taken."""


def _suits_present(hand34: Sequence[int]) -> set[int]:
    return {t // _RANKS_PER_SUIT for t in range(_HONOR_START) if hand34[t] > 0}


def _honors_present(hand34: Sequence[int]) -> bool:
    return any(hand34[t] > 0 for t in range(_HONOR_START, 34))


def _sequence_potential(hand34: Sequence[int]) -> int:
    """A rough count of "this tile could still grow into a chow" spots -- an already-held tile
    with a neighbour 1 or 2 ranks away also held. Used only to gate All Pungs off when the hand
    still has real sequence shape rather than blocks (docs/04-bots.md §4: "few sequence
    shapes") -- not a precise tatsu count (`mahjong_core.shanten` owns that), just cheap enough
    to compute per candidate discard without another shanten-scale search.
    """
    potential = 0
    for suit in range(3):
        base = suit * _RANKS_PER_SUIT
        for rank in range(_RANKS_PER_SUIT):
            t = base + rank
            if hand34[t] == 0:
                continue
            if (
                rank + 1 < _RANKS_PER_SUIT
                and hand34[t + 1] > 0
                or rank + 2 < _RANKS_PER_SUIT
                and hand34[t + 2] > 0
            ):
                potential += 1
    return potential


def reachable_routes(hand34: Sequence[int], *, closed: bool) -> list[tuple[int, str]]:
    """Every route whose docs/04-bots.md §4 commit threshold this hand shape already clears,
    as `(base_faan, route_name)` -- always non-empty (falls back to `all_sequences`, the 1-faan
    floor every hand can reach). Mutually-exclusive-by-suit-count routes (voided suit / half
    flush / full flush) mirror `mahjong_core.scoring.patterns`' own real detectors' suit-count
    conditions exactly, so this list's suit-based entries can never overlap the way the real
    scorer's can't either.
    """
    routes: list[tuple[int, str]] = []
    suits = _suits_present(hand34)
    honors = _honors_present(hand34)

    if len(suits) == 1:
        (suit,) = suits
        base = suit * _RANKS_PER_SUIT
        tiles_in_suit = sum(hand34[base : base + _RANKS_PER_SUIT])
        if not honors and tiles_in_suit >= _FULL_FLUSH_MIN_TILES:
            routes.append((ROUTE_FAAN["full_flush"], "full_flush"))
        tiles_in_suit_and_honors = tiles_in_suit + sum(hand34[_HONOR_START:34])
        if tiles_in_suit_and_honors >= _HALF_FLUSH_MIN_TILES:
            routes.append((ROUTE_FAAN["half_flush"], "half_flush"))
    elif len(suits) == 2:
        routes.append((ROUTE_FAAN["voided_suit"], "voided_suit"))

    block_types = sum(1 for c in hand34 if c >= 2)
    if (
        block_types >= _ALL_PUNGS_MIN_BLOCKS
        and _sequence_potential(hand34) <= _ALL_PUNGS_MAX_SEQUENCE_POTENTIAL
    ):
        routes.append((ROUTE_FAAN["all_pungs"], "all_pungs"))

    dragon_pairs = sum(1 for t in _DRAGON_TYPES if hand34[t] >= 2)
    if dragon_pairs >= _SMALL_DRAGONS_MIN_PAIRS:
        routes.append((ROUTE_FAAN["small_three_dragons"], "small_three_dragons"))

    if closed:
        pair_types = sum(1 for c in hand34 if c >= 2)
        if pair_types >= _SEVEN_PAIRS_MIN_PAIRS:
            routes.append((ROUTE_FAAN["seven_pairs"], "seven_pairs"))

    if not routes:
        routes.append((ROUTE_FAAN["all_sequences"], "all_sequences"))
    return routes


def estimate_best_faan(hand34: Sequence[int], *, closed: bool) -> tuple[int, str]:
    """`(estimated_faan, route_name)` for the single best reachable route, plus the closed
    bonus. This is `E[faan | best reachable pattern]` from docs/04-bots.md §4's scoring
    formula -- an estimate of value *if the hand completes along that route*, not weighted by
    how likely that completion is (shanten/ukeire already carries the likelihood signal;
    `bots/faanbot.py` combines the two rather than this module conflating them).
    """
    routes = reachable_routes(hand34, closed=closed)
    best_faan, best_route = max(routes, key=lambda r: r[0])
    if closed:
        best_faan += _SELF_DRAW_CONCEALED_BONUS
    return best_faan, best_route


def pattern_optionality(hand34: Sequence[int], *, closed: bool) -> int:
    """How many distinct routes are simultaneously reachable right now -- `w_flex *
    pattern_optionality` in docs/04-bots.md §4's formula, a mild preference for discards that
    keep more than one value route alive rather than committing early to a single one."""
    return len(reachable_routes(hand34, closed=closed))
