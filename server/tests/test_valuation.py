"""Golden fixtures for `bots/valuation.py` (docs/bots.md §4).

Two kinds of coverage, per this sub-task's testing requirements: (1) `ROUTE_FAAN`'s constants
cross-checked directly against the real scorer (`mahjong_core.scoring.patterns.score_hand`) on
a real, physically legal winning hand for each route -- so the numbers this module hard-codes
can't silently drift from what the engine actually awards; (2) the threshold logic itself
(`reachable_routes`/`estimate_best_faan`/`pattern_optionality`), exercised directly against
hand-built 34-count arrays at and around each documented commit threshold.

`test_valuation_selfplay.py` holds the organic self-play validation (real `RandomBot` games,
comparing this module's estimate against actual awarded faan) -- kept separate because it's
slower (plays real games) and is itself the measurement this module's docstring reports, not a
pass/fail regression suite of the same kind as the fixtures below.
"""

from __future__ import annotations

import pytest

from app.views import SeatView
from bots.valuation import (
    ROUTE_FAAN,
    estimate_best_faan,
    exact_wait_value,
    pattern_optionality,
    reachable_routes,
    route_faan_for,
)
from mahjong_core.config import RuleSet
from mahjong_core.melds import Meld, MeldKind
from mahjong_core.scoring.faan import score_winning_hand
from mahjong_core.scoring.patterns import ScoringContext, score_hand
from mahjong_core.state import Phase, Wind
from mahjong_core.tiles import TileType, tile_ids_for_type


def _chow(low: TileType) -> Meld:
    ids = tuple(tile_ids_for_type(TileType(int(low) + k))[0] for k in range(3))
    return Meld(MeldKind.CHOW, ids)


def _pung(tile_type: TileType, *, offset: int = 0) -> Meld:
    return Meld(MeldKind.PUNG, tile_ids_for_type(tile_type)[offset : offset + 3])


def _pair(tile_type: TileType, *, offset: int = 0) -> Meld:
    return Meld(MeldKind.PAIR, tile_ids_for_type(tile_type)[offset : offset + 2])


def _ctx() -> ScoringContext:
    return ScoringContext(
        seat_wind=Wind.SOUTH, prevailing_wind=Wind.SOUTH, self_drawn=False, flowers=()
    )


def _hand34(*types: TileType) -> list[int]:
    counts = [0] * 34
    for t in types:
        counts[int(t)] += 1
    return counts


def _routes(hand34: list[int], *, closed: bool) -> dict[str, int]:
    return {name: faan for faan, name in reachable_routes(hand34, closed=closed)}


# --- ROUTE_FAAN constants, cross-checked against the real scorer ----------------------------


def test_half_flush_route_faan_matches_real_scorer() -> None:
    hand = (
        _pung(TileType.MAN_1),
        _chow(TileType.MAN_2),
        _chow(TileType.MAN_5),
        _pung(TileType.MAN_9),
        _pair(TileType.WIND_EAST),
    )
    assert score_hand(hand, _ctx())["混一色"] == ROUTE_FAAN["half_flush"]


def test_full_flush_route_faan_matches_real_scorer() -> None:
    hand = (
        _chow(TileType.MAN_1),
        _chow(TileType.MAN_1),
        _chow(TileType.MAN_4),
        _chow(TileType.MAN_7),
        _pair(TileType.MAN_9, offset=1),
    )
    assert score_hand(hand, _ctx())["清一色"] == ROUTE_FAAN["full_flush"]


def test_all_pungs_route_faan_matches_real_scorer() -> None:
    hand = (
        _pung(TileType.MAN_1),
        Meld(MeldKind.PUNG, tile_ids_for_type(TileType.PIN_5)[:3], from_seat=2),
        _pung(TileType.SOU_9),
        _pung(TileType.WIND_EAST),
        _pair(TileType.DRAGON_RED),
    )
    assert score_hand(hand, _ctx())["對對糊"] == ROUTE_FAAN["all_pungs"]


def test_small_three_dragons_route_faan_matches_real_scorer() -> None:
    hand = (
        _pung(TileType.DRAGON_RED),
        _pung(TileType.DRAGON_GREEN),
        _pung(TileType.MAN_1),
        _chow(TileType.PIN_2),
        _pair(TileType.DRAGON_WHITE),
    )
    assert score_hand(hand, _ctx())["小三元"] == ROUTE_FAAN["small_three_dragons"]


def test_voided_suit_route_faan_matches_real_scorer() -> None:
    hand = (
        _pung(TileType.MAN_1),
        _chow(TileType.PIN_2),
        _pung(TileType.WIND_EAST),
        _chow(TileType.PIN_5),
        _pair(TileType.DRAGON_RED),
    )
    assert score_hand(hand, _ctx())["缺一門"] == ROUTE_FAAN["voided_suit"]


