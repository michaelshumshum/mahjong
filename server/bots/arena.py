"""Bot evaluation harness (docs/bots.md §7):

    python -m bots.arena --a EfficiencyBot --b RandomBot --games 2000 --seed 1 --parallel 8

Uses `dealer_repeat_on_win/draw=False`, not `DEFAULT_RULESET`: duplicate rotation only cancels
seat/wall luck if hand count and dealer rotation are a pure function of `(ruleset, seed)`, never
of who's playing or how a hand ends -- with repeats on, a stronger candidate winning more often in
one rotation would make that rotation play a different number of hands than the others.

`tenpai_rate_on_sub_minimum_hand` hypothesizes completing the hand off each of a tenpai seat's
actual waits via `self_drawn=True` scoring -- a simplification (a real discard win can score
differently) acceptable for a canary metric that only needs to move when play regresses toward
pure efficiency (docs/bots.md §4).

`--parallel` runs duplicate sets across a `ProcessPoolExecutor`; each worker plays its own
4-rotation set start to finish, so nothing needs pickling beyond `(seed, ruleset, bot, bot)`.

`ORACLE` seats are fed `_omniscient_seat_view` via `_view_for`, the one sanctioned call site
outside `app/table.py` (docs/bots.md §9). Offline only: `app/` never imports this module
(`tests/test_oracle_containment.py`).
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import random
import statistics
import sys
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.views import SeatView, _omniscient_seat_view, seat_view
from bots.base import Bot
from bots.efficiency import EfficiencyBot
from bots.faanbot import AGGRESSIVE, DEFENSIVE, FLUSH_CHASING, FaanBot, WeightProfile
from bots.labels import is_tenpai, seat_hand34, unused_tile_id_for_type, winning_tile_types
from bots.random import RandomBot
from mahjong_core.actions import build_scoring_context
from mahjong_core.config import RuleSet
from mahjong_core.engine import Discarded, HandEnded, new_game, reduce, start_next_hand
from mahjong_core.ml import decode_action, legal_mask
from mahjong_core.scoring.faan import score_winning_hand
from mahjong_core.state import GameState, HandOutcome, Phase, WinType

__all__ = [
    "BOT_REGISTRY",
    "OMNISCIENT_BOTS",
    "BotStats",
    "GameRecord",
    "HandRecord",
    "main",
]


def _random_bot_factory(seed: int) -> Bot:
    return RandomBot(rng=random.Random(seed))


def _efficiency_bot_factory(seed: int) -> Bot:
    del seed  # stateless; seed unused
    return EfficiencyBot()


def _faan_bot_factory(seed: int) -> Bot:
    del seed  # stateless; seed unused
    return FaanBot()


def _weight_profile_factory(profile: WeightProfile) -> Callable[[int], Bot]:
    """A `BOT_REGISTRY` factory for a non-`BASELINE` `FaanBot` weight profile (docs/ml.md
    §12's mixed-table personas, also the dataset generator's `--bots`) -- same stateless-seed shape as
    `_faan_bot_factory`, parameterised so `AGGRESSIVE`/`DEFENSIVE`/`FLUSH_CHASING` don't each need
    their own near-identical factory function."""

    def factory(seed: int) -> Bot:
        del seed  # stateless; seed unused
        return FaanBot(weight_profile=profile)

    return factory


def _learned_bot_factory(seed: int) -> Bot:
    del seed  # greedy; seed unused
    from bots.learned import LearnedBot

    return LearnedBot()


BOT_REGISTRY: dict[str, Callable[[int], Bot]] = {
    "RandomBot": _random_bot_factory,
    "EfficiencyBot": _efficiency_bot_factory,
    "FaanBot": _faan_bot_factory,
    "FaanBotAggressive": _weight_profile_factory(AGGRESSIVE),
    "FaanBotDefensive": _weight_profile_factory(DEFENSIVE),
    "FaanBotFlushChasing": _weight_profile_factory(FLUSH_CHASING),
    "ORACLE": _faan_bot_factory,
    "LearnedBot": _learned_bot_factory,
}

OMNISCIENT_BOTS: frozenset[str] = frozenset({"ORACLE"})
"""`BOT_REGISTRY` names played on an omniscient view; any other harness must refuse them."""

_STEP_CAP = 8000
_NO_DEADLINE = float("inf")

# see module docstring: keeps hand count independent of who wins.
_ARENA_RULESET = RuleSet(dealer_repeat_on_win=False, dealer_repeat_on_draw=False)


@dataclass(frozen=True)
class HandRecord:
    hand_no: int
    outcome: HandOutcome
    winner: int | None
    win_type: WinType | None
    discarder: int | None
    faan: int
    payments: tuple[int, int, int, int]
    turns: int
    """Number of `Discarded` events since the previous hand started -- a turn-count proxy."""
    tenpai_seats: tuple[int, ...] = ()
    """Populated only for `HandOutcome.EXHAUSTIVE_DRAW`."""
    sub_minimum_tenpai_seats: tuple[int, ...] = ()
    """Subset of `tenpai_seats` whose current wait has no legal way to reach `min_faan` --
    docs/bots.md §4's canary, see module docstring."""


