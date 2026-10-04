"""`engine.new_hand` / `prevailing_winds`: a first hand dealt with any dealer and reachable
prevailing wind (docs/ml.md §7)."""

from __future__ import annotations

import pytest

from mahjong_core.config import GameLength, RuleSet
from mahjong_core.engine import new_game, new_hand, prevailing_winds
from mahjong_core.state import Phase, Wind

_R = RuleSet()


def test_seat_zero_east_matches_new_game() -> None:
    assert new_hand(_R, 11, dealer=0, prevailing=Wind.EAST) == new_game(_R, 11)


@pytest.mark.parametrize("dealer", range(4))
def test_dealer_holds_fourteen_and_acts_first(dealer: int) -> None:
    state = new_hand(_R, 11, dealer=dealer, prevailing=Wind.EAST)
    assert state.dealer == state.turn == dealer
    assert state.phase == Phase.AWAIT_ACTION and state.hand_no == 1
    sizes = [len(s.concealed) + 3 * len(s.melds) for s in state.seats]
    assert sizes == [14 if i == dealer else 13 for i in range(4)]
    assert all(s.score == 0 for s in state.seats)


def test_prevailing_winds_follow_game_length() -> None:
    assert prevailing_winds(RuleSet(game_length=GameLength.EAST_ONLY)) == (Wind.EAST,)
    assert prevailing_winds(RuleSet(game_length=GameLength.FULL)) == tuple(Wind)


def test_unreachable_prevailing_or_bad_dealer_raises() -> None:
    east_only = RuleSet(game_length=GameLength.EAST_ONLY)
    with pytest.raises(ValueError):
        new_hand(east_only, 1, dealer=0, prevailing=Wind.SOUTH)
    with pytest.raises(ValueError):
        new_hand(_R, 1, dealer=4, prevailing=Wind.EAST)


def test_non_east_prevailing_is_carried() -> None:
    full = RuleSet(game_length=GameLength.FULL)
    state = new_hand(full, 3, dealer=1, prevailing=Wind.WEST)
    assert state.prevailing == Wind.WEST and state.dealer == 1