def test_all_sequences_route_faan_matches_real_scorer() -> None:
    hand = (
        _chow(TileType.MAN_1),
        _chow(TileType.PIN_2),
        _chow(TileType.SOU_4),
        _chow(TileType.MAN_5),
        _pair(TileType.SOU_9),
    )
    assert score_hand(hand, _ctx())["平糊"] == ROUTE_FAAN["all_sequences"]


# --- threshold logic, directly against hand34 arrays -----------------------------------------


def test_half_flush_needs_seven_tiles_in_suit_plus_honors() -> None:
    below = _hand34(
        TileType.MAN_2,
        TileType.MAN_3,
        TileType.MAN_4,
        TileType.MAN_5,
        TileType.WIND_EAST,
        TileType.WIND_EAST,
    )  # 4 man + 2 honor = 6, below the 7-tile threshold
    assert "half_flush" not in _routes(below, closed=True)

    at_threshold = _hand34(
        TileType.MAN_1,
        TileType.MAN_2,
        TileType.MAN_3,
        TileType.MAN_4,
        TileType.MAN_5,
        TileType.WIND_EAST,
        TileType.WIND_EAST,
    )  # 5 man + 2 honor = 7
    assert _routes(at_threshold, closed=True)["half_flush"] == ROUTE_FAAN["half_flush"]


def test_full_flush_needs_nine_tiles_no_honors() -> None:
    eight = [0] * 34
    for r in range(8):
        eight[r] = 1
    assert "full_flush" not in _routes(eight, closed=True)

    nine = [0] * 34
    for r in range(9):
        nine[r] = 1
    assert _routes(nine, closed=True)["full_flush"] == ROUTE_FAAN["full_flush"]


def test_full_flush_excluded_once_a_single_honor_appears() -> None:
    hand = [0] * 34
    for r in range(8):
        hand[r] = 1
    hand[int(TileType.WIND_EAST)] = 1
    routes = _routes(hand, closed=True)
    assert "full_flush" not in routes
    assert routes["half_flush"] == ROUTE_FAAN["half_flush"]


def test_voided_suit_needs_exactly_two_suits() -> None:
    one_suit = _hand34(TileType.MAN_1, TileType.MAN_2)
    assert "voided_suit" not in _routes(one_suit, closed=True)

    two_suits = _hand34(TileType.MAN_1, TileType.PIN_2)
    assert _routes(two_suits, closed=True)["voided_suit"] == ROUTE_FAAN["voided_suit"]

    three_suits = _hand34(TileType.MAN_1, TileType.PIN_2, TileType.SOU_3)
    assert "voided_suit" not in _routes(three_suits, closed=True)


def test_seven_pairs_needs_four_pairs_and_a_closed_hand() -> None:
    three_pairs = _hand34(
        TileType.MAN_1,
        TileType.MAN_1,
        TileType.MAN_2,
        TileType.MAN_2,
        TileType.MAN_3,
        TileType.MAN_3,
        TileType.MAN_4,
    )
    assert "seven_pairs" not in _routes(three_pairs, closed=True)

    four_pairs = _hand34(
        TileType.MAN_1,
        TileType.MAN_1,
        TileType.MAN_2,
        TileType.MAN_2,
        TileType.MAN_3,
        TileType.MAN_3,
        TileType.MAN_4,
        TileType.MAN_4,
    )
    assert _routes(four_pairs, closed=True)["seven_pairs"] == ROUTE_FAAN["seven_pairs"]
    assert "seven_pairs" not in _routes(four_pairs, closed=False)


def test_small_three_dragons_needs_two_dragon_pairs() -> None:
    one_pair = _hand34(TileType.DRAGON_RED, TileType.DRAGON_RED)
    assert "small_three_dragons" not in _routes(one_pair, closed=True)

    two_pairs = _hand34(
        TileType.DRAGON_RED, TileType.DRAGON_RED, TileType.DRAGON_GREEN, TileType.DRAGON_GREEN
    )
    routes = _routes(two_pairs, closed=True)
    assert routes["small_three_dragons"] == ROUTE_FAAN["small_three_dragons"]


def test_empty_shape_falls_back_to_all_sequences_floor() -> None:
    scattered = _hand34(TileType.MAN_1, TileType.PIN_4, TileType.SOU_7)
    assert _routes(scattered, closed=True) == {"all_sequences": ROUTE_FAAN["all_sequences"]}


def test_estimate_best_faan_adds_closed_bonus() -> None:
    hand = _hand34(
        TileType.MAN_1,
        TileType.MAN_2,
        TileType.MAN_3,
        TileType.MAN_4,
        TileType.MAN_5,
        TileType.WIND_EAST,
        TileType.WIND_EAST,
    )
    faan_open, route_open = estimate_best_faan(hand, closed=False)
    faan_closed, route_closed = estimate_best_faan(hand, closed=True)
    assert route_open == route_closed == "half_flush"
    assert faan_closed == faan_open + 2


