"""The mined shortlist (`app/lessons/mined_puzzles.json`, ADR 0025 "Mined puzzles") as one track
per kind, beginner to advanced. Each answer and theme is read off the shortlist's key, regraded
by `make proto`. Prose is shared per kind (`text`), with the key's numbers interpolated; the
title is the theme's."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.lessons.grade import key_from_dict
from app.lessons.model import Band, Puzzle, PuzzleKind, SafeReason, Track
from app.lessons.position import position_from_dict
from app.lessons.themes import puzzle_theme
from mahjong_core.state import WinType
from mahjong_core.tiles import TileType, parse_tiles

SHORTLIST_PATH = Path(__file__).resolve().parents[1] / "mined_puzzles.json"
"""The committed shortlist `tools.mine_puzzles` writes (ADR 0025 "Mined puzzles")."""

TRACKS: Mapping[PuzzleKind, Track] = {
    PuzzleKind.WINNING_TILES: Track.WAITS,
    PuzzleKind.BEST_DISCARD: Track.EFFICIENCY,
    PuzzleKind.SAFE_DISCARD: Track.DEFENCE,
    PuzzleKind.COUNT_FAAN: Track.FAAN,
}


def _text(kind: PuzzleKind, key: Mapping[str, Any]) -> str:
    """One stem per kind; `safe_discard` per reason, `count_faan` per win type."""
    stem = "mined" + TRACKS[kind].capitalize()
    if kind == PuzzleKind.SAFE_DISCARD:
        reason = SafeReason(key["reason"])
        return stem + "".join(w.capitalize() for w in reason.split("_"))
    if kind == PuzzleKind.COUNT_FAAN:
        return stem + ("SelfDraw" if key["win_type"] == WinType.SELF_DRAW else "Discard")
    return stem


def _answer(key: Mapping[str, Any]) -> tuple[str, ...] | int:
    correct = key["correct"]
    return correct if isinstance(correct, int) else tuple(correct)


def mined_puzzles(records: list[Mapping[str, Any]]) -> tuple[Puzzle, ...]:
    """Grouped by track in `TRACKS` order, then band, then shortlist order; ids number each
    track from 01."""
    out: list[Puzzle] = []
    for kind, track in TRACKS.items():
        picked = [r for r in records if r["kind"] == kind]
        picked.sort(key=lambda r: list(Band).index(Band(r["difficulty"]["band"])))
        for n, record in enumerate(picked, start=1):
            key = record["key"]
            position = position_from_dict(record["position"])
            hand = [t for t in parse_tiles(position.seats[0].hand) if isinstance(t, TileType)]
            out.append(
                Puzzle(
                    id=f"{track}-{n:02d}",
                    kind=kind,
                    track=track,
                    band=Band(record["difficulty"]["band"]),
                    position=position,
                    answer=_answer(key),
                    text=_text(kind, key),
                    reason=SafeReason(key["reason"]) if kind == PuzzleKind.SAFE_DISCARD else None,
                    discard=record["discard"],
                    theme=puzzle_theme(key_from_dict(kind, key), hand),
                )
            )
    return tuple(out)


MINED: tuple[Puzzle, ...] = mined_puzzles(json.loads(SHORTLIST_PATH.read_text())["puzzles"])
