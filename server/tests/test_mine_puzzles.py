import dataclasses
import json
from collections.abc import Mapping
from typing import Any

import pytest

from app.lessons.catalog.mined import SHORTLIST_PATH
from app.lessons.grade import (
    BestDiscardKey,
    CountFaanKey,
    DiscardOption,
    FaanLine,
    SafeOption,
    best_discard,
    count_faan,
    safe_discard,
    safe_options,
    winning_tiles,
)
from app.lessons.model import Band, Position, PuzzleKind, SafeReason, SeatSetup
from app.lessons.position import build_position, position_to_dict
from bots.tiers import BotTier
from mahjong_core.engine import ENGINE_VERSION
from mahjong_core.state import GameState, WinType
from mahjong_core.tiles import TileType, parse_tiles, tile_code, tile_id_type
from tests.lesson_positions import PIN as _PIN
from tests.lesson_positions import SOLE_TENPAI, one_route
from tests.lesson_positions import SOU as _SOU
from tests.lesson_positions import position as _position
from tools.mine_puzzles import (
    POLICY_RATE,
    SAME_HAND_WINDOW,
    SHORTLIST_GAME_CAP,
    band_for,
    best_discard_band,
    best_discard_ok,
    count_faan_ok,
    decision_score,
    keeps_value,
    mine,
    naive_discard,
    puzzle_state,
    recheck,
    safe_choice,
    shortlist,
    varied,
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


def test_sole_tenpai_move_is_a_puzzle_but_beginner() -> None:
    """The earlier shortlist rated this advanced: few options make T0 miss often."""
    state = build_position(SOLE_TENPAI)
    key = best_discard(state, 0)
    assert key.correct == ("1s",)
    assert best_discard_ok(key, _naive(state))
    assert best_discard_band(key, 0.9) == Band.BEGINNER


def _key(*options: tuple[str, int, int]) -> BestDiscardKey:
    opts = tuple(DiscardOption(t, s, 1, n) for t, s, n in options)
    best = min((o.shanten, -o.tiles) for o in opts)
    return BestDiscardKey(tuple(o.tile for o in opts if (o.shanten, -o.tiles) == best), opts)


@pytest.mark.parametrize(
    ("key", "score", "band"),
    [
        pytest.param(_key(("1m", 1, 20), ("9p", 2, 30)), 0.9, Band.INTERMEDIATE, id="sole-drop"),
        pytest.param(_key(("1m", 1, 20), ("9p", 2, 30)), 0.1, Band.BEGINNER, id="sole-drop-easy"),
        pytest.param(_key(("1m", 0, 8), ("9p", 0, 2)), 0.9, Band.ADVANCED, id="ready-two-ways"),
        pytest.param(_key(("1m", 1, 20), ("9p", 1, 12)), 0.9, Band.ADVANCED, id="count-tiles"),
        pytest.param(
            _key(("1m", 0, 8), ("9p", 0, 8), ("5s", 1, 30)), 0.9, Band.BEGINNER, id="tied-ready"
        ),
    ],
)
def test_best_discard_band_caps_a_sole_shanten_drop(
    key: BestDiscardKey, score: float, band: Band
) -> None:
    assert best_discard_band(key, score) == band


def test_best_discard_rejected_when_the_answer_abandons_the_only_route() -> None:
    state = build_position(one_route("3f4f"))
    key = best_discard(state, 0)
    assert "7p" in key.correct
    assert not keeps_value(state, key)
    flowerless = build_position(one_route(""))
    assert keeps_value(flowerless, best_discard(flowerless, 0))


def _discard_record(spec: Position, game: int) -> dict[str, Any]:
    key = best_discard(build_position(spec), 0)
    return {
        "kind": PuzzleKind.BEST_DISCARD,
        "position": position_to_dict(spec),
        "discard": None,
        "key": {**dataclasses.asdict(key), "naive": "z1"},
        "difficulty": {"band": Band.ADVANCED, "score": 0.9, "rates": {BotTier.T4: 1.0}},
        "source": {"game_seed": game, "seat": 0, "decision": 0},
    }


def test_recheck_refilters_and_rebands_stored_records() -> None:
    """`--from` reads bands and keys as mined; recheck applies the value filter and band cap."""
    waits = _cut_record(PuzzleKind.WINNING_TILES, 3, 0, 0)
    records = [_discard_record(one_route("3f4f"), 1), _discard_record(SOLE_TENPAI, 2), waits]
    kept, stats = recheck(records, workers=1)
    assert [r["source"]["game_seed"] for r in kept] == [2, 3]
    assert kept[0]["difficulty"]["band"] == Band.BEGINNER
    assert kept[1] is waits
    assert stats == {"value_rejected": 1, "rebanded": 1}


def test_best_discard_rejected_on_a_thin_ukeire_lead() -> None:
    key = BestDiscardKey(
        correct=("1m",),
        options=(DiscardOption("1m", 1, 5, 16), DiscardOption("9p", 1, 5, 14)),
    )
    assert not best_discard_ok(key, "9p")


# seat 1 waits on z1/z2 for a half flush; seat 0's isolated z2 is an efficient cut, its z5
# pair isn't
_WAITING = SeatSetup(hand="123m456m789m11z22z")
_FOLDER = SeatSetup(hand="23456789m99p1s2z55z")


def _fold(*, z5_visible: bool, orphans_closed: bool = True) -> GameState:
    pools = "5z" if z5_visible else ""
    # seat 0 holds 99p: two more in the pools make 9p dead, so no thirteen orphans wait
    nines = "9p" if orphans_closed else ""
    return _position(
        _FOLDER,
        turn=0,
        seat1=_WAITING,
        seat2=SeatSetup(hand=_PIN[:-2] + _PIN[-1], discards=pools + nines),
        seat3=SeatSetup(hand=_SOU[:-2] + _SOU[-1], discards=pools + nines),
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


def test_safe_discard_rejected_while_a_dead_honour_could_feed_thirteen_orphans() -> None:
    state = _fold(z5_visible=True, orphans_closed=False)
    assert safe_choice(safe_options(state, 0), best_discard(state, 0).correct) is None


def test_safe_discard_rejected_when_the_efficient_cut_is_safe() -> None:
    state = _fold(z5_visible=True)
    assert safe_choice(safe_options(state, 0), ("5m",)) is None


_ALL = SafeReason.ALL_COPIES_VISIBLE
_WALLED = SafeReason.NO_CHANCE
_DEALS_IN = SafeOption("z2", deals_in_to=(1,), reasons=())


@pytest.mark.parametrize(
    ("options", "choice"),
    [
        pytest.param(
            [SafeOption("9p", (), (_ALL, _WALLED)), SafeOption("z5", (), (_ALL,))],
            (("9p", "z5"), _ALL),
            id="every-deducible-tile",
        ),
        pytest.param(
            [SafeOption("9p", (), (_ALL, _WALLED)), SafeOption("1s", (), (_WALLED,))],
            (("9p", "1s"), _WALLED),
            id="shared-reason-states-the-weaker",
        ),
        pytest.param(
            [SafeOption("z5", (), (_ALL,)), SafeOption("1s", (), (_WALLED,))],
            None,
            id="no-shared-reason",
        ),
        pytest.param(
            [SafeOption("z5", (), (_ALL,)), SafeOption("1s", (1,), (_WALLED,))],
            None,
            id="walled-tile-deals-in-to-a-pair-wait",
        ),
        pytest.param(
            [SafeOption(t, (), (_WALLED,)) for t in ("1s", "2s", "3s", "4s")],
            None,
            id="too-many",
        ),
        pytest.param([SafeOption("9p", (), ())], None, id="lucky-only"),
    ],
)
def test_safe_choice_accepts_every_deducible_tile(
    options: list[SafeOption], choice: tuple[tuple[str, ...], SafeReason] | None
) -> None:
    assert safe_choice([_DEALS_IN, *options], ("z2",)) == choice


def test_safe_choice_rejected_when_folding_costs_nothing() -> None:
    """The deducible tile is one of the efficient answers too: no tension."""
    options = [_DEALS_IN, SafeOption("z5", (), (_ALL,))]
    assert safe_choice(options, ("z2", "z5")) is None


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


_SPREAD_KEY: Mapping[PuzzleKind, dict[str, Any]] = {
    PuzzleKind.BEST_DISCARD: {"options": [{"shanten": 1}]},
    PuzzleKind.SAFE_DISCARD: {"reason": SafeReason.NO_CHANCE},
    PuzzleKind.WINNING_TILES: {"correct": ["1m", "4m"]},
    PuzzleKind.COUNT_FAAN: {"correct": 3},
}


def _cut_record(kind: PuzzleKind, game: int, seat: int, decision: int) -> dict[str, Any]:
    """Only the fields the shortlist cut reads."""
    return {
        "kind": kind,
        "difficulty": {"band": Band.BEGINNER, "rates": {BotTier.T4: 1}},
        "key": _SPREAD_KEY[kind],
        "source": {"game_seed": game, "seat": seat, "decision": decision},
    }


def _games(records: list[Mapping[str, Any]]) -> list[tuple[str, int, int, int]]:
    return [
        (r["kind"], r["source"]["game_seed"], r["source"]["seat"], r["source"]["decision"])
        for r in records
    ]


def test_shortlist_takes_one_puzzle_per_game_per_kind() -> None:
    waits = PuzzleKind.WINNING_TILES
    records = [
        _cut_record(waits, 1, 0, 10),
        _cut_record(waits, 1, 1, 400),
        _cut_record(waits, 1, 2, 800),
        _cut_record(waits, 2, 0, 10),
    ]
    assert _games(shortlist(records, 15)) == [(waits, 1, 0, 10), (waits, 2, 0, 10)]


def test_shortlist_caps_puzzles_per_game_across_tracks() -> None:
    records = [_cut_record(kind, 1, seat, 300 * seat) for seat, kind in enumerate(PuzzleKind)]
    records.append(_cut_record(PuzzleKind.COUNT_FAAN, 2, 0, 0))
    cut = _games(shortlist(records, 15))
    assert [g for _, g, _, _ in cut].count(1) == SHORTLIST_GAME_CAP
    assert cut[-1] == (PuzzleKind.COUNT_FAAN, 2, 0, 0)


def test_shortlist_drops_the_same_hand_in_another_track() -> None:
    first = _cut_record(PuzzleKind.BEST_DISCARD, 1, 0, 100)
    same_hand = _cut_record(PuzzleKind.SAFE_DISCARD, 1, 0, 100 + SAME_HAND_WINDOW)
    other_seat = _cut_record(PuzzleKind.COUNT_FAAN, 1, 1, 100)
    assert _games(shortlist([first, same_hand], 15)) == _games([first])
    assert _games(shortlist([first, other_seat], 15)) == _games([first, other_seat])
    later = _cut_record(PuzzleKind.SAFE_DISCARD, 1, 0, 101 + SAME_HAND_WINDOW)
    assert _games(shortlist([first, later], 15)) == _games([first, later])


def test_varied_skips_within_a_band_and_keeps_the_round_robin() -> None:
    waits = PuzzleKind.WINNING_TILES
    beginner = [
        _cut_record(waits, 1, 0, 0),
        _cut_record(waits, 1, 1, 500),
        _cut_record(waits, 2, 0, 0),
    ]
    advanced = [_cut_record(waits, 1, 2, 900), _cut_record(waits, 3, 0, 0)]
    taken: dict[int, list[Mapping[str, Any]]] = {}
    picked = varied([beginner, advanced], 3, taken, game_cap=1)
    assert _games(picked) == _games([beginner[0], advanced[1], beginner[2]])
    assert sorted(taken) == [1, 2, 3]


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


def test_committed_shortlist_is_varied() -> None:
    puzzles = _games(json.loads(SHORTLIST_PATH.read_text())["puzzles"])
    games = [g for _, g, _, _ in puzzles]
    assert max(games.count(g) for g in games) <= SHORTLIST_GAME_CAP
    assert len({(k, g) for k, g, _, _ in puzzles}) == len(puzzles)
    for i, (_, game, seat, decision) in enumerate(puzzles):
        for _, g, s, d in puzzles[i + 1 :]:
            assert (g, s) != (game, seat) or abs(d - decision) > SAME_HAND_WINDOW


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
