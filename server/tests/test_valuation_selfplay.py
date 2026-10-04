"""Organic validation of `bots/valuation.py` against the real scorer (docs/bots.md §4's own
"measure it, don't assume" precedent, the same one `mahjong_core/shanten.py`'s frontier-table
tradeoff sets). Plays real `RandomBot` self-play games, and for every real win, compares this
module's `estimate_best_faan` (computed on the winning seat's pre-win, already-tenpai hand
shape) against the actual faan `mahjong_core.scoring.faan.score_winning_hand` awarded via
`state.hand_result`. The measured numbers below are quoted in `bots/valuation.py`'s own module
docstring -- if this test's assertions ever need loosening, that docstring must be updated in
the same change.

**Why `RandomBot`, not `FaanBot` itself.** Validating the estimator against the very bot whose
discards it steers would be circular -- `RandomBot`'s discards are policy-independent of this
module, so its winning hands are an unbiased (if cheap-skewed -- see below) sample of "hand
shapes real games actually produce," the same role `mahjong_core/shanten.py`'s oracle
cross-check plays for shanten.

**Known sample bias, disclosed rather than hidden.** `RandomBot` almost never intentionally
pursues Half Flush/Full Flush/Seven Pairs/etc. -- most of its wins are baseline 平糊/自摸/門前清
hands (1-3 faan) that happen to complete by chance. This makes the sample skew cheap, which
makes the measured MAE conservative in the safe direction: see `bots/valuation.py`'s module
docstring for why under-estimating a cheap accidental hand is a smaller mistake than
over-estimating one that never completes.
"""

from __future__ import annotations

import random
import statistics

import pytest

from bots.labels import seat_hand34
from bots.random import random_action
from bots.valuation import estimate_best_faan
from mahjong_core.config import RuleSet
from mahjong_core.engine import HandEnded, new_game, reduce, start_next_hand
from mahjong_core.state import HandOutcome, Phase

_STEP_CAP = 4000
_GAMES = 1500
"""`RandomBot` wins only a small fraction of hands purely by chance (~2-3% of hands, measured
while sizing this constant) -- getting a few dozen real wins to compare against the real scorer
needs on the order of a thousand games. That makes this test genuinely slow (tens of seconds),
unlike `tests/test_arena.py`'s single-duplicate-set smoke test -- `@pytest.mark.slow`
(`server/AGENTS.md`'s `make test` excludes these), run manually/in CI's slow lane to (re)produce
the numbers quoted in `bots/valuation.py`'s module docstring."""


def _collect_win_samples(seed: int) -> list[tuple[int, int]]:
    """`(estimated_faan, actual_faan)` for every real win across one seeded `RandomBot` game."""
    rng = random.Random(seed)
    ruleset = RuleSet(dealer_repeat_on_win=False, dealer_repeat_on_draw=False)
    state = new_game(ruleset, seed)
    samples: list[tuple[int, int]] = []
    steps = 0
    while state.phase != Phase.GAME_OVER:
        steps += 1
        if steps > _STEP_CAP:
            raise RuntimeError(f"seed={seed}: exceeded {_STEP_CAP} steps")

        if state.phase == Phase.HAND_OVER:
            state, _ = start_next_hand(state)
            continue

        if state.phase in (Phase.AWAIT_CLAIMS, Phase.AWAIT_KONG_ROB):
            assert state.claim_window is not None
            pending = [
                o.seat
                for o in state.claim_window.offers
                if o.seat not in state.claim_window.responses
            ]
            seat = rng.choice(pending)
        else:
            seat = state.turn

        pre_state = state
        action = random_action(state, seat, rng)
        state, events = reduce(state, action)

        for event in events:
            if not isinstance(event, HandEnded) or event.outcome != HandOutcome.WIN:
                continue
            winner = event.winner
            assert winner is not None
            result = state.hand_result
            if result is None:
                continue
            pre_seat_state = pre_state.seats[winner]
            hand34 = seat_hand34(pre_seat_state)
            estimate, _route = estimate_best_faan(hand34, closed=not pre_seat_state.melds)
            samples.append((estimate, result.faan))

    return samples


@pytest.mark.slow
def test_estimate_matches_real_scorer_on_selfplay_sample() -> None:
    samples: list[tuple[int, int]] = []
    for seed in range(_GAMES):
        samples.extend(_collect_win_samples(seed))

    assert len(samples) >= 50, f"only {len(samples)} real wins sampled -- widen _GAMES"

    errors = [abs(est - actual) for est, actual in samples]
    mae = statistics.fmean(errors)
    within_one = sum(1 for e in errors if e <= 1) / len(errors)

    print(
        f"\nvaluation vs real scorer over {len(samples)} RandomBot self-play wins: "
        f"MAE={mae:.2f} faan, within 1 faan={within_one:.0%}"
    )

    # bounds are the measured baseline (67 samples: MAE 2.46, 9% within 1 faan; see
    # bots/valuation.py's docstring) -- catches a regression past it, not a calibrated accuracy bar (the estimator doesn't model situational/win-timing faan).
    assert mae <= 4.0, f"mean absolute error {mae:.2f} faan exceeds the measured baseline"
    assert within_one >= 0.05, f"only {within_one:.0%} of samples within 1 faan"
