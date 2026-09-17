"""Shanten and ukeire (docs/04-bots.md §3).

stdlib-only, see mahjong_core/config.py's note on pyproject.toml.

**Contract: a plain 34-count array, melds included.** `standard_shanten`/`shanten` take the
*whole* hand as a 34-array -- concealed tiles plus 3 tiles per already-exposed meld (chow/pung),
and 3 (not 4) for a kong, dropping its 4th physical tile the same way most shanten
implementations treat a kong as "a pung, plus one already-drawn replacement tile accounted for
elsewhere" -- so the total is always a real hand size (13 mid-turn, 14 after a draw), and an
already-complete meld is simply rediscovered by the same recursive search as any other meld
shape, with no separate "how many melds are already banked" parameter to keep in sync. This is
also exactly `MahjongRepository/mahjong`'s `Shanten.calculate_shanten(tiles_34)` contract (module
docstring's own doctest), which is what makes the two directly comparable tile-for-tile in
`tests/test_shanten.py`'s oracle cross-check -- see that module for how the "3 tiles per meld,
drop the kong's 4th" conversion is done from a real `SeatState`.

**The two classic bugs this module exists to not have** (docs/04-bots.md §3):

1. **Block-count cap.** Counting every partial set found, uncapped, understates shanten for a
   hand with more than 4 melds' worth of proto-blocks (e.g. six ryanmen shapes, no pair) --
   `test_shanten.py::test_block_cap_bug_regression` pins this down against a hand that is far
   from tenpai but scores as if it were, without the cap below.
2. **Seven Pairs' `max(0, 7 - distinct)` term.** `6 - pairs` alone undercounts a hand with 6
   pairs of *distinct* types plus a quad of a 7th (`pairs` still reads 6, since a rank counted
   once whether it holds 2 or 4 copies) -- `test_shanten.py::test_seven_pairs_distinct_bug_regression`
   pins this down too.

**The per-suit lookup table** (docs/04-bots.md §3: "a scheduled M1/M4 deliverable... build the
table alongside T1"). `_frontier` is it: memoised via `functools.cache`, keyed on a suit's
9-rank (or honors' 7-rank) count tuple, returning the Pareto-optimal `(melds, tatsu, pairs)`
triples reachable from that exact tile shape. `standard_shanten` never re-walks a suit's tile
adjacency itself -- it only ever combines 4 already-known per-group answers (man/pin/sou/honors)
via a `itertools.product` over each group's (small, typically 1-4 point) frontier, which is
where "replacing the recursive scan" actually happens: the recursion that used to explore the
full 27-suited-slot space in one pass (`MahjongRepository/mahjong`'s `_RegularShanten._run`, the
oracle's own implementation) now only ever explores one suit's 9 slots at a time, and only once
per distinct shape for the lifetime of the process.

**Why lazy (`functools.cache`), not an eagerly-built or checked-in table.** The full suit table has
5**9 = 1,953,125 possible states (every rank 0-4, shared by man/pin/sou since they're
structurally identical -- only honors, with no sequences, get their own smaller 5**7 = 78,125
table). Measured eager generation of the full suit table (every one of the 5**9 vectors, cold)
at **~104s** of pure-Python recursion on this machine -- far too slow to pay on every process
start (this is a `ProcessPoolExecutor` worker pool per docs/04-bots.md §1; every worker process
would pay it, and a 500k-1.95M-entry table generated once and imported would need to be a
checked-in data file to avoid that, which is a real option but adds a `make`-generated-artifact
you must remember to regenerate if `_frontier`'s logic ever changes). A real game only ever
visits a few hundred to a few thousand *distinct* suit shapes across an entire session (13-14
tiles distributed over 4 groups, and adjacent shanten queries during one ukeire scan share
almost all of their sub-shapes) -- `functools.cache` populates exactly the shapes
actually seen, for free, and the cache is warm within the first hand or two of self-play. This
trades the ~104s worst-case *full* cost (never actually paid in practice) for a per-process
cache that's warm almost immediately and never recomputes a shape twice -- see
`tests/test_shanten.py`'s perf smoke test for the warm-cache-is-fast assertion this tradeoff
depends on, and its import-time test for the "importing this module does no eager work" half.

**Known, narrow divergence from the oracle.** `MahjongRepository/mahjong`'s `_RegularShanten`
carries a bolted-on correction (`_flag_four_copies`/`_flag_isolated_tiles` in its source) for
the case where a hand holds *all four copies* of some tile concealed **and** the winning
decomposition has zero pairs anywhere else -- the leftover 4th copy can never actually complete
a pair (there is no 5th tile in the game), so naively scoring it as a live wait understates
shanten by up to 2. Reproducing that correction exactly requires threading which *specific*
tiles ended up isolated through every Pareto-frontier point (not just the `(melds, tatsu,
pairs)` triple this module tracks), which is a real jump in complexity for a shape that isn't
one of docs/04-bots.md §3's two named bugs and that most real hands resolve by declaring the
kong long before it matters. Measured empirically instead of assumed: **0 divergences across
60,000 random 13/14-tile hands that don't hold all 4 copies of some tile type; every divergence
found does hold a tile at count 4** (`tests/test_shanten.py`'s oracle property test asserts this
exact boundary and is the regression check for this paragraph, not just a docstring claim).

**Pareto frontier, not a single best-per-suit answer.** Maximizing `2*melds + tatsu + pairs`
per suit independently and summing looks sufficient (melds are always weakly better than any
other block, and an excess tatsu/pair beyond the whole-hand cap is worth exactly zero net) but
under-covers one case: two suit-local options tied on that score but differing in raw block
count (`melds + tatsu + pairs`) are *not* interchangeable once the combined hand is right at the
5-block cap -- the option with fewer raw blocks can avoid tipping the whole hand over the cap
while the higher-block one doesn't. Keeping the small Pareto set (non-dominated on
`(score, -blocks)`) and letting `standard_shanten`'s `itertools.product` try every combination
handles this correctly without having to reason about it per suit.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from functools import cache

__all__ = [
    "AGARI",
    "seven_pairs_shanten",
    "shanten",
    "standard_shanten",
    "thirteen_orphans_shanten",
    "ukeire",
]

AGARI = -1
"""Shanten value for a complete (winning-shape) hand -- docs/04-bots.md §3: "0 = tenpai, -1 =
won"."""

