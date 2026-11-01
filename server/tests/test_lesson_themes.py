import pytest

from app.lessons.catalog.mined import MINED
from app.lessons.grade import (
    AnswerKey,
    BestDiscardKey,
    DiscardOption,
    SafeDiscardKey,
    WaitOption,
    WinningTilesKey,
    answer_key,
    best_discard,
    count_faan,
    puzzle_state,
    safe_discard,
    winning_tiles,
)
from app.lessons.model import (
    THEMES_BY_KIND,
    MeldSetup,
    Puzzle,
    PuzzleKind,
    PuzzleTheme,
    SafeReason,
    SeatSetup,
)
from app.lessons.position import build_position
from app.lessons.themes import WaitShape, puzzle_theme, wait_shapes
from mahjong_core.melds import MeldKind
from mahjong_core.state import GameState
from mahjong_core.tiles import TileType, parse_tile, parse_tiles, tile_id_type
from tests.lesson_positions import DEDUCED, position


def _hand(state: GameState) -> list[TileType]:
    return [tile_id_type(t) for t in state.seats[0].concealed]


def _theme(state: GameState, key: AnswerKey) -> PuzzleTheme:
    return puzzle_theme(key, _hand(state))


def _types(spec: str) -> list[TileType]:
    return [t for t in parse_tiles(spec) if isinstance(t, TileType)]


@pytest.mark.parametrize(
    ("hand", "tile", "shapes"),
    [
        pytest.param("23m456m789m111z55z", "1m", {WaitShape.TWO_SIDED}, id="two-sided"),
        pytest.param("12m456m789m111z55z", "3m", {WaitShape.EDGE}, id="edge-12"),
        pytest.param("89m123m456m111z55z", "7m", {WaitShape.EDGE}, id="edge-89"),
        pytest.param("13m456m789m111z55z", "2m", {WaitShape.CLOSED}, id="closed"),
        pytest.param("123m456m789m11z22z", "z1", {WaitShape.PAIR}, id="pair"),
        pytest.param("123m456m789m111z5z", "z5", {WaitShape.SINGLE}, id="single"),
        pytest.param(
            "7899m123m456m111z", "9m", {WaitShape.TWO_SIDED, WaitShape.SINGLE}, id="two-readings"
        ),
    ],
)
def test_wait_shapes(hand: str, tile: str, shapes: set[WaitShape]) -> None:
    assert wait_shapes(_types(hand), TileType(int(parse_tile(tile)))) == shapes


# seat 0 dealer (east): every hand here is a half flush, so each wait clears min_faan
_DEAD = {
    "seat1": SeatSetup(hand="22334455667788s", discards="5z"),
    "seat2": SeatSetup(hand="2233445566778p", discards="5z"),
    "seat3": SeatSetup(hand="2233445566778s", discards="5z"),
}
# 2 faan by discard, 3 by self-draw on the east pung; the white pung is 1 / 2
_EAST_OR_WHITE = SeatSetup(
    hand="234m567p11z77z", melds=(MeldSetup(MeldKind.CHOW, "789p", from_seat=3),), flowers="2f"
)


@pytest.mark.parametrize(
    ("seat0", "others", "theme"),
    [
        pytest.param(_EAST_OR_WHITE, {}, PuzzleTheme.TOO_CHEAP, id="too-cheap"),
        pytest.param(SeatSetup(hand="123m456m789m111z5z"), _DEAD, PuzzleTheme.DEAD_WAIT, id="dead"),
        pytest.param(SeatSetup(hand="2345678m111z555z"), {}, PuzzleTheme.MANY_SIDED, id="many"),
        pytest.param(SeatSetup(hand="23m789m111z555z66z"), {}, PuzzleTheme.TWO_SIDED, id="two"),
        pytest.param(SeatSetup(hand="123m456m789m11z22z"), {}, PuzzleTheme.PAIR_WAIT, id="pair"),
        pytest.param(
            SeatSetup(hand="123m456m789m111z5z"), {}, PuzzleTheme.SINGLE_WAIT, id="single"
        ),
        pytest.param(SeatSetup(hand="12m456m789m111z55z"), {}, PuzzleTheme.EDGE_CLOSED, id="edge"),
        pytest.param(SeatSetup(hand="6668m123m111z555z"), {}, PuzzleTheme.MIXED_WAIT, id="mixed"),
    ],
)
def test_winning_tiles_theme(
    seat0: SeatSetup, others: dict[str, SeatSetup], theme: PuzzleTheme
) -> None:
    state = position(seat0, turn=1, **others)
    assert _theme(state, winning_tiles(state, 0)) == theme


