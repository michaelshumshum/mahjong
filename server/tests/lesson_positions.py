"""Hand-built lesson positions: seat 0 as given, the others hidden fillers."""

from app.lessons.model import Position, SeatSetup
from app.lessons.position import build_position
from mahjong_core.state import GameState

# hidden filler hands: two copies each of 2-8, so test hands keep every man, honor and 1/9
SOU = "22334455667788s"
PIN = "22334455667788p"


def _filler(spec: str, to_act: bool) -> SeatSetup:
    return SeatSetup(hand=spec if to_act else spec[:-2] + spec[-1])


def position(seat0: SeatSetup, *, turn: int, dealer: int = 0, **others: SeatSetup) -> GameState:
    """Seat 0 as given; seats 1-3 are hidden fillers unless passed as `seat1=` etc."""
    fillers = {1: SOU, 2: PIN, 3: SOU}
    seats = [seat0] + [
        others.get(f"seat{n}", _filler(fillers[n], to_act=n == turn)) for n in (1, 2, 3)
    ]
    return build_position(
        Position(seats=(seats[0], seats[1], seats[2], seats[3]), turn=turn, dealer=dealer)
    )
