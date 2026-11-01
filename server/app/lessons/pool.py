"""The endless puzzle pool behind `GET /lessons/random` (ADR 0025 "Random endless puzzles"):
`puzzle_pool.json`, mined puzzles per kind and band with their answer keys stored, written by
`tools.mine_puzzles --pool`. Serving reads the stored key and never grades;
`tests/test_lessons_pool.py` regrades every puzzle. Loaded on first use, not at import."""

from __future__ import annotations

import dataclasses
import functools
import json
import random
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.lessons.catalog.mined import mined_puzzles
from app.lessons.grade import puzzle_state
from app.lessons.model import Band, Puzzle, PuzzleKind
from app.lessons.payload import puzzle_entry, puzzle_payload

POOL_PATH = Path(__file__).resolve().parent / "puzzle_pool.json"


@dataclass(frozen=True)
class PooledPuzzle:
    """`key`: the stored answer key, `dataclasses.asdict` of `answer_key(puzzle)`. `n`: its place
    among its kind's pooled puzzles."""

    puzzle: Puzzle
    key: Mapping[str, Any]
    n: int


@dataclass(frozen=True)
class Pool:
    engine_version: str
    puzzles: Mapping[tuple[PuzzleKind, Band], Sequence[PooledPuzzle]]


def pool_from_dict(payload: Mapping[str, Any]) -> Pool:
    """Each record becomes its `Puzzle` the way the mined catalog builds one, under its pool
    id, so endless puzzles share the mined tracks' text."""
    puzzles: dict[tuple[PuzzleKind, Band], list[PooledPuzzle]] = {}
    seen: dict[PuzzleKind, int] = {}
    for record in payload["puzzles"]:
        (puzzle,) = mined_puzzles([record])
        puzzle = dataclasses.replace(puzzle, id=record["id"])
        seen[puzzle.kind] = seen.get(puzzle.kind, 0) + 1
        pooled = PooledPuzzle(puzzle, record["key"], seen[puzzle.kind])
        puzzles.setdefault((puzzle.kind, puzzle.band), []).append(pooled)
    return Pool(payload["engine_version"], puzzles)


@functools.cache
def load_pool(path: Path = POOL_PATH) -> Pool:
    return pool_from_dict(json.loads(path.read_text()))


def pick(
    pool: Pool,
    kind: PuzzleKind,
    band: Band | None,
    exclude: Collection[str] = (),
    rng: random.Random | None = None,
) -> PooledPuzzle:
    """A random puzzle of `kind` (and `band`, any if `None`) whose id isn't in `exclude`; when
    `exclude` covers them all, any of them."""
    bands = list(Band) if band is None else [band]
    candidates = [p for b in bands for p in pool.puzzles.get((kind, b), ())]
    if not candidates:
        raise LookupError(f"no pooled {kind} puzzles")
    fresh = [p for p in candidates if p.puzzle.id not in exclude]
    return (rng or random).choice(fresh or candidates)


def lesson_payload(pooled: PooledPuzzle) -> dict[str, Any]:
    """`pooled` as a lesson file (docs/protocol.md §6): the position is built per call, the key
    is the stored one."""
    entry = puzzle_entry(pooled.puzzle, pooled.n)
    return puzzle_payload(entry, puzzle_state(pooled.puzzle), pooled.key)
