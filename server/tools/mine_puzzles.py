"""Mine learn-mode puzzles from seeded Expert self-play and rate them with the bot tiers
(docs/decisions/0025-learn-mode.md "Random endless puzzles").

    uv run python -m tools.mine_puzzles --games 2000 --seed 20000000 --workers 8 \\
        --out /tmp/mined.jsonl --shortlist app/lessons/mined_puzzles.json
    uv run python -m tools.mine_puzzles --from /tmp/mined.jsonl --pool app/lessons/puzzle_pool.json

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
from multiprocessing import get_context
from pathlib import Path
from typing import Any

from app.lessons.catalog.mined import TRACKS, mined_puzzles
from app.lessons.grade import (
    BestDiscardKey,
    CountFaanKey,
    SafeOption,
    WinningTilesKey,
    best_discard,
    count_faan,
    key_from_dict,
    reaches_min_faan,
    safe_discard,
    safe_options,
    winning_tiles,
)
from app.lessons.model import LESSON_RULESET, Band, PuzzleKind, SafeReason
from app.lessons.position import (
    build_position,
    discard_on,
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
from mahjong_core.actions import can_declare_win
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
# the stated reason: the strongest one every accepted tile shares
SAFE_REASON_ORDER = (SafeReason.ALL_COPIES_VISIBLE, SafeReason.NO_CHANCE)
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
# endless pool size per kind and band: ~1.1 kB a puzzle (adr 0025 "random endless puzzles")
POOL_PER_BAND = 100
# shortlist variety: a game recurs at most this often across all tracks, once per track
SHORTLIST_GAME_CAP = 2
# decisions: the same seat this close in one game is the same hand (a hand is ~70-120)
SAME_HAND_WINDOW = 60


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


def best_discard_band(key: BestDiscardKey, score: float) -> Band:
    """`band_for` the score, capped where shanten alone decides: when every wrong discard ends
    further from ready than the answer, ready (shanten 0) is beginner and 1-2 at most
    intermediate (adr 0025 "difficulty, decision kinds")."""
    band = band_for(score, DECISION_BANDS[PuzzleKind.BEST_DISCARD])
    best = min(o.shanten for o in key.options)
    if any(o.shanten == best for o in key.options if o.tile not in key.correct):
        return band
    cap = Band.BEGINNER if best <= 0 else Band.INTERMEDIATE
    order = list(Band)
    return order[min(order.index(band), order.index(cap))]


def keeps_value(state: GameState, key: BestDiscardKey) -> bool:
    """Every answer keeps a route to `min_faan` (`reaches_min_faan`): efficiency must not grade
    a discard that leaves the hand unable to win as right."""
    return all(reaches_min_faan(state, 0, tile) for tile in key.correct)


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
    discard (`best_discard`'s answer) must deal in, so the puzzle is a real fold, and none of
    them may be deducible, so folding costs shape. Accepted are every tile with a deduction:
    1 to `MAX_ACCEPTED` of them, none dealing in, sharing a reason the explanation can state."""
    natural = set(efficient)
    dealing = {o.tile for o in options if o.deals_in_to}
    if not dealing & natural:
        return None
    deducible = [o for o in options if o.reasons]
    if not 1 <= len(deducible) <= MAX_ACCEPTED:
        return None
    if any(o.deals_in_to or o.tile in natural for o in deducible):
        return None
    for reason in SAFE_REASON_ORDER:
        if all(reason in o.reasons for o in deducible):
            return tuple(o.tile for o in deducible), reason
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


def puzzle_state(record: Mapping[str, Any]) -> GameState:
    """The state a mined record poses its question on, seat 0 answering."""
    state = build_position(position_from_dict(record["position"]))
    return state if record["discard"] is None else discard_on(state, record["discard"])


def _record_keeps_value(record: Mapping[str, Any]) -> bool:
    key = key_from_dict(PuzzleKind.BEST_DISCARD, record["key"])
    assert isinstance(key, BestDiscardKey)
    return keeps_value(puzzle_state(record), key)


