"""Learn-mode lesson bundle for the web (docs/protocol.md §6, ADR 0025).

Builds every `app.lessons.catalog` puzzle, grades it with `answer_key`, runs every tutorial
script (`run_tutorial`), and writes into `web/src/lib/learn/generated/`:

- `index.json`: every lesson's `IndexEntry`, tutorials first, then puzzles in catalog order;
- `<id>.json`: one `Lesson` per puzzle (the entry, `engine_version`, a seat-0 `state_sync`
  frame and the answer key) or `Tutorial` (the entry, `engine_version`, the opening
  `state_sync` and the steps with seat 0's frames);
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

from app.frames import state_sync_frame, to_envelope
from app.lessons.catalog import CATALOG, TUTORIALS
from app.lessons.grade import (
    BestDiscardKey,
    CountFaanKey,
    SafeDiscardKey,
    WinningTilesKey,
    answer_key,
    puzzle_state,
    stated_answer_holds,
)
from app.lessons.model import (
    Auto,
    Band,
    Expect,
    Highlight,
    LessonKind,
    Narrate,
    Puzzle,
    PuzzleKind,
    PuzzleTheme,
    SafeReason,
    StepKind,
    Track,
    Tutorial,
)
from app.lessons.themes import puzzle_theme
from app.lessons.tutorial import ScriptedStep, run_tutorial
from mahjong_core.actions import action_to_dict
from mahjong_core.engine import ENGINE_VERSION
from mahjong_core.state import GameState, WinType
from mahjong_core.tiles import tile_id_type

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

_LESSON_ENUMS: tuple[type[StrEnum], ...] = (
    LessonKind,
    PuzzleKind,
    Track,
    Band,
    SafeReason,
    PuzzleTheme,
    StepKind,
    Highlight,
)
# already named in protocol.d.ts
_PROTOCOL_ENUMS: tuple[type[StrEnum], ...] = (WinType,)

_HEADER = (
    "// GENERATED FILE — do not hand-edit. Run `make proto` to regenerate.\n"
    "// Source of truth: server/app/lessons/ (docs/protocol.md §6).\n"
)


def _text_stems(lesson: Puzzle | Tutorial) -> list[str]:
    if isinstance(lesson, Puzzle):
        return [lesson.text]
    return [lesson.text, *(s.text for s in lesson.steps if not isinstance(s, Auto))]


def check_catalog(catalog: Sequence[Puzzle], tutorials: Sequence[Tutorial] = ()) -> None:
    """Raises `ValueError` on a duplicate or malformed id or text stem, a tutorial's step stems
    included."""
    lessons: list[Puzzle | Tutorial] = [*tutorials, *catalog]
    dupes = [i for i, n in Counter(p.id for p in lessons).items() if n > 1]
    if dupes:
        raise ValueError(f"duplicate lesson ids: {dupes}")
    for p in lessons:
        if not _ID.fullmatch(p.id):
            raise ValueError(f"lesson id {p.id!r} is not lowercase kebab-case")
        for stem in _text_stems(p):
            if not _TEXT.fullmatch(stem):
                raise ValueError(f"{p.id}: text stem {stem!r} is not alphanumeric")


def snapshot(state: GameState) -> dict[str, Any]:
    """Seat 0's `state_sync` frame, as `Table.state_sync_wire` and `ws.py` would send it to a
    fresh seat with no clock: no deadlines, no history, `seq`/`ts` 0."""
    return to_envelope(state_sync_frame(state, 0), seq=0, ts=0)


def index_entries(
    catalog: Sequence[Puzzle], tutorials: Sequence[Tutorial] = ()
) -> list[dict[str, Any]]:
    """Tutorials first, then puzzles. `n` is the 1-based place among the track's lessons of
    the same `lesson_kind`, for titles shared across a track."""
    seen: Counter[tuple[LessonKind, Track]] = Counter()
    entries = []
    for p in (*tutorials, *catalog):
        lesson_kind = LessonKind.TUTORIAL if isinstance(p, Tutorial) else LessonKind.PUZZLE
        seen[lesson_kind, p.track] += 1
        kind = {"kind": str(p.kind)} if isinstance(p, Puzzle) else {}
        theme = (
            {"theme": None if p.theme is None else str(p.theme)} if isinstance(p, Puzzle) else {}
        )
        entries.append(
            {"id": p.id, "lesson_kind": str(lesson_kind)}
            | kind
            | {
                "track": str(p.track),
                "band": str(p.band),
                "text": p.text,
                "n": seen[lesson_kind, p.track],
            }
            | theme
        )
    return entries


def _step_payload(scripted: ScriptedStep) -> dict[str, Any]:
    step = scripted.step
    if isinstance(step, Narrate):
        return {
            "kind": str(StepKind.NARRATE),
            "text": step.text,
            "highlight": None if step.highlight is None else str(step.highlight),
        }
    assert scripted.action is not None
    played = {"action": action_to_dict(scripted.action), "frames": list(scripted.frames)}
    if isinstance(step, Expect):
        expect = {"kind": str(StepKind.EXPECT), "text": step.text, "snapshot": scripted.snapshot}
        return expect | played
    return {"kind": str(StepKind.AUTO), "seat": scripted.seat} | played


def tutorial_payload(tutorial: Tutorial, entry: Mapping[str, Any]) -> dict[str, Any]:
    """Raises `ValueError` on a script that doesn't run (`run_tutorial`)."""
    run = run_tutorial(tutorial)
    return {
        **entry,
        "engine_version": ENGINE_VERSION,
        "start": run.start,
        "steps": [_step_payload(s) for s in run.steps],
    }


