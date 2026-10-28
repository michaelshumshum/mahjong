"""Hand-written beginner puzzles: two per kind, one teaching point each (ADR 0025). Seat 0
plays in characters and honours; the hidden opponents hold dots and bamboo fillers."""

from __future__ import annotations

from collections.abc import Mapping

from app.lessons.model import (
    Band,
    MeldSetup,
    Position,
    Puzzle,
    PuzzleKind,
    SafeReason,
    SeatSetup,
    Track,
)
from mahjong_core.melds import MeldKind

# not tenpai, no characters or honours. the seat to act draws `_DRAWN` on top
_FILLERS = ("1135799p124689s", "2246688p135579s", "12468p12356789s")
_DRAWN = "3p"
# a west in each opponent's pool: past the first go-round, so no heavenly or earthly hand
_POOL = "3z"
# seat 1 waits on 6s/9s with a half flush and a red dragon pung: 4 faan by discard
_TENPAI = "234s567s99s78s555z"


def _table(
    seat0: SeatSetup,
    *,
    turn: int = 0,
    hands: Mapping[int, str] | None = None,
    pools: Mapping[int, str] | None = None,
) -> Position:
    """Seat 0 as given, dealer seat 1 (seat 0 sits north); opponents hold `_FILLERS` and
    `_POOL` unless `hands`/`pools` name them."""
    seats = [seat0]
    for n, filler in enumerate(_FILLERS, start=1):
        hand = (hands or {}).get(n, filler + _DRAWN if n == turn else filler)
        seats.append(SeatSetup(hand=hand, discards=(pools or {}).get(n, _POOL)))
    return Position(seats=(seats[0], seats[1], seats[2], seats[3]), turn=turn, dealer=1)


def _puzzle(
    slug: str,
    kind: PuzzleKind,
    position: Position,
    answer: tuple[str, ...] | int,
    *,
    reason: SafeReason | None = None,
    discard: str | None = None,
) -> Puzzle:
    return Puzzle(
        id=f"basics-{slug}",
        kind=kind,
        track=Track.BASICS,
        band=Band.BEGINNER,
        position=position,
        answer=answer,
        text="basics" + "".join(w.capitalize() for w in slug.split("-")),
        reason=reason,
        discard=discard,
    )


BASICS: tuple[Puzzle, ...] = (
    _puzzle(
        "isolated-honour",
        PuzzleKind.BEST_DISCARD,
        _table(SeatSetup(hand="123m456m789m34m11z5z", discards="2z")),
        ("z5",),
    ),
    _puzzle(
        "two-sided-wait",
        PuzzleKind.WINNING_TILES,
        _table(SeatSetup(hand="123m456m789m11z45m", discards="2z"), turn=1),
        ("3m", "6m"),
    ),
    _puzzle(
        "keep-two-sided",
        PuzzleKind.BEST_DISCARD,
        _table(SeatSetup(hand="123m456m11z555z235m", discards="2z")),
        ("5m",),
    ),
    _puzzle(
        "pair-wait",
        PuzzleKind.WINNING_TILES,
        _table(SeatSetup(hand="123m456m789m11z77z", discards="2z"), turn=1),
        ("z1", "z7"),
    ),
    _puzzle(
        "simple-hand",
        PuzzleKind.COUNT_FAAN,
        _table(SeatSetup(hand="123m345m678m789p22m", flowers="1f", discards="2z")),
        3,
    ),
    _puzzle(
        "discard-win",
        PuzzleKind.COUNT_FAAN,
        _table(
            SeatSetup(
                hand="123m789m66z77z",
                melds=(MeldSetup(MeldKind.PUNG, "555m", from_seat=2),),
                flowers="1f",
                discards="2z",
            ),
            turn=1,
            hands={1: _FILLERS[0] + "6z"},
        ),
        4,
        discard="z6",
    ),
    _puzzle(
        "all-copies-visible",
        PuzzleKind.SAFE_DISCARD,
        _table(
            SeatSetup(hand="123m456m78m99m6s3z9p1s", discards="2z"),
            hands={1: _TENPAI},
        ),
        ("z3",),
        reason=SafeReason.ALL_COPIES_VISIBLE,
    ),
    _puzzle(
        "no-chance",
        PuzzleKind.SAFE_DISCARD,
        _table(
            SeatSetup(hand="13m456m789m11z66z6s9p", discards="2z2m"),
            hands={1: _TENPAI},
            pools={1: "3z2m", 2: "3z2m", 3: "3z2m"},
        ),
        ("1m",),
        reason=SafeReason.NO_CHANCE,
    ),
)
