"""Golden fixtures for mahjong_core/scoring/faan.py (docs/testing.md §1).

`test_scoring.py` covers each `Pattern` detector in isolation via `score_hand`; this file
covers what only `score_winning_hand` does on top of that: decomposition maximisation,
`hand_sets` filtering, `faan_overrides`, limit-hand non-stacking, the `faan_cap` clamp,
Chicken Hand, and the `min_faan` gate. Every fixture here is a real, physically legal 14-tile
hand (verified against `melds.decompose` directly while authoring these, not hand-picked
faan numbers) -- see docs/rules.md §11 edge case 9, the reason decomposition
maximisation exists at all.
"""

from __future__ import annotations

from mahjong_core.config import HandSet, RuleSet
from mahjong_core.melds import Meld, MeldKind
from mahjong_core.scoring.faan import CHICKEN_HAND_NAME, FaanResult, score_winning_hand
from mahjong_core.scoring.patterns import ScoringContext
from mahjong_core.state import Wind
from mahjong_core.tiles import Flower, TileId, TileType, tile_ids_for_type


def _tiles(*types: TileType) -> tuple[TileId, ...]:
    """One concealed hand as tile ids, one copy of each `TileType` given, in order --
    duplicates draw a fresh physical tile each time (up to 4 copies per type)."""
    seen: dict[TileType, int] = {}
    ids = []
    for t in types:
        n = seen.get(t, 0)
        ids.append(tile_ids_for_type(t)[n])
        seen[t] = n + 1
    return tuple(ids)


def _pung(tile_type: TileType, from_seat: int | None = None) -> Meld:
    return Meld(MeldKind.PUNG, tile_ids_for_type(tile_type)[:3], from_seat=from_seat)


def _ctx(
    *,
    seat_wind: Wind = Wind.SOUTH,
    prevailing_wind: Wind = Wind.SOUTH,
    self_drawn: bool = False,
    flowers: tuple[Flower, ...] = (),
    won_before_any_discard: bool = False,
    is_last_tile: bool = False,
    is_kong_replacement: bool = False,
) -> ScoringContext:
    return ScoringContext(
        seat_wind=seat_wind,
        prevailing_wind=prevailing_wind,
        self_drawn=self_drawn,
        flowers=flowers,
        won_before_any_discard=won_before_any_discard,
        is_last_tile=is_last_tile,
        is_kong_replacement=is_kong_replacement,
    )


# --- Decomposition maximisation --------------------------------------------------------------


def test_seven_pairs_vs_standard_decomposition_maximizes() -> None:
    """rules.md §11.9, specifically for Seven Pairs (the collision the edge case names):
    11223344556677m parses both as 七對子 (7 distinct pairs, `decompose()`'s empty-tuple raw
    shape -- patterns.py's "Raw-hand access" note) and as a standard hand (123m 123m 456m 456m
    77m, a real `decompose()` split -- 平糊 too, since every group is a chow). The standard
    parse scores far higher here (清一色 alone outvalues 七對子), so maximization must pick it
    over the raw-shape candidate. Also proves the fix for a real bug the audit found: 七對子
    must NOT also leak onto the winning standard-decomposition candidate just because the raw
    14 tiles separately happen to satisfy the seven-pairs shape too (see
    `patterns._detect_seven_pairs`'s docstring) -- `七對子` must be entirely absent below, not
    just outweighed."""
    tiles = _tiles(
        TileType.MAN_1,
        TileType.MAN_1,
        TileType.MAN_2,
        TileType.MAN_2,
        TileType.MAN_3,
        TileType.MAN_3,
        TileType.MAN_4,
        TileType.MAN_4,
        TileType.MAN_5,
        TileType.MAN_5,
        TileType.MAN_6,
        TileType.MAN_6,
        TileType.MAN_7,
        TileType.MAN_7,
    )
    ctx = _ctx()
    ruleset = RuleSet(faan_cap=13, min_faan=0)
    result = score_winning_hand(tiles, (), ctx, ruleset)
    assert result == FaanResult(
        total_faan=11,
        breakdown={"平糊": 1, "清一色": 6, "一般高": 2, "無花": 1, "門前清": 1},
        clears_min_faan=True,
    )
    assert "七對子" not in result.breakdown


