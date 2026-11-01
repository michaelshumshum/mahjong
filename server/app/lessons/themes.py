"""Puzzle themes (ADR 0025 "Themes"): what a puzzle teaches, read off its answer key and seat
0's concealed hand. Each kind tries its `THEMES_BY_KIND` themes in order and takes the first
that holds; the last always holds. Pure, like `grade.py`."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from enum import Enum, auto

from app.lessons.grade import (
    AnswerKey,
    BestDiscardKey,
    CountFaanKey,
    SafeDiscardKey,
    WinningTilesKey,
)
from app.lessons.model import THEMES_BY_KIND, PuzzleKind, PuzzleTheme, SafeReason
from mahjong_core.scoring.patterns import PATTERNS
from mahjong_core.tiles import (
    N_SUITED_TYPES,
    RANKS_PER_SUIT,
    TileType,
    count_array_from_types,
    parse_tile,
)

_LIMIT_PATTERNS = frozenset(p.name for p in PATTERNS if p.is_limit)
_HONOUR_PUNG_PATTERNS = frozenset({"箭刻", "門風", "圈風"})
_FLOWER_PATTERNS = frozenset({"正花", "一台花"})


class WaitShape(Enum):
    """The part a winning tile plays in a completed hand."""

    TWO_SIDED = auto()
    EDGE = auto()
    CLOSED = auto()
    PAIR = auto()
    SINGLE = auto()


def _rank(t: int) -> int:
    return t % RANKS_PER_SUIT


def _groups(counts: list[int], pair: bool) -> list[list[tuple[int, ...]]]:
    """Every split of `counts` into sets and, unless `pair` is already taken, one pair."""
    first = next((t for t, c in enumerate(counts) if c), None)
    if first is None:
        return [[]] if pair else []
    shapes: list[tuple[int, ...]] = [(first,) * 3]
    if not pair:
        shapes.append((first,) * 2)
    if first < N_SUITED_TYPES and _rank(first) <= RANKS_PER_SUIT - 3:
        shapes.append((first, first + 1, first + 2))
    out = []
    for shape in shapes:
        if any(counts[t] < shape.count(t) for t in set(shape)):
            continue
        for t in shape:
            counts[t] -= 1
        for rest in _groups(counts, pair or len(shape) == 2):
            out.append([shape, *rest])
        for t in shape:
            counts[t] += 1
    return out


def _shape(group: tuple[int, ...], tile: int) -> WaitShape:
    if len(group) == 2:
        return WaitShape.SINGLE
    if group[0] == group[1]:
        return WaitShape.PAIR
    if tile == group[1]:
        return WaitShape.CLOSED
    # 12 waiting on 3, 89 waiting on 7
    low_edge = tile == group[2] and _rank(group[0]) == 0
    high_edge = tile == group[0] and _rank(group[2]) == RANKS_PER_SUIT - 1
    return WaitShape.EDGE if low_edge or high_edge else WaitShape.TWO_SIDED


def wait_shapes(hand: Sequence[TileType], tile: TileType) -> frozenset[WaitShape]:
    """The shapes `tile` completes `hand` (concealed, one short) as, over every standard split;
    empty for a non-standard win (Thirteen Orphans)."""
    counts = count_array_from_types([*hand, tile])
    return frozenset(
        _shape(group, tile) for split in _groups(counts, False) for group in split if tile in group
    )


def _winning_tiles(
    key: WinningTilesKey, hand: Sequence[TileType]
) -> Mapping[PuzzleTheme, Callable[[], bool]]:
    shapes = [wait_shapes(hand, TileType(int(parse_tile(o.tile)))) for o in key.options]

    def only(*allowed: WaitShape) -> bool:
        return all(s and s <= set(allowed) for s in shapes)

    return {
        PuzzleTheme.TOO_CHEAP: lambda: bool(key.below_minimum),
        PuzzleTheme.DEAD_WAIT: lambda: bool(key.dead),
        PuzzleTheme.MANY_SIDED: lambda: len(key.options) >= 3,
        PuzzleTheme.TWO_SIDED: lambda: only(WaitShape.TWO_SIDED),
        PuzzleTheme.PAIR_WAIT: lambda: only(WaitShape.PAIR),
        PuzzleTheme.SINGLE_WAIT: lambda: only(WaitShape.SINGLE),
        PuzzleTheme.EDGE_CLOSED: lambda: only(WaitShape.EDGE, WaitShape.CLOSED),
        PuzzleTheme.MIXED_WAIT: lambda: True,
    }


def _best_discard(
    key: BestDiscardKey, hand: Sequence[TileType]
) -> Mapping[PuzzleTheme, Callable[[], bool]]:
    counts = count_array_from_types(hand)
    correct = [int(parse_tile(c)) for c in key.correct]
    best = min(o.shanten for o in key.options)
    ready_elsewhere = any(o.shanten <= 0 and o.tile not in key.correct for o in key.options)

    def held(t: int, near: int) -> bool:
        """`near` is a held tile of `t`'s suit."""
        n = t + near
        return 0 <= _rank(t) + near < RANKS_PER_SUIT and counts[n] > 0

    def run_end(t: int) -> bool:
        """`t` ends four or more held consecutive ranks."""
        for step in (1, -1):
            if all(held(t, step * k) for k in (1, 2, 3)):
                return True
        return False

    def leaves_two_sided(t: int) -> bool:
        """A lone `t`, two from a held tile that has its own neighbour beyond it: cutting `t`
        leaves the two-sided shape (the 2 of 245)."""
        return counts[t] == 1 and any(
            held(t, 2 * step) and held(t, 3 * step) and not held(t, step) for step in (1, -1)
        )

    def floating(t: int) -> bool:
        return counts[t] == 1 and not any(held(t, d) for d in (-2, -1, 1, 2))

    def suited(t: int) -> bool:
        return t < N_SUITED_TYPES

    return {
        PuzzleTheme.WIDER_WAIT: lambda: best <= 0 and ready_elsewhere,
        PuzzleTheme.REACH_READY: lambda: best <= 0,
        PuzzleTheme.TRIM_RUN: lambda: any(suited(t) and run_end(t) for t in correct),
        PuzzleTheme.CUT_TERMINAL: lambda: any(
            suited(t) and _rank(t) in (0, RANKS_PER_SUIT - 1) for t in correct
        ),
        PuzzleTheme.KEEP_TWO_SIDED: lambda: any(suited(t) and leaves_two_sided(t) for t in correct),
        PuzzleTheme.CUT_FLOATER: lambda: any(
            floating(t) if suited(t) else counts[t] == 1 for t in correct
        ),
        PuzzleTheme.BREAK_PAIR: lambda: any(counts[t] >= 2 for t in correct),
        PuzzleTheme.MOST_TILES: lambda: True,
    }


