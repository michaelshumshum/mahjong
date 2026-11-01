"""One puzzle's lesson JSON (docs/protocol.md §6 "Generated lesson bundle"): the shape both
`tools/gen_lessons.py` writes as `<id>.json` and `GET /lessons/random` returns."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.frames import state_sync_frame, to_envelope
from app.lessons.model import LessonKind, Puzzle
from mahjong_core.engine import ENGINE_VERSION
from mahjong_core.state import GameState


def snapshot(state: GameState) -> dict[str, Any]:
    """Seat 0's `state_sync` frame, as `Table.state_sync_wire` and `ws.py` would send it to a
    fresh seat with no clock: no deadlines, no history, `seq`/`ts` 0."""
    return to_envelope(state_sync_frame(state, 0), seq=0, ts=0)


def puzzle_entry(puzzle: Puzzle, n: int) -> dict[str, Any]:
    """A puzzle's `LessonIndexEntry`; `n` is its place among its track's puzzles."""
    return {
        "id": puzzle.id,
        "lesson_kind": str(LessonKind.PUZZLE),
        "kind": str(puzzle.kind),
        "track": str(puzzle.track),
        "band": str(puzzle.band),
        "text": puzzle.text,
        "n": n,
        "theme": None if puzzle.theme is None else str(puzzle.theme),
    }


def puzzle_payload(
    entry: Mapping[str, Any], state: GameState, key: Mapping[str, Any]
) -> dict[str, Any]:
    """A `Lesson`: the entry, the engine version, the snapshot of `state` (the puzzle's
    `puzzle_state`) and `key` (`dataclasses.asdict` of its answer key)."""
    return {
        **entry,
        "engine_version": ENGINE_VERSION,
        "snapshot": snapshot(state),
        "key": key,
    }
