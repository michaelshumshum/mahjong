"""Mine learn-mode puzzles from seeded Expert self-play and rate them with the bot tiers
(docs/decisions/0025-learn-mode.md "Random endless puzzles").

    uv run python -m tools.mine_puzzles --games 2000 --seed 20000000 --workers 8 \\
        --out /tmp/mined.jsonl --shortlist app/lessons/mined_puzzles.json

Four `T4` seats play `LESSON_RULESET` games; a game is a pure function of its seed, so a record
replays from `source.game_seed` + `source.decision` (the step index in that game). Every seat's
decisions are scanned, each rotated into a seat-0 position (`position_from_state`), so one game
yields puzzles from four hands. Keys are graded on the rebuilt position, the one a player is
shown, never on the live state.

Filters and the difficulty rule are documented in ADR 0025 "Mined puzzles".
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import os
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from enum import StrEnum
from multiprocessing import get_context
from pathlib import Path
from typing import Any

from app.lessons.grade import (
    BestDiscardKey,
    CountFaanKey,
    SafeOption,
    WinningTilesKey,
    best_discard,
    count_faan,
    safe_discard,
    safe_options,
    winning_tiles,
)
from app.lessons.model import LESSON_RULESET, PuzzleKind, SafeReason
from app.lessons.position import (
    build_position,
    position_from_dict,
    position_from_state,
    position_to_dict,
)
from app.views import seat_view
from bots.base import GAME_STEP_CAP, NO_DEADLINE
from bots.features import seen34
from bots.labels import is_tenpai, seat_hand34
from bots.tiers import BOT_TIERS, BotTier
from bots.worker import compute_action
from mahjong_core.actions import Discard, can_declare_win
from mahjong_core.engine import ENGINE_VERSION, new_game, reduce, start_next_hand
from mahjong_core.ml import DISCARD_BASE, decode_action, legal_mask
from mahjong_core.shanten import shanten
from mahjong_core.state import GameState, Phase
from mahjong_core.tiles import (
    N_SUITED_TYPES,
    ORPHAN_TYPES,
    RANKS_PER_SUIT,
    TileType,
    count_array_from_types,
    parse_tile,
    tile_code,
    tile_id_type,
)

MINER_TIER = BotTier.T4
FALLBACK_TIER = BotTier.T2
"""Strongest tier that needs no weights, played when `learned.npz` doesn't load."""

# best_discard: a hand further than this from tenpai is too open to teach one answer
MAX_SHANTEN = 2
# a puzzle with more tied answers stops being about the right shape
MAX_CORRECT = 2
# ukeire lead over the best wrong discard at the same shanten: one tile type's four copies
MIN_UKEIRE_MARGIN = 4
# strongest proof first: a reason only qualifies when every hand tile it covers is safe
SAFE_REASON_ORDER = (SafeReason.ALL_COPIES_VISIBLE, SafeReason.NO_CHANCE, SafeReason.GENBUTSU)
# a reason that clears half the hand isn't a deduction worth asking for
MAX_ACCEPTED = 3

# rated on a plain seat_view only; ORACLE plays on every hand, so it would rate nothing
RATED_TIERS = tuple(t for t in BOT_TIERS if t != BotTier.ORACLE)
# T4's softmax mass on the correct ids: the rate its policy would score if sampled
POLICY_RATE = "T4_policy"
# left out of the score: argmax T4, since POLICY_RATE carries it graded; and on best_discard
# T1, whose discard rule is the key's own grading rule
_UNINFORMATIVE: Mapping[PuzzleKind, frozenset[str]] = {
    PuzzleKind.BEST_DISCARD: frozenset({BotTier.T1, BotTier.T4}),
    PuzzleKind.SAFE_DISCARD: frozenset({BotTier.T4}),
}

