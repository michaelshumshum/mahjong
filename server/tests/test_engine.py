import dataclasses
import random

import pytest

from mahjong_core.actions import (
    ClaimChow,
    ClaimPung,
    ClaimWin,
    DeclareAddedKong,
    DeclareConcealedKong,
    DeclareWin,
    Discard,
    Pass,
    legal_actions,
)
from mahjong_core.config import DEFAULT_RULESET, GameLength, RuleSet
from mahjong_core.engine import (
    ClaimResolved,
    Discarded,
    Drawn,
    FlowerReplaced,
    GameEnded,
    HandEnded,
    IllegalActionError,
    KongReplacementDrawn,
    MeldFormed,
    new_game,
    reduce,
    start_next_hand,
)
from mahjong_core.melds import Meld, MeldKind
from mahjong_core.state import (
    ClaimKind,
    GameState,
    HandOutcome,
    HandResult,
    Phase,
    SeatState,
    Wind,
    WinType,
)
from mahjong_core.tiles import TOTAL_PHYSICAL_TILES, Flower, TileType, tile_ids_for_type
from mahjong_core.wall import Wall

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
_PIN_9 = tile_ids_for_type(TileType.PIN_9)
_SOU_1 = tile_ids_for_type(TileType.SOU_1)
_SOU_2 = tile_ids_for_type(TileType.SOU_2)
_SOU_4 = tile_ids_for_type(TileType.SOU_4)
_SOU_6 = tile_ids_for_type(TileType.SOU_6)
_SOU_8 = tile_ids_for_type(TileType.SOU_8)
_EAST = tile_ids_for_type(TileType.WIND_EAST)
_SOUTH = tile_ids_for_type(TileType.WIND_SOUTH)
_WEST = tile_ids_for_type(TileType.WIND_WEST)
_NORTH = tile_ids_for_type(TileType.WIND_NORTH)
_RED = tile_ids_for_type(TileType.DRAGON_RED)
_GREEN = tile_ids_for_type(TileType.DRAGON_GREEN)
_WHITE = tile_ids_for_type(TileType.DRAGON_WHITE)

# 13 distinct tiles, deliberately confined to sou-evens + honors: every other test in this
# file discards/claims man or pin tiles, so this filler can never accidentally collide with
# (duplicate) the tile under test -- see the man-suit collision this replaced.
_JUNK_HAND = (
    _SOU_2[0],
    _SOU_4[0],
    _SOU_6[0],
    _SOU_8[0],
    _SOU_2[1],
    _SOU_4[1],
    _SOU_6[1],
    _SOUTH[0],
    _WEST[0],
    _NORTH[0],
    _RED[0],
    _GREEN[0],
    _WHITE[0],
)


def _state(**overrides: object) -> GameState:
    state = new_game(DEFAULT_RULESET, game_seed=1)
    return dataclasses.replace(state, **overrides)  # type: ignore[arg-type]


def _with_seat(state: GameState, seat: int, **overrides: object) -> GameState:
    seats = list(state.seats)
    seats[seat] = dataclasses.replace(seats[seat], **overrides)  # type: ignore[arg-type]
    return dataclasses.replace(state, seats=tuple(seats))  # type: ignore[arg-type]


def _all_junk(state: GameState, *, except_seat: int) -> GameState:
    for seat in range(4):
        if seat != except_seat:
            state = _with_seat(state, seat, concealed=_JUNK_HAND)
    return state


def _total_tiles(state: GameState) -> int:
    seat_tiles = sum(
        len(seat.concealed) + sum(len(m.tiles) for m in seat.melds) + len(seat.discards)
        for seat in state.seats
    )
    seat_flowers = sum(len(seat.flowers) for seat in state.seats)
    return seat_tiles + len(state.wall.tiles) + seat_flowers


# --- discard: no claims -> advance to next seat's draw --------------------------------------


def test_discard_with_no_claims_advances_to_next_seat_draw() -> None:
    # a deterministic, flower-free wall -- new_game()'s real dealt wall can legitimately put
    # a flower on top, which would chain into extra replacement draws and make the plain
    # "-1" wall-count assertion below flaky.
    state = _state(phase=Phase.AWAIT_ACTION, turn=0, wall=Wall(tiles=(_SOU_8[2], _SOU_8[3])))
    state = _with_seat(state, 0, concealed=(*_JUNK_HAND, _EAST[0]))
    state = _all_junk(state, except_seat=0)

    wall_before = len(state.wall.tiles)
    state, events = reduce(state, Discard(tile_id=_EAST[0]))

    assert state.phase == Phase.AWAIT_ACTION
    assert state.turn == 1
    assert state.claim_window is None
    assert state.seats[0].discards == (_EAST[0],)
    assert len(state.seats[1].concealed) == len(_JUNK_HAND) + 1
    assert len(state.wall.tiles) == wall_before - 1
    assert events[0] == Discarded(seat=0, tile_id=_EAST[0])
    assert any(isinstance(e, Drawn) and e.seat == 1 for e in events)


