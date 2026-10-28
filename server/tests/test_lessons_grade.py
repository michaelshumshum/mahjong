import pytest

from app.lessons.grade import (
    BestDiscardKey,
    CountFaanKey,
    FaanLine,
    SafeOption,
    WaitOption,
    WinningTilesKey,
    best_discard,
    count_faan,
    safe_discard,
    winning_tiles,
)
from app.lessons.model import LESSON_RULESET, MeldSetup, Position, SafeReason, SeatSetup
from app.lessons.position import build_position
from mahjong_core.actions import ClaimWin, DeclareWin, Discard, Pass
from mahjong_core.engine import reduce
from mahjong_core.hand_check import check_hand
from mahjong_core.melds import MeldKind
from mahjong_core.scoring.patterns import seat_wind_for
from mahjong_core.state import GameState, Phase, WinType
from mahjong_core.tiles import TileType, parse_tile, parse_tiles, tile_id_type

# hidden filler hands: two copies each of 2-8, so test hands keep every man, honor and 1/9
_SOU = "22334455667788s"
_PIN = "22334455667788p"


def _filler(spec: str, to_act: bool) -> SeatSetup:
    return SeatSetup(hand=spec if to_act else spec[:-2] + spec[-1])


def _position(seat0: SeatSetup, *, turn: int, dealer: int = 0, **others: SeatSetup) -> GameState:
    """Seat 0 as given; seats 1-3 are hidden fillers unless passed as `seat1=` etc."""
    fillers = {1: _SOU, 2: _PIN, 3: _SOU}
    seats = [seat0] + [
        others.get(f"seat{n}", _filler(fillers[n], to_act=n == turn)) for n in (1, 2, 3)
    ]
    return build_position(
        Position(seats=(seats[0], seats[1], seats[2], seats[3]), turn=turn, dealer=dealer)
    )


# 2 faan by discard (seat and prevailing east pung), 3 by self-draw; white pung is 1 / 2
_EAST_OR_WHITE = SeatSetup(
    hand="234m567p11z77z", melds=(MeldSetup(MeldKind.CHOW, "789p", from_seat=3),), flowers="2f"
)


@pytest.mark.parametrize(
    ("seat0", "others", "correct", "below", "dead"),
    [
        pytest.param(
            SeatSetup(hand="123m456m789m11z22z"), {}, ("z1", "z2"), (), (), id="half-flush-shanpon"
        ),
        pytest.param(_EAST_OR_WHITE, {}, ("z1",), ("z7",), (), id="one-wait-below-minimum"),
        pytest.param(
            SeatSetup(hand="123m456m789m111z5z"),
            {
                "seat1": SeatSetup(hand=_SOU, discards="5z"),
                "seat2": SeatSetup(hand=_PIN[:-2] + _PIN[-1], discards="5z"),
                "seat3": SeatSetup(hand=_SOU[:-2] + _SOU[-1], discards="5z"),
            },
            (),
            (),
            ("z5",),
            id="dead-wait-all-copies-visible",
        ),
        pytest.param(
            SeatSetup(hand="123m456m789m111z5z"),
            {
                "seat2": SeatSetup(hand="223344556677p5z", discards="5z"),
                "seat3": SeatSetup(hand=_SOU[:-2] + _SOU[-1], discards="5z"),
            },
            ("z5",),
            (),
            (),
            id="last-copy-hidden-still-counts",
        ),
    ],
)
def test_winning_tiles(
    seat0: SeatSetup,
    others: dict[str, SeatSetup],
    correct: tuple[str, ...],
    below: tuple[str, ...],
    dead: tuple[str, ...],
) -> None:
    key = winning_tiles(_position(seat0, turn=1, **others), 0)
    assert (key.correct, key.below_minimum, key.dead) == (correct, below, dead)


def test_winning_tiles_reports_faan_per_route() -> None:
    key = winning_tiles(_position(_EAST_OR_WHITE, turn=1), 0)
    assert key == WinningTilesKey(
        correct=("z1",),
        below_minimum=("z7",),
        dead=(),
        options=(
            WaitOption("z1", discard_faan=2, discard_wins=False, self_draw_faan=3,
                       self_draw_wins=True, live=2),
            WaitOption("z7", discard_faan=1, discard_wins=False, self_draw_faan=2,
                       self_draw_wins=False, live=2),
        ),
    )  # fmt: skip


def test_winning_tiles_needs_a_hand_one_short() -> None:
    with pytest.raises(ValueError):
        winning_tiles(_position(SeatSetup(hand="123m456m789m11z22z"), turn=1), 1)


_ISOLATED = SeatSetup(hand="123m456m789m19p11z1s")


@pytest.mark.parametrize(
    ("others", "correct"),
    [
        pytest.param({}, ("1p", "9p", "1s"), id="three-way-tie"),
        pytest.param(
            {"seat2": SeatSetup(hand=_PIN[:-2] + _PIN[-1], discards="23p")},
            ("1p",),
            id="visible-discards-break-the-tie",
        ),
    ],
)
def test_best_discard(others: dict[str, SeatSetup], correct: tuple[str, ...]) -> None:
    key = best_discard(_position(_ISOLATED, turn=0, **others), 0)
    assert key.correct == correct
    by_tile = {o.tile: o for o in key.options}
    assert by_tile["1p"].shanten == 1
    assert by_tile["1m"].shanten > 1


def test_best_discard_ignores_hidden_tiles() -> None:
    def key(seat2: str) -> BestDiscardKey:
        return best_discard(_position(_ISOLATED, turn=0, seat2=SeatSetup(hand=seat2)), 0)

    assert key(_PIN[:-2] + _PIN[-1]) == key("2223334445556p")


def test_best_discard_needs_the_seat_to_act() -> None:
    with pytest.raises(ValueError):
        best_discard(_position(_ISOLATED, turn=0), 1)