def test_estimate_best_faan_picks_the_highest_reachable_route() -> None:
    # A one-suit, all-pung hand structurally reaches both full_flush (6) and all_pungs (3) --
    # the higher one should win.
    hand = _hand34(
        TileType.MAN_1,
        TileType.MAN_1,
        TileType.MAN_1,
        TileType.MAN_3,
        TileType.MAN_3,
        TileType.MAN_3,
        TileType.MAN_5,
        TileType.MAN_5,
        TileType.MAN_5,
    )
    faan, route = estimate_best_faan(hand, closed=False)
    assert route == "full_flush"
    assert faan == ROUTE_FAAN["full_flush"]


def test_pattern_optionality_counts_distinct_reachable_routes() -> None:
    scattered = _hand34(TileType.MAN_1, TileType.PIN_4, TileType.SOU_7)
    assert pattern_optionality(scattered, closed=True) == 1  # only the all_sequences floor

    # voided_suit, small_three_dragons, and all_pungs all reach threshold at once here ->
    # optionality 3, not the all_sequences floor (only added when nothing else is reachable).
    multi_route = _hand34(
        TileType.MAN_1,
        TileType.PIN_2,
        TileType.DRAGON_RED,
        TileType.DRAGON_RED,
        TileType.DRAGON_GREEN,
        TileType.DRAGON_GREEN,
    )
    assert pattern_optionality(multi_route, closed=True) == 3


# --- faan_overrides-aware ROUTE_FAAN (docs/bots.md §8 Tier 2) ----------------------------


def test_route_faan_for_empty_overrides_returns_route_faan_unchanged() -> None:
    """`{}` is `RuleSet.faan_overrides`'s default for every existing preset and every
    pre-existing test -- `route_faan_for` must reproduce `ROUTE_FAAN` byte-identically (the
    same object, not just an equal copy) so every caller that doesn't thread a ruleset through
    keeps its exact prior behavior."""
    assert route_faan_for({}) is ROUTE_FAAN


def test_route_faan_for_applies_an_override_via_the_pattern_name_mapping() -> None:
    """`faan_overrides` is keyed by the Chinese pattern name `scoring/patterns.py`'s registry
    uses (混一色 = Half Flush), not the English route name `ROUTE_FAAN` uses -- this is the
    route-name -> pattern-name mapping the module docstring for `route_faan_for` describes.
    Every other route stays at its `ROUTE_FAAN` default; a name absent from `faan_overrides`
    (e.g. an unrelated pattern) doesn't perturb anything."""
    overridden = route_faan_for({"混一色": 10, "雞糊": 0})
    assert overridden["half_flush"] == 10
    assert overridden["full_flush"] == ROUTE_FAAN["full_flush"]
    assert overridden["voided_suit"] == ROUTE_FAAN["voided_suit"]


def test_estimate_best_faan_reads_route_faan_override() -> None:
    """A one-suit, no-honor 9+ tile hand reaches both `full_flush` (6) and `half_flush` (3) --
    `full_flush` wins by default (matches `test_estimate_best_faan_picks_the_highest_reachable_
    route`). Overriding `混一色` (Half Flush) to 20 via `route_faan_for` must flip which route
    `estimate_best_faan` reports as best, proving the override actually reaches the value
    estimator, not just `reachable_routes`'s raw list."""
    hand = _hand34(
        TileType.MAN_1,
        TileType.MAN_1,
        TileType.MAN_1,
        TileType.MAN_3,
        TileType.MAN_3,
        TileType.MAN_3,
        TileType.MAN_5,
        TileType.MAN_5,
        TileType.MAN_5,
    )
    faan_default, route_default = estimate_best_faan(hand, closed=False)
    assert route_default == "full_flush"
    assert faan_default == ROUTE_FAAN["full_flush"]

    route_faan = route_faan_for({"混一色": 20})
    faan_overridden, route_overridden = estimate_best_faan(
        hand, closed=False, route_faan=route_faan
    )
    assert route_overridden == "half_flush"
    assert faan_overridden == 20


def test_estimate_best_faan_with_empty_overrides_matches_the_fixed_default() -> None:
    """Same hand as `test_estimate_best_faan_picks_the_highest_reachable_route`, run through
    `route_faan_for({})` explicitly -- must match the no-`route_faan`-argument call exactly,
    pinning that an empty `faan_overrides` reproduces today's fixed `ROUTE_FAAN` behavior
    structurally, not just "probably" (docs/decisions/0014-ruleset-aware-bots.md)."""
    hand = _hand34(
        TileType.MAN_1,
        TileType.MAN_1,
        TileType.MAN_1,
        TileType.MAN_3,
        TileType.MAN_3,
        TileType.MAN_3,
        TileType.MAN_5,
        TileType.MAN_5,
        TileType.MAN_5,
    )
    assert estimate_best_faan(hand, closed=False) == estimate_best_faan(
        hand, closed=False, route_faan=route_faan_for({})
    )


