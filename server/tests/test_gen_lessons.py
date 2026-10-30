import dataclasses
import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from app.lessons.catalog import CATALOG, TUTORIALS
from app.lessons.catalog.tutorials import BASICS_TUTORIAL
from app.lessons.grade import answer_key
from app.lessons.model import (
    Band,
    Expect,
    MeldSetup,
    Narrate,
    Puzzle,
    PuzzleKind,
    SafeReason,
    SeatSetup,
    StepKind,
    Track,
    Tutorial,
)
from app.lessons.tutorial import run_tutorial
from app.protocol import ServerMessage, StateSync
from mahjong_core.engine import ENGINE_VERSION
from mahjong_core.melds import MeldKind
from mahjong_core.state import Phase
from tests.lesson_positions import DEFENCE, PIN, spec
from tools.gen_lessons import (
    INDEX_FILE,
    OUT_DIR,
    TYPES_FILE,
    check_catalog,
    render_bundle,
    render_types,
    write_bundle,
)

_server_message: TypeAdapter[object] = TypeAdapter(ServerMessage)

_FIXTURE = (
    Puzzle(
        id="waits-a",
        kind=PuzzleKind.WINNING_TILES,
        track=Track.WAITS,
        band=Band.BEGINNER,
        position=spec(SeatSetup(hand="123m456m789m11z22z"), turn=1),
        answer=("z1", "z2"),
        text="fixtureWaits",
    ),
    Puzzle(
        id="efficiency-a",
        kind=PuzzleKind.BEST_DISCARD,
        track=Track.EFFICIENCY,
        band=Band.BEGINNER,
        position=spec(
            SeatSetup(hand="123m456m789m19p11z1s"),
            turn=0,
            seat2=SeatSetup(hand=PIN[:-2] + PIN[-1], discards="23p"),
        ),
        answer=("1p",),
        text="fixtureEfficiency",
    ),
    Puzzle(
        id="faan-a",
        kind=PuzzleKind.COUNT_FAAN,
        track=Track.FAAN,
        band=Band.BEGINNER,
        position=spec(
            SeatSetup(hand="123m789m55z77z", melds=(MeldSetup(MeldKind.PUNG, "666m", 2),)),
            turn=1,
            seat1=SeatSetup(hand="2233445566778s5z"),
        ),
        answer=5,
        text="fixtureFaan",
        discard="z5",
    ),
    Puzzle(
        id="defence-a",
        kind=PuzzleKind.SAFE_DISCARD,
        track=Track.DEFENCE,
        band=Band.BEGINNER,
        position=DEFENCE,
        answer=("z1",),
        text="fixtureDefence",
        reason=SafeReason.ALL_COPIES_VISIBLE,
    ),
)


def _lessons(files: dict[str, str]) -> dict[str, dict]:
    return {
        name.removesuffix(".json"): json.loads(text)
        for name, text in files.items()
        if name not in (INDEX_FILE, TYPES_FILE)
    }


def test_output_is_deterministic() -> None:
    assert render_bundle(_FIXTURE) == render_bundle(_FIXTURE)


def test_index_lists_lessons_in_catalog_order() -> None:
    index = json.loads(render_bundle(_FIXTURE)[INDEX_FILE])
    assert [e["id"] for e in index] == [p.id for p in _FIXTURE]
    assert index[2] == {
        "id": "faan-a",
        "lesson_kind": "puzzle",
        "kind": "count_faan",
        "track": "faan",
        "band": "beginner",
        "text": "fixtureFaan",
        "n": 1,
    }


def test_lesson_round_trips_the_answer_key() -> None:
    lessons = _lessons(render_bundle(_FIXTURE))
    assert lessons.keys() == {p.id for p in _FIXTURE}
    for puzzle in _FIXTURE:
        lesson = lessons[puzzle.id]
        assert lesson["engine_version"] == ENGINE_VERSION
        want = json.loads(json.dumps(dataclasses.asdict(answer_key(puzzle))))
        assert lesson["key"] == want


@pytest.mark.parametrize("puzzle", _FIXTURE, ids=lambda p: p.id)
def test_snapshot_is_a_seat_zero_state_sync_frame(puzzle: Puzzle) -> None:
    snapshot = _lessons(render_bundle(_FIXTURE))[puzzle.id]["snapshot"]
    frame = _server_message.validate_python(snapshot)
    assert isinstance(frame, StateSync)
    assert frame.d.seat == 0
    assert frame.d.hands is None
    assert frame.d.ruleset_preset == "hk_classic"


def test_discard_win_snapshot_is_the_claim_window() -> None:
    snapshot = _lessons(render_bundle(_FIXTURE))["faan-a"]["snapshot"]["d"]
    assert snapshot["phase"] == Phase.AWAIT_CLAIMS
    assert snapshot["turn"] == 1
    assert [o["can_win"] for o in snapshot["claim_options"]] == [True]