@dataclass(frozen=True)
class GameRecord:
    seed: int
    roles: tuple[str, str, str, str]
    """"A"/"B" per seat -- which side of the comparison occupied that seat this rotation."""
    hands: tuple[HandRecord, ...]
    final_scores: tuple[int, int, int, int]


def _tenpai_can_reach_min_faan(state: GameState, seat: int) -> bool:
    """Whether any of this seat's actual waits legally clears `min_faan` if completed self-drawn
    right now."""
    seat_state = state.seats[seat]
    hand34 = seat_hand34(seat_state)
    closed = not seat_state.melds
    ctx = build_scoring_context(state, seat, self_drawn=True)
    for t in winning_tile_types(hand34, closed=closed, hand_sets=state.ruleset.hand_sets):
        try:
            tile_id = unused_tile_id_for_type(t, seat_state)
        except AssertionError:
            continue  # a kong counts 3 in hand34: a wait on its own type has no 5th copy
        concealed = (*seat_state.concealed, tile_id)
        result = score_winning_hand(concealed, seat_state.melds, ctx, state.ruleset)
        if result.clears_min_faan:
            return True
    return False


def _view_for(state: GameState, seat: int, name: str) -> SeatView:
    if name in OMNISCIENT_BOTS:
        return _omniscient_seat_view(state, seat)
    return seat_view(state, seat)


async def _play_instrumented_game(
    seed: int, ruleset: RuleSet, bots: Sequence[Bot], names: Sequence[str]
) -> GameRecord:
    """Like `bots/selfplay.py`'s `play_game`, plus per-hand `HandRecord`s. Claim-window order is
    `min(pending)`, not a seeded random choice -- resolution is correct regardless of response
    order, and the arena just needs a reproducible-per-seed run."""
    state = new_game(ruleset, seed)
    hands: list[HandRecord] = []
    turns = 0
    steps = 0
    while state.phase != Phase.GAME_OVER:
        steps += 1
        if steps > _STEP_CAP:
            raise RuntimeError(f"seed={seed}: exceeded {_STEP_CAP} steps -- possible deadlock")

        if state.phase == Phase.HAND_OVER:
            state, _ = start_next_hand(state)
            turns = 0
            continue

        if state.phase in (Phase.AWAIT_CLAIMS, Phase.AWAIT_KONG_ROB):
            assert state.claim_window is not None
            pending = [
                o.seat
                for o in state.claim_window.offers
                if o.seat not in state.claim_window.responses
            ]
            seat = min(pending)
        else:
            seat = state.turn

        view = _view_for(state, seat, names[seat])
        mask = legal_mask(state, seat)
        aid = await bots[seat].act(view, mask, _NO_DEADLINE)
        action = decode_action(aid, state, seat)
        state, events = reduce(state, action)

        for event in events:
            if isinstance(event, Discarded):
                turns += 1
            elif isinstance(event, HandEnded):
                hands.append(_hand_record(state, event, turns))

    return GameRecord(
        seed=seed,
        roles=("", "", "", ""),
        hands=tuple(hands),
        final_scores=tuple(s.score for s in state.seats),  # type: ignore[arg-type]
    )


