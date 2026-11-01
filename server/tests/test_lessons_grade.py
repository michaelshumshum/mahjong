import pytest

from app.lessons.grade import (
    BestDiscardKey,
    CountFaanKey,
    DiscardOption,
    FaanLine,
    SafeOption,
    WaitOption,
    WinningTilesKey,
    best_discard,
    count_faan,
    reaches_min_faan,
    safe_discard,
    safe_options,
    winning_tiles,
)
from app.lessons.model import LESSON_RULESET, MeldSetup, Position, SafeReason, SeatSetup
from app.lessons.position import build_position
from mahjong_core.actions import ClaimWin, DeclareWin, Discard, Pass
from mahjong_core.engine import reduce
from mahjong_core.hand_check import check_hand
from mahjong_core.melds import MeldKind
from mahjong_core.scoring.patterns import seat_wind_for
from mahjong_core.state import Phase, WinType
from mahjong_core.tiles import TileType, parse_tile, parse_tiles, tile_id_type
from tests.lesson_positions import DEDUCED, DEFENCE, ORPHANS, SOLE_TENPAI, one_route
from tests.lesson_positions import PIN as _PIN
from tests.lesson_positions import SOU as _SOU
from tests.lesson_positions import position as _position

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


@pytest.mark.parametrize(
    ("position", "tile", "reaches"),
    [
        # the chows and a self-draw make 2: only a flush clears 3, and 7p leaves 8m, 2s, 6s
        pytest.param(one_route("3f4f"), "7p", False, id="cut-keeps-off-suit-tiles"),
        pytest.param(one_route("3f4f"), "8m", True, id="cut-heads-for-the-flush"),
        pytest.param(one_route(""), "7p", True, id="no-flowers-is-the-third-faan"),
        pytest.param(SOLE_TENPAI, "1s", True, id="ready-on-a-full-flush"),
    ],
)
def test_reaches_min_faan(position: Position, tile: str, reaches: bool) -> None:
    assert reaches_min_faan(build_position(position), 0, tile) is reaches


def test_reaches_min_faan_rejects_a_tile_not_held() -> None:
    with pytest.raises(ValueError):
        reaches_min_faan(build_position(SOLE_TENPAI), 0, "5m")


def test_best_discard_keeps_exposed_melds_fixed() -> None:
    """Mined position (seed 20000000, decision 304): regrouping the chows read 5m as the better
    discard (8 tiles); 1666p really waits on 1p alone."""
    chows = tuple(MeldSetup(MeldKind.CHOW, t, from_seat=3) for t in ("123p", "789p", "234p"))
    seat0 = SeatSetup(hand="5m1666p", melds=chows)
    state = _position(seat0, turn=0, seat2=SeatSetup(hand="2233445566778m"))
    key = best_discard(state, 0)
    by_tile = {o.tile: o for o in key.options}
    assert key.correct == ("1p",)
    assert by_tile["5m"] == DiscardOption("5m", shanten=0, kinds=1, tiles=2)
    assert by_tile["1p"] == DiscardOption("1p", shanten=0, kinds=1, tiles=3)


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


_DEFENCE = build_position(DEFENCE)


def test_safe_options_are_exact_against_the_hidden_hands() -> None:
    by_tile = {o.tile: o for o in safe_options(_DEFENCE, 0)}
    safe = tuple(tile for tile, o in by_tile.items() if not o.deals_in_to)
    assert safe == ("1m", "2m", "3m", "8m", "9m", "9p", "1s", "z1", "z5")
    # every 4m is visible, but 56m waits on it: a run wait holds no copy
    assert by_tile["4m"] == SafeOption("4m", deals_in_to=(1,), reasons=())
    assert by_tile["7m"] == SafeOption("7m", deals_in_to=(1,), reasons=())
    # in every opponent's pool with every copy visible, but 78p is open: safe only by luck
    assert by_tile["9p"].reasons == ()
    assert by_tile["z1"].reasons == (SafeReason.ALL_COPIES_VISIBLE,)
    assert by_tile["1s"].reasons == (SafeReason.NO_CHANCE,)


_DEDUCED = build_position(DEDUCED)


def test_every_copy_visible_counts_for_a_suited_tile_only_with_its_runs_walled() -> None:
    by_tile = {o.tile: o for o in safe_options(_DEDUCED, 0)}
    both = (SafeReason.ALL_COPIES_VISIBLE, SafeReason.NO_CHANCE)
    assert by_tile["9p"] == SafeOption("9p", deals_in_to=(), reasons=both)
    assert by_tile["4m"] == SafeOption("4m", deals_in_to=(1,), reasons=())
    assert by_tile["z1"].reasons == (SafeReason.ALL_COPIES_VISIBLE,)
    assert [o.tile for o in by_tile.values() if o.reasons] == ["9p", "z1"]


def test_a_dead_honour_is_no_deduction_while_thirteen_orphans_can_wait_on_it() -> None:
    by_tile = {o.tile: o for o in safe_options(build_position(ORPHANS), 0)}
    assert by_tile["z7"] == SafeOption("z7", deals_in_to=(1,), reasons=())


def test_safe_discard_accepts_every_deducible_tile() -> None:
    key = safe_discard(_DEDUCED, 0, ["z1", "9p"], SafeReason.ALL_COPIES_VISIBLE)
    assert key.correct == ("9p", "z1")
    assert key.reason == SafeReason.ALL_COPIES_VISIBLE


@pytest.mark.parametrize(
    ("accepted", "reason"),
    [
        pytest.param(["z1"], SafeReason.ALL_COPIES_VISIBLE, id="deducible-9p-left-out"),
        pytest.param(["9p", "z1"], SafeReason.NO_CHANCE, id="reason-not-shared"),
        pytest.param(["9p", "z1", "4m"], SafeReason.ALL_COPIES_VISIBLE, id="last-copy-deals-in"),
        pytest.param(["9p", "z1", "2m"], SafeReason.ALL_COPIES_VISIBLE, id="not-deducible"),
        pytest.param(["9p", "z1", "5p"], SafeReason.ALL_COPIES_VISIBLE, id="not-in-hand"),
        pytest.param([], SafeReason.ALL_COPIES_VISIBLE, id="nothing-accepted"),
    ],
)
def test_safe_discard_rejects(accepted: list[str], reason: SafeReason) -> None:
    with pytest.raises(ValueError):
        safe_discard(_DEDUCED, 0, accepted, reason)


def test_safe_discard_rejects_mixed_reasons() -> None:
    """z1 is a full deduction and 1s only no-chance: no one stated reason covers both."""
    for reason in SafeReason:
        with pytest.raises(ValueError):
            safe_discard(_DEFENCE, 0, ["z1", "1s"], reason)
