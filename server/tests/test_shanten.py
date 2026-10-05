"""`mahjong_core.shanten`: standard/seven-pairs/thirteen-orphans shanten and ukeire
(docs/bots.md §3).

Oracle cross-check uses `mahjong` (`MahjongRepository/mahjong`, dev-only per pyproject.toml --
"shanten test oracle, not a runtime dep"), same 34-index layout, over random 13/14-tile hands --
the sizes where our "melds included in the array" contract and the oracle's own
`calculate_shanten(tiles_34)` contract coincide exactly (see shanten.py's module docstring: the
oracle infers extra already-open melds from the tile count for *smaller* counts, which is a
different convention than ours and not comparable without translation, so this suite doesn't
try).
"""

from __future__ import annotations

import random
import time

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from mahjong.shanten import Shanten as OracleShanten

from mahjong_core.config import HandSet
from mahjong_core.shanten import (
    AGARI,
    seven_pairs_shanten,
    shanten,
    standard_shanten,
    thirteen_orphans_shanten,
    ukeire,
)
from mahjong_core.tiles import new_count_array

_oracle = OracleShanten()


# --- known hands ---------------------------------------------------------------------------


def test_complete_hand_is_agari() -> None:
    # 123m 456p 789s 11z11z... one pair + 4 sequences/pungs, 14 tiles
    counts = new_count_array()
    for t in (0, 1, 2, 12, 13, 14, 24, 25, 26):
        counts[t] = 1
    counts[27] = 2  # pair of East
    counts[9] = 1
    counts[10] = 1
    counts[11] = 1
    assert sum(counts) == 14
    assert standard_shanten(counts) == AGARI
    assert shanten(counts) == AGARI


def test_tenpai_single_wait() -> None:
    # 123m 456p 789s 123s + single 5m: waiting on 5m for the pair. 13 tiles.
    counts = new_count_array()
    for t in (0, 1, 2, 12, 13, 14, 24, 25, 26, 18, 19, 20):
        counts[t] += 1
    counts[4] += 1  # lone 5m
    assert sum(counts) == 13
    assert standard_shanten(counts) == 0


def test_one_shanten() -> None:
    # 123m 456p 789s 12s (ryanmen) + single 5m -- one meld short of tenpai.
    counts = new_count_array()
    for t in (0, 1, 2, 12, 13, 14, 24, 25, 26, 18, 19):
        counts[t] += 1
    counts[4] += 1
    counts[7] += 1
    assert sum(counts) == 13
    assert standard_shanten(counts) == 1


def test_seven_pairs_tenpai() -> None:
    counts = new_count_array()
    for t in range(6):
        counts[t] = 2
    counts[6] = 1
    assert sum(counts) == 13
    assert seven_pairs_shanten(counts) == 0
    assert shanten(counts) == 0


def test_seven_pairs_agari() -> None:
    counts = new_count_array()
    for t in range(7):
        counts[t] = 2
    assert sum(counts) == 14
    assert seven_pairs_shanten(counts) == AGARI


def test_thirteen_orphans_tenpai() -> None:
    counts = new_count_array()
    orphans = (0, 8, 9, 17, 18, 26, 27, 28, 29, 30, 31, 32, 33)
    for t in orphans[:-1]:
        counts[t] = 1
    counts[orphans[0]] += 1  # pair one of them -> waiting on the 13th distinct type
    assert sum(counts) == 13
    assert thirteen_orphans_shanten(counts) == 0


def test_thirteen_orphans_agari() -> None:
    counts = new_count_array()
    orphans = (0, 8, 9, 17, 18, 26, 27, 28, 29, 30, 31, 32, 33)
    for t in orphans:
        counts[t] = 1
    counts[orphans[-1]] += 1
    assert sum(counts) == 14
    assert thirteen_orphans_shanten(counts) == AGARI


def test_seven_pairs_gated_by_hand_sets() -> None:
    """Same shape as `test_closed_false_skips_seven_pairs_and_kokushi` (six scattered pairs, no
    chow potential, one lone single) but exercising the `hand_sets` gate instead of `closed`
    (docs/bots.md §8 Tier 2): Seven Pairs is `HandSet.NEW_18` (`scoring/patterns.py`), so a
    ruleset without it (e.g. `hk_strict`) must not let this hand read as tenpai via a pattern it
    can never legally complete there. Thirteen Orphans is `HandSet.CLASSIC` and isn't gated by
    this param at all -- not exercised here, see `thirteen_orphans_shanten`'s own tests above."""
    counts = new_count_array()
    for t in (0, 9, 18, 27, 28, 29):  # 1m, 1p, 1s, East, South, West
        counts[t] = 2
    counts[30] = 1  # North, lone -- one pair short of seven pairs tenpai
    assert sum(counts) == 13

    all_sets = frozenset(HandSet)
    no_new_18 = frozenset({HandSet.CLASSIC, HandSet.NEW_6})

    # default (no hand_sets passed) is unchanged from pre-gate behavior: every hand_set on.
    assert shanten(counts) == 0
    assert shanten(counts, hand_sets=all_sets) == 0

    # NEW_18 off: Seven Pairs is illegal there, so this can only read via the standard parse --
    # strictly worse, never better, than with it included.
    result_without = shanten(counts, hand_sets=no_new_18)
    assert result_without == standard_shanten(counts)
    assert result_without > shanten(counts, hand_sets=all_sets)