@pytest.mark.parametrize(
    ("hand", "correct", "theme"),
    [
        pytest.param("123m456m789m235p11z", ("5p",), PuzzleTheme.WIDER_WAIT, id="wider"),
        pytest.param("123m456m789m11z55z7z", ("z7",), PuzzleTheme.REACH_READY, id="ready"),
        pytest.param("3456m12899p111s33z", ("3m", "6m"), PuzzleTheme.TRIM_RUN, id="trim-run"),
        pytest.param("1345889m567789p1s", ("9m",), PuzzleTheme.CUT_TERMINAL, id="terminal"),
        pytest.param(
            "4447788m4557p89s3z", ("7p", "z3"), PuzzleTheme.KEEP_TWO_SIDED, id="keep-two-sided"
        ),
        pytest.param("12234478p88s2666z", ("z2",), PuzzleTheme.CUT_FLOATER, id="floater"),
        pytest.param("2456789m47889p33z", ("8p",), PuzzleTheme.BREAK_PAIR, id="break-pair"),
        pytest.param("12666788899m556p", ("7m",), PuzzleTheme.MOST_TILES, id="most-tiles"),
    ],
)
def test_best_discard_theme(hand: str, correct: tuple[str, ...], theme: PuzzleTheme) -> None:
    state = position(SeatSetup(hand=hand), turn=0)
    key = best_discard(state, 0)
    assert key.correct == correct
    assert _theme(state, key) == theme


def test_safe_discard_theme_on_a_graded_key() -> None:
    state = build_position(DEDUCED)
    key = safe_discard(state, 0, ["9p", "z1"], SafeReason.ALL_COPIES_VISIBLE)
    assert _theme(state, key) == PuzzleTheme.ALL_VISIBLE


@pytest.mark.parametrize(
    ("accepted", "reason", "theme"),
    [
        pytest.param(("1s",), SafeReason.NO_CHANCE, PuzzleTheme.WALLED_RUNS, id="walled"),
        pytest.param(("z1",), SafeReason.ALL_COPIES_VISIBLE, PuzzleTheme.DEAD_HONOUR, id="honour"),
        pytest.param(("9p",), SafeReason.ALL_COPIES_VISIBLE, PuzzleTheme.ALL_VISIBLE, id="suited"),
        pytest.param(
            ("9p", "1s"), SafeReason.NO_CHANCE, PuzzleTheme.WALLED_RUNS, id="walled-beats-visible"
        ),
    ],
)
def test_safe_discard_theme(
    accepted: tuple[str, ...], reason: SafeReason, theme: PuzzleTheme
) -> None:
    key = SafeDiscardKey(correct=accepted, reason=reason, safe=accepted, options=())
    assert puzzle_theme(key, []) == theme


def _pung(tiles: str) -> MeldSetup:
    return MeldSetup(MeldKind.PUNG, tiles, from_seat=2)