# --- exact_wait_value: real-scorer tenpai valuation (ORACLE, ADR 0019 §5.2) -------------------


def _wait_view(melds: tuple[Meld, ...], concealed: tuple[TileType, ...]) -> SeatView:
    used: dict[TileType, int] = {}
    ids = []
    for t in concealed:
        n = used.get(t, 0)
        ids.append(tile_ids_for_type(t)[n])
        used[t] = n + 1
    return SeatView(
        seat=1,
        hand_no=1,
        prevailing=Wind.EAST,
        dealer=0,
        turn=1,
        phase=Phase.AWAIT_ACTION,
        own_hand=tuple(ids),
        concealed_counts=(13, len(ids), 13, 13),
        melds=((), melds, (), ()),
        discard_pools=((), (), (), ()),
        flowers=((), (), (), ()),
        wall_remaining=50,
        seat_status=("bot", "bot", "bot", "bot"),
        names=(None, None, None, None),
        scores=(0, 0, 0, 0),
        legal_actions=(),
        claim_options=(),
        deadline_ts=None,
        host_seat=None,
        ruleset=RuleSet(),
        hands=None,
    )


_SOU_5 = int(TileType.SOU_5)
_CLAIMED_RED_PUNG = Meld(MeldKind.PUNG, tile_ids_for_type(TileType.DRAGON_RED)[:3], from_seat=0)
_CLAIMED_PIN_CHOW = Meld(
    MeldKind.CHOW,
    tuple(tile_ids_for_type(TileType(int(TileType.PIN_2) + k))[0] for k in range(3)),
    from_seat=0,
)
# 123m 456m + 5s tanki
_TANKI_CONCEALED = (
    TileType.MAN_1,
    TileType.MAN_2,
    TileType.MAN_3,
    TileType.MAN_4,
    TileType.MAN_5,
    TileType.MAN_6,
    TileType.SOU_5,
)


def _seen_with(tile_type: int, n: int) -> list[int]:
    seen = [0] * 34
    seen[tile_type] = n
    return seen


def _real_faan(view: SeatView, *, self_drawn: bool) -> int:
    candidate = (*view.own_hand, tile_ids_for_type(TileType.SOU_5)[3])
    ctx = ScoringContext(
        seat_wind=Wind.SOUTH, prevailing_wind=Wind.EAST, self_drawn=self_drawn, flowers=()
    )
    return score_winning_hand(candidate, view.melds[1], ctx, view.ruleset).total_faan


def test_exact_wait_value_scores_ron_copies_in_the_discard_context() -> None:
    view = _wait_view((_CLAIMED_RED_PUNG,), _TANKI_CONCEALED)
    self_faan, ron_faan = _real_faan(view, self_drawn=True), _real_faan(view, self_drawn=False)
    assert self_faan > ron_faan >= view.ruleset.min_faan  # an open hand loses 自摸 on a ron

    assert exact_wait_value(view, view.own_hand, [_SOU_5], _seen_with(_SOU_5, 2), {}) == (
        2.0,
        self_faan,
    )
    acceptance, value = exact_wait_value(
        view, view.own_hand, [_SOU_5], _seen_with(_SOU_5, 2), {_SOU_5: 1.0}
    )
    assert acceptance == 3.0
    assert value == pytest.approx((2 * self_faan + ron_faan) / 3)


def test_exact_wait_value_counts_nothing_for_a_sub_minimum_context() -> None:
    view = _wait_view((_CLAIMED_PIN_CHOW,), _TANKI_CONCEALED)
    assert _real_faan(view, self_drawn=False) < view.ruleset.min_faan
    assert _real_faan(view, self_drawn=True) >= view.ruleset.min_faan

    ron_only = exact_wait_value(view, view.own_hand, [_SOU_5], _seen_with(_SOU_5, 4), {_SOU_5: 1.0})
    assert ron_only == (0.0, 0.0)
    both = exact_wait_value(view, view.own_hand, [_SOU_5], _seen_with(_SOU_5, 3), {_SOU_5: 1.0})
    assert both == (1.0, _real_faan(view, self_drawn=True))


def test_exact_wait_value_counts_nothing_for_a_dead_wait() -> None:
    view = _wait_view((_CLAIMED_RED_PUNG,), _TANKI_CONCEALED)
    assert exact_wait_value(view, view.own_hand, [_SOU_5], _seen_with(_SOU_5, 4), {}) == (0.0, 0.0)
