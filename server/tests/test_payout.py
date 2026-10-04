"""Tests for mahjong_core/scoring/payout.py (docs/testing.md §1):
faan -> points table lookup and per-seat payment splits (docs/rules.md §8).
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from mahjong_core.config import DiscardPayment, RuleSet, ScoreTable
from mahjong_core.scoring.payout import Discard, SelfDraw, payout, points

_FULL_SPICY = RuleSet(score_table=ScoreTable.FULL_SPICY, min_faan=0)
_HALF_SPICY = RuleSet(score_table=ScoreTable.HALF_SPICY, min_faan=0)


# --- points() ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("faan", "expected"),
    [(0, 1), (1, 2), (3, 8), (4, 16), (10, 1024), (13, 8192)],
)
def test_points_full_spicy(faan: int, expected: int) -> None:
    assert points(faan, _FULL_SPICY) == expected


@pytest.mark.parametrize(
    ("faan", "expected"),
    # rules.md §8's worked values, plus the 0-2 baseline and the 11-13 extension.
    [
        (0, 1),
        (1, 2),
        (2, 4),
        (3, 8),
        (4, 16),
        (5, 24),
        (6, 32),
        (7, 48),
        (8, 64),
        (9, 96),
        (10, 128),
        (11, 192),
        (12, 256),
        (13, 384),
    ],
)
def test_points_half_spicy(faan: int, expected: int) -> None:
    assert points(faan, _HALF_SPICY) == expected


def test_points_cap_boundary_faan_cap_10() -> None:
    ruleset = replace(_FULL_SPICY, faan_cap=10)
    assert points(10, ruleset) == 1024


def test_points_cap_boundary_faan_cap_13() -> None:
    ruleset = replace(_HALF_SPICY, faan_cap=13)
    assert points(13, ruleset) == 384


def test_points_out_of_range_rejected() -> None:
    with pytest.raises(ValueError):
        points(14, _FULL_SPICY)
    with pytest.raises(ValueError):
        points(-1, _FULL_SPICY)


# --- payout(): self-draw -----------------------------------------------------------------------


def test_self_draw_split_matches_worked_example() -> None:
    # §8 worked example: 3 faan, full spicy -> P=8. Self-draw: each loser -4, winner +12.
    p = points(3, _FULL_SPICY)
    result = payout(0, p, SelfDraw(), dealer_seat=3, ruleset=_FULL_SPICY)
    assert result == {0: 12, 1: -4, 2: -4, 3: -4}


def test_self_draw_split_at_low_points_rounds_up_and_balances() -> None:
    # faan=0 -> P=1 (only legal at min_faan=0). 0.5 rounds up to 1 per loser.
    result = payout(2, 1, SelfDraw(), dealer_seat=0, ruleset=_FULL_SPICY)
    assert result == {0: -1, 1: -1, 2: 3, 3: -1}


# --- payout(): discard win -----------------------------------------------------------------------


def test_discard_win_pays_all() -> None:
    ruleset = replace(_FULL_SPICY, discard_payment=DiscardPayment.ALL)
    p = points(3, ruleset)
    result = payout(0, p, Discard(discarder_seat=2), dealer_seat=3, ruleset=ruleset)
    assert result == {0: 8, 1: 0, 2: -8, 3: 0}


def test_discard_win_pays_half_matches_worked_example() -> None:
    # §8 worked example: discarder pays P/2, the other two pay P/4 each.
    ruleset = replace(_FULL_SPICY, discard_payment=DiscardPayment.HALF)
    p = points(3, ruleset)
    result = payout(0, p, Discard(discarder_seat=2), dealer_seat=3, ruleset=ruleset)
    assert result == {0: 8, 1: -2, 2: -4, 3: -2}


def test_discard_win_pays_half_at_low_points_favors_discarder_paying_more() -> None:
    ruleset = replace(_FULL_SPICY, discard_payment=DiscardPayment.HALF)
    # P=2: an even split would be 1/0.5/0.5. Rounding keeps the discarder responsible for the
    # whole amount rather than shifting the odd half-point onto a bystander.
    result = payout(0, 2, Discard(discarder_seat=1), dealer_seat=3, ruleset=ruleset)
    assert result == {0: 2, 1: -2, 2: 0, 3: 0}


def test_discard_win_discarder_cannot_be_winner() -> None:
    with pytest.raises(ValueError):
        payout(0, 8, Discard(discarder_seat=0), dealer_seat=3, ruleset=_FULL_SPICY)


# --- dealer involvement: no multiplier ---------------------------------------------------------


def test_dealer_as_winner_no_multiplier() -> None:
    """rules.md §8 has no dealer-doubling rule; dealer winning pays out identically
    to any other seat winning."""
    non_dealer = payout(1, 8, SelfDraw(), dealer_seat=0, ruleset=_FULL_SPICY)
    dealer_wins = payout(0, 8, SelfDraw(), dealer_seat=0, ruleset=_FULL_SPICY)
    assert sorted(non_dealer.values()) == sorted(dealer_wins.values())
    assert dealer_wins[0] == 12  # winner's own share, not doubled for being dealer


def test_dealer_as_discarder_no_multiplier() -> None:
    ruleset = replace(_FULL_SPICY, discard_payment=DiscardPayment.ALL)
    dealer_feeds = payout(1, 8, Discard(discarder_seat=0), dealer_seat=0, ruleset=ruleset)
    non_dealer_feeds = payout(1, 8, Discard(discarder_seat=2), dealer_seat=0, ruleset=ruleset)
    assert dealer_feeds[0] == non_dealer_feeds[2] == -8


# --- invariants ---------------------------------------------------------------------------------


@pytest.mark.parametrize("faan", [0, 1, 3, 5, 8, 10, 13])
@pytest.mark.parametrize("score_table", [ScoreTable.FULL_SPICY, ScoreTable.HALF_SPICY])
@pytest.mark.parametrize("discard_payment", [DiscardPayment.ALL, DiscardPayment.HALF])
@pytest.mark.parametrize("winner_seat", range(4))
@pytest.mark.parametrize("dealer_seat", range(4))
def test_payout_always_sums_to_zero(
    faan: int,
    score_table: ScoreTable,
    discard_payment: DiscardPayment,
    winner_seat: int,
    dealer_seat: int,
) -> None:
    ruleset = RuleSet(
        min_faan=0, score_table=score_table, discard_payment=discard_payment, faan_cap=13
    )
    p = points(faan, ruleset)

    self_draw_result = payout(winner_seat, p, SelfDraw(), dealer_seat, ruleset)
    assert sum(self_draw_result.values()) == 0

    for discarder_seat in range(4):
        if discarder_seat == winner_seat:
            continue
        discard_result = payout(
            winner_seat, p, Discard(discarder_seat=discarder_seat), dealer_seat, ruleset
        )
        assert sum(discard_result.values()) == 0
