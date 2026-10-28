"""Hand-built lesson positions: seat 0 as given, the others hidden fillers."""

from app.lessons.model import MeldSetup, Position, SeatSetup
from app.lessons.position import build_position
from mahjong_core.melds import MeldKind
from mahjong_core.state import GameState

# hidden filler hands: two copies each of 2-8, so test hands keep every man, honor and 1/9
SOU = "22334455667788s"
PIN = "22334455667788p"


# seat 1 is tenpai on 4m/7m (3 faan) and has discarded a 4m: no furiten, so it still wins on
# one. every 4m, 9p and z1 is visible to seat 0; seat 3's pung and seat 1's pool hold every 2s
DEFENCE = Position(
    seats=(
        SeatSetup(hand="12347789m9p1s1155z"),
        SeatSetup(hand="56m234678p34599s", discards="4m9p1z2s"),
        SeatSetup(hand="19m135p19s234567z", discards="4m9p1z"),
        SeatSetup(
            hand="19m15p78s3467z",
            melds=(MeldSetup(MeldKind.PUNG, "222s", from_seat=2),),
            discards="4m9p",
        ),
    ),
    turn=0,
)


def _filler(spec: str, to_act: bool) -> SeatSetup:
    return SeatSetup(hand=spec if to_act else spec[:-2] + spec[-1])


def spec(seat0: SeatSetup, *, turn: int, dealer: int = 0, **others: SeatSetup) -> Position:
    """Seat 0 as given; seats 1-3 are hidden fillers unless passed as `seat1=` etc."""
    fillers = {1: SOU, 2: PIN, 3: SOU}
    seats = [seat0] + [
        others.get(f"seat{n}", _filler(fillers[n], to_act=n == turn)) for n in (1, 2, 3)
    ]
    return Position(seats=(seats[0], seats[1], seats[2], seats[3]), turn=turn, dealer=dealer)


def position(seat0: SeatSetup, *, turn: int, dealer: int = 0, **others: SeatSetup) -> GameState:
    return build_position(spec(seat0, turn=turn, dealer=dealer, **others))