# --- discard: opens a claim window -----------------------------------------------------------


def test_discard_with_a_legal_pung_opens_claim_window() -> None:
    state = _state(phase=Phase.AWAIT_ACTION, turn=0)
    state = _with_seat(state, 0, concealed=(*_JUNK_HAND, _MAN_5[0]))
    state = _all_junk(state, except_seat=0)
    state = _with_seat(state, 2, concealed=(_MAN_5[1], _MAN_5[2], *_JUNK_HAND[:11]))

    state, events = reduce(state, Discard(tile_id=_MAN_5[0]))

    assert state.phase == Phase.AWAIT_CLAIMS
    assert state.claim_window is not None
    assert state.claim_window.kind == ClaimKind.DISCARD
    assert state.claim_window.source_seat == 0
    assert state.claim_window.tile == _MAN_5[0]
    assert {o.seat for o in state.claim_window.offers} == {2}
    offer = state.claim_window.offers[0]
    assert not offer.can_win
    assert {m.kind for m in offer.melds} == {MeldKind.PUNG}
    assert not any(isinstance(e, Drawn) for e in events)


# --- claim response accumulation: a chow claim doesn't resolve while a pung is pending -------


def _claims_window_state() -> GameState:
    state = _state(phase=Phase.AWAIT_ACTION, turn=0)
    state = _with_seat(state, 0, concealed=(*_JUNK_HAND, _MAN_5[0]), discards=())
    state = _all_junk(state, except_seat=0)
    state = _with_seat(state, 1, concealed=(_MAN_4[0], _MAN_6[0], *_JUNK_HAND[:11]))
    state = _with_seat(state, 2, concealed=(_MAN_5[1], _MAN_5[2], *_JUNK_HAND[:11]))
    state, _ = reduce(state, Discard(tile_id=_MAN_5[0]))
    return state


def test_partial_claim_response_does_not_resolve_when_a_higher_tier_is_pending() -> None:
    state = _claims_window_state()
    window = state.claim_window
    assert window is not None
    chow_action = next(a for a in legal_actions(state, 1) if isinstance(a, ClaimChow))

    state, events = reduce(state, chow_action)

    assert state.phase == Phase.AWAIT_CLAIMS
    assert state.claim_window is not None
    assert state.claim_window.responses == {1: chow_action}
    assert events == []


def test_pung_beats_pending_chow_once_both_respond() -> None:
    state = _claims_window_state()
    chow_action = next(a for a in legal_actions(state, 1) if isinstance(a, ClaimChow))
    state, _ = reduce(state, chow_action)
    pung_action = next(a for a in legal_actions(state, 2) if isinstance(a, ClaimPung))

    state, events = reduce(state, pung_action)

    assert state.phase == Phase.AWAIT_ACTION
    assert state.turn == 2
    assert state.claim_window is None
    assert state.seats[0].discards == ()  # claimed tile removed from the discard pool
    assert any(m.kind == MeldKind.PUNG for m in state.seats[2].melds)
    resolved = next(e for e in events if isinstance(e, ClaimResolved))
    assert resolved.winning_seat == 2
    assert any(isinstance(e, MeldFormed) for e in events)


# --- claim resolution: all pass -> advance to next seat's draw -------------------------------


def test_all_pass_advances_to_next_seat_draw() -> None:
    state = _claims_window_state()
    window = state.claim_window
    assert window is not None
    for seat in (1, 2):
        pass_action = next(a for a in legal_actions(state, seat) if isinstance(a, Pass))
        state, events = reduce(state, pass_action)

    assert state.phase == Phase.AWAIT_ACTION
    assert state.turn == 1
    assert state.claim_window is None
    resolved = next(e for e in events if isinstance(e, ClaimResolved))
    assert resolved.winning_seat is None


# --- claim resolution: kong claim draws a replacement -----------------------------------------


def test_claim_kong_draws_replacement_and_returns_to_await_action() -> None:
    state = _state(phase=Phase.AWAIT_ACTION, turn=0)
    state = _with_seat(state, 0, concealed=(*_JUNK_HAND, _MAN_5[0]), discards=())
    state = _all_junk(state, except_seat=0)
    state = _with_seat(state, 2, concealed=(_MAN_5[1], _MAN_5[2], _MAN_5[3], *_JUNK_HAND[:10]))
    state, _ = reduce(state, Discard(tile_id=_MAN_5[0]))
    kong_action = next(a for a in legal_actions(state, 2) if a.kind.value == "claim_kong")

    wall_before = len(state.wall.tiles)
    state, events = reduce(state, kong_action)

    assert state.phase == Phase.AWAIT_ACTION
    assert state.turn == 2
    assert any(m.kind == MeldKind.EXPOSED_KONG for m in state.seats[2].melds)
    assert len(state.wall.tiles) == wall_before - 1
    assert any(isinstance(e, KongReplacementDrawn) and e.seat == 2 for e in events)


