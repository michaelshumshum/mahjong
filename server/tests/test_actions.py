import dataclasses

import pytest

from mahjong_core.actions import (
    ClaimChow,
    ClaimKong,
    ClaimPung,
    ClaimWin,
    DeclareAddedKong,
    DeclareConcealedKong,
    DeclareWin,
    Discard,
    Pass,
    hand_is_winning_shape,
    legal_actions,
)
from mahjong_core.config import DEFAULT_RULESET
from mahjong_core.melds import Meld, MeldKind
from mahjong_core.state import (
    ClaimKind,
    ClaimOffer,
    ClaimWindow,
    GameState,
    HandOutcome,
    HandResult,
    Phase,
    SeatState,
    new_game,
)
from mahjong_core.tiles import Flower, TileId, TileType, tile_ids_for_type

_MAN_1 = tile_ids_for_type(TileType.MAN_1)
_MAN_2 = tile_ids_for_type(TileType.MAN_2)
_MAN_3 = tile_ids_for_type(TileType.MAN_3)
_MAN_4 = tile_ids_for_type(TileType.MAN_4)
_MAN_5 = tile_ids_for_type(TileType.MAN_5)
_MAN_6 = tile_ids_for_type(TileType.MAN_6)
_MAN_7 = tile_ids_for_type(TileType.MAN_7)
_MAN_8 = tile_ids_for_type(TileType.MAN_8)
_MAN_9 = tile_ids_for_type(TileType.MAN_9)
_PIN_1 = tile_ids_for_type(TileType.PIN_1)
_PIN_2 = tile_ids_for_type(TileType.PIN_2)
_PIN_3 = tile_ids_for_type(TileType.PIN_3)
_PIN_4 = tile_ids_for_type(TileType.PIN_4)
_PIN_9 = tile_ids_for_type(TileType.PIN_9)
_SOU_1 = tile_ids_for_type(TileType.SOU_1)
_SOU_2 = tile_ids_for_type(TileType.SOU_2)
_SOU_3 = tile_ids_for_type(TileType.SOU_3)
_SOU_4 = tile_ids_for_type(TileType.SOU_4)
_SOU_9 = tile_ids_for_type(TileType.SOU_9)
_EAST = tile_ids_for_type(TileType.WIND_EAST)
_SOUTH = tile_ids_for_type(TileType.WIND_SOUTH)
_WEST = tile_ids_for_type(TileType.WIND_WEST)
_NORTH = tile_ids_for_type(TileType.WIND_NORTH)
_RED = tile_ids_for_type(TileType.DRAGON_RED)
_GREEN = tile_ids_for_type(TileType.DRAGON_GREEN)
_WHITE = tile_ids_for_type(TileType.DRAGON_WHITE)


def _base_state(**overrides: object) -> GameState:
    state = new_game(DEFAULT_RULESET, game_seed=1)
    return dataclasses.replace(state, **overrides)  # type: ignore[arg-type]


def _standard_winning_hand() -> tuple[TileId, ...]:
    # 111m 456m 789m 22m 33m -- wait that's only pairs; build a clean 4-melds+pair 14-tile hand.
    return (
        *_MAN_1[:3],
        _MAN_4[0],
        _MAN_5[0],
        _MAN_6[0],
        _MAN_7[0],
        _MAN_8[0],
        _MAN_9[0],
        *_PIN_1[:3],
        _MAN_2[0],
        _MAN_2[1],
    )


def _seven_pairs_hand() -> tuple[TileId, ...]:
    return (
        _MAN_1[0],
        _MAN_1[1],
        _MAN_2[0],
        _MAN_2[1],
        _MAN_3[0],
        _MAN_3[1],
        _MAN_4[0],
        _MAN_4[1],
        _MAN_5[0],
        _MAN_5[1],
        _MAN_6[0],
        _MAN_6[1],
        _MAN_7[0],
        _MAN_7[1],
    )


def _thirteen_orphans_hand() -> tuple[TileId, ...]:
    return (
        _MAN_1[0],
        _MAN_9[0],
        _PIN_1[0],
        _PIN_9[0],
        _SOU_1[0],
        _SOU_9[0],
        _EAST[0],
        _SOUTH[0],
        _WEST[0],
        _NORTH[0],
        _RED[0],
        _GREEN[0],
        _WHITE[0],
        _MAN_1[1],  # duplicate to reach 14
    )