def test_a_wrong_stated_answer_fails_generation() -> None:
    wrong = dataclasses.replace(_FIXTURE[2], answer=4)
    with pytest.raises(ValueError, match="faan-a"):
        render_bundle([wrong])


@pytest.mark.parametrize(
    "catalog",
    [
        pytest.param([_FIXTURE[0], _FIXTURE[0]], id="duplicate-id"),
        pytest.param([dataclasses.replace(_FIXTURE[0], id="Waits_1")], id="bad-id"),
        pytest.param([dataclasses.replace(_FIXTURE[0], text="fixture-waits")], id="bad-text"),
    ],
)
def test_check_catalog_rejects(catalog: list[Puzzle]) -> None:
    with pytest.raises(ValueError):
        check_catalog(catalog)


def test_write_bundle_drops_stale_lessons(tmp_path: Path) -> None:
    (tmp_path / "gone.json").write_text("{}")
    files = render_bundle(_FIXTURE)
    write_bundle(tmp_path, files)
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(files)


def test_types_name_every_kind() -> None:
    types = render_types()
    for kind in (*PuzzleKind, *StepKind):
        assert f"kind: '{kind}'" in types


_TUTORIALS = (BASICS_TUTORIAL,)


def test_tutorials_lead_the_index_without_a_puzzle_kind() -> None:
    index = json.loads(render_bundle(_FIXTURE, _TUTORIALS)[INDEX_FILE])
    assert [e["id"] for e in index] == [BASICS_TUTORIAL.id, *(p.id for p in _FIXTURE)]
    assert index[0] == {
        "id": "basics-tutorial",
        "lesson_kind": "tutorial",
        "track": "basics",
        "band": "beginner",
        "text": "basicsTutorial",
        "n": 1,
    }
    assert index[1]["n"] == 1  # puzzles count their own places in a track


def test_tutorial_file_holds_the_script_and_seat_zero_frames() -> None:
    lesson = _lessons(render_bundle(_FIXTURE, _TUTORIALS))[BASICS_TUTORIAL.id]
    run = run_tutorial(BASICS_TUTORIAL)
    assert lesson["engine_version"] == ENGINE_VERSION
    assert isinstance(_server_message.validate_python(lesson["start"]), StateSync)
    assert len(lesson["steps"]) == len(BASICS_TUTORIAL.steps)
    for step, scripted in zip(lesson["steps"], run.steps, strict=True):
        source = scripted.step
        if isinstance(source, Narrate):
            assert step == {"kind": "narrate", "text": source.text, "highlight": source.highlight}
            continue
        assert step["frames"] == json.loads(json.dumps(list(scripted.frames)))
        if isinstance(source, Expect):
            assert step["kind"] == "expect" and step["text"] == source.text
            assert step["snapshot"]["d"]["seat"] == 0
        else:
            assert step["kind"] == "auto" and step["seat"] == source.seat
        for frame in step["frames"]:
            _server_message.validate_python(frame)


def test_tutorial_output_is_deterministic() -> None:
    assert render_bundle(_FIXTURE, _TUTORIALS) == render_bundle(_FIXTURE, _TUTORIALS)


@pytest.mark.parametrize(
    "tutorial",
    [
        pytest.param(
            dataclasses.replace(BASICS_TUTORIAL, id="waits-a"), id="id-shared-with-a-puzzle"
        ),
        pytest.param(
            dataclasses.replace(
                BASICS_TUTORIAL, steps=(Narrate("bad-stem"), *BASICS_TUTORIAL.steps[1:])
            ),
            id="bad-step-stem",
        ),
    ],
)
def test_check_catalog_rejects_tutorials(tutorial: Tutorial) -> None:
    with pytest.raises(ValueError):
        check_catalog(_FIXTURE, (tutorial,))


def test_a_broken_tutorial_fails_generation() -> None:
    broken = dataclasses.replace(BASICS_TUTORIAL, steps=BASICS_TUTORIAL.steps[:-3])
    with pytest.raises(ValueError, match="basics-tutorial"):
        render_bundle(_FIXTURE, (broken,))


# the api container mounts server/ alone; ci runs natively with the whole repo
@pytest.mark.skipif(not OUT_DIR.is_dir(), reason="web/ is not mounted")
def test_committed_bundle_is_current() -> None:
    """Content only: `make proto` formats the files with oxfmt afterwards."""
    files = render_bundle(CATALOG, TUTORIALS)
    committed = {p.name for p in OUT_DIR.glob("*.json")}
    assert committed == {n for n in files if n.endswith(".json")}
    for name in committed:
        assert json.loads((OUT_DIR / name).read_text()) == json.loads(files[name]), name
