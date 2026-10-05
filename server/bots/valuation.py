"""Hand-value estimation for T2 `FaanBot` (docs/bots.md §4): fast structural proxy for "faan
of the best reachable pattern from this hand shape", used to rank discards by value, not to
predict a real score.

Proxy, not the real scorer: `score_winning_hand` only scores a complete 14-tile hand; this reads
route eligibility off the 34-count array instead.

Validated against `score_hand`: `tests/test_valuation_selfplay.py` (slow) measured mean absolute
error 2.46 faan over 67 real `RandomBot` wins -- large because real wins often carry situational/
win-timing faan (箭刻, flowers, timing sets) this module doesn't model.

Still safe to rank discards with: the omitted bonuses are close to shape-independent, so they
shift every candidate's estimate by about the same amount and barely disturb relative order --
which is all ranking needs. Not safe as an absolute faan prediction.

`exact_wait_value` is the exception: real-scorer faan for an already-tenpai hand, used only by
`ORACLE` (docs/bots.md §9), where every wait's live copies are known.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.views import SeatView
from bots.safety import synthetic_tile_id
from mahjong_core.actions import hand_is_winning_shape
from mahjong_core.melds import Meld
from mahjong_core.scoring.faan import score_winning_hand
from mahjong_core.scoring.patterns import ScoringContext, seat_wind_for
from mahjong_core.state import SeatState
from mahjong_core.tiles import TileId, TileType

__all__ = [
    "ROUTE_FAAN",
    "estimate_best_faan",
    "exact_wait_value",
    "pattern_optionality",
    "reachable_routes",
    "route_faan_for",
]

_HONOR_START = 27
_RANKS_PER_SUIT = 9
_DRAGON_TYPES = (int(TileType.DRAGON_RED), int(TileType.DRAGON_GREEN), int(TileType.DRAGON_WHITE))

# base faan per route, before closed bonus (docs/bots.md §4). "Half Flush + dragon/wind pung"
# isn't modeled separately -- it's half_flush + a dragon block bumping small_three_dragons.
ROUTE_FAAN: dict[str, int] = {
    "full_flush": 7,
    "half_flush": 3,
    "all_pungs": 3,
    "small_three_dragons": 5,
    "seven_pairs": 4,
    "all_sequences": 1,  # 平糊 -- the floor every hand can reach, T1's whole failure mode
}

# route name -> Chinese pattern name (RuleSet.faan_overrides / scoring/patterns.py's registry key,
# docs/bots.md §8 Tier 2); every ROUTE_FAAN value is pinned against it in tests/test_valuation.py.
_ROUTE_PATTERN_NAMES: dict[str, str] = {
    "full_flush": "清一色",
    "half_flush": "混一色",
    "all_pungs": "對對糊",
    "small_three_dragons": "小三元",
    "seven_pairs": "七對子",
    "all_sequences": "平糊",
}


def route_faan_for(faan_overrides: Mapping[str, int]) -> dict[str, int]:
    """`ROUTE_FAAN` with `faan_overrides` applied via `_ROUTE_PATTERN_NAMES`. Empty overrides --
    every ruleset preset and every pre-existing test -- returns `ROUTE_FAAN` itself unchanged,
    so callers that skip this (or pass the default `route_faan=ROUTE_FAAN`) see byte-identical
    behavior to before `faan_overrides` was threaded through."""
    if not faan_overrides:
        return ROUTE_FAAN
    return {
        route: faan_overrides.get(_ROUTE_PATTERN_NAMES[route], base)
        for route, base in ROUTE_FAAN.items()
    }


_HALF_FLUSH_MIN_TILES = 7
_FULL_FLUSH_MIN_TILES = 9
_ALL_PUNGS_MIN_BLOCKS = 2
_ALL_PUNGS_MAX_SEQUENCE_POTENTIAL = 1
_SMALL_DRAGONS_MIN_PAIRS = 2
_SEVEN_PAIRS_MIN_PAIRS = 4
"""Doc's "honors-heavy" qualifier isn't checked separately: any 4+ pair-types already signals
seven-pairs shanten, and restricting to honors-heavy hands would miss real all-suit cases."""
_SELF_DRAW_CONCEALED_BONUS = 2
"""Additive bonus, not its own route -- requires staying closed regardless of which other route
is taken."""


def _suits_present(hand34: Sequence[int]) -> set[int]:
    return {t // _RANKS_PER_SUIT for t in range(_HONOR_START) if hand34[t] > 0}


def _honors_present(hand34: Sequence[int]) -> bool:
    return any(hand34[t] > 0 for t in range(_HONOR_START, 34))


def _sequence_potential(hand34: Sequence[int]) -> int:
    """Rough count of "could still grow into a chow" spots -- gates All Pungs off when the hand
    has real sequence shape. Not a precise tatsu count (`mahjong_core.shanten` owns that); cheap
    enough to run per candidate discard."""
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


def reachable_routes(
    hand34: Sequence[int], *, closed: bool, route_faan: dict[str, int] = ROUTE_FAAN
) -> list[tuple[int, str]]:
    """Every route this hand shape's commit threshold already clears, as `(base_faan,
    route_name)` -- always non-empty (falls back to `all_sequences`). Suit-based routes mirror
    `mahjong_core.scoring.patterns`' own suit-count conditions, so they can't overlap.

    `route_faan` defaults to the fixed `ROUTE_FAAN` table; pass `route_faan_for(ruleset.
    faan_overrides)` to rank by the active ruleset's real per-pattern values instead."""
    routes: list[tuple[int, str]] = []
    suits = _suits_present(hand34)
    honors = _honors_present(hand34)

    if len(suits) == 1:
        (suit,) = suits
        base = suit * _RANKS_PER_SUIT
        tiles_in_suit = sum(hand34[base : base + _RANKS_PER_SUIT])
        if not honors and tiles_in_suit >= _FULL_FLUSH_MIN_TILES:
            routes.append((route_faan["full_flush"], "full_flush"))
        tiles_in_suit_and_honors = tiles_in_suit + sum(hand34[_HONOR_START:34])
        if tiles_in_suit_and_honors >= _HALF_FLUSH_MIN_TILES:
            routes.append((route_faan["half_flush"], "half_flush"))

    block_types = sum(1 for c in hand34 if c >= 2)
    if (
        block_types >= _ALL_PUNGS_MIN_BLOCKS
        and _sequence_potential(hand34) <= _ALL_PUNGS_MAX_SEQUENCE_POTENTIAL
    ):
        routes.append((route_faan["all_pungs"], "all_pungs"))

    dragon_pairs = sum(1 for t in _DRAGON_TYPES if hand34[t] >= 2)
    if dragon_pairs >= _SMALL_DRAGONS_MIN_PAIRS:
        routes.append((route_faan["small_three_dragons"], "small_three_dragons"))

    if closed:
        pair_types = sum(1 for c in hand34 if c >= 2)
        if pair_types >= _SEVEN_PAIRS_MIN_PAIRS:
            routes.append((route_faan["seven_pairs"], "seven_pairs"))

    if not routes:
        routes.append((route_faan["all_sequences"], "all_sequences"))
    return routes


def estimate_best_faan(
    hand34: Sequence[int], *, closed: bool, route_faan: dict[str, int] = ROUTE_FAAN
) -> tuple[int, str]:
    """`(estimated_faan, route_name)` for the best reachable route, plus the closed bonus --
    `E[faan | best reachable pattern]`, not weighted by likelihood of completion (that's
    shanten/ukeire's job; `bots/faanbot.py` combines the two)."""
    routes = reachable_routes(hand34, closed=closed, route_faan=route_faan)
    best_faan, best_route = max(routes, key=lambda r: r[0])
    if closed:
        best_faan += _SELF_DRAW_CONCEALED_BONUS
    return best_faan, best_route


def pattern_optionality(
    hand34: Sequence[int], *, closed: bool, route_faan: dict[str, int] = ROUTE_FAAN
) -> int:
    """How many distinct routes are reachable right now -- rewards discards that keep more than
    one value route alive rather than committing early."""
    return len(reachable_routes(hand34, closed=closed, route_faan=route_faan))


def _wait_faan(
    view: SeatView,
    concealed: Sequence[TileId],
    melds: tuple[Meld, ...],
    wait: int,
    *,
    self_drawn: bool,
) -> int:
    """Real faan of completing this seat's hand on `wait`, or 0 below `min_faan`."""
    assert view.seat is not None
    synthetic = synthetic_tile_id(wait, concealed)
    if synthetic is None:
        return 0
    candidate = (*concealed, synthetic)
    if not hand_is_winning_shape(SeatState(concealed=candidate, melds=melds)):
        return 0
    ctx = ScoringContext(
        seat_wind=seat_wind_for(view.seat, view.dealer),
        prevailing_wind=view.prevailing,
        self_drawn=self_drawn,
        flowers=view.flowers[view.seat],
        flowers_score=view.ruleset.flowers_score,
        winning_tile=None if self_drawn else candidate[-1],
    )
    result = score_winning_hand(candidate, melds, ctx, view.ruleset)
    return result.total_faan if result.clears_min_faan else 0


def exact_wait_value(
    view: SeatView,
    concealed: Sequence[TileId],
    waits: Sequence[int],
    seen: Sequence[int],
    ron: Mapping[int, float],
    *,
    melds: tuple[Meld, ...] | None = None,
) -> tuple[float, float]:
    """`(acceptance, value)` of a tenpai hand scored with the real scorer, per wait: live wall
    copies (`4 - seen`) in the self-draw context, plus `ron` credited copies in the discard
    context. A wait that can't clear `min_faan` in a context adds nothing in it; `value` is the
    copy-weighted mean faan, 0 when nothing clears. Exact only when `seen` is hands-aware
    (`ORACLE`, docs/bots.md §9) -- otherwise opponents' tiles read as live."""
    assert view.seat is not None
    own_melds = view.melds[view.seat] if melds is None else melds
    acceptance = total = 0.0
    for w in waits:
        live = 4 - seen[w]
        if live > 0 and (faan := _wait_faan(view, concealed, own_melds, w, self_drawn=True)):
            acceptance += live
            total += live * faan
        copies = ron.get(w, 0.0)
        if copies and (faan := _wait_faan(view, concealed, own_melds, w, self_drawn=False)):
            acceptance += copies
            total += copies * faan
    return acceptance, (total / acceptance if acceptance else 0.0)