def _breakdown(key: CountFaanKey) -> dict[str, int]:
    return {line.pattern: line.faan for line in key.breakdown}


@pytest.mark.parametrize(
    ("hand", "flowers", "dealer"),
    [
        pytest.param("123m456m789m111z22z", "", 1, id="half-flush-prevailing-pung"),
        pytest.param("123m456m789m111z22z", "4f", 1, id="seat-flower"),
        pytest.param("11123455678999m", "", 2, id="nine-gates-limit"),
        pytest.param("123m234m345p678m22p", "", 3, id="all-sequences"),
    ],
)
def test_count_faan_matches_check_hand(hand: str, flowers: str, dealer: int) -> None:
    state = _position(SeatSetup(hand=hand, flowers=flowers), turn=0, dealer=dealer)
    key = count_faan(state, 0)
    check = check_hand(
        [t for t in parse_tiles(hand) if isinstance(t, TileType)],
        [f for f in parse_tiles(flowers) if not isinstance(f, TileType)],
        self_drawn=True,
        seat_wind=seat_wind_for(0, dealer),
        prevailing_wind=state.prevailing,
        ruleset=LESSON_RULESET,
    )
    assert check.result is not None
    assert key.win_type == WinType.SELF_DRAW
    assert key.correct == check.result.total_faan
    assert _breakdown(key) == check.result.breakdown
    assert key.points == check.points

    won, _ = reduce(state, DeclareWin())
    assert won.hand_result is not None
    assert (key.correct, key.points) == (won.hand_result.faan, won.hand_result.points)


def test_count_faan_on_a_claimed_discard_with_a_meld() -> None:
    seat0 = SeatSetup(hand="123m789m55z77z", melds=(MeldSetup(MeldKind.PUNG, "666m", from_seat=2),))
    state = _position(seat0, turn=1, seat1=SeatSetup(hand="2233445566778s5z"))
    red = next(t for t in state.seats[1].concealed if tile_id_type(t) == parse_tile("z5"))
    state, _ = reduce(state, Discard(tile_id=red))
    assert state.phase == Phase.AWAIT_CLAIMS

    key = count_faan(state, 0)
    assert key.win_type == WinType.DISCARD
    assert FaanLine("混一色", 3) in key.breakdown

    assert state.claim_window is not None
    window = state.claim_window
    state, _ = reduce(state, ClaimWin(window_id=window.window_id, seat=0))
    for offer in window.offers:
        if state.phase == Phase.AWAIT_CLAIMS and offer.seat != 0:
            state, _ = reduce(state, Pass(window_id=window.window_id, seat=offer.seat))
    assert state.hand_result is not None
    assert state.hand_result.win_type == WinType.DISCARD
    assert (key.correct, key.points) == (state.hand_result.faan, state.hand_result.points)
    assert _breakdown(key) == dict(state.hand_result.faan_breakdown)


def test_count_faan_needs_a_legal_win() -> None:
    with pytest.raises(ValueError):
        count_faan(_position(_ISOLATED, turn=0), 0)


# seat 1 is tenpai on 4m/7m (3 faan) and has discarded a 4m: no furiten, so it still wins on
# one. every 4m, 9p and z1 is visible to seat 0; seat 3's pung and seat 1's pool hold every 2s
_DEFENCE = build_position(
    Position(
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
)


def test_safe_discard_is_exact_against_the_hidden_hands() -> None:
    key = safe_discard(_DEFENCE, 0, ["9p"], SafeReason.GENBUTSU)
    assert key.correct == ("9p",)
    assert key.safe == ("1m", "2m", "3m", "8m", "9m", "9p", "1s", "z1", "z5")
    by_tile = {o.tile: o for o in key.options}
    both = (SafeReason.GENBUTSU, SafeReason.ALL_COPIES_VISIBLE)
    assert by_tile["4m"] == SafeOption("4m", deals_in_to=(1,), reasons=both)
    assert by_tile["7m"] == SafeOption("7m", deals_in_to=(1,), reasons=())
    assert by_tile["z1"].reasons == (SafeReason.ALL_COPIES_VISIBLE,)
    assert by_tile["1s"].reasons == (SafeReason.NO_CHANCE,)


@pytest.mark.parametrize(
    ("accepted", "reason"),
    [
        pytest.param(["z1"], SafeReason.ALL_COPIES_VISIBLE, id="fourth-honor"),
        pytest.param(["1s"], SafeReason.NO_CHANCE, id="walled-terminal"),
        pytest.param(["9p", "z1"], SafeReason.ALL_COPIES_VISIBLE, id="several"),
    ],
)
def test_safe_discard_accepts_a_stated_reason(accepted: list[str], reason: SafeReason) -> None:
    assert safe_discard(_DEFENCE, 0, accepted, reason).correct == tuple(accepted)


@pytest.mark.parametrize(
    ("accepted", "reason"),
    [
        pytest.param(["4m"], SafeReason.GENBUTSU, id="genbutsu-deals-in-without-furiten"),
        pytest.param(["4m"], SafeReason.ALL_COPIES_VISIBLE, id="last-copy-deals-in-to-a-run"),
        pytest.param(["z1"], SafeReason.GENBUTSU, id="reason-does-not-hold"),
        pytest.param(["2m"], SafeReason.NO_CHANCE, id="safe-but-not-deducible"),
        pytest.param(["5p"], SafeReason.GENBUTSU, id="not-in-hand"),
        pytest.param([], SafeReason.GENBUTSU, id="nothing-accepted"),
    ],
)
def test_safe_discard_rejects(accepted: list[str], reason: SafeReason) -> None:
    with pytest.raises(ValueError):
        safe_discard(_DEFENCE, 0, accepted, reason)
