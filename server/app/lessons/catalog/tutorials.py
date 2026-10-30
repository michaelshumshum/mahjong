"""Guided tutorials (ADR 0025). Opponents hold scattered suited tiles and throw honours nobody
can claim, so every claim window in a script is one it means to open."""

from app.lessons.model import (
    Auto,
    Band,
    Expect,
    Highlight,
    Move,
    Narrate,
    Position,
    SeatSetup,
    Track,
    Tutorial,
)
from mahjong_core.actions import ActionKind


def _discard(tile: str) -> Move:
    return Move(ActionKind.DISCARD, tile)


# seat 0 is East and dealer. it ends with an East pung (seat and prevailing wind), a chow, a
# kong and 678s + 2p2p: four faan with self-draw and no flowers
BASICS_TUTORIAL = Tutorial(
    id="basics-tutorial",
    track=Track.BASICS,
    band=Band.BEGINNER,
    text="basicsTutorial",
    position=Position(
        seats=(
            SeatSetup(hand="359m999p2p678s116z"),
            SeatSetup(hand="12457m13467p147s"),
            SeatSetup(hand="268m1357p235689s"),
            SeatSetup(hand="1368m3568p13479s2z"),
        ),
        turn=3,
        wall_front="5z1z3z4z4m9p3z4z2z2p",
        wall_back="7z",
        seed=1,
    ),
    steps=(
        Narrate("welcome", Highlight.HUB),
        Narrate("yourHand", Highlight.HAND),
        Auto(3, _discard("2z")),
        Narrate("draw", Highlight.WALL),
        Expect(_discard("6z"), "discardFirst"),
        Auto(1, _discard("1z")),
        Narrate("pungOffer", Highlight.CLAIM),
        Expect(Move(ActionKind.CLAIM_PUNG, "11z"), "claimPung"),
        Narrate("pungLaid", Highlight.MELDS),
        Expect(_discard("9m"), "discardAfterPung"),
        Auto(1, _discard("3z")),
        Auto(2, _discard("4z")),
        Auto(3, _discard("4m")),
        Narrate("chowOffer", Highlight.CLAIM),
        Expect(Move(ActionKind.CLAIM_CHOW, "35m"), "claimChow"),
        Expect(_discard("5z"), "discardAfterChow"),
        Auto(1, _discard("9p")),
        Narrate("kongOffer", Highlight.CLAIM),
        Expect(Move(ActionKind.CLAIM_KONG, "999p"), "claimKong"),
        Narrate("replacement", Highlight.WALL),
        Expect(_discard("7z"), "discardAfterKong"),
        Auto(1, _discard("3z")),
        Auto(2, _discard("4z")),
        Auto(3, _discard("2z")),
        Narrate("selfDrawn", Highlight.HAND),
        Expect(Move(ActionKind.DECLARE_WIN), "declareWin"),
        Narrate("result", Highlight.HUB),
    ),
)

TUTORIALS: tuple[Tutorial, ...] = (BASICS_TUTORIAL,)
