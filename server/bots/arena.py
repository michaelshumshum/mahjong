"""Bot evaluation harness (docs/04-bots.md §8):

    python -m bots.arena --a EfficiencyBot --b RandomBot --games 2000 --seed 1 --parallel 8

**Duplicate seeding + paired difference, not raw win totals.** §8 is explicit that raw win
counts over N games aren't a statistical test -- HK scoring's variance (limit hands swing points
sharply) can hide a real edge inside the noise of thousands of games' worth of point totals. Each
"game" here (`--games N`) is actually a *duplicate set*: one seed, played out 4 times with the
same wall (`new_game(ruleset, seed)` is a pure function of `(ruleset, seed)`, independent of
which bots occupy which seats), rotating which single seat candidate `--a` occupies (the other
three seats always run `--b`) across the 4 rotations. Averaging the candidate's score across all
4 seat positions for the same deal, then comparing against the incumbent's average score in that
same deal, cancels both seat/dealer-order luck and which-bot-got-the-good-wall luck -- the two
sources of variance a bare win-rate can't distinguish from real skill.

**Why `dealer_repeat_on_win/draw=False`, not `DEFAULT_RULESET`.** Duplicate rotation only means
what it's supposed to if hand-by-hand progression (`hand_no`, dealer rotation) is a function of
`(ruleset, seed)` alone, never of who's playing or how a hand ends -- otherwise a stronger
candidate winning more often in one rotation than another would make the 4 rotations play a
*different number* of hands, breaking the "same wall, only the seat assignment differs"
guarantee the whole method depends on. With repeats off (this module's own `RulesetChoice`,
matching `bots/selfplay.py`/`tests/test_selfplay.py`'s established precedent), dealer rotation
and hand count are unconditional every hand, so every rotation of every duplicate set plays
exactly the same number of hands (4 for `EAST_ONLY`) regardless of outcome.

**Metrics** (§8): average points/hand, win rate, deal-in rate, average winning faan,
tenpai-at-draw rate, average turns to win, and `tenpai_rate_on_sub_minimum_hand` -- tracked per
bot (`--a`/`--b`), pooled across every seat instance that bot occupied. `tenpai_rate_on_sub_
minimum_hand`'s "does this tenpai shape have a legal way to reach `min_faan`" check
hypothesizes completing the hand off *each* of the seat's actual waiting tiles (found by asking
`mahjong_core.shanten` which tile types would bring shanten to -1) via `self_drawn=True` scoring
context -- a simplification (a real win off a discard can score differently, e.g. 接龍/rob-kong
timing faan), acceptable for a canary metric that doesn't need to be exact, only to move when a
policy actually regresses toward pure efficiency play (docs/04-bots.md §4).

**`--parallel`** runs duplicate sets across a `ProcessPoolExecutor` -- each worker plays its own
4-rotation set start to finish (own event loop via `asyncio.run`), so this needs no shared state
and no pickling beyond `(seed, ruleset, bot_name, bot_name)`.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import random
import statistics
import sys
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass

from app.views import seat_view
from bots.base import Bot
from bots.efficiency import EfficiencyBot
from bots.random import RandomBot
from mahjong_core.actions import build_scoring_context
from mahjong_core.config import RuleSet
from mahjong_core.engine import Discarded, HandEnded, new_game, reduce, start_next_hand
from mahjong_core.ml import decode_action, legal_mask
from mahjong_core.scoring.faan import score_winning_hand
from mahjong_core.shanten import shanten
from mahjong_core.state import GameState, HandOutcome, Phase, SeatState, WinType
from mahjong_core.tiles import TileId, TileType, new_count_array, tile_id_type, tile_ids_for_type

__all__ = [
    "BOT_REGISTRY",
    "BotStats",
    "GameRecord",
    "HandRecord",
    "main",
]


def _random_bot_factory(seed: int) -> Bot:
    return RandomBot(rng=random.Random(seed))


def _efficiency_bot_factory(seed: int) -> Bot:
    del seed  # stateless -- see module docstring's determinism note
    return EfficiencyBot()


BOT_REGISTRY: dict[str, Callable[[int], Bot]] = {
    "RandomBot": _random_bot_factory,
    "EfficiencyBot": _efficiency_bot_factory,
}

_STEP_CAP = 8000
_NO_DEADLINE = float("inf")

# See module docstring: duplicate rotation needs hand-by-hand progression independent of who's
# playing or how a hand ends.
_ARENA_RULESET = RuleSet(dealer_repeat_on_win=False, dealer_repeat_on_draw=False)


# --- per-hand / per-game records --------------------------------------------------------------


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
    docs/04-bots.md §4's canary, see module docstring."""


@dataclass(frozen=True)
class GameRecord:
    seed: int
    roles: tuple[str, str, str, str]
    """"A"/"B" per seat -- which side of the comparison occupied that seat this rotation."""
    hands: tuple[HandRecord, ...]
    final_scores: tuple[int, int, int, int]


# --- shanten/scoring helpers (arena-side: full GameState access, not a bot) -------------------