# --- own-turn concealed kong: no rob window under default ruleset ----------------------------


def test_declare_concealed_kong_draws_replacement_with_no_rob_window() -> None:
    state = _state(phase=Phase.AWAIT_ACTION, turn=0)
    state = _with_seat(state, 0, concealed=(*_MAN_1, *_JUNK_HAND[:10]))
    state = _all_junk(state, except_seat=0)
    meld = Meld(MeldKind.CONCEALED_KONG, tuple(_MAN_1))

    state, events = reduce(state, DeclareConcealedKong(meld=meld))

    assert state.phase == Phase.AWAIT_ACTION
    assert state.turn == 0
    assert state.claim_window is None
    assert meld in state.seats[0].melds
    assert any(isinstance(e, MeldFormed) for e in events)
    assert any(isinstance(e, KongReplacementDrawn) for e in events)


# --- own-turn added kong: opens a robbing-the-kong window when a chow-completion is live -----


def _tenpai_on_man1() -> tuple[int, ...]:
    """13 tiles: standard shape missing only the 1m that completes 123m (a chow-completion
    wait, the realistic robbable shape -- see engine.py module docstring / 01-rules-spec.md
    §11.3: robbing needs the robber to hold zero copies of the robbed tile already, since the
    kong declarer already accounts for all 4 physical copies)."""
    return (
        _MAN_2[0],
        _MAN_3[0],
        _MAN_4[0],
        _MAN_5[0],
        _MAN_6[0],
        _MAN_7[0],
        _MAN_8[0],
        _MAN_9[0],
        _PIN_1[0],
        _PIN_2[0],
        _PIN_3[0],
        _PIN_9[0],
        _PIN_9[1],
    )


def _added_kong_state() -> GameState:
    pung = Meld(MeldKind.PUNG, (_MAN_1[0], _MAN_1[1], _MAN_1[2]), from_seat=1)
    state = _state(phase=Phase.AWAIT_ACTION, turn=0)
    state = _with_seat(state, 0, concealed=(_MAN_1[3], *_JUNK_HAND[:10]), melds=(pung,))
    state = _all_junk(state, except_seat=0)
    state = _with_seat(state, 2, concealed=_tenpai_on_man1())
    return state


def test_added_kong_opens_kong_rob_window_for_a_tenpai_seat() -> None:
    state = _added_kong_state()
    meld = Meld(MeldKind.ADDED_KONG, tuple(_MAN_1), from_seat=1)

    state, events = reduce(state, DeclareAddedKong(meld=meld))

    assert state.phase == Phase.AWAIT_KONG_ROB
    assert state.claim_window is not None
    assert state.claim_window.kind == ClaimKind.KONG_ROB
    assert state.claim_window.source_seat == 0
    assert state.claim_window.tile == _MAN_1[3]
    assert {o.seat for o in state.claim_window.offers} == {2}
    assert state.claim_window.offers[0].can_win
    assert any(isinstance(e, MeldFormed) for e in events)
    assert not any(isinstance(e, KongReplacementDrawn) for e in events)


def test_robbing_the_kong_ends_the_hand_as_a_kong_rob_win() -> None:
    # forced flowerless so the faan below is deterministic regardless of the real seeded deal
    state = _with_seat(_added_kong_state(), 2, flowers=())
    meld = Meld(MeldKind.ADDED_KONG, tuple(_MAN_1), from_seat=1)
    state, _ = reduce(state, DeclareAddedKong(meld=meld))
    win_action = next(a for a in legal_actions(state, 2) if isinstance(a, ClaimWin))

    state, events = reduce(state, win_action)

    assert state.phase == Phase.HAND_OVER
    # 缺一門(2) + 平糊(1) + 門前清(1) + 搶槓(1) + 無花(1) = 6 faan; half-spicy points(6) = 32;
    # a discard-shaped payment (§8's robbing-the-kong note) with default DiscardPayment.ALL.
    assert state.hand_result == HandResult(
        outcome=HandOutcome.WIN,
        winner=2,
        win_type=WinType.KONG_ROB,
        discarder=0,
        faan=6,
        faan_breakdown={"缺一門": 2, "平糊": 1, "門前清": 1, "搶槓": 1, "無花": 1},
        points=32,
        payments={0: -32, 1: 0, 2: 32, 3: 0},
    )
    assert any(isinstance(e, HandEnded) for e in events)


