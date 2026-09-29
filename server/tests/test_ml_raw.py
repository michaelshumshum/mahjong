"""Unit tests for `ml/raw.py` -- entitlement-safe values read off a `SeatView`. Pure Python, so
no `importorskip`."""

from __future__ import annotations

from app.views import SeatView
from mahjong_core.config import RuleSet
from mahjong_core.melds import Meld, MeldKind
from mahjong_core.state import Phase, Wind
from mahjong_core.tiles import TileType, tile_ids_for_type
from ml.raw import concealed_kong_counts, visible_meld_counts34


def _view(seat: int, melds: tuple[tuple[Meld, ...], ...]) -> SeatView:
    return SeatView(
        seat=seat,
        hand_no=1,
        prevailing=Wind.EAST,
        dealer=0,
        turn=seat,
        phase=Phase.AWAIT_ACTION,
        own_hand=(),
        concealed_counts=(0, 0, 0, 0),
        melds=melds,
        discard_pools=((), (), (), ()),
        flowers=((), (), (), ()),
        wall_remaining=50,
        seat_status=("connected",) * 4,
        names=(None,) * 4,
        scores=(0, 0, 0, 0),
        legal_actions=(),
        claim_options=(),
        deadline_ts=None,
        host_seat=None,
        ruleset=RuleSet(),
        hands=None,
    )


def _concealed_kong(t: TileType) -> Meld:
    return Meld(kind=MeldKind.CONCEALED_KONG, tiles=tile_ids_for_type(t))


def test_another_seats_concealed_kong_is_hidden_but_own_and_exposed_are_kept() -> None:
    exposed = Meld(
        kind=MeldKind.EXPOSED_KONG, tiles=tile_ids_for_type(TileType.WIND_EAST), from_seat=0
    )
    kong = _concealed_kong(TileType.DRAGON_RED)
    view = _view(0, ((kong,), (kong, exposed), (), ()))

    assert visible_meld_counts34(view, 0)[int(TileType.DRAGON_RED)] == 3
    hidden = visible_meld_counts34(view, 1)
    assert hidden[int(TileType.DRAGON_RED)] == 0
    assert hidden[int(TileType.WIND_EAST)] == 3


def test_concealed_kong_counts_are_public_per_absolute_seat() -> None:
    kong = _concealed_kong(TileType.DRAGON_RED)
    view = _view(2, ((kong,), (kong, kong), (), ()))
    assert concealed_kong_counts(view) == [1, 2, 0, 0]