def test_maximizes_across_decompositions() -> None:
    """111p 222p 333p 444p 99s parses two ways: four pungs (對對糊 + 三暗刻, 9 total with
    缺一門), or 123p x3 chows + 444p pung (三般高, 10 total with 缺一門) -- rules.md
    §11 edge case 9. The chow parse scores higher; maximisation must pick it, not whichever
    `decompose()` happens to list first."""
    tiles = _tiles(
        TileType.PIN_1,
        TileType.PIN_1,
        TileType.PIN_1,
        TileType.PIN_2,
        TileType.PIN_2,
        TileType.PIN_2,
        TileType.PIN_3,
        TileType.PIN_3,
        TileType.PIN_3,
        TileType.PIN_4,
        TileType.PIN_4,
        TileType.PIN_4,
        TileType.SOU_9,
        TileType.SOU_9,
    )
    ctx = _ctx()
    ruleset = RuleSet(faan_cap=10, min_faan=0)
    result = score_winning_hand(tiles, (), ctx, ruleset)
    assert result == FaanResult(
        total_faan=10,
        breakdown={"缺一門": 2, "無花": 1, "門前清": 1, "三般高": 6},
        clears_min_faan=True,
    )


# --- Limit shape vs. standard decomposition, and limit non-stacking ---------------------------


def _nine_gates_tiles(extra_rank: int) -> tuple[TileId, ...]:
    counts = [3, 1, 1, 1, 1, 1, 1, 1, 3]
    counts[extra_rank] += 1
    types = [
        TileType(int(TileType.PIN_1) + rank) for rank, n in enumerate(counts) for _ in range(n)
    ]
    return _tiles(*types)


def test_limit_shape_vs_standard_decomposition_picks_the_limit() -> None:
    """1112345678999p + 5p is both a valid standard decomposition (清一色 + 無花 + 門前清 =
    8) and 九蓮寶燈 (limit). Limit hands don't stack with anything (rules.md §7
    "Stacking and caps") -- the winning candidate must show only the limit pattern, at
    `faan_cap`, not `patterns.py`'s `LIMIT_FAAN` placeholder and not summed with the classic
    patterns that also matched the same tiles."""
    tiles = _nine_gates_tiles(extra_rank=4)
    ctx = _ctx()
    ruleset = RuleSet(faan_cap=13, min_faan=0)
    result = score_winning_hand(tiles, (), ctx, ruleset)
    assert result == FaanResult(total_faan=13, breakdown={"九蓮寶燈": 13}, clears_min_faan=True)


def test_limit_shape_resolves_against_the_actual_faan_cap_not_the_placeholder() -> None:
    """Same hand, `faan_cap=10` -- proves the award tracks `ruleset.faan_cap`, not a value
    baked into the pattern."""
    tiles = _nine_gates_tiles(extra_rank=4)
    ctx = _ctx()
    ruleset = RuleSet(faan_cap=10, min_faan=0)
    result = score_winning_hand(tiles, (), ctx, ruleset)
    assert result.total_faan == 10
    assert result.breakdown == {"九蓮寶燈": 10}


def test_two_simultaneous_limit_patterns_collapse_to_one() -> None:
    """A dealer completing Thirteen Orphans before any discard qualifies for both 十三么 and
    天糊 at once. §7: "If a hand qualifies for more than one limit hand, take the highest, not
    the sum" -- the breakdown must carry exactly one limit entry."""
    orphan_types = [
        TileType.MAN_1,
        TileType.MAN_9,
        TileType.PIN_1,
        TileType.PIN_9,
        TileType.SOU_1,
        TileType.SOU_9,
        TileType.WIND_EAST,
        TileType.WIND_SOUTH,
        TileType.WIND_WEST,
        TileType.WIND_NORTH,
        TileType.DRAGON_RED,
        TileType.DRAGON_GREEN,
        TileType.DRAGON_WHITE,
    ]
    tiles = _tiles(*orphan_types, TileType.MAN_1)
    ctx = _ctx(
        seat_wind=Wind.EAST, prevailing_wind=Wind.EAST, self_drawn=True, won_before_any_discard=True
    )
    ruleset = RuleSet(faan_cap=13, min_faan=0)
    result = score_winning_hand(tiles, (), ctx, ruleset)
    assert len(result.breakdown) == 1
    assert result.total_faan == 13


# --- faan_cap clamp (non-limit) ----------------------------------------------------------------


def test_faan_cap_clamps_a_hand_that_exceeds_it() -> None:
    """111p 333p 555p 777p 99p, self-drawn: 對對糊(3) + 清一色(6) + 三暗刻(2) + 自摸(1) +
    無花(1) = 13 raw, clamped to the default `faan_cap` of 10."""
    tiles = _tiles(
        TileType.PIN_1,
        TileType.PIN_1,
        TileType.PIN_1,
        TileType.PIN_3,
        TileType.PIN_3,
        TileType.PIN_3,
        TileType.PIN_5,
        TileType.PIN_5,
        TileType.PIN_5,
        TileType.PIN_7,
        TileType.PIN_7,
        TileType.PIN_7,
        TileType.PIN_9,
        TileType.PIN_9,
    )
    ctx = _ctx(seat_wind=Wind.WEST, prevailing_wind=Wind.WEST, self_drawn=True)
    ruleset = RuleSet(faan_cap=10, min_faan=0)
    result = score_winning_hand(tiles, (), ctx, ruleset)
    assert sum(result.breakdown.values()) == 13  # raw breakdown stays uncapped, for display
    assert result.total_faan == 10  # the clamped value a payout calculation uses
    assert result.clears_min_faan is True