def test_declining_to_rob_the_kong_lets_declarer_draw_replacement() -> None:
    state = _added_kong_state()
    meld = Meld(MeldKind.ADDED_KONG, tuple(_MAN_1), from_seat=1)
    state, _ = reduce(state, DeclareAddedKong(meld=meld))
    pass_action = next(a for a in legal_actions(state, 2) if isinstance(a, Pass))

    state, events = reduce(state, pass_action)

    assert state.phase == Phase.AWAIT_ACTION
    assert state.turn == 0
    assert state.claim_window is None
    assert any(isinstance(e, KongReplacementDrawn) and e.seat == 0 for e in events)


# --- self-draw win -----------------------------------------------------------------------------


def _standard_winning_hand() -> tuple[int, ...]:
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


def test_declare_win_ends_hand_as_self_draw() -> None:
    # total_discards=1 so this isn't also a (real, correctly-scored) Heavenly Hand -- seat 0
    # is the dealer and would otherwise still be "before any discard" here.
    state = _state(phase=Phase.AWAIT_ACTION, turn=0, total_discards=1)
    state = _with_seat(state, 0, concealed=_standard_winning_hand(), flowers=())

    state, events = reduce(state, DeclareWin())

    assert state.phase == Phase.HAND_OVER
    # 缺一門(2) + 自摸(1) + 無花(1) = 4 faan; half-spicy points(4) = 16; self-draw split 3 ways.
    assert state.hand_result == HandResult(
        outcome=HandOutcome.WIN,
        winner=0,
        win_type=WinType.SELF_DRAW,
        discarder=None,
        faan=4,
        faan_breakdown={"缺一門": 2, "自摸": 1, "無花": 1},
        points=16,
        payments={0: 24, 1: -8, 2: -8, 3: -8},
    )
    assert any(isinstance(e, HandEnded) for e in events)


# --- claimed win: real faan/points/payments, and the min_faan gate on claim offers -----------


def _claimable_standard_hand() -> tuple[int, ...]:
    """13 concealed tiles: `_standard_winning_hand()` minus its 14th (pairing) tile -- the
    same shape, waiting on a discard to complete the 2m pair instead of already holding it."""
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
    )


def test_claim_win_off_discard_scores_and_pays_real_faan() -> None:
    state = _state(phase=Phase.AWAIT_ACTION, turn=1, total_discards=1)
    state = _with_seat(state, 1, concealed=(*_JUNK_HAND, _MAN_2[1]), flowers=())
    state = _all_junk(state, except_seat=1)
    state = _with_seat(state, 3, concealed=_claimable_standard_hand(), flowers=())

    state, _ = reduce(state, Discard(tile_id=_MAN_2[1]))
    win_action = next(a for a in legal_actions(state, 3) if isinstance(a, ClaimWin))
    state, events = reduce(state, win_action)

    assert state.phase == Phase.HAND_OVER
    # 缺一門(2) + 門前清(1, claimed not self-drawn) + 無花(1) = 4 faan; points(4) = 16;
    # DiscardPayment.ALL (default): discarder pays it all, winner takes it all.
    assert state.hand_result == HandResult(
        outcome=HandOutcome.WIN,
        winner=3,
        win_type=WinType.DISCARD,
        discarder=1,
        faan=4,
        faan_breakdown={"缺一門": 2, "門前清": 1, "無花": 1},
        points=16,
        payments={0: 0, 1: -16, 2: 0, 3: 16},
    )
    assert any(isinstance(e, HandEnded) for e in events)


def test_claim_win_gated_by_min_faan_even_when_window_opens_for_another_seat() -> None:
    """The engine-level half of the min_faan gate (`_can_win_with`/`_discard_claim_offers`,
    distinct from `actions.can_declare_win`'s own-turn path -- see test_actions.py's
    `test_declare_win_not_offered_below_min_faan` for that one). Seat 2 holds a legitimate
    pung claim on the same discard so the claim window genuinely opens; seat 3's hand is
    structurally a complete win (the same 4-faan shape as the test above) but `min_faan=5`
    here puts it under the bar -- proving the absent offer is the gate, not an empty window.
    """
    ruleset = RuleSet(min_faan=5)
    state = _state(ruleset=ruleset, phase=Phase.AWAIT_ACTION, turn=1, total_discards=1)
    state = _with_seat(state, 1, concealed=(*_JUNK_HAND, _MAN_2[1]), flowers=())
    state = _all_junk(state, except_seat=1)
    state = _with_seat(state, 2, concealed=(_MAN_2[2], _MAN_2[3], *_JUNK_HAND[:11]))
    state = _with_seat(state, 3, concealed=_claimable_standard_hand(), flowers=())

    state, _ = reduce(state, Discard(tile_id=_MAN_2[1]))

    assert state.phase == Phase.AWAIT_CLAIMS
    assert state.claim_window is not None
    assert {o.seat for o in state.claim_window.offers} == {2}  # seat 3's win gated off
    assert legal_actions(state, 3) == ()
    pung_offer = state.claim_window.offers[0]
    assert pung_offer.seat == 2
    assert not pung_offer.can_win


