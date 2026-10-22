import pytest

from mahjong_core.config import RuleSet
from mahjong_core.hand_check import HandCheck, check_hand
from mahjong_core.presets import RULESET_PRESETS
from mahjong_core.state import Wind
from mahjong_core.tiles import Flower, TileType, parse_tile

CLASSIC = RULESET_PRESETS["hk_classic"]
CASUAL = RULESET_PRESETS["hk_casual"]


def _tiles(codes: str) -> list[TileType]:
    tiles = [parse_tile(codes[i : i + 2]) for i in range(0, len(codes), 2)]
    return [t for t in tiles if isinstance(t, TileType)]


def _check(
    codes: str,
    *,
    self_drawn: bool = False,
    flowers: tuple[Flower, ...] = (),
    ruleset: RuleSet = CLASSIC,
) -> HandCheck:
    return check_hand(
        _tiles(codes),
        flowers,
        self_drawn=self_drawn,
        seat_wind=Wind.EAST,
        prevailing_wind=Wind.SOUTH,
        ruleset=ruleset,
    )


def _breakdown(codes: str, **kwargs: object) -> dict[str, int]:
    checked = _check(codes, **kwargs)  # type: ignore[arg-type]
    assert checked.result is not None
    return checked.result.breakdown


def test_scores_a_full_flush_with_points() -> None:
    checked = _check("1s2s3s4s5s6s7s8s9s2s2s2s5s5s")
    assert checked.winning
    assert checked.result is not None
    assert checked.result.breakdown == {"清一色": 7, "無花": 1, "門前清": 1}
    assert checked.result.total_faan == 9
    assert checked.points == 96  # half spicy


def test_a_broken_shape_is_not_a_win() -> None:
    checked = _check("1m2m4m5p6p7p7s8s9s2s3s4s8m9m")
    assert not checked.winning
    assert checked.result is None
    assert checked.points is None


def test_last_tile_off_a_discard_opens_its_pung() -> None:
    hand = "2m2m2m5p5p5p8s8s8s4m4mz5z5z5"
    assert "四暗刻" not in _breakdown(hand)
    assert "四暗刻" in _breakdown(hand, self_drawn=True)


def test_seat_flower_and_self_draw_score() -> None:
    breakdown = _breakdown("1m2m3m4p5p6p7p8p9p2s3s4sz1z1", self_drawn=True, flowers=(Flower(0),))
    assert breakdown.get("正花") == 1
    assert breakdown.get("自摸") == 1
    assert "無花" not in breakdown


def test_flowers_are_ignored_with_flowers_off() -> None:
    no_flowers = RuleSet.from_dict({**CLASSIC.to_dict(), "flowers_enabled": False})
    breakdown = _breakdown("1m2m3m4p5p6p7p8p9p2s3s4sz1z1", flowers=(Flower(0),), ruleset=no_flowers)
    assert "正花" not in breakdown
    assert "無花" in breakdown


def test_seven_pairs_wins_only_where_it_scores() -> None:
    hand = "2m2m5m5m3p3p8p8p1s1s6s6sz6z6"
    assert not _check(hand).winning
    assert "七對子" in _breakdown(hand, ruleset=CASUAL)


@pytest.mark.parametrize(
    ("codes", "flowers"),
    [
        ("1m1m1m1m1m2m3m4p5p6p7s8s9sz1", ()),  # a fifth 1m
        ("1m2m3m4p5p6p7s8s9sz1z1z1z2", ()),  # 13 tiles
        ("1m2m3m4p5p6p7s8s9sz1z1z1z2z2", (Flower(0), Flower(0))),
    ],
)
def test_rejects_hands_no_deal_can_produce(codes: str, flowers: tuple[Flower, ...]) -> None:
    with pytest.raises(ValueError):
        _check(codes, flowers=flowers)