def _not_winning_hand() -> tuple[TileId, ...]:
    return (
        _MAN_1[0],
        _MAN_2[0],
        _MAN_4[0],
        _MAN_5[0],
        _MAN_7[0],
        _MAN_9[0],
        _PIN_1[0],
        _PIN_9[0],
        _SOU_1[0],
        _EAST[0],
        _SOUTH[0],
        _WEST[0],
        _NORTH[0],
        _RED[0],
    )


def _with_seat_concealed(state: GameState, seat: int, concealed: tuple[int, ...]) -> GameState:
    seats = list(state.seats)
    seats[seat] = dataclasses.replace(seats[seat], concealed=concealed)  # type: ignore[arg-type]
    return dataclasses.replace(state, seats=tuple(seats))  # type: ignore[arg-type]


# --- AWAIT_DRAW / SCORING / HAND_OVER / GAME_OVER: nobody acts -----------------------------


@pytest.mark.parametrize(
    "phase", [Phase.AWAIT_DRAW, Phase.SCORING, Phase.HAND_OVER, Phase.GAME_OVER]
)
def test_no_actions_for_any_seat_in_non_deciding_phases(phase: Phase) -> None:
    overrides: dict[str, object] = {"phase": phase}
    if phase == Phase.HAND_OVER:
        overrides["hand_result"] = HandResult(outcome=HandOutcome.EXHAUSTIVE_DRAW)
    state = _base_state(**overrides)
    for seat in range(4):
        assert legal_actions(state, seat) == ()


# --- AWAIT_ACTION: turn seat only, discard always offered ----------------------------------


def test_only_turn_seat_gets_actions_in_await_action() -> None:
    state = _base_state(phase=Phase.AWAIT_ACTION, turn=0)
    assert legal_actions(state, 0) != ()
    for seat in (1, 2, 3):
        assert legal_actions(state, seat) == ()


def test_discard_offered_for_every_concealed_tile() -> None:
    state = _base_state(phase=Phase.AWAIT_ACTION, turn=0)
    concealed = state.seats[0].concealed
    actions = legal_actions(state, 0)
    discards = {a.tile_id for a in actions if isinstance(a, Discard)}
    assert discards == set(concealed)


def test_await_action_never_empty_for_turn_seat() -> None:
    state = _base_state(phase=Phase.AWAIT_ACTION, turn=0)
    assert legal_actions(state, 0) != ()


# --- concealed kong / added kong -------------------------------------------------------------


def test_concealed_kong_offered_with_4_matching_in_hand() -> None:
    concealed = (*_MAN_1, *_MAN_2[:3])
    state = _with_seat_concealed(_base_state(phase=Phase.AWAIT_ACTION, turn=0), 0, concealed)
    actions = legal_actions(state, 0)
    konged = [a for a in actions if isinstance(a, DeclareConcealedKong)]
    assert len(konged) == 1
    assert konged[0].meld.kind == MeldKind.CONCEALED_KONG


def test_added_kong_offered_when_matching_exposed_pung() -> None:
    pung = Meld(MeldKind.PUNG, tuple(_MAN_1[:3]), from_seat=1)
    state = _base_state(phase=Phase.AWAIT_ACTION, turn=0)
    seats = list(state.seats)
    seats[0] = dataclasses.replace(seats[0], concealed=(_MAN_1[3], _MAN_2[0]), melds=(pung,))
    state = dataclasses.replace(state, seats=tuple(seats))  # type: ignore[arg-type]
    actions = legal_actions(state, 0)
    added = [a for a in actions if isinstance(a, DeclareAddedKong)]
    assert len(added) == 1
    assert added[0].meld.kind == MeldKind.ADDED_KONG
    assert added[0].meld.from_seat == 1


# --- win-shape legality (structural only, see actions.py's boundary note) -------------------


def test_hand_is_winning_shape_standard() -> None:
    seat = SeatState(concealed=_standard_winning_hand())
    assert hand_is_winning_shape(seat)


def test_hand_is_winning_shape_seven_pairs() -> None:
    seat = SeatState(concealed=_seven_pairs_hand())
    assert hand_is_winning_shape(seat)


def test_hand_is_winning_shape_thirteen_orphans() -> None:
    seat = SeatState(concealed=_thirteen_orphans_hand())
    assert hand_is_winning_shape(seat)