def _hand_record(state: GameState, event: HandEnded, turns: int) -> HandRecord:
    tenpai_seats: tuple[int, ...] = ()
    sub_minimum: tuple[int, ...] = ()
    if event.outcome == HandOutcome.EXHAUSTIVE_DRAW:
        tenpai = []
        sub_min = []
        for s in range(4):
            if is_tenpai(state, s):
                tenpai.append(s)
                if not _tenpai_can_reach_min_faan(state, s):
                    sub_min.append(s)
        tenpai_seats = tuple(tenpai)
        sub_minimum = tuple(sub_min)

    result = state.hand_result
    faan = result.faan if result is not None else 0
    payments = (
        tuple(result.payments.get(s, 0) for s in range(4)) if result is not None else (0, 0, 0, 0)
    )
    return HandRecord(
        hand_no=event.hand_no,
        outcome=event.outcome,
        winner=event.winner,
        win_type=event.win_type,
        discarder=event.discarder,
        faan=faan,
        payments=payments,  # type: ignore[arg-type]
        turns=turns,
        tenpai_seats=tenpai_seats,
        sub_minimum_tenpai_seats=sub_minimum,
    )


def _roles_for_rotation(rotation: int) -> tuple[str, str, str, str]:
    roles = ["B", "B", "B", "B"]
    roles[rotation] = "A"
    return (roles[0], roles[1], roles[2], roles[3])


def _make_bot(name: str, seed: int) -> Bot:
    try:
        factory = BOT_REGISTRY[name]
    except KeyError:
        raise ValueError(f"unknown bot {name!r}; choices: {sorted(BOT_REGISTRY)}") from None
    return factory(seed)


async def _run_duplicate_set_async(
    seed: int, ruleset: RuleSet, name_a: str, name_b: str
) -> tuple[GameRecord, ...]:
    """`seed` also derives each seat's bot-internal RNG seed (`seed * 4 + seat`) so a run is
    bit-for-bit reproducible end to end, including stochastic bots like `RandomBot`."""
    records = []
    for rotation in range(4):
        seat_bots: list[Bot] = [_make_bot(name_b, seed * 4 + i) for i in range(4)]
        seat_bots[rotation] = _make_bot(name_a, seed * 4 + rotation)
        names = [name_b] * 4
        names[rotation] = name_a
        roles = _roles_for_rotation(rotation)
        record = await _play_instrumented_game(seed, ruleset, seat_bots, names)
        records.append(dataclasses.replace(record, roles=roles))
    return tuple(records)


def _run_duplicate_set(
    seed: int, ruleset: RuleSet, name_a: str, name_b: str
) -> tuple[GameRecord, ...]:
    """Top-level, picklable `ProcessPoolExecutor` entry point -- see module docstring."""
    return asyncio.run(_run_duplicate_set_async(seed, ruleset, name_a, name_b))


@dataclass
class BotStats:
    hands_played: int = 0
    wins: int = 0
    deal_ins: int = 0
    winning_faan_total: int = 0
    turns_to_win_total: int = 0
    exhaustive_draws_played: int = 0
    tenpai_at_draw: int = 0
    sub_minimum_tenpai: int = 0
    points_total: int = 0

    def add_hand(self, seat: int, hand: HandRecord) -> None:
        self.hands_played += 1
        self.points_total += hand.payments[seat]
        if hand.winner == seat:
            self.wins += 1
            self.winning_faan_total += hand.faan
            self.turns_to_win_total += hand.turns
        if hand.outcome == HandOutcome.WIN and hand.discarder == seat and hand.winner != seat:
            self.deal_ins += 1
        if hand.outcome == HandOutcome.EXHAUSTIVE_DRAW:
            self.exhaustive_draws_played += 1
            if seat in hand.tenpai_seats:
                self.tenpai_at_draw += 1
                if seat in hand.sub_minimum_tenpai_seats:
                    self.sub_minimum_tenpai += 1

    def summary(self) -> dict[str, float | int]:
        hands_n = max(self.hands_played, 1)
        return {
            "hands_played": self.hands_played,
            "avg_points_per_hand": self.points_total / hands_n,
            "win_rate": self.wins / hands_n,
            "deal_in_rate": self.deal_ins / hands_n,
            "avg_winning_faan": (self.winning_faan_total / self.wins) if self.wins else 0.0,
            "tenpai_at_draw_rate": (
                self.tenpai_at_draw / self.exhaustive_draws_played
                if self.exhaustive_draws_played
                else 0.0
            ),
            "avg_turns_to_win": (self.turns_to_win_total / self.wins) if self.wins else 0.0,
            "tenpai_rate_on_sub_minimum_hand": (
                self.sub_minimum_tenpai / self.tenpai_at_draw if self.tenpai_at_draw else 0.0
            ),
        }