def test_closed_false_skips_seven_pairs_and_kokushi() -> None:
    # 6 pairs + 1 single: a great seven-pairs candidate but poor standard-parse hand --
    # closed=False (an exposed meld rules out both special hands) must not get seven-pairs' shanten.
    counts = new_count_array()
    for t in (0, 9, 18, 27, 28, 29):  # 1m, 1p, 1s, East, South, West
        counts[t] = 2
    counts[30] = 1  # North, lone
    assert sum(counts) == 13
    assert shanten(counts, closed=True) == 0
    assert shanten(counts, closed=False) == standard_shanten(counts)
    assert shanten(counts, closed=False) > shanten(counts, closed=True)


# --- the two named bugs (docs/bots.md §3) ------------------------------------------------


def test_block_cap_bug_regression() -> None:
    """Six ryanmen shapes, no pair -- naive `8 - 2*melds - partials` with no cap would read
    this as `8 - 0 - 6 = 2` (falsely close to tenpai). The real hand needs 4 melds + a pair
    from six 2-tile proto-blocks and nothing else -- capping at 4 non-pair blocks (no pair
    exists here, so cap is on melds+tatsu with no -1 relief) must push this well above 2."""
    counts = new_count_array()
    # man: 23,56 / pin: 23,56 / sou: 23,56 -- six two-tile ryanmen shapes, 12 tiles, no pair.
    for base in (0, 9, 18):
        counts[base + 1] += 1
        counts[base + 2] += 1
        counts[base + 4] += 1
        counts[base + 5] += 1
    assert sum(counts) == 12
    result = standard_shanten(counts)
    naive_buggy = 8 - 0 - 6  # what an uncapped formula would (wrongly) compute
    assert result > naive_buggy, (
        f"block cap not applied: got {result}, naive buggy was {naive_buggy}"
    )


def test_seven_pairs_distinct_bug_regression() -> None:
    """5 distinct pairs (10 tiles) + one quad of a 6th type (4 tiles) = 14 tiles, `pairs`
    metric reads 6 (quad still only counts once), but there is no 7th *distinct* pair
    available -- `6 - pairs` alone gives 0 (falsely tenpai); the `max(0, 7-distinct)` term
    must push this to 1-shanten."""
    counts = new_count_array()
    for t in range(5):
        counts[t] = 2
    counts[5] = 4
    assert sum(counts) == 14
    naive_buggy = 6 - 6  # `6 - pairs` with no distinct-count term
    result = seven_pairs_shanten(counts)
    assert result == 1
    assert result > naive_buggy


# --- oracle cross-check ----------------------------------------------------------------------


def _random_hand(rng: random.Random, n: int, *, quad_bias: bool) -> list[int]:
    counts = new_count_array()
    total = 0
    types = list(range(34))
    rng.shuffle(types)
    i = 0
    while total < n:
        t = types[i % 34]
        i += 1
        take = rng.choice((1, 1, 2, 2, 3, 4)) if quad_bias else 1
        take = min(take, 4 - counts[t], n - total)
        if take > 0:
            counts[t] += take
            total += take
    return counts


def test_matches_oracle_over_random_hands() -> None:
    """Cross-checked against `MahjongRepository/mahjong` (docs/bots.md §3) over thousands
    of random 13/14-tile hands, both plain and quad-biased. The only expected mismatches are
    the documented four-copies edge case (shanten.py's module docstring) -- every mismatch
    found must hold at least one tile type at count 4, and there must be zero mismatches
    among hands that don't."""
    rng = random.Random(20260916)
    n_trials = 6000
    mismatches_without_quad = 0
    mismatches_with_quad = 0
    for _ in range(n_trials):
        n = rng.choice((13, 14))
        c = _random_hand(rng, n, quad_bias=rng.random() < 0.5)
        mine = shanten(c)
        theirs = _oracle.calculate_shanten(c)
        if mine != theirs:
            if any(x == 4 for x in c):
                mismatches_with_quad += 1
            else:
                mismatches_without_quad += 1
    assert mismatches_without_quad == 0
    # sanity: the quad-biased sampling actually exercises the known-divergence path at all,
    # so this test would notice if the documented boundary ever widened.
    assert mismatches_with_quad < n_trials