def lesson_payload(puzzle: Puzzle, entry: Mapping[str, Any]) -> dict[str, Any]:
    """Raises `ValueError` when the engine's key disagrees with the author's `answer`."""
    state = puzzle_state(puzzle)
    key = answer_key(puzzle, state)
    if not stated_answer_holds(puzzle, key):
        raise ValueError(f"{puzzle.id}: answer {puzzle.answer!r}, engine says {key.correct!r}")
    hand = [tile_id_type(t) for t in state.seats[0].concealed]
    if puzzle.theme is not None and puzzle.theme != (theme := puzzle_theme(key, hand)):
        raise ValueError(f"{puzzle.id}: theme {puzzle.theme}, the key reads as {theme}")
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
    common = [("track", "Track"), ("band", "Band"), ("text", "string"), ("n", "number")]
    puzzle_entry = _interface(
        "LessonIndexEntry",
        [
            ("id", "string"),
            ("lesson_kind", _ts_literal(LessonKind.PUZZLE)),
            ("kind", "PuzzleKind"),
            *common,
            ("theme", "PuzzleTheme | null"),
        ],
    )
    tutorial_entry = _interface(
        "TutorialIndexEntry",
        [("id", "string"), ("lesson_kind", _ts_literal(LessonKind.TUTORIAL)), *common],
    )
    variants = "\n".join(
        f"\t| {{ kind: {_ts_literal(kind.value)}; key: {cls.__name__} }}"
        for kind, cls in KEY_TYPES.items()
    )
    played = "action: Record<string, unknown>; frames: ServerEvent[]"
    steps = (
        f"\t| {{ kind: {_ts_literal(StepKind.NARRATE)}; text: string; highlight: Highlight | null }}\n"
        f"\t| {{ kind: {_ts_literal(StepKind.EXPECT)}; text: string; snapshot: StateSync; {played} }}\n"
        f"\t| {{ kind: {_ts_literal(StepKind.AUTO)}; seat: Seat; {played} }}"
    )
    protocol = ", ".join(
        sorted(["Seat", "ServerEvent", "StateSync", *(e.__name__ for e in _PROTOCOL_ENUMS)])
    )
    return (
        f"{_HEADER}\n"
        f"import type {{ {protocol} }} from '$lib/net/protocol';\n\n"
        f"{enums}\n{keys}\n{puzzle_entry}\n{tutorial_entry}\n"
        "export type IndexEntry = LessonIndexEntry | TutorialIndexEntry;\n\n"
        "export type Lesson = LessonIndexEntry & {\n"
        "\tengine_version: string;\n"
        "\tsnapshot: StateSync;\n"
        f"}} & (\n{variants}\n);\n\n"
        f"export type TutorialStep =\n{steps};\n\n"
        "export type Tutorial = TutorialIndexEntry & {\n"
        "\tengine_version: string;\n"
        "\tstart: StateSync;\n"
        "\tsteps: TutorialStep[];\n"
        "};\n"
    )


def render_bundle(catalog: Sequence[Puzzle], tutorials: Sequence[Tutorial] = ()) -> dict[str, str]:
    """File name -> contents."""
    check_catalog(catalog, tutorials)
    entries = index_entries(catalog, tutorials)
    files = {INDEX_FILE: _dump(entries), TYPES_FILE: render_types()}
    for lesson, entry in zip((*tutorials, *catalog), entries, strict=True):
        payload = (
            tutorial_payload(lesson, entry)
            if isinstance(lesson, Tutorial)
            else lesson_payload(lesson, entry)
        )
        files[f"{lesson.id}.json"] = _dump(payload)
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
    files = render_bundle(CATALOG, TUTORIALS)
    write_bundle(args.out, files)
    print(f"wrote {len(files)} files to {args.out}")


if __name__ == "__main__":
    main()