# safe_discard: t2 and t4 both right ~0.45, one miss ~0.7, both ~0.95. best_discard: score
# terciles of an 80-game calibration run (seeds 20,000,000+); adr 0025 "mined puzzles"
DECISION_BANDS: Mapping[PuzzleKind, tuple[float, float]] = {
    PuzzleKind.BEST_DISCARD: (0.28, 0.32),
    PuzzleKind.SAFE_DISCARD: (0.55, 0.85),
}
# structural points; see winning_tiles_points / count_faan_points
WINNING_TILES_BANDS = (2, 4)
COUNT_FAAN_BANDS = (3, 4)


class Band(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


def band_for(score: float, bounds: tuple[float, float]) -> Band:
    """Below `bounds[0]` is beginner, from `bounds[1]` advanced."""
    low, high = bounds
    if score < low:
        return Band.BEGINNER
    if score < high:
        return Band.INTERMEDIATE
    return Band.ADVANCED


def naive_discard(hand: Iterable[TileType]) -> TileType:
    """A beginner's pick, blind to shanten: the tile with the fewest neighbours (extra copies,
    then same-suit tiles one or two ranks away); ties go to honours, then terminals, then the
    tile furthest from the middle."""
    counts = count_array_from_types(hand)

    def links(t: int) -> int:
        n = (counts[t] - 1) * 2
        if t < N_SUITED_TYPES:
            rank = t % RANKS_PER_SUIT
            for d in (-2, -1, 1, 2):
                if 0 <= rank + d < RANKS_PER_SUIT:
                    n += counts[t + d]
        return n

    def order(t: int) -> tuple[int, int, int, int]:
        middle = RANKS_PER_SUIT // 2
        honour = t >= N_SUITED_TYPES
        edge = 0 if honour else -abs(t % RANKS_PER_SUIT - middle)
        return links(t), 0 if honour else 1 if TileType(t) in ORPHAN_TYPES else 2, edge, t

    return TileType(min((t for t in range(len(counts)) if counts[t]), key=order))


def best_discard_ok(key: BestDiscardKey, naive: str) -> bool:
    best = min(o.shanten for o in key.options)
    if best > MAX_SHANTEN or not 1 <= len(key.correct) <= MAX_CORRECT or naive in key.correct:
        return False
    top = max(o.tiles for o in key.options if o.tile in key.correct)
    runners = [o.tiles for o in key.options if o.shanten == best and o.tile not in key.correct]
    return not runners or top - max(runners) >= MIN_UKEIRE_MARGIN


def safe_choice(
    options: Sequence[SafeOption], efficient: Iterable[str]
) -> tuple[tuple[str, ...], SafeReason] | None:
    """The accepted tiles and reason for a `safe_discard` puzzle, or `None`. A shape-efficient
    discard (`best_discard`'s answer) must deal in, so the puzzle is a real fold; every tile
    the chosen reason covers must be safe; and at most `MAX_ACCEPTED` tiles are."""
    dealing = {o.tile for o in options if o.deals_in_to}
    if not dealing & set(efficient):
        return None
    for reason in SAFE_REASON_ORDER:
        covered = [o for o in options if reason in o.reasons]
        if covered and not any(o.deals_in_to for o in covered):
            if len(covered) > MAX_ACCEPTED:
                return None
            return tuple(o.tile for o in covered), reason
    return None


def winning_tiles_ok(key: WinningTilesKey) -> bool:
    return bool(key.correct) and (len(key.correct) >= 2 or bool(key.below_minimum or key.dead))


def count_faan_ok(key: CountFaanKey) -> bool:
    return len(key.breakdown) >= 2


def winning_tiles_points(key: WinningTilesKey) -> int:
    """One per wait past the first; two each for a wait below the minimum and a dead wait."""
    return len(key.correct) - 1 + 2 * bool(key.below_minimum) + 2 * bool(key.dead)


def count_faan_points(key: CountFaanKey) -> int:
    return len(key.breakdown)


def decision_score(kind: PuzzleKind, rates: Mapping[str, float]) -> float:
    """Mean miss rate over the informative tiers present in `rates`."""
    misses = [1 - r for tier, r in rates.items() if tier not in _UNINFORMATIVE[kind]]
    return sum(misses) / len(misses)


def _policy_rate(state: GameState, correct_ids: set[int], mask: list[bool]) -> float:
    from bots.learned import LearnedBot

    logits = LearnedBot().logits(seat_view(state, 0))
    legal = [i for i, ok in enumerate(mask) if ok]
    top = max(float(logits[i]) for i in legal)
    weights = {i: math.exp(float(logits[i]) - top) for i in legal}
    return sum(w for i, w in weights.items() if i in correct_ids) / sum(weights.values())


def tier_rates(
    state: GameState, correct: Iterable[str], tiers: Sequence[str], seed: int
) -> dict[str, float]:
    """Each tier's chance of a correct discard from seat 0 of `state`. `T0` is exact (correct
    legal ids over all legal ids); the other tiers are greedy, so one `compute_action` call is
    their rate."""
    view = seat_view(state, 0)
    mask = legal_mask(state, 0)
    correct_ids = {DISCARD_BASE + int(parse_tile(c)) for c in correct}
    rates: dict[str, float] = {}
    for tier in tiers:
        if tier == BotTier.T0:
            rates[tier] = sum(mask[i] for i in correct_ids) / sum(mask)
        else:
            aid = compute_action(view, mask, seed, tier, NO_DEADLINE)
            rates[tier] = float(aid in correct_ids)
    if BotTier.T4 in tiers:
        rates[POLICY_RATE] = _policy_rate(state, correct_ids, mask)
    return rates


def _discard_on(state: GameState, code: str) -> GameState:
    """The seat to act discards a `code` tile, opening the claim window (ADR 0025 "Claim
    positions")."""
    tile = next(t for t in state.seats[state.turn].concealed if tile_code(tile_id_type(t)) == code)
    after, _ = reduce(state, Discard(tile_id=tile))
    return after


def puzzle_state(record: Mapping[str, Any]) -> GameState:
    """The state a mined record poses its question on, seat 0 answering."""
    state = build_position(position_from_dict(record["position"]))
    return state if record["discard"] is None else _discard_on(state, record["discard"])


@dataclass(frozen=True)
class Source:
    game_seed: int
    decision: int
    seat: int


def _record(
    kind: PuzzleKind,
    state: GameState,
    source: Source,
    position_seed: int,
    key: Any,
    difficulty: dict[str, Any],
    miner: str,
    *,
    discard: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    spec = position_from_state(state, seed=position_seed, seat=source.seat)
    return {
        "kind": str(kind),
        "position": position_to_dict(spec),
        "discard": discard,
        "key": {**dataclasses.asdict(key), **(extra or {})},
        "difficulty": difficulty,
        "source": dataclasses.asdict(source),
        "miner_tier": miner,
        "engine_version": ENGINE_VERSION,
    }


def _dedupe_key(record: Mapping[str, Any], state: GameState) -> str:
    """Same kind, seat-0 hand and melds, and the same visible tiles: one puzzle."""
    seat0 = record["position"]["seats"][0]
    parts: list[Any] = [record["kind"], seat0["hand"], seat0["melds"], record["discard"]]
    key = record["key"]
    if record["kind"] in (PuzzleKind.BEST_DISCARD, PuzzleKind.SAFE_DISCARD):
        parts.append(seen34(seat_view(state, 0)))
    elif record["kind"] == PuzzleKind.WINNING_TILES:
        parts += [key["correct"], key["below_minimum"], key["dead"]]
    else:
        parts += [key["breakdown"], key["win_type"]]
    return json.dumps(parts)


class _Miner:
    """One game's scan. Every candidate is rebuilt from its spec before it's graded."""

    def __init__(self, game_seed: int, play_tier: str, rate_tiers: Sequence[str]) -> None:
        self.game_seed = game_seed
        self.play_tier = play_tier
        self.rate_tiers = rate_tiers
        self.records: list[tuple[str, dict[str, Any]]] = []
        self.stats: Counter[str] = Counter()

    def _rebuilt(self, state: GameState, source: Source, seed: int) -> GameState | None:
        try:
            return build_position(position_from_state(state, seed=seed, seat=source.seat))
        except ValueError:
            self.stats["unrepresentable"] += 1
            return None

    def _keep(self, record: dict[str, Any], rebuilt: GameState) -> None:
        self.records.append((_dedupe_key(record, rebuilt), record))
        self.stats[record["kind"]] += 1

    def _decision(
        self, kind: PuzzleKind, state: GameState, src: Source, seed: int, rebuilt: GameState,
        key: Any, correct: Sequence[str], extra: Mapping[str, Any],
    ) -> None:  # fmt: skip
        rates = tier_rates(rebuilt, correct, self.rate_tiers, seed)
        score = decision_score(kind, rates)
        band = band_for(score, DECISION_BANDS[kind])
        difficulty = {"band": band, "score": score, "rates": rates}
        record = _record(kind, state, src, seed, key, difficulty, self.play_tier, extra=extra)
        self._keep(record, rebuilt)

    def scan_turn(self, state: GameState, decision: int) -> None:
        turn = state.turn
        seed = self.game_seed * GAME_STEP_CAP + decision
        if can_declare_win(state, turn):
            self.count_faan(state, Source(self.game_seed, decision, turn), seed, None)
            return
        src = Source(self.game_seed, decision, turn)
        hand34 = seat_hand34(state.seats[turn])
        closed = not state.seats[turn].melds
        if shanten(hand34, closed=closed, hand_sets=state.ruleset.hand_sets) <= MAX_SHANTEN:
            self.best_discard(state, src, seed)
        if any(is_tenpai(state, s) for s in range(4) if s != turn):
            self.safe_discard(state, src, seed)
        for s in range(4):
            if s != turn and is_tenpai(state, s):
                self.winning_tiles(state, Source(self.game_seed, decision, s), seed)

    def best_discard(self, state: GameState, src: Source, seed: int) -> None:
        rebuilt = self._rebuilt(state, src, seed)
        if rebuilt is None:
            return
        key = best_discard(rebuilt, 0)
        naive = tile_code(naive_discard(tile_id_type(t) for t in rebuilt.seats[0].concealed))
        if best_discard_ok(key, naive):
            extra = {"naive": naive}
            self._decision(PuzzleKind.BEST_DISCARD, state, src, seed, rebuilt, key, key.correct,
                           extra)  # fmt: skip

    def safe_discard(self, state: GameState, src: Source, seed: int) -> None:
        rebuilt = self._rebuilt(state, src, seed)
        if rebuilt is None:
            return
        choice = safe_choice(safe_options(rebuilt, 0), best_discard(rebuilt, 0).correct)
        if choice is None:
            return
        accepted, reason = choice
        key = safe_discard(rebuilt, 0, accepted, reason)
        self._decision(PuzzleKind.SAFE_DISCARD, state, src, seed, rebuilt, key, key.correct, {})

    def winning_tiles(self, state: GameState, src: Source, seed: int) -> None:
        rebuilt = self._rebuilt(state, src, seed)
        if rebuilt is None:
            return
        key = winning_tiles(rebuilt, 0)
        if winning_tiles_ok(key):
            points = winning_tiles_points(key)
            difficulty = {"band": band_for(points, WINNING_TILES_BANDS), "score": points}
            record = _record(PuzzleKind.WINNING_TILES, state, src, seed, key, difficulty,
                             self.play_tier)  # fmt: skip
            self._keep(record, rebuilt)

    def count_faan(self, state: GameState, src: Source, seed: int, code: str | None) -> None:
        """`code`: the tile `state.turn` discards into the win, or `None` for a self-draw."""
        rebuilt = self._rebuilt(state, src, seed)
        if rebuilt is None:
            return
        if code is not None:
            rebuilt = _discard_on(rebuilt, code)
        key = count_faan(rebuilt, 0)
        if count_faan_ok(key):
            points = count_faan_points(key)
            difficulty = {"band": band_for(points, COUNT_FAAN_BANDS), "score": points}
            record = _record(PuzzleKind.COUNT_FAAN, state, src, seed, key, difficulty,
                             self.play_tier, discard=code)  # fmt: skip
            self._keep(record, rebuilt)


def _turns(seed: int, tier: str) -> Iterator[tuple[int, GameState, GameState]]:
    """`(decision, state, after)` for every decision of a seeded game, all four seats `tier`.
    Claim order is `min(pending)`, as in `bots.arena`."""
    state = new_game(LESSON_RULESET, seed)
    for decision in range(GAME_STEP_CAP):
        if state.phase == Phase.GAME_OVER:
            return
        if state.phase == Phase.HAND_OVER:
            state, _ = start_next_hand(state)
            continue
        window = state.claim_window
        if window is not None:
            seat = min(o.seat for o in window.offers if o.seat not in window.responses)
        else:
            seat = state.turn
        mask = legal_mask(state, seat)
        aid = compute_action(seat_view(state, seat), mask, seed * 4 + seat, tier, NO_DEADLINE)
        after, _ = reduce(state, decode_action(aid, state, seat))
        yield decision, state, after
        state = after
    raise RuntimeError(f"seed={seed}: exceeded {GAME_STEP_CAP} steps")


def mine_game(
    seed: int, play_tier: str, rate_tiers: Sequence[str]
) -> tuple[list[tuple[str, dict[str, Any]]], Counter[str]]:
    """Top-level for the process pool: `(dedupe key, record)` pairs and scan counters."""
    miner = _Miner(seed, play_tier, rate_tiers)
    for decision, state, after in _turns(seed, play_tier):
        miner.stats["decisions"] += 1
        if state.phase != Phase.AWAIT_ACTION:
            continue
        miner.stats["turns_scanned"] += 1
        miner.scan_turn(state, decision)
        window = after.claim_window
        if window is not None and after.phase == Phase.AWAIT_CLAIMS:
            discard = tile_code(tile_id_type(window.tile))
            for offer in window.offers:
                if offer.can_win:
                    src = Source(seed, decision, offer.seat)
                    miner.count_faan(state, src, seed * GAME_STEP_CAP + decision, discard)
    miner.stats["games"] += 1
    return miner.records, miner.stats


_SPREAD: Mapping[str, Callable[[Mapping[str, Any]], Any]] = {
    PuzzleKind.BEST_DISCARD: lambda r: min(o["shanten"] for o in r["key"]["options"]),
    PuzzleKind.SAFE_DISCARD: lambda r: r["key"]["reason"],
    PuzzleKind.WINNING_TILES: lambda r: len(r["key"]["correct"]),
    PuzzleKind.COUNT_FAAN: lambda r: r["key"]["correct"],
}
"""What a kind's shortlist varies within a band: shanten, reason, wait count, faan total."""


def _round_robin(groups: Iterable[list[Any]]) -> Iterator[Any]:
    queues = [list(g) for g in groups]
    while any(queues):
        for q in queues:
            if q:
                yield q.pop(0)


def _shortlist_eligible(record: Mapping[str, Any]) -> bool:
    """A best_discard key is pure efficiency; keep it only where the strongest public tier
    played a correct answer too, so a value play isn't marked wrong."""
    if record["kind"] != PuzzleKind.BEST_DISCARD:
        return True
    rates = record["difficulty"]["rates"]
    strongest = BotTier.T4 if BotTier.T4 in rates else BotTier.T2
    return bool(rates[strongest])


def shortlist(records: Sequence[Mapping[str, Any]], per_kind: int) -> list[Mapping[str, Any]]:
    """Up to `per_kind` per kind, round-robin over bands, then over `_SPREAD` values within a
    band, in mining order. Deterministic for a given `records`."""
    out: list[Mapping[str, Any]] = []
    for kind in PuzzleKind:
        mine = [r for r in records if r["kind"] == kind and _shortlist_eligible(r)]
        bands = []
        for band in Band:
            in_band = [r for r in mine if r["difficulty"]["band"] == band]
            by_value: dict[Any, list[Any]] = {}
            for r in in_band:
                by_value.setdefault(_SPREAD[kind](r), []).append(r)
            bands.append(list(_round_robin(by_value[v] for v in sorted(by_value))))
        out += list(_round_robin(bands))[:per_kind]
    return out


def mine(
    seeds: Sequence[int], workers: int, play_tier: str, rate_tiers: Sequence[str]
) -> tuple[list[dict[str, Any]], Counter[str]]:
    """Deduped records in seed order (first sighting kept) and summed counters."""
    stats: Counter[str] = Counter()
    seen: set[str] = set()
    records: list[dict[str, Any]] = []

    def collect(results: Iterable[tuple[list[tuple[str, dict[str, Any]]], Counter[str]]]) -> None:
        for game_records, game_stats in results:
            stats.update(game_stats)
            for dedupe, record in game_records:
                if dedupe in seen:
                    stats["duplicates"] += 1
                    continue
                seen.add(dedupe)
                records.append(record)

    args = ([play_tier] * len(seeds), [rate_tiers] * len(seeds))
    if workers <= 1:
        collect(map(mine_game, seeds, *args))
    else:
        # spawn: a fresh numpy per worker reads OPENBLAS_NUM_THREADS
        with ProcessPoolExecutor(workers, mp_context=get_context("spawn")) as pool:
            collect(pool.map(mine_game, seeds, *args))
    return records, stats


def _tiers() -> tuple[str, list[str], str | None]:
    """`(play tier, rated tiers, why T4 is unavailable)`."""
    from bots.learned import weights_problem

    problem = weights_problem()
    if problem is None:
        return MINER_TIER, list(RATED_TIERS), None
    return FALLBACK_TIER, [t for t in RATED_TIERS if t != BotTier.T4], problem


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--games", type=int, default=10)
    parser.add_argument("--seed", type=int, default=0, help="first game seed")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--out", type=Path, required=True, help="every candidate, JSONL")
    parser.add_argument("--shortlist", type=Path, help="curated JSON, per kind and band")
    parser.add_argument("--per-kind", type=int, default=15)
    args = parser.parse_args(argv)

    # one thread per process: workers already fill the cores (docs/testing.md §1)
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    play_tier, rate_tiers, problem = _tiers()
    if problem is not None:
        print(
            f"T4 unavailable ({problem}); playing {play_tier}, rating without T4", file=sys.stderr
        )

    seeds = range(args.seed, args.seed + args.games)
    records, stats = mine(seeds, args.workers, play_tier, rate_tiers)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as f:
        for record in records:
            f.write(json.dumps(record, sort_keys=True) + "\n")
    if args.shortlist is not None:
        picked = shortlist(records, args.per_kind)
        payload = {
            "engine_version": ENGINE_VERSION,
            "miner_tier": play_tier,
            "seeds": [args.seed, args.seed + args.games - 1],
            "puzzles": picked,
        }
        args.shortlist.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n")

    bands = Counter((r["kind"], r["difficulty"]["band"]) for r in records)
    summary = {
        "play_tier": play_tier,
        "stats": dict(stats),
        "kept": dict(Counter(r["kind"] for r in records)),
        "bands": {f"{k}/{b}": n for (k, b), n in sorted(bands.items())},
    }
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