# --- real timing-flag contexts, from actual gameplay sequences -------------------------------


def test_heavenly_hand_win_before_any_discard() -> None:
    """天糊: the dealer's own dealt hand is already complete before anyone has discarded --
    `_state()`'s fresh `new_game()` output already has `total_discards == 0` and `turn ==
    dealer == 0`, so this is genuinely "the first decision point of the hand", not a
    hand-built context override."""
    state = _state(phase=Phase.AWAIT_ACTION, turn=0)
    state = _with_seat(state, 0, concealed=_standard_winning_hand(), flowers=())

    state, events = reduce(state, DeclareWin())

    assert state.phase == Phase.HAND_OVER
    assert state.hand_result == HandResult(
        outcome=HandOutcome.WIN,
        winner=0,
        win_type=WinType.SELF_DRAW,
        discarder=None,
        faan=DEFAULT_RULESET.faan_cap,
        faan_breakdown={"天糊": DEFAULT_RULESET.faan_cap},
        points=128,
        payments={0: 192, 1: -64, 2: -64, 3: -64},
    )
    assert any(isinstance(e, HandEnded) for e in events)


def test_earthly_hand_win_on_dealer_first_discard() -> None:
    """地糊: a non-dealer claims win on the dealer's own first discard of the hand -- reached
    via one real `Discard` from the fresh post-deal state (`total_discards` goes 0 -> 1 right
    there), not by setting the flag directly."""
    state = _state(phase=Phase.AWAIT_ACTION, turn=0)
    state = _with_seat(state, 0, concealed=(*_JUNK_HAND, _MAN_2[1]), flowers=())
    state = _all_junk(state, except_seat=0)
    state = _with_seat(state, 2, concealed=_claimable_standard_hand(), flowers=())

    state, _ = reduce(state, Discard(tile_id=_MAN_2[1]))  # dealer's first discard
    win_action = next(a for a in legal_actions(state, 2) if isinstance(a, ClaimWin))
    state, events = reduce(state, win_action)

    assert state.phase == Phase.HAND_OVER
    assert state.hand_result == HandResult(
        outcome=HandOutcome.WIN,
        winner=2,
        win_type=WinType.DISCARD,
        discarder=0,
        faan=DEFAULT_RULESET.faan_cap,
        faan_breakdown={"地糊": DEFAULT_RULESET.faan_cap},
        points=128,
        payments={0: -128, 1: 0, 2: 128, 3: 0},
    )
    assert any(isinstance(e, HandEnded) for e in events)


def test_win_on_last_wall_tile_scores_last_tile_self_draw() -> None:
    """海底撈月: a real front draw off a one-tile wall lands the winning tile, setting
    `wall_exhausted_at_last_draw` from `_draw_for_turn` itself -- not a hand-built context."""
    state = _state(phase=Phase.AWAIT_ACTION, turn=0, wall=Wall(tiles=(_MAN_2[1],)))
    state = _with_seat(state, 0, concealed=(*_JUNK_HAND, _EAST[0]), flowers=())
    state = _all_junk(state, except_seat=0)
    state = _with_seat(state, 1, concealed=_claimable_standard_hand(), flowers=())

    state, _ = reduce(state, Discard(tile_id=_EAST[0]))  # no claims -> seat 1 draws the last tile

    assert state.phase == Phase.AWAIT_ACTION
    assert state.turn == 1
    assert state.wall_exhausted_at_last_draw is True
    assert state.last_draw_was_kong_replacement is False
    assert _MAN_2[1] in state.seats[1].concealed

    state, events = reduce(state, DeclareWin())

    assert state.phase == Phase.HAND_OVER
    result = state.hand_result
    assert result is not None
    assert result.win_type == WinType.SELF_DRAW
    # 缺一門(2) + 自摸(1) + 無花(1) + 海底撈月(1) = 5 faan.
    assert result.faan == 5
    assert result.faan_breakdown["海底撈月"] == 1
    assert any(isinstance(e, HandEnded) for e in events)