_ORPHAN_INDICES = (0, 8, 9, 17, 18, 26, 27, 28, 29, 30, 31, 32, 33)
_CAP = 4


def _sub(counts: tuple[int, ...], *positions: int) -> tuple[int, ...]:
    out = list(counts)
    for p in positions:
        out[p] -= 1
    return tuple(out)


def _dominates(a: tuple[int, int, int], b: tuple[int, int, int]) -> bool:
    """Whether block-triple `a` is at least as good as `b` on both axes (higher score, no more
    raw blocks) and strictly better on one -- see module docstring's Pareto-frontier note."""
    score_a, score_b = 2 * a[0] + a[1] + a[2], 2 * b[0] + b[1] + b[2]
    blocks_a, blocks_b = sum(a), sum(b)
    return (
        score_a >= score_b and blocks_a <= blocks_b and (score_a > score_b or blocks_a < blocks_b)
    )


def _pareto(points: set[tuple[int, int, int]]) -> tuple[tuple[int, int, int], ...]:
    return tuple(p for p in points if not any(_dominates(q, p) for q in points if q != p))


@cache
def _frontier(counts: tuple[int, ...], sequences: bool) -> tuple[tuple[int, int, int], ...]:
    """Pareto-optimal `(melds, tatsu, pairs)` triples reachable from one suit's (or honors')
    count vector -- see module docstring. `sequences=False` (honors: 7 independent ranks, no
    chow/tatsu) reuses the same search with the run-forming branches simply never taken."""
    idx = next((i for i, c in enumerate(counts) if c > 0), None)
    if idx is None:
        return ((0, 0, 0),)

    results: set[tuple[int, int, int]] = set()

    def extend(sub_counts: tuple[int, ...], add: tuple[int, int, int]) -> None:
        for m, t, p in _frontier(sub_counts, sequences):
            results.add((m + add[0], t + add[1], p + add[2]))

    c = counts[idx]
    extend(_sub(counts, idx), (0, 0, 0))  # isolate one tile
    if c >= 2:
        extend(_sub(counts, idx, idx), (0, 0, 1))  # pair
    if c >= 3:
        extend(_sub(counts, idx, idx, idx), (1, 0, 0))  # pung
    if sequences:
        n = len(counts)
        if idx + 2 < n and counts[idx + 1] > 0 and counts[idx + 2] > 0:
            extend(_sub(counts, idx, idx + 1, idx + 2), (1, 0, 0))  # chow
        if idx + 1 < n and counts[idx + 1] > 0:
            extend(_sub(counts, idx, idx + 1), (0, 1, 0))  # ryanmen/penchan tatsu
        if idx + 2 < n and counts[idx + 2] > 0:
            extend(_sub(counts, idx, idx + 2), (0, 1, 0))  # kanchan tatsu

    return _pareto(results)


