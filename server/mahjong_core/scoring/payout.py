"""Faan -> points -> per-seat payments. Pure arithmetic over
`scoring.faan.FaanResult.total_faan` -- no I/O, no engine wiring.
"""

from __future__ import annotations

from dataclasses import dataclass

from mahjong_core.config import DiscardPayment, RuleSet, ScoreTable

_MAX_FAAN = 13  # config.py's _VALID_FAAN_CAP tops out at 13

_FULL_SPICY: tuple[int, ...] = tuple(2**faan for faan in range(_MAX_FAAN + 1))
"""全辣: `2 ** faan`."""

_HALF_SPICY: tuple[int, ...] = (1, 2, 4, 8, 16, 24, 32, 48, 64, 96, 128, 192, 256, 384)
"""半辣: matches full spicy through faan 4, then doubles every two faan with the odd faan in
between at 1.5x the preceding even faan's value. Written out as a literal table rather than
re-derived at call time."""


def points(faan: int, ruleset: RuleSet) -> int:
    """Faan -> points lookup, table selected by `ruleset.score_table`."""
    if not 0 <= faan <= _MAX_FAAN:
        raise ValueError(f"faan must be 0..{_MAX_FAAN}, got {faan}")
    table = _FULL_SPICY if ruleset.score_table == ScoreTable.FULL_SPICY else _HALF_SPICY
    return table[faan]


@dataclass(frozen=True)
class SelfDraw:
    """Win by drawing the winning tile (自摸) -- the other three seats all pay."""


@dataclass(frozen=True)
class Discard:
    """Win by claiming a discard, or by robbing a kong (搶槓): the seat whose kong was robbed
    pays as the discarder here -- it's the seat responsible for the winning tile reaching the
    winner, exactly like a discard.
    """

    discarder_seat: int


WinType = SelfDraw | Discard


def _round_half_up(numerator: int, denominator: int) -> int:
    """`numerator / denominator` rounded to the nearest integer, ties up. Only engages where
    the payment fractions (P/2, P/4) don't divide evenly -- reachable at low faan (e.g. faan=0
    => P=1, a legal win when `min_faan=0`)."""
    return (2 * numerator + denominator) // (2 * denominator)


def _check_seat(seat: int) -> None:
    if not 0 <= seat < 4:
        raise ValueError(f"seat must be 0..3, got {seat}")


def payout(
    winner_seat: int,
    points: int,
    win_type: WinType,
    dealer_seat: int,
    ruleset: RuleSet,
) -> dict[int, int]:
    """Per-seat point deltas for one win, summing to zero. `points` is the caller's
    `points(faan, ruleset)` result -- `faan` already clamped to `ruleset.faan_cap`.

    No dealer multiplier: unlike riichi scoring, a dealer's payments/receipts here are plain
    `points()`. Dealer advantage in this ruleset is entirely `dealer_repeat_on_win`/
    `dealer_repeat_on_draw` (flow, not points).
    """
    _check_seat(winner_seat)
    _check_seat(dealer_seat)
    if points < 0:
        raise ValueError(f"points must be >= 0, got {points}")

    deltas = dict.fromkeys(range(4), 0)

    if isinstance(win_type, SelfDraw):
        loser_share = _round_half_up(points, 2)
        for seat in range(4):
            if seat != winner_seat:
                deltas[seat] -= loser_share
        deltas[winner_seat] = 3 * loser_share
        return deltas

    discarder_seat = win_type.discarder_seat
    _check_seat(discarder_seat)
    if discarder_seat == winner_seat:
        raise ValueError("discarder cannot be the winner")

    if ruleset.discard_payment == DiscardPayment.ALL:
        deltas[discarder_seat] = -points
        deltas[winner_seat] = points
        return deltas

    # DiscardPayment.HALF: discarder pays half, the other two pay a quarter each. any leftover
    # from splitting the bystanders' half goes back onto the discarder, not a bystander.
    discarder_share = _round_half_up(points, 2)
    bystander_total = points - discarder_share
    bystander_share, leftover = divmod(bystander_total, 2)
    discarder_share += leftover

    for seat in range(4):
        if seat not in (winner_seat, discarder_seat):
            deltas[seat] -= bystander_share
    deltas[discarder_seat] = -discarder_share
    deltas[winner_seat] = points
    return deltas