def test_win_on_last_discard_scores_river_bottom() -> None:
    """河底撈魚: the wall empties on seat 1's draw (a tile they don't need), they discard it
    right back out, and seat 3 claims that discard for the win -- `wall_exhausted_at_last_draw`
    carries across the intervening discard/claim-window turns untouched, exactly as it must
    for "the last possible discard" to be claimable at all."""
    state = _state(phase=Phase.AWAIT_ACTION, turn=0, wall=Wall(tiles=(_MAN_2[1],)))
    state = _with_seat(state, 0, concealed=(*_JUNK_HAND, _EAST[0]), flowers=())
    state = _all_junk(state, except_seat=0)
    state = _with_seat(state, 3, concealed=_claimable_standard_hand(), flowers=())

    state, _ = reduce(state, Discard(tile_id=_EAST[0]))  # seat 1 draws the wall's last tile
    assert _MAN_2[1] in state.seats[1].concealed
    assert state.wall_exhausted_at_last_draw is True

    state, _ = reduce(state, Discard(tile_id=_MAN_2[1]))  # seat 1 doesn't need it either
    win_action = next(a for a in legal_actions(state, 3) if isinstance(a, ClaimWin))
    state, events = reduce(state, win_action)

    assert state.phase == Phase.HAND_OVER
    result = state.hand_result
    assert result is not None
    assert result.win_type == WinType.DISCARD
    assert result.discarder == 1
    # 缺一門(2) + 門前清(1) + 無花(1) + 河底撈魚(1) = 5 faan.
    assert result.faan == 5
    assert result.faan_breakdown["河底撈魚"] == 1
    assert any(isinstance(e, HandEnded) for e in events)


def test_win_on_kong_replacement_scores_kong_replacement() -> None:
    """槓上開花: a concealed kong's own replacement draw (drawn from the back of the wall by
    `_apply_self_kong` -> `_draw_for_turn`) completes the hand -- `last_draw_was_kong_replacement`
    comes from that real draw, not a hand-built context. An extra tile ahead of it on the wall
    keeps `wall_exhausted_at_last_draw` false, isolating this from 海底撈月. `total_discards=1`
    so seat 0 (the dealer) isn't also mistaken for a (real, correctly-scored) Heavenly Hand."""
    state = _state(
        phase=Phase.AWAIT_ACTION, turn=0, total_discards=1, wall=Wall(tiles=(_SOU_1[3], _MAN_2[1]))
    )
    state = _with_seat(
        state,
        0,
        concealed=(
            *_MAN_1,
            _MAN_4[0],
            _MAN_5[0],
            _MAN_6[0],
            _MAN_7[0],
            _MAN_8[0],
            _MAN_9[0],
            *_PIN_1[:3],
            _MAN_2[0],
        ),
        flowers=(),
    )
    meld = Meld(MeldKind.CONCEALED_KONG, tuple(_MAN_1))

    state, _ = reduce(state, DeclareConcealedKong(meld=meld))

    assert state.phase == Phase.AWAIT_ACTION
    assert state.last_draw_was_kong_replacement is True
    assert state.wall_exhausted_at_last_draw is False
    assert _MAN_2[1] in state.seats[0].concealed

    state, events = reduce(state, DeclareWin())

    assert state.phase == Phase.HAND_OVER
    result = state.hand_result
    assert result is not None
    assert result.win_type == WinType.SELF_DRAW
    # 缺一門(2) + 自摸(1) + 無花(1) + 槓上開花(1) = 5 faan.
    assert result.faan == 5
    assert result.faan_breakdown["槓上開花"] == 1
    assert any(isinstance(e, HandEnded) for e in events)


# --- flower instant-win ------------------------------------------------------------------------


def test_seven_flowers_instant_win_ends_hand_immediately() -> None:
    """`seven_flowers_instant_win`: a seat's flower-replacement cascade itself ends the hand
    the moment its 7th flower is set aside -- no winning tile, no meld decomposition. The wall
    is arranged so a plain discard's follow-up draw cascades through 7 distinct flowers
    (`Flower` has only 8 values total, no duplicates, so 7 is "all but one")."""
    ruleset = RuleSet(seven_flowers_instant_win=True)
    tiles = (
        Flower.FLOWER_1,
        Flower.SEASON_3,
        Flower.SEASON_2,
        Flower.SEASON_1,
        Flower.FLOWER_4,
        Flower.FLOWER_3,
        Flower.FLOWER_2,
    )
    state = _state(ruleset=ruleset, phase=Phase.AWAIT_ACTION, turn=0, wall=Wall(tiles=tiles))
    state = _with_seat(state, 0, concealed=(*_JUNK_HAND, _EAST[0]))
    state = _all_junk(state, except_seat=0)

    state, events = reduce(state, Discard(tile_id=_EAST[0]))

    assert state.phase == Phase.HAND_OVER
    assert len(state.seats[1].flowers) == 7
    assert state.hand_result == HandResult(
        outcome=HandOutcome.WIN,
        winner=1,
        win_type=WinType.FLOWERS,
        discarder=None,
        faan=3,
        faan_breakdown={"七花": 3},
        points=8,
        payments={0: -4, 1: 12, 2: -4, 3: -4},
    )
    assert any(isinstance(e, FlowerReplaced) for e in events)
    assert any(isinstance(e, HandEnded) for e in events)


# --- exhaustive draw -----------------------------------------------------------------------