def standard_shanten(tiles34: Sequence[int]) -> int:
    """Standard-shape shanten (4 melds + 1 pair) -- min over every way to split man/pin/sou/
    honors into complete melds, partial sets, and (at most one) pair, block-cap applied
    (docs/04-bots.md §3, bug 1). `tiles34` per the module docstring: concealed tiles plus 3
    tiles per already-exposed meld, kongs contributing 3 of their 4."""
    groups = (
        _frontier(tuple(tiles34[0:9]), True),
        _frontier(tuple(tiles34[9:18]), True),
        _frontier(tuple(tiles34[18:27]), True),
        _frontier(tuple(tiles34[27:34]), False),
    )
    best: int | None = None
    for combo in itertools.product(*groups):
        melds = sum(c[0] for c in combo)
        tatsu = sum(c[1] for c in combo)
        pairs = sum(c[2] for c in combo)
        result = 8 - 2 * melds - tatsu - pairs
        blocks = melds + tatsu + (pairs - 1 if pairs > 0 else 0)
        if blocks > _CAP:
            result += blocks - _CAP
        if best is None or result < best:
            best = result
    assert best is not None
    return best


def seven_pairs_shanten(tiles34: Sequence[int]) -> int:
    """七對子 shanten: `6 - pairs + max(0, 7 - distinct)` (docs/04-bots.md §3, bug 2) --
    the `max(0, ...)` term is what stops 6 pairs-of-distinct-types + a 7th type's quad from
    reading as tenpai when it's actually 1-shanten (no 7th *distinct* pair available)."""
    pairs = sum(1 for c in tiles34 if c >= 2)
    distinct = sum(1 for c in tiles34 if c >= 1)
    return 6 - pairs + max(0, 7 - distinct)


def thirteen_orphans_shanten(tiles34: Sequence[int]) -> int:
    """十三么 shanten: `13 - distinct_terminals_honors - (1 if has_pair else 0)`."""
    present = sum(1 for i in _ORPHAN_INDICES if tiles34[i] >= 1)
    has_pair = any(tiles34[i] >= 2 for i in _ORPHAN_INDICES)
    return 13 - present - (1 if has_pair else 0)


def shanten(tiles34: Sequence[int], *, closed: bool = True) -> int:
    """Overall shanten: the minimum of all three parses (docs/04-bots.md §3). `closed=False`
    (any exposed meld present) skips Seven Pairs/Thirteen Orphans -- both require a fully
    concealed hand by construction (`mahjong_core.actions.hand_is_winning_shape`'s same rule),
    so evaluating them against a hand with an exposed meld baked into `tiles34` would either
    error or silently produce a meaningless number depending on shape.
    """
    best = standard_shanten(tiles34)
    if closed:
        best = min(best, seven_pairs_shanten(tiles34), thirteen_orphans_shanten(tiles34))
    return best


def ukeire(
    hand34: Sequence[int], seen34: Sequence[int], *, closed: bool = True
) -> dict[int, tuple[int, int]]:
    """For each tile type actually held, how many unseen tiles reduce shanten if drawn after
    discarding it -- docs/04-bots.md §3. `-> {tile_type_value: (kinds_accepted, tiles_accepted)}`.
    `seen34` counts everything publicly visible plus the hand itself; never the wall.
    """
    result: dict[int, tuple[int, int]] = {}
    after = list(hand34)
    for d in range(34):
        if hand34[d] == 0:
            continue
        after[d] -= 1
        base = shanten(after, closed=closed)
        kinds = tiles = 0
        for t in range(34):
            live = 4 - seen34[t]
            if live <= 0:
                continue
            after[t] += 1
            if shanten(after, closed=closed) < base:
                kinds += 1
                tiles += live
            after[t] -= 1
        after[d] += 1
        result[d] = (kinds, tiles)
    return result
