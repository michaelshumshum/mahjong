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


# seat 1 is tenpai on 4m/7m. every 4m, 8p, 9p and z1 is visible to seat 0: 9p is walled by
# the dead 8p, and z1 can't feed thirteen orphans with 9p dead. 1s stays open (2s hidden)
DEDUCED = Position(
    seats=(
        SeatSetup(hand="12347789m9p1s1155z"),
        SeatSetup(hand="56m234567p34599s", discards="4m9p1z8p"),
        SeatSetup(hand="19m135p19s234567z", discards="4m9p1z8p8p"),
        SeatSetup(hand="19m15p78s3467z222s", discards="4m9p8p"),
    ),
    turn=0,
)

# seat 1 is closed and waits on z7 for thirteen orphans; seat 0 can see the other three z7 but
# no orphan type is dead, so that wait stays open
ORPHANS = Position(
    seats=(
        SeatSetup(hand="123m456m789m22p7z56s"),
        SeatSetup(hand="119m19p19s123456z", discards="7z"),
        SeatSetup(hand="2233445566788s", discards="7z"),
        SeatSetup(hand="2233445566788p", discards="7z"),
    ),
    turn=0,
)


def one_route(flowers: str) -> Position:
    """Seat 0 holds two exposed dots chows; 7p is the most efficient cut but keeps off-suit 8m,
    2s and 6s. With two flowers that aren't its own, a flush is its only way to 3 faan; with
    none, 無花 + 平糊 + self-draw get there too."""
    chows = tuple(MeldSetup(MeldKind.CHOW, t, from_seat=3) for t in ("789p", "456p"))
    return Position(
        seats=(
            SeatSetup(hand="8m12347p26s", melds=chows, flowers=flowers),
            SeatSetup(hand="2233445566778m"),
            SeatSetup(hand="1122334455667z"),
            SeatSetup(hand="99m3345577889s7z"),
        ),
        turn=0,
    )


# full flush, three exposed melds: 1s is the only discard that reaches ready (2s pair, 67s)
SOLE_TENPAI = Position(
    seats=(
        SeatSetup(
            hand="12267s",
            melds=(
                MeldSetup(MeldKind.CHOW, "345s", from_seat=3),
                MeldSetup(MeldKind.PUNG, "999s", from_seat=2),
                MeldSetup(MeldKind.CHOW, "789s", from_seat=3),
            ),
        ),
        SeatSetup(hand="2233445566778m"),
        SeatSetup(hand="1122334455667z"),
        SeatSetup(hand="99m1122334455p7z"),
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