# --- min_faan gate -------------------------------------------------------------------------


def test_hand_below_min_faan_does_not_clear_the_gate() -> None:
    """234m 567p 345s 111m 99s, win on discard with an open meld elsewhere in the hand only
    conceptually -- here it's simply not self-drawn and has no open meld, three suits used (no
    缺一門), one pung breaks 平糊: only 無花(1) + 門前清(1) = 2, below the default
    `min_faan` of 3."""
    tiles = _tiles(
        TileType.MAN_2,
        TileType.MAN_3,
        TileType.MAN_4,
        TileType.PIN_5,
        TileType.PIN_6,
        TileType.PIN_7,
        TileType.SOU_3,
        TileType.SOU_4,
        TileType.SOU_5,
        TileType.MAN_1,
        TileType.MAN_1,
        TileType.MAN_1,
        TileType.SOU_9,
        TileType.SOU_9,
    )
    ctx = _ctx(seat_wind=Wind.WEST, prevailing_wind=Wind.EAST, self_drawn=False)
    ruleset = RuleSet()  # default min_faan=3
    result = score_winning_hand(tiles, (), ctx, ruleset)
    assert result.total_faan == 2
    assert result.clears_min_faan is False


# --- hand_sets filtering ---------------------------------------------------------------------


def test_hand_sets_disabled_pattern_contributes_nothing() -> None:
    """Seven Pairs (七對子) is `NEW_18` -- disabling that hand_set must drop it entirely, not
    just cap it, leaving only the `CLASSIC` context patterns (自摸/無花) behind."""
    tiles = _tiles(
        TileType.MAN_1,
        TileType.MAN_1,
        TileType.PIN_5,
        TileType.PIN_5,
        TileType.SOU_9,
        TileType.SOU_9,
        TileType.WIND_EAST,
        TileType.WIND_EAST,
        TileType.DRAGON_RED,
        TileType.DRAGON_RED,
        TileType.MAN_3,
        TileType.MAN_3,
        TileType.PIN_7,
        TileType.PIN_7,
    )
    ctx = _ctx(self_drawn=True)
    with_new_18 = RuleSet(hand_sets=frozenset({HandSet.CLASSIC, HandSet.NEW_18}))
    without_new_18 = RuleSet(hand_sets=frozenset({HandSet.CLASSIC}))

    enabled = score_winning_hand(tiles, (), ctx, with_new_18)
    disabled = score_winning_hand(tiles, (), ctx, without_new_18)

    assert enabled.breakdown == {"無花": 1, "自摸": 1, "七對子": 4}
    assert disabled.breakdown == {"無花": 1, "自摸": 1}
    assert "七對子" not in disabled.breakdown


def test_faan_overrides_replace_a_patterns_value() -> None:
    """`RuleSet.faan_overrides` (config.py): a per-pattern value swap applied at this layer,
    after `hand_sets` selection. `0` disables a pattern the same way an unmatched `hand_set`
    does; any other value replaces its per-occurrence faan."""
    tiles = _tiles(
        TileType.MAN_1,
        TileType.MAN_1,
        TileType.PIN_5,
        TileType.PIN_5,
        TileType.SOU_9,
        TileType.SOU_9,
        TileType.WIND_EAST,
        TileType.WIND_EAST,
        TileType.DRAGON_RED,
        TileType.DRAGON_RED,
        TileType.MAN_3,
        TileType.MAN_3,
        TileType.PIN_7,
        TileType.PIN_7,
    )
    ctx = _ctx(self_drawn=True)
    overridden = RuleSet(faan_overrides={"七對子": 8})
    disabled = RuleSet(faan_overrides={"七對子": 0})

    assert score_winning_hand(tiles, (), ctx, overridden).breakdown["七對子"] == 8
    assert "七對子" not in score_winning_hand(tiles, (), ctx, disabled).breakdown


# --- Chicken Hand (雞糊) -----------------------------------------------------------------------