def _collect_stats(duplicate_sets: Sequence[tuple[GameRecord, ...]]) -> tuple[BotStats, BotStats]:
    stats_a, stats_b = BotStats(), BotStats()
    for records in duplicate_sets:
        for record in records:
            for seat, role in enumerate(record.roles):
                target = stats_a if role == "A" else stats_b
                for hand in record.hands:
                    target.add_hand(seat, hand)
    return stats_a, stats_b


def _paired_differences(duplicate_sets: Sequence[tuple[GameRecord, ...]]) -> list[float]:
    """One sample per duplicate set: mean over its 4 rotations of (A's score in that rotation
    minus the mean of the other three seats' scores) -- docs/bots.md §7 step 2."""
    diffs = []
    for records in duplicate_sets:
        per_rotation = []
        for record in records:
            a_seat = record.roles.index("A")
            a_score = record.final_scores[a_seat]
            b_scores = [record.final_scores[i] for i in range(4) if i != a_seat]
            per_rotation.append(a_score - statistics.fmean(b_scores))
        diffs.append(statistics.fmean(per_rotation))
    return diffs


def _per_set_wins(duplicate_sets: Sequence[tuple[GameRecord, ...]]) -> list[tuple[int, int]]:
    """`(A's wins, A's hands)` per duplicate set, summed over its 4 rotations."""
    out = []
    for records in duplicate_sets:
        wins = hands = 0
        for record in records:
            a_seat = record.roles.index("A")
            hands += len(record.hands)
            wins += sum(1 for h in record.hands if h.winner == a_seat)
        out.append((wins, hands))
    return out


def _diffs_payload(
    name_a: str,
    name_b: str,
    seeds: Sequence[int],
    duplicate_sets: Sequence[tuple[GameRecord, ...]],
) -> dict[str, Any]:
    wins = _per_set_wins(duplicate_sets)
    return {
        "a": name_a,
        "b": name_b,
        "seeds": list(seeds),
        "diffs": _paired_differences(duplicate_sets),
        "wins": [w for w, _ in wins],
        "hands": [h for _, h in wins],
    }


