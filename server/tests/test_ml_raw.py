"""Unit tests for `ml/raw.py` -- entitlement-safe values read off a `SeatView`. Pure Python, so
no `importorskip`."""

from __future__ import annotations

from app.views import SeatView
from mahjong_core.config import RuleSet
from mahjong_core.melds import Meld, MeldKind
from mahjong_core.state import Phase, Wind
from mahjong_core.tiles import Flower, TileId, TileType, tile_ids_for_type
from ml.raw import concealed_kong_counts, raw_row, relative_seats, visible_meld_counts34


def _view(
    seat: int,
    melds: tuple[tuple[Meld, ...], ...],
    discard_pools: tuple[tuple[TileId, ...], ...] = ((), (), (), ()),
    flowers: tuple[tuple[Flower, ...], ...] = ((), (), (), ()),
) -> SeatView:
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
        discard_pools=discard_pools,
        flowers=flowers,
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


def test_every_seats_concealed_kong_is_counted_like_any_meld() -> None:
    exposed = Meld(
        kind=MeldKind.EXPOSED_KONG, tiles=tile_ids_for_type(TileType.WIND_EAST), from_seat=0
    )
    kong = _concealed_kong(TileType.DRAGON_RED)
    view = _view(0, ((kong,), (kong, exposed), (), ()))

    assert visible_meld_counts34(view, 0)[int(TileType.DRAGON_RED)] == 3
    other = visible_meld_counts34(view, 1)
    assert other[int(TileType.DRAGON_RED)] == 3
    assert other[int(TileType.WIND_EAST)] == 3


def test_concealed_kong_counts_are_public_per_absolute_seat() -> None:
    kong = _concealed_kong(TileType.DRAGON_RED)
    view = _view(2, ((kong,), (kong, kong), (), ()))
    assert concealed_kong_counts(view) == [1, 2, 0, 0]


def test_relative_seats_puts_self_first() -> None:
    assert relative_seats(2) == (2, 3, 0, 1)


def test_raw_row_keeps_discard_order_flower_counts_and_relative_seat_order() -> None:
    def tid(t: TileType, n: int = 0) -> TileId:
        return tile_ids_for_type(t)[n]

    pools = (
        (),
        (tid(TileType.MAN_9), tid(TileType.MAN_1), tid(TileType.MAN_9, 1)),
        (),
        (tid(TileType.PIN_5),),
    )
    kong = _concealed_kong(TileType.DRAGON_RED)
    view = _view(
        1,
        ((), (kong,), (kong,), ()),
        discard_pools=pools,
        flowers=((Flower.FLOWER_1,), (), (Flower.SEASON_1, Flower.SEASON_2), ()),
    )
    row = raw_row(view)

    # seat 1 -> relative order (1, 2, 3, 0)
    assert row["discard_seq"] == [
        [int(TileType.MAN_9), int(TileType.MAN_1), int(TileType.MAN_9)],
        [],
        [int(TileType.PIN_5)],
        [],
    ]
    assert row["flowers"] == [0, 2, 0, 1]
    assert row["concealed_kongs"] == [1, 1, 0, 0]
    assert row["meld_counts"][1][int(TileType.DRAGON_RED)] == 3  # seat 2's concealed kong
    assert row["meld_counts"][0][int(TileType.DRAGON_RED)] == 3
    assert row["dealer_idx"] == 3  # dealer is absolute seat 0