def test_hand_is_not_winning_shape() -> None:
    seat = SeatState(concealed=_not_winning_hand())
    assert not hand_is_winning_shape(seat)


def test_seven_pairs_not_recognized_with_exposed_melds() -> None:
    pung = Meld(MeldKind.PUNG, tuple(_MAN_1[:3]), from_seat=1)
    # 12 tiles of the seven-pairs shape plus an exposed pung is not itself seven pairs.
    seat = SeatState(concealed=_seven_pairs_hand()[:11], melds=(pung,))
    assert not hand_is_winning_shape(seat)


def test_declare_win_offered_for_structurally_complete_hand() -> None:
    state = _with_seat_concealed(
        _base_state(phase=Phase.AWAIT_ACTION, turn=0), 0, _standard_winning_hand()
    )
    actions = legal_actions(state, 0)
    assert any(isinstance(a, DeclareWin) for a in actions)


def test_declare_win_not_offered_for_incomplete_hand() -> None:
    state = _with_seat_concealed(
        _base_state(phase=Phase.AWAIT_ACTION, turn=0), 0, _not_winning_hand()
    )
    actions = legal_actions(state, 0)
    assert not any(isinstance(a, DeclareWin) for a in actions)


def _below_min_faan_hand() -> tuple[TileId, ...]:
    """A real, structurally complete 14-tile hand that scores exactly 2 faan under
    `DEFAULT_RULESET` for a self-declared win: 平糊 (all sequences, 1) + 自摸 (1), with the
    man 234 chow claimed (the test adds it as an open meld) so 門前清 misses. Three suits
    used (man/pin/sou) so half/full-flush miss; a plain 9s pair so no wind/dragon faan; paired
    with a held flower that does *not* match the acting seat's wind in the test below, killing
    無花 without adding 正花."""
    return (
        _MAN_5[0],
        _MAN_6[0],
        _MAN_7[0],
        _PIN_2[0],
        _PIN_3[0],
        _PIN_4[0],
        _SOU_2[0],
        _SOU_3[0],
        _SOU_4[0],
        _SOU_9[0],
        _SOU_9[1],
    )


def test_declare_win_not_offered_below_min_faan() -> None:
    """Real gate, now closed (see actions.py module docstring / rules.md §11.8): a
    structurally complete hand that scores below `min_faan` under real faan counting is not
    offered `DeclareWin`. Seat 1 (non-dealer under dealer 0, seat_wind SOUTH) so this isn't
    confused with a dealer's pre-discard Heavenly Hand; the held flower (FLOWER_1, matches
    EAST) doesn't match seat 1's own wind, so it kills 無花 without adding 正花 either."""
    assert DEFAULT_RULESET.min_faan == 3
    state = _base_state(phase=Phase.AWAIT_ACTION, turn=1)
    seats = list(state.seats)
    open_chow = Meld(MeldKind.CHOW, (_MAN_2[0], _MAN_3[0], _MAN_4[0]), from_seat=0)
    seats[1] = dataclasses.replace(
        seats[1],
        concealed=_below_min_faan_hand(),
        melds=(open_chow,),
        flowers=(Flower.FLOWER_1,),
    )
    state = dataclasses.replace(state, seats=tuple(seats))  # type: ignore[arg-type]

    assert hand_is_winning_shape(state.seats[1])
    actions = legal_actions(state, 1)
    assert not any(isinstance(a, DeclareWin) for a in actions)


# --- AWAIT_CLAIMS ----------------------------------------------------------------------------


def _claim_window(offers: tuple[ClaimOffer, ...]) -> ClaimWindow:
    return ClaimWindow(
        window_id=7,
        kind=ClaimKind.DISCARD,
        source_seat=0,
        tile=_MAN_5[0],
        offers=offers,
    )


def test_claim_actions_only_for_offered_seat() -> None:
    chow = Meld(MeldKind.CHOW, (_MAN_4[0], _MAN_6[0], _MAN_5[0]), from_seat=0)
    window = _claim_window((ClaimOffer(seat=1, can_win=False, melds=(chow,)),))
    state = _base_state(phase=Phase.AWAIT_CLAIMS, claim_window=window, turn=0)

    actions = legal_actions(state, 1)
    assert any(isinstance(a, ClaimChow) for a in actions)
    assert any(isinstance(a, Pass) for a in actions)

    for seat in (0, 2, 3):
        assert legal_actions(state, seat) == ()