def _compare_to_baseline(
    current: Mapping[str, Any], baseline: Mapping[str, Any]
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Per-set `(current - baseline)` paired over the same seeds and opponents: `(Δ points/game,
    Δ win rate in percentage points)`, each as `(mean, lo, hi)`. Valid only when both runs share
    `b` and seeds."""
    if current["seeds"] != baseline["seeds"]:
        raise ValueError(
            "baseline was run on different seeds; the paired comparison needs the same"
        )
    if current["b"] != baseline["b"]:
        raise ValueError(f"baseline B is {baseline['b']!r}, this run's is {current['b']!r}")
    points = [c - b for c, b in zip(current["diffs"], baseline["diffs"], strict=True)]
    rate = [
        100.0 * (cw / ch - bw / bh)
        for cw, ch, bw, bh in zip(
            current["wins"], current["hands"], baseline["wins"], baseline["hands"], strict=True
        )
    ]
    return _mean_ci95(points), _mean_ci95(rate)


def _mean_ci95(values: Sequence[float]) -> tuple[float, float, float]:
    """Normal-approximation 95% CI over the paired differences."""
    n = len(values)
    mean = statistics.fmean(values)
    if n < 2:
        return mean, mean, mean
    sd = statistics.stdev(values)
    half = 1.96 * sd / (n**0.5)
    return mean, mean - half, mean + half


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m bots.arena",
        description="Paired-duplicate bot evaluation (docs/bots.md §7).",
    )
    parser.add_argument("--a", required=True, choices=sorted(BOT_REGISTRY), help="candidate bot")
    parser.add_argument("--b", required=True, choices=sorted(BOT_REGISTRY), help="incumbent bot")
    parser.add_argument(
        "--games", type=int, default=1000, help="number of duplicate seed sets (4 games each)"
    )
    parser.add_argument("--seed", type=int, default=0, help="base seed; set i uses seed+i")
    parser.add_argument("--parallel", type=int, default=1, help="worker processes")
    parser.add_argument(
        "--diffs-out",
        type=Path,
        help="write per-set paired differences and A's per-set wins as JSON",
    )
    parser.add_argument(
        "--baseline-diffs",
        type=Path,
        help="a previous --diffs-out on the same seeds and B: report Δ points and Δ win rate vs it",
    )
    return parser.parse_args(argv)


def _print_report(
    name_a: str, name_b: str, stats_a: BotStats, stats_b: BotStats, diffs: list[float]
) -> None:
    mean, lo, hi = _mean_ci95(diffs)
    print(f"\n=== {name_a} (A) vs {name_b} (B) -- {len(diffs)} duplicate set(s) ===\n")
    header = f"{'metric':32s} {'A':>14s} {'B':>14s}"
    print(header)
    print("-" * len(header))
    for key in (
        "hands_played",
        "avg_points_per_hand",
        "win_rate",
        "deal_in_rate",
        "avg_winning_faan",
        "tenpai_at_draw_rate",
        "avg_turns_to_win",
        "tenpai_rate_on_sub_minimum_hand",
    ):
        a_val = stats_a.summary()[key]
        b_val = stats_b.summary()[key]
        print(f"{key:32s} {a_val:>14.4f} {b_val:>14.4f}")
    print()
    print(f"paired difference (A - B), mean points/game: {mean:+.3f}")
    print(f"95% CI: [{lo:+.3f}, {hi:+.3f}]")
    if lo > 0:
        print(f"CI excludes zero in {name_a}'s favor -- merge gate passes for A over B.")
    elif hi < 0:
        print(f"CI excludes zero in {name_b}'s favor -- {name_a} is worse, not better.")
    else:
        print("CI includes zero -- no statistically significant difference at this sample size.")


def main(argv: Sequence[str] | None = None) -> None:
    args = _parse_args(argv)
    seeds = [args.seed + i for i in range(args.games)]

    duplicate_sets: list[tuple[GameRecord, ...]] = []
    if args.parallel > 1:
        with ProcessPoolExecutor(max_workers=args.parallel) as pool:
            futures = [
                pool.submit(_run_duplicate_set, s, _ARENA_RULESET, args.a, args.b) for s in seeds
            ]
            for f in futures:
                duplicate_sets.append(f.result())
    else:
        for s in seeds:
            duplicate_sets.append(_run_duplicate_set(s, _ARENA_RULESET, args.a, args.b))

    stats_a, stats_b = _collect_stats(duplicate_sets)
    diffs = _paired_differences(duplicate_sets)
    _print_report(args.a, args.b, stats_a, stats_b, diffs)

    payload = _diffs_payload(args.a, args.b, seeds, duplicate_sets)
    if args.diffs_out is not None:
        args.diffs_out.write_text(json.dumps(payload))
    if args.baseline_diffs is not None:
        baseline = json.loads(args.baseline_diffs.read_text())
        (pm, plo, phi), (wm, wlo, whi) = _compare_to_baseline(payload, baseline)
        print(f"\nvs baseline {baseline['a']} ({args.baseline_diffs}), paired per set:")
        print(f"  Δ points/game: {pm:+.3f}  95% CI [{plo:+.3f}, {phi:+.3f}]")
        print(f"  Δ win rate (pp): {wm:+.2f}  95% CI [{wlo:+.2f}, {whi:+.2f}]")


if __name__ == "__main__":
    main(sys.argv[1:])