def _safe_discard(key: SafeDiscardKey) -> Mapping[PuzzleTheme, Callable[[], bool]]:
    honours = all(int(parse_tile(c)) >= N_SUITED_TYPES for c in key.correct)
    return {
        PuzzleTheme.WALLED_RUNS: lambda: key.reason == SafeReason.NO_CHANCE,
        PuzzleTheme.DEAD_HONOUR: lambda: honours,
        PuzzleTheme.ALL_VISIBLE: lambda: True,
    }


def _count_faan(key: CountFaanKey) -> Mapping[PuzzleTheme, Callable[[], bool]]:
    names = {line.pattern for line in key.breakdown}
    half = "混一色" in names
    return {
        PuzzleTheme.LIMIT_HAND: lambda: bool(names & _LIMIT_PATTERNS),
        PuzzleTheme.FULL_FLUSH: lambda: "清一色" in names,
        PuzzleTheme.HALF_FLUSH_PUNGS: lambda: half and "對對糊" in names,
        PuzzleTheme.HALF_FLUSH_HONOURS: lambda: half and bool(names & _HONOUR_PUNG_PATTERNS),
        PuzzleTheme.HALF_FLUSH: lambda: half,
        PuzzleTheme.ALL_PUNGS: lambda: "對對糊" in names,
        PuzzleTheme.ALL_CHOWS: lambda: "平糊" in names,
        PuzzleTheme.FLOWERS: lambda: bool(names & _FLOWER_PATTERNS),
        PuzzleTheme.SMALL_FAAN: lambda: True,
    }


def puzzle_theme(key: AnswerKey, hand: Sequence[TileType]) -> PuzzleTheme:
    """`hand`: seat 0's concealed tiles as posed (a discard win's claimed tile not among them);
    only `winning_tiles` and `best_discard` read it."""
    tests: Mapping[PuzzleTheme, Callable[[], bool]]
    match key:
        case WinningTilesKey():
            kind, tests = PuzzleKind.WINNING_TILES, _winning_tiles(key, hand)
        case BestDiscardKey():
            kind, tests = PuzzleKind.BEST_DISCARD, _best_discard(key, hand)
        case SafeDiscardKey():
            kind, tests = PuzzleKind.SAFE_DISCARD, _safe_discard(key)
        case CountFaanKey():
            kind, tests = PuzzleKind.COUNT_FAAN, _count_faan(key)
    return next(theme for theme in THEMES_BY_KIND[kind] if tests[theme]())
