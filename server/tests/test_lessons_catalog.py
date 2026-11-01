import json

import pytest

from app.lessons.catalog import CATALOG
from app.lessons.catalog.basics import BASICS
from app.lessons.catalog.mined import MINED, SHORTLIST_PATH, TRACKS
from app.lessons.grade import (
    CountFaanKey,
    SafeDiscardKey,
    answer_key,
    puzzle_state,
    stated_answer_holds,
)
from app.lessons.model import THEMES_BY_KIND, Position, Puzzle, PuzzleKind, Track
from app.views import seat_view
from mahjong_core.state import Phase, WinType
from tools.gen_lessons import check_catalog


def _of(kind: PuzzleKind) -> list[Puzzle]:
    return [p for p in CATALOG if p.kind == kind]


def _ids(p: Puzzle) -> str:
    return p.id


def test_catalog_ids_and_stems_are_valid() -> None:
    check_catalog(CATALOG)


def test_every_mined_record_is_in_the_catalog() -> None:
    records = json.loads(SHORTLIST_PATH.read_text())["puzzles"]
    assert len(MINED) == len(records)
    assert {p.track for p in MINED} == set(TRACKS.values())


def test_mined_puzzles_are_titled_by_theme() -> None:
    """Basics keep their own titles; every mined puzzle has a theme of its own kind."""
    assert all(p.theme is None for p in BASICS)
    assert all(p.theme in THEMES_BY_KIND[p.kind] for p in MINED)


def test_basics_cover_every_kind() -> None:
    assert {p.kind for p in BASICS} == set(PuzzleKind)
    assert {p.track for p in BASICS} == {Track.BASICS}


def test_catalog_uses_explicit_positions() -> None:
    """A `FromSeed` position breaks on any change to dealing (ADR 0025 "Consequences")."""
    assert all(isinstance(p.position, Position) for p in CATALOG)


@pytest.mark.parametrize("puzzle", CATALOG, ids=_ids)
def test_position_builds_for_seat_zero(puzzle: Puzzle) -> None:
    state = puzzle_state(puzzle)
    if puzzle.discard is not None:
        assert state.phase == Phase.AWAIT_CLAIMS
        assert any(o.can_win for o in seat_view(state, 0).claim_options)
    elif puzzle.kind == PuzzleKind.WINNING_TILES:
        assert state.phase == Phase.AWAIT_ACTION
        assert state.turn != 0
    else:
        assert (state.phase, state.turn) == (Phase.AWAIT_ACTION, 0)


@pytest.mark.parametrize("puzzle", CATALOG, ids=_ids)
def test_stated_answer_is_the_engines(puzzle: Puzzle) -> None:
    key = answer_key(puzzle)
    assert stated_answer_holds(puzzle, key), (puzzle.answer, key.correct)


@pytest.mark.parametrize("puzzle", _of(PuzzleKind.SAFE_DISCARD), ids=_ids)
def test_safe_discard_reason_holds(puzzle: Puzzle) -> None:
    key = answer_key(puzzle)
    assert isinstance(key, SafeDiscardKey)
    assert key.reason == puzzle.reason
    by_tile = {o.tile: o for o in key.options}
    for tile in key.correct:
        assert not by_tile[tile].deals_in_to
        assert puzzle.reason in by_tile[tile].reasons


@pytest.mark.parametrize("puzzle", _of(PuzzleKind.COUNT_FAAN), ids=_ids)
def test_count_faan_win_type_follows_the_discard(puzzle: Puzzle) -> None:
    key = answer_key(puzzle)
    assert isinstance(key, CountFaanKey)
    assert key.win_type == (WinType.SELF_DRAW if puzzle.discard is None else WinType.DISCARD)