def recheck(
    records: Sequence[dict[str, Any]], workers: int
) -> tuple[list[dict[str, Any]], Counter[str]]:
    """What `--from` re-applies, since a stored record keeps the band and filters it was mined
    under: drops a `best_discard` that fails `keeps_value` and re-bands the rest by
    `best_discard_band` on the stored score. Both read only the stored key and position."""
    discards = [r for r in records if r["kind"] == PuzzleKind.BEST_DISCARD]
    if workers <= 1:
        verdicts = list(map(_record_keeps_value, discards))
    else:
        with ProcessPoolExecutor(workers, mp_context=get_context("spawn")) as executor:
            verdicts = list(executor.map(_record_keeps_value, discards, chunksize=200))
    keeps = {id(r): ok for r, ok in zip(discards, verdicts, strict=True)}
    stats: Counter[str] = Counter()
    out: list[dict[str, Any]] = []
    for record in records:
        if record["kind"] != PuzzleKind.BEST_DISCARD:
            out.append(record)
            continue
        if not keeps[id(record)]:
            stats["value_rejected"] += 1
            continue
        key = key_from_dict(PuzzleKind.BEST_DISCARD, record["key"])
        assert isinstance(key, BestDiscardKey)
        band = best_discard_band(key, record["difficulty"]["score"])
        if band != record["difficulty"]["band"]:
            stats["rebanded"] += 1
            record = {**record, "difficulty": {**record["difficulty"], "band": band}}
        out.append(record)
    return out, stats


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
        if isinstance(key, BestDiscardKey):
            band = best_discard_band(key, score)
        else:
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
        if best_discard_ok(key, naive) and keeps_value(rebuilt, key):
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
            rebuilt = discard_on(rebuilt, code)
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


def _by_band(
    records: Sequence[Mapping[str, Any]], kind: PuzzleKind
) -> list[list[Mapping[str, Any]]]:
    """A kind's eligible records per band in `Band` order, each band round-robin over
    `_SPREAD` values, in mining order within a value."""
    mine = [r for r in records if r["kind"] == kind and _shortlist_eligible(r)]
    bands = []
    for band in Band:
        by_value: dict[Any, list[Any]] = {}
        for r in mine:
            if r["difficulty"]["band"] == band:
                by_value.setdefault(_SPREAD[kind](r), []).append(r)
        bands.append(list(_round_robin(by_value[v] for v in sorted(by_value))))
    return bands


def _fits(record: Mapping[str, Any], same_game: Sequence[Mapping[str, Any]], game_cap: int) -> bool:
    if len(same_game) >= game_cap or any(t["kind"] == record["kind"] for t in same_game):
        return False
    src = record["source"]
    return not any(
        t["source"]["seat"] == src["seat"]
        and abs(t["source"]["decision"] - src["decision"]) <= SAME_HAND_WINDOW
        for t in same_game
    )


def varied(
    bands: Sequence[Sequence[Mapping[str, Any]]],
    n: int,
    taken: dict[int, list[Mapping[str, Any]]],
    game_cap: int,
) -> list[Mapping[str, Any]]:
    """Up to `n` records round-robin over `bands`, each band skipping ahead past a record whose
    game already has `game_cap` in `taken`, one of its kind, or its seat's same hand
    (`SAME_HAND_WINDOW`). Adds what it picks to `taken`, keyed by game seed."""
    out: list[Mapping[str, Any]] = []
    at = [0] * len(bands)
    while len(out) < n and any(i < len(b) for i, b in zip(at, bands, strict=True)):
        for b, band in enumerate(bands):
            while at[b] < len(band):
                record = band[at[b]]
                at[b] += 1
                game = record["source"]["game_seed"]
                if _fits(record, taken.get(game, []), game_cap):
                    taken.setdefault(game, []).append(record)
                    out.append(record)
                    break
            if len(out) == n:
                break
    return out


def shortlist(records: Sequence[Mapping[str, Any]], per_kind: int) -> list[Mapping[str, Any]]:
    """Up to `per_kind` per kind, round-robin over bands, then over `_SPREAD` values within a
    band, in mining order, skipping what `varied` refuses against every track taken so far.
    Deterministic for a given `records`."""
    out: list[Mapping[str, Any]] = []
    taken: dict[int, list[Mapping[str, Any]]] = {}
    for kind in PuzzleKind:
        out += varied(_by_band(records, kind), per_kind, taken, SHORTLIST_GAME_CAP)
    return out