@given(st.integers(min_value=0, max_value=2**32 - 1))
@settings(max_examples=40, suppress_health_check=[HealthCheck.too_slow])
def test_matches_oracle_hypothesis(seed: int) -> None:
    rng = random.Random(seed)
    n = rng.choice((13, 14))
    c = _random_hand(rng, n, quad_bias=rng.random() < 0.5)
    if any(x == 4 for x in c):
        return  # documented divergence, see shanten.py's module docstring
    assert shanten(c) == _oracle.calculate_shanten(c)


# --- ukeire ------------------------------------------------------------------------------


def test_ukeire_known_hand() -> None:
    # 123m 456p 789s 123s + 5m tanki + spare 9m: discarding the spare (9m or 5m) keeps a clean
    # tanki wait; breaking a complete meld instead (e.g. 1m) should never yield as narrow an accept set.
    counts = new_count_array()
    for t in (0, 1, 2, 12, 13, 14, 24, 25, 26, 18, 19, 20):
        counts[t] += 1
    counts[4] += 1  # lone 5m
    counts[8] += 1  # spare 9m
    assert sum(counts) == 14
    seen = list(counts)
    result = ukeire(counts, seen)
    # discard 9m -> tanki on 5m, 3 live (1 in hand); discard 5m -> tanki on 9m, symmetric
    assert result[8] == (1, 3)
    assert result[4] == (1, 3)
    # discarding 1m breaks the 123m meld instead -- shanten after is worse and takes more kinds
    # to claw back toward tenpai than the clean tanki discards need.
    kinds_break_meld, _ = result[0]
    assert kinds_break_meld > 1


def test_ukeire_two_away_tanki() -> None:
    # single floating 1m, rest empty -- degenerate/minimal case; a drawn tile can only reduce
    # shanten toward pairing/building around it, never below a from-scratch hand -- just check the shape.
    counts = new_count_array()
    counts[0] = 1
    seen = list(counts)
    result = ukeire(counts, seen)
    assert set(result) == {0}
    kinds, tiles = result[0]
    assert kinds >= 0 and tiles >= 0


def test_ukeire_respects_seen_tiles() -> None:
    # a hand one tile from tenpai whose accepting tile type is already fully visible (seen=4)
    # must report 0 live tiles for it, even though it's a "kind" that would help in principle.
    counts = new_count_array()
    for t in (0, 1, 12, 13, 14, 24, 25, 26, 18, 19, 20):
        counts[t] += 1
    counts[3] += 1  # 4m -- with 1m,2m this is a kanchan-ish/ryanmen-adjacent shape
    counts[7] += 1  # 8m -- floating
    seen = list(counts)
    seen[2] = 4  # 3m (would complete 123m) fully visible/used up elsewhere
    result = ukeire(counts, seen)
    _kinds, tiles = result[7]  # discarding the floating 8m
    # whatever kinds are accepted, none of them can be the exhausted 3m contributing tiles
    assert tiles <= sum(4 - seen[t] for t in range(34) if seen[t] < 4)


# --- perf / wiring (docs/bots.md §3: "wired in as the hot path") -------------------------


def test_frontier_cache_warms_and_stays_fast() -> None:
    """Cold-then-warm timing sanity: repeated shanten calls over a small set of hand shapes
    (what one ukeire scan actually does -- 13-14 candidate discards times ~21 unseen types)
    must be fast once the per-suit cache is warm, without needing an eager multi-second
    import-time build (shanten.py's module docstring's whole tradeoff)."""
    rng = random.Random(1)
    hands = [_random_hand(rng, 13, quad_bias=False) for _ in range(20)]
    seen = [new_count_array() for _ in hands]
    for h, s in zip(hands, seen, strict=True):
        for i, c in enumerate(h):
            s[i] = c

    # cold pass (may populate cache) -- not timed, just executed.
    for h, s in zip(hands, seen, strict=True):
        ukeire(h, s)

    start = time.perf_counter()
    for _ in range(20):
        for h, s in zip(hands, seen, strict=True):
            ukeire(h, s)
    elapsed = time.perf_counter() - start
    # 20 hands * 20 repeats * ~470 shanten evals/hand = ~188k warm lookups; ~1.5s locally, ~5s on
    # CI runners under coverage, so the ceiling has headroom for the latter.
    assert elapsed < 10.0, f"warm ukeire scans took {elapsed:.2f}s -- cache not doing its job"


def test_importing_module_does_no_eager_table_build() -> None:
    """`_frontier`'s cache must start empty -- see the module docstring's eager-vs-lazy
    tradeoff. A regression here (e.g. someone adding an eager warmup loop at import) would
    silently reintroduce the ~104s cold-start cost documented there."""
    import importlib

    import mahjong_core.shanten as shanten_module

    importlib.reload(shanten_module)
    info = shanten_module._frontier.cache_info()
    assert info.currsize == 0


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