def test_genuine_chicken_hand() -> None:
    """234m 345s 678p (open, claimed) 99m: three suits (no 缺一門), one open meld (no 自摸,
    no 門前清), a flower held that doesn't match the seat (no 無花, no 座位花), no wind/dragon
    pung. `score_hand` matches nothing at all on this hand -- only reachable at `min_faan ==
    0` (§7 note ¹), where Chicken Hand's floor faan applies."""
    open_pung = Meld(MeldKind.PUNG, tile_ids_for_type(TileType.PIN_2)[:3], from_seat=2)
    concealed = _tiles(
        TileType.MAN_2,
        TileType.MAN_3,
        TileType.MAN_4,
        TileType.SOU_3,
        TileType.SOU_4,
        TileType.SOU_5,
        TileType.PIN_6,
        TileType.PIN_7,
        TileType.PIN_8,
        TileType.MAN_9,
        TileType.MAN_9,
    )
    ctx = _ctx(
        seat_wind=Wind.SOUTH,
        prevailing_wind=Wind.SOUTH,
        self_drawn=False,
        flowers=(Flower.FLOWER_1,),
    )
    ruleset = RuleSet(min_faan=0)
    result = score_winning_hand(concealed, (open_pung,), ctx, ruleset)
    assert result == FaanResult(
        total_faan=1, breakdown={CHICKEN_HAND_NAME: 1}, clears_min_faan=True
    )


def test_chicken_hand_does_not_apply_above_min_faan_zero() -> None:
    """The same zero-faan hand at `min_faan >= 1`: Chicken Hand must not fire (§7 note ¹ --
    "servers should skip evaluating this pattern entirely when min_faan >= 1"), and the hand
    correctly fails to clear the gate instead."""
    open_pung = Meld(MeldKind.PUNG, tile_ids_for_type(TileType.PIN_2)[:3], from_seat=2)
    concealed = _tiles(
        TileType.MAN_2,
        TileType.MAN_3,
        TileType.MAN_4,
        TileType.SOU_3,
        TileType.SOU_4,
        TileType.SOU_5,
        TileType.PIN_6,
        TileType.PIN_7,
        TileType.PIN_8,
        TileType.MAN_9,
        TileType.MAN_9,
    )
    ctx = _ctx(
        seat_wind=Wind.SOUTH,
        prevailing_wind=Wind.SOUTH,
        self_drawn=False,
        flowers=(Flower.FLOWER_1,),
    )
    ruleset = RuleSet(min_faan=1)
    result = score_winning_hand(concealed, (open_pung,), ctx, ruleset)
    assert result == FaanResult(total_faan=0, breakdown={}, clears_min_faan=False)


def test_chicken_hand_gated_by_new_6_hand_set() -> None:
    """Chicken Hand is tabled under New 6 (§7) -- disabling that `hand_set` must suppress it
    even at `min_faan == 0`, same as every other New 6 pattern."""
    open_pung = Meld(MeldKind.PUNG, tile_ids_for_type(TileType.PIN_2)[:3], from_seat=2)
    concealed = _tiles(
        TileType.MAN_2,
        TileType.MAN_3,
        TileType.MAN_4,
        TileType.SOU_3,
        TileType.SOU_4,
        TileType.SOU_5,
        TileType.PIN_6,
        TileType.PIN_7,
        TileType.PIN_8,
        TileType.MAN_9,
        TileType.MAN_9,
    )
    ctx = _ctx(
        seat_wind=Wind.SOUTH,
        prevailing_wind=Wind.SOUTH,
        self_drawn=False,
        flowers=(Flower.FLOWER_1,),
    )
    ruleset = RuleSet(min_faan=0, hand_sets=frozenset({HandSet.CLASSIC, HandSet.NEW_18}))
    result = score_winning_hand(concealed, (open_pung,), ctx, ruleset)
    assert result == FaanResult(total_faan=0, breakdown={}, clears_min_faan=True)


# --- Stacking rules that survive end-to-end through score_winning_hand ------------------------


def test_kong_replacement_last_tile_exclusion_survives_maximization() -> None:
    """rules.md §7 note ³: a kong replacement that's also the wall's last tile scores
    as 槓上開花 only, never also 海底撈月 -- `patterns.py`'s detectors already enforce this;
    this proves `score_winning_hand`'s maximisation/candidate scoring doesn't reintroduce
    double-counting across candidates."""
    tiles = _tiles(
        TileType.MAN_1,
        TileType.MAN_2,
        TileType.MAN_3,
        TileType.PIN_4,
        TileType.PIN_5,
        TileType.PIN_6,
        TileType.SOU_2,
        TileType.SOU_3,
        TileType.SOU_4,
        TileType.MAN_7,
        TileType.MAN_8,
        TileType.MAN_9,
        TileType.DRAGON_GREEN,
        TileType.DRAGON_GREEN,
    )
    ctx = _ctx(self_drawn=True, is_last_tile=True, is_kong_replacement=True)
    ruleset = RuleSet(faan_cap=13, min_faan=0)
    result = score_winning_hand(tiles, (), ctx, ruleset)
    assert result.breakdown.get("槓上開花") == 1
    assert "海底撈月" not in result.breakdown