def test_wall_exhaustion_ends_hand_as_exhaustive_draw() -> None:
    state = _state(phase=Phase.AWAIT_ACTION, turn=0, wall=Wall(tiles=()))
    state = _with_seat(state, 0, concealed=(*_JUNK_HAND, _EAST[0]))
    state = _all_junk(state, except_seat=0)

    state, events = reduce(state, Discard(tile_id=_EAST[0]))

    assert state.phase == Phase.HAND_OVER
    assert state.hand_result == HandResult(outcome=HandOutcome.EXHAUSTIVE_DRAW)
    assert any(
        isinstance(e, HandEnded) and e.outcome == HandOutcome.EXHAUSTIVE_DRAW for e in events
    )


# --- flower cascade ---------------------------------------------------------------------------


def test_flower_drawn_mid_game_chains_to_a_replacement() -> None:
    # back of the wall: [..., real_tile, Flower]; draw_back pops Flower first, then real_tile.
    state = _state(phase=Phase.AWAIT_ACTION, turn=0, wall=Wall(tiles=(_SOU_1[0], Flower.FLOWER_1)))
    state = _with_seat(state, 0, concealed=(*_JUNK_HAND, _MAN_1[0]))
    state = _all_junk(state, except_seat=0)
    state = _with_seat(state, 2, concealed=(_MAN_1[1], _MAN_1[2], _MAN_1[3], *_JUNK_HAND[:10]))

    state, events = reduce(state, Discard(tile_id=_MAN_1[0]))
    kong_action = next(a for a in legal_actions(state, 2) if a.kind.value == "claim_kong")
    state, events = reduce(state, kong_action)

    assert _SOU_1[0] in state.seats[2].concealed
    assert Flower.FLOWER_1 in state.seats[2].flowers
    assert len(state.wall.tiles) == 0
    assert any(isinstance(e, FlowerReplaced) and e.seat == 2 for e in events)
    assert any(isinstance(e, KongReplacementDrawn) and e.seat == 2 for e in events)


# --- illegal actions --------------------------------------------------------------------------


def test_reduce_rejects_discard_of_a_tile_not_held() -> None:
    state = _state(phase=Phase.AWAIT_ACTION, turn=0)
    held = set(state.seats[0].concealed)
    not_held = next(t for t in _JUNK_HAND if t not in held)
    with pytest.raises(IllegalActionError):
        reduce(state, Discard(tile_id=not_held))


def test_reduce_rejects_declare_win_on_an_incomplete_hand() -> None:
    state = _state(phase=Phase.AWAIT_ACTION, turn=0)
    with pytest.raises(IllegalActionError):
        reduce(state, DeclareWin())  # seat 0's dealt hand isn't a winning shape


def test_reduce_rejects_claim_from_a_seat_with_no_offer() -> None:
    state = _claims_window_state()
    pass_action = Pass(window_id=state.claim_window.window_id, seat=3)  # type: ignore[union-attr]
    with pytest.raises(IllegalActionError):
        reduce(state, pass_action)


# --- start_next_hand: dealer repeat / rotation -------------------------------------------------


def _hand_over_state(
    *, dealer: int, prevailing: Wind, hand_no: int, ruleset: RuleSet, result: HandResult
) -> GameState:
    seats = tuple(SeatState(concealed=()) for _ in range(4))
    return GameState(
        ruleset=ruleset,
        game_seed=1,
        hand_seed=b"\x00" * 32,
        wall=Wall(tiles=()),
        seats=seats,  # type: ignore[arg-type]
        phase=Phase.HAND_OVER,
        turn=dealer,
        dealer=dealer,
        prevailing=prevailing,
        hand_no=hand_no,
        hand_result=result,
    )


def test_dealer_repeats_on_dealer_win() -> None:
    ruleset = RuleSet(dealer_repeat_on_win=True)
    state = _hand_over_state(
        dealer=1,
        prevailing=Wind.EAST,
        hand_no=5,
        ruleset=ruleset,
        result=HandResult(outcome=HandOutcome.WIN, winner=1),
    )
    state, events = start_next_hand(state)
    assert state.dealer == 1
    assert state.prevailing == Wind.EAST
    assert state.hand_no == 6
    assert state.phase == Phase.AWAIT_ACTION
    assert events == []


def test_dealer_passes_on_non_dealer_win() -> None:
    ruleset = RuleSet()
    state = _hand_over_state(
        dealer=1,
        prevailing=Wind.EAST,
        hand_no=5,
        ruleset=ruleset,
        result=HandResult(outcome=HandOutcome.WIN, winner=2),
    )
    state, _ = start_next_hand(state)
    assert state.dealer == 2
    assert state.hand_no == 6


