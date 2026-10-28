import dataclasses
import json
from collections.abc import Mapping
from typing import Any

import pytest

from app.lessons.grade import (
    BestDiscardKey,
    CountFaanKey,
    DiscardOption,
    FaanLine,
    best_discard,
    count_faan,
    safe_discard,
    safe_options,
    winning_tiles,
)
from app.lessons.model import PuzzleKind, SafeReason, SeatSetup
from bots.tiers import BotTier
from mahjong_core.engine import ENGINE_VERSION
from mahjong_core.state import GameState, WinType
from mahjong_core.tiles import TileType, parse_tiles, tile_code, tile_id_type
from tests.lesson_positions import PIN as _PIN
from tests.lesson_positions import SOU as _SOU
from tests.lesson_positions import position as _position
from tools.mine_puzzles import (
    POLICY_RATE,
    SHORTLIST_PATH,
    Band,
    band_for,
    best_discard_ok,
    count_faan_ok,
    decision_score,
    mine,
    naive_discard,
    puzzle_state,
    safe_choice,
    winning_tiles_ok,
    winning_tiles_points,
)


def _naive(state: GameState) -> str:
    return tile_code(naive_discard(tile_id_type(t) for t in state.seats[0].concealed))


@pytest.mark.parametrize(
    ("hand", "naive"),
    [
        pytest.param("11223456789m345p", TileType.MAN_9, id="loose-terminal"),
        pytest.param("123m456m9p1s5z", TileType.DRAGON_RED, id="honour-first"),
        pytest.param("123m456m9p1s", TileType.PIN_9, id="terminal-tie-by-type"),
    ],
)
def test_naive_discard_cuts_the_most_isolated_tile(hand: str, naive: TileType) -> None:
    assert naive_discard(t for t in parse_tiles(hand) if isinstance(t, TileType)) == naive


def test_best_discard_kept_when_the_naive_cut_loses_tiles() -> None:
    # 9m leaves a 1-4m wait (4 live), 2m a 1-4-7m wait (8)
    state = _position(SeatSetup(hand="11223456789m345p"), turn=0)
    key = best_discard(state, 0)
    assert (key.correct, _naive(state)) == (("2m",), "9m")
    assert best_discard_ok(key, _naive(state))


@pytest.mark.parametrize(
    "hand",
    [
        pytest.param("12345m6789m13p11z5z", id="naive-cut-is-correct"),
        pytest.param("123m456m78m24p5z99s1p", id="three-way-tie"),
        pytest.param("123m456m79m13p15z99s", id="too-far-from-tenpai"),
    ],
)
def test_best_discard_rejected(hand: str) -> None:
    state = _position(SeatSetup(hand=hand), turn=0)
    assert not best_discard_ok(best_discard(state, 0), _naive(state))


def test_best_discard_rejected_on_a_thin_ukeire_lead() -> None:
    key = BestDiscardKey(
        correct=("1m",),
        options=(DiscardOption("1m", 1, 5, 16), DiscardOption("9p", 1, 5, 14)),
    )
    assert not best_discard_ok(key, "9p")


# seat 1 waits on z1/z2 for a half flush; seat 0's isolated honours are z2 and z5
_WAITING = SeatSetup(hand="123m456m789m11z22z")
_FOLDER = SeatSetup(hand="23456789m99p11s2z5z")


def _fold(*, z5_visible: bool) -> GameState:
    pools = "5z" if z5_visible else ""
    return _position(
        _FOLDER,
        turn=0,
        seat1=_WAITING,
        seat2=SeatSetup(hand=_PIN[:-2] + _PIN[-1], discards=pools),
        seat3=SeatSetup(hand=_SOU[:-2] + _SOU[-1], discards=pools * 2),
    )


def test_safe_discard_kept_when_the_efficient_cut_deals_in() -> None:
    state = _fold(z5_visible=True)
    efficient = best_discard(state, 0).correct
    assert "z2" in efficient
    choice = safe_choice(safe_options(state, 0), efficient)
    assert choice == (("z5",), SafeReason.ALL_COPIES_VISIBLE)
    assert safe_discard(state, 0, *choice).correct == ("z5",)


def test_safe_discard_rejected_without_a_provable_tile() -> None:
    state = _fold(z5_visible=False)
    assert safe_choice(safe_options(state, 0), best_discard(state, 0).correct) is None


def test_safe_discard_rejected_when_the_efficient_cut_is_safe() -> None:
    state = _fold(z5_visible=True)
    assert safe_choice(safe_options(state, 0), ("5m",)) is None