@pytest.mark.parametrize(
    ("seat0", "theme"),
    [
        pytest.param(SeatSetup(hand="111z222z333z555z66z"), PuzzleTheme.LIMIT_HAND, id="limit"),
        pytest.param(SeatSetup(hand="123m456m789m234m55m"), PuzzleTheme.FULL_FLUSH, id="full"),
        pytest.param(
            SeatSetup(hand="111m999m111z22z", melds=(_pung("555m"),)),
            PuzzleTheme.HALF_FLUSH_PUNGS,
            id="half-flush-pungs",
        ),
        pytest.param(
            SeatSetup(hand="123m456m789m555z22z"), PuzzleTheme.HALF_FLUSH_HONOURS, id="dragon"
        ),
        pytest.param(SeatSetup(hand="123m456m789m234m22z"), PuzzleTheme.HALF_FLUSH, id="half"),
        pytest.param(
            SeatSetup(hand="111m555m222m11p", melds=(_pung("999p"),)),
            PuzzleTheme.ALL_PUNGS,
            id="pungs",
        ),
        pytest.param(SeatSetup(hand="123m234m345p678m22p"), PuzzleTheme.ALL_CHOWS, id="chows"),
        pytest.param(
            SeatSetup(hand="123m456m789p111s99p", flowers="4f8f"), PuzzleTheme.FLOWERS, id="flowers"
        ),
        pytest.param(SeatSetup(hand="123m456m789p111s99p"), PuzzleTheme.SMALL_FAAN, id="small"),
    ],
)
def test_count_faan_theme(seat0: SeatSetup, theme: PuzzleTheme) -> None:
    # dealer 1 makes seat 0 north, and not the dealer: no heavenly hand
    state = position(seat0, turn=0, dealer=1)
    assert _theme(state, count_faan(state, 0)) == theme


def _wait(tile: str, live: int = 2, wins: bool = True) -> WaitOption:
    return WaitOption(tile, 3, wins, 4, wins, live)


def test_winning_tiles_priority() -> None:
    """Too cheap, then dead, then three or more waits, before any shape."""
    hand = _types("2345678m111z555z")
    below = WinningTilesKey(
        correct=("2m",),
        below_minimum=("5m",),
        dead=("8m",),
        options=(_wait("2m"), _wait("5m", wins=False), _wait("8m", live=0)),
    )
    assert puzzle_theme(below, hand) == PuzzleTheme.TOO_CHEAP
    dead = WinningTilesKey(("2m", "5m"), (), ("8m",), (_wait("2m"), _wait("5m"), _wait("8m", 0)))
    assert puzzle_theme(dead, hand) == PuzzleTheme.DEAD_WAIT


def test_best_discard_priority() -> None:
    """At tenpai the wait decides; off it, a run end beats a terminal beats a two-sided cut."""
    hand = _types("1234m6m89p11z")
    options = (
        DiscardOption("1m", 1, 5, 16),
        DiscardOption("6m", 1, 5, 16),
        DiscardOption("9p", 1, 5, 16),
        DiscardOption("8p", 1, 3, 8),
    )
    assert puzzle_theme(BestDiscardKey(("1m", "6m"), options), hand) == PuzzleTheme.TRIM_RUN
    assert puzzle_theme(BestDiscardKey(("6m", "9p"), options), hand) == PuzzleTheme.CUT_TERMINAL
    assert puzzle_theme(BestDiscardKey(("6m",), options), hand) == PuzzleTheme.KEEP_TWO_SIDED
    ready = (DiscardOption("1m", 0, 2, 6), DiscardOption("6m", 0, 1, 2))
    assert puzzle_theme(BestDiscardKey(("1m",), ready), hand) == PuzzleTheme.WIDER_WAIT


def test_every_kind_ends_on_a_catch_all() -> None:
    """The last theme per kind always holds, so every key gets one."""
    assert [themes[-1] for themes in THEMES_BY_KIND.values()] == [
        PuzzleTheme.MIXED_WAIT,
        PuzzleTheme.MOST_TILES,
        PuzzleTheme.ALL_VISIBLE,
        PuzzleTheme.SMALL_FAAN,
    ]
    listed = [t for themes in THEMES_BY_KIND.values() for t in themes]
    assert sorted(listed) == sorted(PuzzleTheme)


@pytest.mark.parametrize("puzzle", MINED, ids=lambda p: p.id)
def test_mined_theme_reads_off_the_engines_key(puzzle: Puzzle) -> None:
    state = puzzle_state(puzzle)
    theme = _theme(state, answer_key(puzzle, state))
    assert puzzle.theme == theme
    assert theme in THEMES_BY_KIND[PuzzleKind(puzzle.kind)]