def test_dealer_repeats_on_draw_when_configured() -> None:
    ruleset = RuleSet(dealer_repeat_on_draw=True)
    state = _hand_over_state(
        dealer=3,
        prevailing=Wind.EAST,
        hand_no=8,
        ruleset=ruleset,
        result=HandResult(outcome=HandOutcome.EXHAUSTIVE_DRAW),
    )
    state, _ = start_next_hand(state)
    assert state.dealer == 3
    assert state.hand_no == 9


def test_start_next_hand_requires_hand_over_phase() -> None:
    state = _state(phase=Phase.AWAIT_ACTION, turn=0)
    with pytest.raises(IllegalActionError):
        start_next_hand(state)


# --- hang-safety invariant: GAME_OVER is reached in a bounded number of hands ------------------


def _force_hand_over(state: GameState, result: HandResult) -> GameState:
    return dataclasses.replace(state, phase=Phase.HAND_OVER, claim_window=None, hand_result=result)


@pytest.mark.parametrize(
    "game_length,expected_hands",
    [(GameLength.EAST_ONLY, 4), (GameLength.EAST_SOUTH, 8), (GameLength.FULL, 16)],
)
def test_game_over_reached_in_bounded_hands_with_no_repeats(
    game_length: GameLength, expected_hands: int
) -> None:
    """Never-repeating dealer (every hand a non-dealer exhaustive draw, repeat-on-draw off):
    the dealer rotation is forced to advance every single hand, so this directly measures the
    rotation math's bound. A hard iteration cap well above `expected_hands` turns any bug that
    makes this loop forever into a fast, clear assertion failure instead of a hang."""
    ruleset = RuleSet(
        game_length=game_length, dealer_repeat_on_draw=False, dealer_repeat_on_win=False
    )
    state = _hand_over_state(
        dealer=0,
        prevailing=Wind.EAST,
        hand_no=1,
        ruleset=ruleset,
        result=HandResult(outcome=HandOutcome.EXHAUSTIVE_DRAW),
    )

    hands_played = 0
    for _ in range(expected_hands + 10):
        state, _ = start_next_hand(state)
        hands_played += 1
        if state.phase == Phase.GAME_OVER:
            # hand_no is left at the last hand actually played, not incremented past it.
            assert state.hand_no == hands_played
            break
        # a hand was dealt: hand_no advanced to the new (not-yet-played) hand number.
        assert state.hand_no == hands_played + 1
        state = _force_hand_over(state, HandResult(outcome=HandOutcome.EXHAUSTIVE_DRAW))

    assert state.phase == Phase.GAME_OVER
    assert hands_played == expected_hands


def test_game_over_state_carries_scores_event() -> None:
    ruleset = RuleSet(game_length=GameLength.EAST_ONLY, dealer_repeat_on_draw=False)
    state = _hand_over_state(
        dealer=3,
        prevailing=Wind.EAST,
        hand_no=4,
        ruleset=ruleset,
        result=HandResult(outcome=HandOutcome.EXHAUSTIVE_DRAW),
    )
    state, events = start_next_hand(state)
    assert state.phase == Phase.GAME_OVER
    assert events == [GameEnded(hand_no=4, scores=(0, 0, 0, 0))]


# --- self-play smoke test ----------------------------------------------------------------------


def _play_one_game(seed: int, ruleset: RuleSet, step_cap: int) -> None:
    rng = random.Random(seed)
    state = new_game(ruleset, seed)
    total = TOTAL_PHYSICAL_TILES if ruleset.flowers_enabled else 136
    assert _total_tiles(state) == total

    steps = 0
    while state.phase != Phase.GAME_OVER:
        steps += 1
        assert steps < step_cap, (
            f"seed={seed}: exceeded {step_cap} steps -- possible infinite loop in reduce()"
        )

        if state.phase == Phase.HAND_OVER:
            state, _ = start_next_hand(state)
            assert _total_tiles(state) == total
            continue

        if state.phase in (Phase.AWAIT_CLAIMS, Phase.AWAIT_KONG_ROB):
            assert state.claim_window is not None
            pending = [
                o.seat
                for o in state.claim_window.offers
                if o.seat not in state.claim_window.responses
            ]
            seat = rng.choice(pending)
        else:
            seat = state.turn

        actions = legal_actions(state, seat)
        assert actions, f"seed={seed}: no legal actions for seat {seat} in {state.phase}"
        action = rng.choice(actions)
        state, _ = reduce(state, action)
        assert _total_tiles(state) == total


@pytest.mark.slow
def test_selfplay_50_games_terminate_and_conserve_tiles() -> None:
    # dealer never repeats: keeps EAST_ONLY deterministically bounded at exactly 4 hands/game,
    # so a real hang shows up fast against the step cap rather than a long-but-legitimate game
    # muddying the signal (dealer-repeat's own boundedness is covered separately, above).
    ruleset = RuleSet(dealer_repeat_on_win=False, dealer_repeat_on_draw=False)
    for seed in range(50):
        _play_one_game(seed, ruleset, step_cap=3000)