@pytest.mark.parametrize(
    ("hand", "ok"),
    [
        pytest.param("123m456m789m11z22z", True, id="two-waits"),
        pytest.param("123m456m789m111z5z", False, id="one-plain-wait"),
    ],
)
def test_winning_tiles_filter(hand: str, ok: bool) -> None:
    key = winning_tiles(_position(SeatSetup(hand=hand), turn=1), 0)
    assert winning_tiles_ok(key) is ok


def test_winning_tiles_rejected_for_a_dead_single_wait() -> None:
    hand = SeatSetup(hand="123m456m789m111z5z")
    others = {
        "seat1": SeatSetup(hand=_SOU, discards="5z"),
        "seat2": SeatSetup(hand=_PIN[:-2] + _PIN[-1], discards="5z"),
        "seat3": SeatSetup(hand=_SOU[:-2] + _SOU[-1], discards="5z"),
    }
    key = winning_tiles(_position(hand, turn=1, **others), 0)
    assert key.dead == ("z5",)
    # no live winner left to select, so not a puzzle
    assert not winning_tiles_ok(key)


def _faan(*lines: int) -> CountFaanKey:
    breakdown = tuple(FaanLine(f"p{n}", f) for n, f in enumerate(lines))
    return CountFaanKey(sum(lines), WinType.SELF_DRAW, breakdown, 0)


def test_count_faan_needs_two_patterns() -> None:
    assert count_faan_ok(_faan(1, 3))
    assert not count_faan_ok(_faan(3))


def test_band_for_bounds() -> None:
    assert band_for(0.2, (0.3, 0.6)) == Band.BEGINNER
    assert band_for(0.3, (0.3, 0.6)) == Band.INTERMEDIATE
    assert band_for(0.6, (0.3, 0.6)) == Band.ADVANCED


def test_decision_score_ignores_the_grader_and_argmax_expert() -> None:
    rates = {BotTier.T0: 0.25, BotTier.T1: 1.0, BotTier.T2: 0.0, BotTier.T4: 0.0, POLICY_RATE: 0.5}
    # best_discard: T0, T2 and the policy rate only
    assert decision_score(PuzzleKind.BEST_DISCARD, rates) == pytest.approx((0.75 + 1 + 0.5) / 3)
    assert decision_score(PuzzleKind.SAFE_DISCARD, rates) == pytest.approx((0.75 + 0 + 1 + 0.5) / 4)


def test_winning_tiles_points() -> None:
    key = winning_tiles(_position(SeatSetup(hand="123m456m789m11z22z"), turn=1), 0)
    assert winning_tiles_points(key) == 1


_TIERS = [BotTier.T0, BotTier.T1, BotTier.T2]


def test_mining_is_deterministic_and_every_record_regrades() -> None:
    """One `FaanBot` game, so the test needs no learned weights."""
    first, stats = mine([7], 1, BotTier.T2, _TIERS)
    again, _ = mine([7], 1, BotTier.T2, _TIERS)
    assert first == again
    assert stats["turns_scanned"] and first
    assert {r["kind"] for r in first} == set(PuzzleKind)
    for record in first:
        assert_regrades(record)


def test_committed_shortlist_regrades() -> None:
    payload = json.loads(SHORTLIST_PATH.read_text())
    assert payload["engine_version"] == ENGINE_VERSION
    puzzles = payload["puzzles"]
    assert {p["kind"] for p in puzzles} == set(PuzzleKind)
    for record in puzzles:
        assert record["engine_version"] == ENGINE_VERSION
        assert_regrades(record)


def assert_regrades(record: Mapping[str, Any]) -> None:
    """The record's stored answer is what grading its rebuilt position says now."""
    state = puzzle_state(record)
    stored = json.loads(json.dumps(record["key"]))
    regraded: Any
    match record["kind"]:
        case PuzzleKind.BEST_DISCARD:
            regraded = best_discard(state, 0)
            del stored["naive"]
        case PuzzleKind.SAFE_DISCARD:
            regraded = safe_discard(state, 0, stored["correct"], SafeReason(stored["reason"]))
        case PuzzleKind.WINNING_TILES:
            regraded = winning_tiles(state, 0)
        case PuzzleKind.COUNT_FAAN:
            regraded = count_faan(state, 0)
    assert json.loads(json.dumps(dataclasses.asdict(regraded))) == stored
