"""Learn-mode lesson bundle for the web (docs/protocol.md §6, ADR 0025).

Builds every `app.lessons.catalog` puzzle, grades it with `answer_key`, and writes into
`web/src/lib/learn/generated/`:

- `index.json`: every lesson's `LessonIndexEntry`, in catalog order;
- `<id>.json`: one `Lesson` each: the entry, `engine_version`, a seat-0 `state_sync` frame and
  the answer key;
- `lessons.d.ts`: the TS types for both, and the lesson vocabularies.

Usage (from `server/`): uv run python -m tools.gen_lessons [--out <dir>]
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import types
import typing
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.lessons.catalog import CATALOG
from app.lessons.grade import (
    BestDiscardKey,
    CountFaanKey,
    SafeDiscardKey,
    WinningTilesKey,
    answer_key,
    puzzle_state,
    stated_answer_holds,
)
from app.lessons.model import Band, LessonKind, Puzzle, PuzzleKind, SafeReason, Track
from app.views import seat_view, seat_view_wire
from mahjong_core.engine import ENGINE_VERSION
from mahjong_core.presets import preset_id_for
from mahjong_core.state import GameState, WinType

OUT_DIR = Path(__file__).resolve().parents[2] / "web" / "src" / "lib" / "learn" / "generated"
INDEX_FILE = "index.json"
TYPES_FILE = "lessons.d.ts"

KEY_TYPES: Mapping[PuzzleKind, type] = {
    PuzzleKind.WINNING_TILES: WinningTilesKey,
    PuzzleKind.BEST_DISCARD: BestDiscardKey,
    PuzzleKind.COUNT_FAAN: CountFaanKey,
    PuzzleKind.SAFE_DISCARD: SafeDiscardKey,
}

# a url segment, and a paraglide key segment
_ID = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
_TEXT = re.compile(r"[A-Za-z0-9]+")

_LESSON_ENUMS: tuple[type[StrEnum], ...] = (LessonKind, PuzzleKind, Track, Band, SafeReason)
# already named in protocol.d.ts
_PROTOCOL_ENUMS: tuple[type[StrEnum], ...] = (WinType,)

_HEADER = (
    "// GENERATED FILE — do not hand-edit. Run `make proto` to regenerate.\n"
    "// Source of truth: server/app/lessons/ (docs/protocol.md §6).\n"
)


def check_catalog(catalog: Sequence[Puzzle]) -> None:
    """Raises `ValueError` on a duplicate or malformed id or text stem."""
    dupes = [i for i, n in Counter(p.id for p in catalog).items() if n > 1]
    if dupes:
        raise ValueError(f"duplicate lesson ids: {dupes}")
    for p in catalog:
        if not _ID.fullmatch(p.id):
            raise ValueError(f"lesson id {p.id!r} is not lowercase kebab-case")
        if not _TEXT.fullmatch(p.text):
            raise ValueError(f"{p.id}: text stem {p.text!r} is not alphanumeric")


def snapshot(state: GameState) -> dict[str, Any]:
    """Seat 0's `state_sync` frame, as `Table.state_sync_wire` and `ws.py` would send it to a
    fresh seat with no clock: no deadlines, no history, `seq`/`ts` 0."""
    d = seat_view_wire(seat_view(state, 0))
    d["hand_history"] = []
    d["ruleset_preset"] = preset_id_for(state.ruleset)
    d["ruleset"] = state.ruleset.to_dict()
    d["bot_levels"] = [None] * len(state.seats)
    return {"v": 1, "t": "state_sync", "seq": 0, "ts": 0, "d": d}


def index_entries(catalog: Sequence[Puzzle]) -> list[dict[str, Any]]:
    """`n` is the 1-based place within the track, for titles shared across a track."""
    per_track: Counter[Track] = Counter()
    entries = []
    for p in catalog:
        per_track[p.track] += 1
        entries.append(
            {
                "id": p.id,
                "lesson_kind": str(LessonKind.PUZZLE),
                "kind": str(p.kind),
                "track": str(p.track),
                "band": str(p.band),
                "text": p.text,
                "n": per_track[p.track],
            }
        )
    return entries


def lesson_payload(puzzle: Puzzle, entry: Mapping[str, Any]) -> dict[str, Any]:
    """Raises `ValueError` when the engine's key disagrees with the author's `answer`."""
    state = puzzle_state(puzzle)
    key = answer_key(puzzle, state)
    if not stated_answer_holds(puzzle, key):
        raise ValueError(f"{puzzle.id}: answer {puzzle.answer!r}, engine says {key.correct!r}")
    return {
        **entry,
        "engine_version": ENGINE_VERSION,
        "snapshot": snapshot(state),
        "key": dataclasses.asdict(key),
    }


def _dump(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent="\t", sort_keys=True) + "\n"


def _ts_literal(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def ts_type(annotation: Any) -> str:
    origin = typing.get_origin(annotation)
    if origin in (types.UnionType, typing.Union):
        members = typing.get_args(annotation)
        return " | ".join("null" if m is type(None) else ts_type(m) for m in members)
    if origin is tuple:
        inner = ts_type(typing.get_args(annotation)[0])
        return f"({inner})[]" if " | " in inner else f"{inner}[]"
    if annotation is str:
        return "string"
    if annotation is bool:
        return "boolean"
    if annotation is int:
        return "number"
    if isinstance(annotation, type) and (
        issubclass(annotation, StrEnum) or dataclasses.is_dataclass(annotation)
    ):
        return annotation.__name__
    raise TypeError(f"gen_lessons: unhandled annotation {annotation!r}")


def _key_dataclasses() -> list[type]:
    """Every dataclass reachable from the key types, dependencies first."""
    order: list[type] = []

    def visit(cls: type) -> None:
        if cls in order:
            return
        for hint in typing.get_type_hints(cls).values():
            for arg in (hint, *typing.get_args(hint)):
                if isinstance(arg, type) and dataclasses.is_dataclass(arg):
                    visit(arg)
        order.append(cls)

    for cls in KEY_TYPES.values():
        visit(cls)
    return order


def _interface(name: str, fields: Iterable[tuple[str, str]]) -> str:
    body = "".join(f"\t{field}: {ts};\n" for field, ts in fields)
    return f"export interface {name} {{\n{body}}}\n"


def render_types() -> str:
    enums = "".join(
        f"export type {e.__name__} = {' | '.join(_ts_literal(m.value) for m in e)};\n"
        for e in _LESSON_ENUMS
    )
    keys = "\n".join(
        _interface(cls.__name__, ((f, ts_type(h)) for f, h in typing.get_type_hints(cls).items()))
        for cls in _key_dataclasses()
    )
    entry = _interface(
        "LessonIndexEntry",
        [
            ("id", "string"),
            ("lesson_kind", "LessonKind"),
            ("kind", "PuzzleKind"),
            ("track", "Track"),
            ("band", "Band"),
            ("text", "string"),
            ("n", "number"),
        ],
    )
    variants = "\n".join(
        f"\t| {{ kind: {_ts_literal(kind.value)}; key: {cls.__name__} }}"
        for kind, cls in KEY_TYPES.items()
    )
    protocol = ", ".join(sorted(["StateSync", *(e.__name__ for e in _PROTOCOL_ENUMS)]))
    return (
        f"{_HEADER}\n"
        f"import type {{ {protocol} }} from '$lib/net/protocol';\n\n"
        f"{enums}\n{keys}\n{entry}\n"
        "export type Lesson = LessonIndexEntry & {\n"
        "\tengine_version: string;\n"
        "\tsnapshot: StateSync;\n"
        f"}} & (\n{variants}\n);\n"
    )


def render_bundle(catalog: Sequence[Puzzle]) -> dict[str, str]:
    """File name -> contents."""
    check_catalog(catalog)
    entries = index_entries(catalog)
    files = {INDEX_FILE: _dump(entries), TYPES_FILE: render_types()}
    for puzzle, entry in zip(catalog, entries, strict=True):
        files[f"{puzzle.id}.json"] = _dump(lesson_payload(puzzle, entry))
    return files


def write_bundle(out_dir: Path, files: Mapping[str, str]) -> None:
    """Replaces every `.json` in `out_dir`, so a removed lesson's file goes too."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.json"):
        if stale.name not in files:
            stale.unlink()
    for name, text in files.items():
        (out_dir / name).write_text(text)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args(argv)
    files = render_bundle(CATALOG)
    write_bundle(args.out, files)
    print(f"wrote {len(files)} files to {args.out}")


if __name__ == "__main__":
    main()