def pool_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """What `app/lessons/pool.py` serves: the record without its bot rates, with an id from its
    source (unique within a kind) and the theme the mined catalog reads off it."""
    src = record["source"]
    kind = PuzzleKind(record["kind"])
    # naive is a mining filter's input, not part of answer_key()
    key = {k: v for k, v in record["key"].items() if k != "naive"}
    out = {
        "id": f"{TRACKS[kind]}-{src['game_seed']}-{src['decision']}-{src['seat']}",
        "kind": record["kind"],
        "difficulty": {"band": record["difficulty"]["band"]},
        "position": record["position"],
        "discard": record["discard"],
        "key": key,
        "source": src,
    }
    (puzzle,) = mined_puzzles([out])
    return out | {"theme": None if puzzle.theme is None else str(puzzle.theme)}


def pool(records: Sequence[Mapping[str, Any]], per_band: int) -> list[dict[str, Any]]:
    """The endless pool: up to `per_band` per kind and band, picked as `shortlist` orders a
    band, one per game per kind (`varied` with the kind's own `taken`). Endless plays one kind
    at a time, so a game recurring across kinds is never seen back to back. Deterministic for a
    given `records`."""
    out = []
    for kind in PuzzleKind:
        taken: dict[int, list[Mapping[str, Any]]] = {}
        for in_band in _by_band(records, kind):
            out += [pool_record(r) for r in varied([in_band], per_band, taken, game_cap=1)]
    return out


def pool_text(puzzles: Sequence[Mapping[str, Any]], meta: Mapping[str, Any]) -> str:
    """`meta` plus `puzzles`, one puzzle per line so a regenerated pool diffs by puzzle."""
    lines = ",\n".join(json.dumps(p, sort_keys=True, separators=(",", ":")) for p in puzzles)
    head = json.dumps(dict(meta), sort_keys=True)
    return f'{head[:-1]}, "puzzles": [\n{lines}\n]}}\n'


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
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--out", type=Path, help="mine, and write every candidate as JSONL")
    source.add_argument("--from", dest="from_", type=Path, help="read an earlier --out instead")
    parser.add_argument("--shortlist", type=Path, help="curated JSON, per kind and band")
    parser.add_argument("--per-kind", type=int, default=15)
    parser.add_argument("--pool", type=Path, help="endless pool JSON, per kind and band")
    parser.add_argument("--per-band", type=int, default=POOL_PER_BAND)
    args = parser.parse_args(argv)

    stats: Counter[str] = Counter()
    if args.from_ is not None:
        with args.from_.open() as f:
            records = [json.loads(line) for line in f]
        records, stats = recheck(records, args.workers)
        play_tier = records[0]["miner_tier"]
        game_seeds = [r["source"]["game_seed"] for r in records]
        seed_range = [min(game_seeds), max(game_seeds)]
    else:
        # one thread per process: workers already fill the cores (docs/testing.md §1)
        os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
        play_tier, rate_tiers, problem = _tiers()
        if problem is not None:
            print(
                f"T4 unavailable ({problem}); playing {play_tier}, rating without T4",
                file=sys.stderr,
            )
        seeds = range(args.seed, args.seed + args.games)
        records, stats = mine(seeds, args.workers, play_tier, rate_tiers)
        seed_range = [args.seed, args.seed + args.games - 1]
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w") as f:
            for record in records:
                f.write(json.dumps(record, sort_keys=True) + "\n")
    meta = {"engine_version": ENGINE_VERSION, "miner_tier": play_tier, "seeds": seed_range}
    if args.shortlist is not None:
        payload = {**meta, "puzzles": shortlist(records, args.per_kind)}
        args.shortlist.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n")
    if args.pool is not None:
        pooled = pool(records, args.per_band)
        args.pool.write_text(pool_text(pooled, {**meta, "per_band": args.per_band}))

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