def test_claim_pung_and_kong_both_offered_same_seat() -> None:
    pung = Meld(MeldKind.PUNG, (*_MAN_1[:2], _MAN_1[3]), from_seat=0)
    kong = Meld(MeldKind.EXPOSED_KONG, tuple(_MAN_1), from_seat=0)
    window = _claim_window((ClaimOffer(seat=2, can_win=False, melds=(pung, kong)),))
    state = _base_state(phase=Phase.AWAIT_CLAIMS, claim_window=window, turn=0)

    actions = legal_actions(state, 2)
    assert any(isinstance(a, ClaimPung) for a in actions)
    assert any(isinstance(a, ClaimKong) for a in actions)
    assert any(isinstance(a, Pass) for a in actions)


def test_claim_win_offered_and_passable() -> None:
    window = _claim_window((ClaimOffer(seat=3, can_win=True),))
    state = _base_state(phase=Phase.AWAIT_CLAIMS, claim_window=window, turn=0)

    actions = legal_actions(state, 3)
    assert any(isinstance(a, ClaimWin) for a in actions)
    assert any(isinstance(a, Pass) for a in actions)


def test_await_claims_offered_seat_never_empty() -> None:
    window = _claim_window((ClaimOffer(seat=1, can_win=True),))
    state = _base_state(phase=Phase.AWAIT_CLAIMS, claim_window=window, turn=0)
    assert legal_actions(state, 1) != ()


# --- AWAIT_KONG_ROB ---------------------------------------------------------------------------


def test_kong_rob_window_offers_only_win_and_pass() -> None:
    window = ClaimWindow(
        window_id=9,
        kind=ClaimKind.KONG_ROB,
        source_seat=2,
        tile=_MAN_5[0],
        offers=(ClaimOffer(seat=0, can_win=True),),
    )
    state = _base_state(phase=Phase.AWAIT_KONG_ROB, claim_window=window, turn=2)

    actions = legal_actions(state, 0)
    assert {type(a) for a in actions} == {ClaimWin, Pass}
    for seat in (1, 2, 3):
        assert legal_actions(state, seat) == ()


# --- Action variant validation ----------------------------------------------------------------


def test_claim_chow_rejects_non_chow_meld() -> None:
    pung = Meld(MeldKind.PUNG, tuple(_MAN_1[:3]), from_seat=0)
    with pytest.raises(ValueError):
        ClaimChow(window_id=0, seat=1, meld=pung)


def test_claim_pung_rejects_non_pung_meld() -> None:
    chow = Meld(MeldKind.CHOW, (_MAN_1[0], _MAN_2[0], _MAN_3[0]), from_seat=0)
    with pytest.raises(ValueError):
        ClaimPung(window_id=0, seat=1, meld=chow)


def test_claim_kong_rejects_non_exposed_kong_meld() -> None:
    pung = Meld(MeldKind.PUNG, tuple(_MAN_1[:3]), from_seat=0)
    with pytest.raises(ValueError):
        ClaimKong(window_id=0, seat=1, meld=pung)


def test_declare_concealed_kong_rejects_wrong_meld_kind() -> None:
    pung = Meld(MeldKind.PUNG, tuple(_MAN_1[:3]), from_seat=0)
    with pytest.raises(ValueError):
        DeclareConcealedKong(meld=pung)


def test_declare_added_kong_rejects_wrong_meld_kind() -> None:
    kong = Meld(MeldKind.CONCEALED_KONG, tuple(_MAN_1))
    with pytest.raises(ValueError):
        DeclareAddedKong(meld=kong)


@pytest.mark.parametrize("bad_seat", [-1, 4])
def test_claim_action_rejects_bad_seat(bad_seat: int) -> None:
    with pytest.raises(ValueError):
        Pass(window_id=0, seat=bad_seat)


@pytest.mark.parametrize("bad_seat", [-1, 4])
def test_legal_actions_rejects_bad_seat(bad_seat: int) -> None:
    state = _base_state(phase=Phase.AWAIT_ACTION, turn=0)
    with pytest.raises(ValueError):
        legal_actions(state, bad_seat)


def test_actions_are_frozen() -> None:
    action = Discard(tile_id=_MAN_1[0])
    with pytest.raises(dataclasses.FrozenInstanceError):
        action.tile_id = _MAN_2[0]  # type: ignore[misc]