def _seat_hand34(seat_state: SeatState) -> list[int]:
    """`mahjong_core.shanten`'s 34-array contract, straight from `SeatState` -- the arena has
    real `GameState`, unlike `bots/features.py`'s `SeatView`-based equivalent, so it builds its
    own rather than reaching into another module's redaction-respecting helper for no reason."""
    counts = new_count_array()
    for t in seat_state.concealed:
        counts[int(tile_id_type(t))] += 1
    for meld in seat_state.melds:
        tiles = meld.tiles[:3] if meld.is_kong else meld.tiles
        for t in tiles:
            counts[int(tile_id_type(t))] += 1
    return counts


def _winning_tile_types(hand34: list[int], *, closed: bool) -> list[int]:
    """Every tile type that would bring `hand34` (already tenpai) to agari."""
    out = []
    for t in range(34):
        if hand34[t] >= 4:
            continue
        candidate = list(hand34)
        candidate[t] += 1
        if shanten(candidate, closed=closed) == -1:
            out.append(t)
    return out


def _unused_tile_id_for_type(tile_type_value: int, seat_state: SeatState) -> TileId:
    used = set(seat_state.concealed)
    for m in seat_state.melds:
        used.update(m.tiles)
    for tid in tile_ids_for_type(TileType(tile_type_value)):
        if tid not in used:
            return tid
    raise AssertionError("no unused physical tile for a hypothetical win check")


def _tenpai_can_reach_min_faan(state: GameState, seat: int) -> bool:
    """Whether *any* of this (already-tenpai) seat's actual waits legally clears
    `ruleset.min_faan` if completed self-drawn right now -- see module docstring."""
    seat_state = state.seats[seat]
    hand34 = _seat_hand34(seat_state)
    closed = not seat_state.melds
    ctx = build_scoring_context(state, seat, self_drawn=True)
    for t in _winning_tile_types(hand34, closed=closed):
        tile_id = _unused_tile_id_for_type(t, seat_state)
        concealed = (*seat_state.concealed, tile_id)
        result = score_winning_hand(concealed, seat_state.melds, ctx, state.ruleset)
        if result.clears_min_faan:
            return True
    return False


# --- one instrumented game -----------------------------------------------------------------


async def _play_instrumented_game(seed: int, ruleset: RuleSet, bots: Sequence[Bot]) -> GameRecord:
    """Like `bots/selfplay.py`'s `play_game`, plus per-hand `HandRecord`s. Pending-claimant
    order during a claim window is `min(pending)` (deterministic, no extra RNG needed) rather
    than a seeded random choice -- claim *resolution* is correct regardless of response order
    (00-architecture.md §4: "never resolve on first-arrival"), and the arena needs a
    reproducible-per-seed run, not a specific arrival order preserved across rotations (each
    rotation's trajectory necessarily differs anyway, since different bots occupy different
    seats).
    """
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

        view = seat_view(state, seat)
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
            seat_state = state.seats[s]
            hand34 = _seat_hand34(seat_state)
            if shanten(hand34, closed=not seat_state.melds) == 0:
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


# --- duplicate sets --------------------------------------------------------------------------


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
    """`seed` also derives each seat's own bot-internal RNG seed (`seed * 4 + seat`) so a
    given `--seed`/`--games` invocation is bit-for-bit reproducible end to end, not just the
    wall -- `server/AGENTS.md`'s "a failing game is reproducible from (ruleset, seed, actions)"
    convention, extended to stochastic bots (`RandomBot`) rather than only deterministic ones.
    """
    records = []
    for rotation in range(4):
        seat_bots: list[Bot] = [_make_bot(name_b, seed * 4 + i) for i in range(4)]
        seat_bots[rotation] = _make_bot(name_a, seed * 4 + rotation)
        roles = _roles_for_rotation(rotation)
        record = await _play_instrumented_game(seed, ruleset, seat_bots)
        records.append(dataclasses.replace(record, roles=roles))
    return tuple(records)


def _run_duplicate_set(
    seed: int, ruleset: RuleSet, name_a: str, name_b: str
) -> tuple[GameRecord, ...]:
    """Top-level, picklable `ProcessPoolExecutor` entry point -- see module docstring."""
    return asyncio.run(_run_duplicate_set_async(seed, ruleset, name_a, name_b))


# --- aggregation -----------------------------------------------------------------------------


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
    minus the mean of the other three seats' scores) -- docs/04-bots.md §8 step 2."""
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


def _mean_ci95(values: Sequence[float]) -> tuple[float, float, float]:
    """Normal-approximation 95% CI over the paired differences (docs/04-bots.md §8 step 3:
    "bootstrap or normal-approximation... is fine given the sample size")."""
    n = len(values)
    mean = statistics.fmean(values)
    if n < 2:
        return mean, mean, mean
    sd = statistics.stdev(values)
    half = 1.96 * sd / (n**0.5)
    return mean, mean - half, mean + half


# --- CLI -------------------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m bots.arena",
        description="Paired-duplicate bot evaluation (docs/04-bots.md §8).",
    )
    parser.add_argument("--a", required=True, choices=sorted(BOT_REGISTRY), help="candidate bot")
    parser.add_argument("--b", required=True, choices=sorted(BOT_REGISTRY), help="incumbent bot")
    parser.add_argument(
        "--games", type=int, default=1000, help="number of duplicate seed sets (4 games each)"
    )
    parser.add_argument("--seed", type=int, default=0, help="base seed; set i uses seed+i")
    parser.add_argument("--parallel", type=int, default=1, help="worker processes")
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


if __name__ == "__main__":
    main(sys.argv[1:])
