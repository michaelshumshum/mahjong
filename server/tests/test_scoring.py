"""Golden fixtures for mahjong_core/scoring/patterns.py (docs/testing.md §1: "Golden
fixtures, one per faan pattern plus combinations"). Fixtures are (hand melds, context) ->
expected faan at the `score_hand`/detector layer -- `faan.py`'s decomposition-maximisation,
`min_faan` gate, caps, and `payout.py`'s points/payments (docs/rules.md §8) don't exist
yet (see the M2 sub-task breakdown), so there's no ruleset/payments axis to fixture here yet;
that's the shape a later sub-task's golden suite adds.
"""

from __future__ import annotations

import pytest

from mahjong_core.actions import _is_seven_pairs as _actions_is_seven_pairs
from mahjong_core.actions import _is_thirteen_orphans as _actions_is_thirteen_orphans
from mahjong_core.config import HandSet
from mahjong_core.melds import Meld, MeldKind
from mahjong_core.scoring.patterns import (
    LIMIT_FAAN,
    PATTERNS,
    ScoringContext,
    score_hand,
    seat_wind_for,
)
from mahjong_core.state import Wind
from mahjong_core.tiles import Flower, TileId, TileType, tile_ids_for_type


def _chow(low: TileType, from_seat: int | None = None) -> Meld:
    ids = tuple(tile_ids_for_type(TileType(int(low) + k))[0] for k in range(3))
    return Meld(MeldKind.CHOW, ids, from_seat=from_seat)


def _pung(tile_type: TileType, from_seat: int | None = None) -> Meld:
    return Meld(MeldKind.PUNG, tile_ids_for_type(tile_type)[:3], from_seat=from_seat)


def _kong(tile_type: TileType, from_seat: int | None = None) -> Meld:
    return Meld(MeldKind.EXPOSED_KONG, tile_ids_for_type(tile_type), from_seat=from_seat)


def _concealed_kong(tile_type: TileType) -> Meld:
    return Meld(MeldKind.CONCEALED_KONG, tile_ids_for_type(tile_type))


def _pair(tile_type: TileType) -> Meld:
    return Meld(MeldKind.PAIR, tile_ids_for_type(tile_type)[:2])


def _ctx(
    *,
    seat_wind: Wind = Wind.SOUTH,
    prevailing_wind: Wind = Wind.SOUTH,
    self_drawn: bool = False,
    flowers: tuple[Flower, ...] = (),
    concealed_tiles: tuple[TileId, ...] = (),
    won_before_any_discard: bool = False,
    won_on_dealer_first_discard: bool = False,
    is_last_tile: bool = False,
    is_kong_replacement: bool = False,
    is_robbing_kong: bool = False,
    flowers_score: bool = True,
) -> ScoringContext:
    return ScoringContext(
        seat_wind=seat_wind,
        prevailing_wind=prevailing_wind,
        self_drawn=self_drawn,
        flowers=flowers,
        concealed_tiles=concealed_tiles,
        won_before_any_discard=won_before_any_discard,
        won_on_dealer_first_discard=won_on_dealer_first_discard,
        is_last_tile=is_last_tile,
        is_kong_replacement=is_kong_replacement,
        is_robbing_kong=is_robbing_kong,
        flowers_score=flowers_score,
    )


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


def _occurrences(name: str, hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    pattern = next(p for p in PATTERNS if p.name == name)
    return pattern.detect(hand, ctx)


# --- seat_wind_for -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("seat", "dealer", "expected"),
    [
        (0, 0, Wind.EAST),
        (1, 0, Wind.SOUTH),
        (2, 0, Wind.WEST),
        (3, 0, Wind.NORTH),
        (0, 2, Wind.WEST),  # dealer at seat 2 -> seat 0 is two seats behind -> West wind
        (2, 2, Wind.EAST),  # the dealer is always East for their own deal
    ],
)
def test_seat_wind_for(seat: int, dealer: int, expected: Wind) -> None:
    assert seat_wind_for(seat, dealer) == expected


@pytest.mark.parametrize("bad", [-1, 4])
def test_seat_wind_for_rejects_bad_seat(bad: int) -> None:
    with pytest.raises(ValueError):
        seat_wind_for(bad, 0)


# --- All Sequences (平糊) -------------------------------------------------------------------


def test_all_sequences() -> None:
    hand = (
        _chow(TileType.MAN_1),
        _chow(TileType.MAN_5),
        _chow(TileType.PIN_2),
        _chow(TileType.SOU_7),
        _pair(TileType.DRAGON_GREEN),
    )
    assert _occurrences("平糊", hand, _ctx()) == 1


def test_all_sequences_false_with_one_pung() -> None:
    hand = (
        _chow(TileType.MAN_1),
        _chow(TileType.MAN_5),
        _chow(TileType.PIN_2),
        _pung(TileType.SOU_7),
        _pair(TileType.DRAGON_GREEN),
    )
    assert _occurrences("平糊", hand, _ctx()) == 0


# --- All Pungs (對對糊) ---------------------------------------------------------------------


def test_all_pungs() -> None:
    hand = (
        _pung(TileType.MAN_1),
        _pung(TileType.PIN_5),
        _pung(TileType.SOU_9),
        _kong(TileType.WIND_NORTH),
        _pair(TileType.DRAGON_RED),
    )
    assert _occurrences("對對糊", hand, _ctx()) == 1


def test_all_pungs_false_with_one_chow() -> None:
    hand = (
        _pung(TileType.MAN_1),
        _pung(TileType.PIN_5),
        _pung(TileType.SOU_9),
        _chow(TileType.MAN_5),
        _pair(TileType.DRAGON_RED),
    )
    assert _occurrences("對對糊", hand, _ctx()) == 0


# --- Voided Suit (缺一門) -------------------------------------------------------------------


def test_voided_suit_two_suits() -> None:
    hand = (
        _chow(TileType.MAN_1),
        _chow(TileType.MAN_4),
        _pung(TileType.PIN_9),
        _chow(TileType.PIN_1),
        _pair(TileType.MAN_7),
    )
    assert _occurrences("缺一門", hand, _ctx()) == 1


def test_voided_suit_false_for_one_suit() -> None:
    """One suit used (plus honors) is Half Flush territory, not Voided Suit -- see the note
    in patterns.py's `_detect_voided_suit`."""
    hand = (
        _chow(TileType.SOU_1),
        _chow(TileType.SOU_4),
        _pung(TileType.DRAGON_WHITE),
        _pung(TileType.WIND_NORTH),
        _pair(TileType.SOU_9),
    )
    assert _occurrences("缺一門", hand, _ctx()) == 0


def test_voided_suit_false_for_three_suits() -> None:
    hand = (
        _chow(TileType.MAN_1),
        _chow(TileType.PIN_1),
        _chow(TileType.SOU_1),
        _chow(TileType.MAN_4),
        _pair(TileType.DRAGON_RED),
    )
    assert _occurrences("缺一門", hand, _ctx()) == 0


# --- Half Flush (混一色) / Full Flush (清一色) ----------------------------------------------


def test_half_flush() -> None:
    hand = (
        _chow(TileType.SOU_1),
        _chow(TileType.SOU_4),
        _pung(TileType.DRAGON_WHITE),
        _pung(TileType.WIND_NORTH),
        _pair(TileType.SOU_9),
    )
    assert _occurrences("混一色", hand, _ctx()) == 1
    assert _occurrences("清一色", hand, _ctx()) == 0


def test_full_flush() -> None:
    hand = (
        _chow(TileType.PIN_1),
        _chow(TileType.PIN_4),
        _pung(TileType.PIN_7),
        _pung(TileType.PIN_8),
        _pair(TileType.PIN_9),
    )
    assert _occurrences("清一色", hand, _ctx()) == 1
    assert _occurrences("混一色", hand, _ctx()) == 0
    assert _occurrences("缺一門", hand, _ctx()) == 0


# --- No Flowers (無花) / Self-Draw (自摸) / Fully Concealed (門前清) -------------------------


def test_no_flowers() -> None:
    hand = (
        _chow(TileType.MAN_1),
        _chow(TileType.MAN_5),
        _chow(TileType.PIN_2),
        _chow(TileType.SOU_7),
        _pair(TileType.DRAGON_GREEN),
    )
    assert _occurrences("無花", hand, _ctx(flowers=())) == 1
    assert _occurrences("無花", hand, _ctx(flowers=(Flower.FLOWER_1,))) == 0


def test_self_draw() -> None:
    hand = (
        _chow(TileType.MAN_1),
        _chow(TileType.MAN_5),
        _chow(TileType.PIN_2),
        _chow(TileType.SOU_7),
        _pair(TileType.DRAGON_GREEN),
    )
    assert _occurrences("自摸", hand, _ctx(self_drawn=True)) == 1
    assert _occurrences("自摸", hand, _ctx(self_drawn=False)) == 0


def test_fully_concealed_true_when_no_open_melds_and_not_self_drawn() -> None:
    hand = (
        _chow(TileType.MAN_1),
        _chow(TileType.MAN_5),
        _chow(TileType.PIN_2),
        _chow(TileType.SOU_7),
        _pair(TileType.DRAGON_GREEN),
    )
    assert _occurrences("門前清", hand, _ctx(self_drawn=False)) == 1


def test_fully_concealed_false_when_self_drawn() -> None:
    """This ruleset's 門前清 entry is defined as "win on discard" specifically -- a self-draw
    win never gets it, even fully concealed; it gets 自摸 instead (rules.md §7)."""
    hand = (
        _chow(TileType.MAN_1),
        _chow(TileType.MAN_5),
        _chow(TileType.PIN_2),
        _chow(TileType.SOU_7),
        _pair(TileType.DRAGON_GREEN),
    )
    assert _occurrences("門前清", hand, _ctx(self_drawn=True)) == 0


def test_fully_concealed_false_with_an_open_meld() -> None:
    hand = (
        _chow(TileType.MAN_1, from_seat=3),  # claimed -- open
        _chow(TileType.MAN_5),
        _chow(TileType.PIN_2),
        _chow(TileType.SOU_7),
        _pair(TileType.DRAGON_GREEN),
    )
    assert _occurrences("門前清", hand, _ctx(self_drawn=False)) == 0


# --- Seat Wind (門風) / Prevailing Wind (圈風) ------------------------------------------------


def test_seat_and_prevailing_wind_stack_on_dealers_own_hand() -> None:
    """Dealer's seat wind is always East (rules.md §2); in the East round the
    prevailing wind is also East, so an East pung earns both patterns -- 2 faan total, not 1.
    See the note in patterns.py's `_detect_prevailing_wind`."""
    hand = (
        _pung(TileType.WIND_EAST),
        _chow(TileType.MAN_1),
        _chow(TileType.PIN_4),
        _chow(TileType.SOU_2),
        _pair(TileType.MAN_7),
    )
    ctx = _ctx(seat_wind=Wind.EAST, prevailing_wind=Wind.EAST)
    assert _occurrences("門風", hand, ctx) == 1
    assert _occurrences("圈風", hand, ctx) == 1
    scored = score_hand(hand, ctx)
    assert scored["門風"] == 1
    assert scored["圈風"] == 1


def test_seat_wind_only_when_winds_differ() -> None:
    hand = (
        _pung(TileType.WIND_SOUTH),
        _chow(TileType.MAN_1),
        _chow(TileType.PIN_4),
        _chow(TileType.SOU_2),
        _pair(TileType.MAN_7),
    )
    ctx = _ctx(seat_wind=Wind.SOUTH, prevailing_wind=Wind.EAST)
    assert _occurrences("門風", hand, ctx) == 1
    assert _occurrences("圈風", hand, ctx) == 0


def test_wind_pung_absent_scores_neither() -> None:
    hand = (
        _pung(TileType.MAN_1),
        _chow(TileType.PIN_4),
        _chow(TileType.SOU_2),
        _chow(TileType.MAN_5),
        _pair(TileType.SOU_9),
    )
    ctx = _ctx(seat_wind=Wind.SOUTH, prevailing_wind=Wind.EAST)
    assert _occurrences("門風", hand, ctx) == 0
    assert _occurrences("圈風", hand, ctx) == 0


# --- Dragon pung (箭刻), "each" ---------------------------------------------------------------


def test_dragon_pung_counts_each() -> None:
    hand = (
        _pung(TileType.DRAGON_RED),
        _pung(TileType.DRAGON_GREEN),
        _chow(TileType.MAN_1),
        _chow(TileType.PIN_4),
        _pair(TileType.SOU_9),
    )
    ctx = _ctx()
    assert _occurrences("箭刻", hand, ctx) == 2
    assert score_hand(hand, ctx)["箭刻"] == 2  # 2 occurrences * 1 faan each


def test_dragon_pair_alone_does_not_count() -> None:
    hand = (
        _chow(TileType.MAN_1),
        _chow(TileType.MAN_5),
        _chow(TileType.PIN_2),
        _chow(TileType.SOU_7),
        _pair(TileType.DRAGON_GREEN),
    )
    assert _occurrences("箭刻", hand, _ctx()) == 0


# --- Small Three Dragons (小三元) / Big Three Dragons (大三元) -----------------------------------


def test_small_three_dragons() -> None:
    hand = (
        _pung(TileType.DRAGON_RED),
        _pung(TileType.DRAGON_GREEN),
        _chow(TileType.MAN_1),
        _chow(TileType.PIN_4),
        _pair(TileType.DRAGON_WHITE),
    )
    ctx = _ctx()
    assert _occurrences("小三元", hand, ctx) == 1
    assert _occurrences("大三元", hand, ctx) == 0


def test_big_three_dragons() -> None:
    hand = (
        _pung(TileType.DRAGON_RED),
        _pung(TileType.DRAGON_GREEN),
        _kong(TileType.DRAGON_WHITE),
        _chow(TileType.MAN_1),
        _pair(TileType.SOU_9),
    )
    ctx = _ctx()
    assert _occurrences("大三元", hand, ctx) == 1
    assert _occurrences("小三元", hand, ctx) == 0


def test_two_dragon_pungs_without_dragon_pair_is_neither_small_nor_big() -> None:
    """The small/big boundary: two dragon pungs alone (pair non-dragon) satisfy neither --
    Small needs the dragon pair too, Big needs a third dragon pung."""
    hand = (
        _pung(TileType.DRAGON_RED),
        _pung(TileType.DRAGON_GREEN),
        _chow(TileType.MAN_1),
        _chow(TileType.PIN_4),
        _pair(TileType.SOU_9),
    )
    ctx = _ctx()
    assert _occurrences("小三元", hand, ctx) == 0
    assert _occurrences("大三元", hand, ctx) == 0


def test_dragon_pung_still_stacks_with_small_three_dragons() -> None:
    """rules.md §7 note ²: 箭刻 keeps firing per dragon pung even once Small/Big Three
    Dragons also fires on the same pungs."""
    hand = (
        _pung(TileType.DRAGON_RED),
        _pung(TileType.DRAGON_GREEN),
        _chow(TileType.MAN_1),
        _chow(TileType.PIN_4),
        _pair(TileType.DRAGON_WHITE),
    )
    scored = score_hand(hand, _ctx())
    assert scored["小三元"] == 3
    assert scored["箭刻"] == 2


# --- Small Four Winds (小四喜) / Big Four Winds (大四喜) -------------------------------------


def test_small_four_winds() -> None:
    hand = (
        _pung(TileType.WIND_EAST),
        _pung(TileType.WIND_SOUTH),
        _pung(TileType.WIND_WEST),
        _chow(TileType.MAN_1),
        _pair(TileType.WIND_NORTH),
    )
    ctx = _ctx(seat_wind=Wind.SOUTH, prevailing_wind=Wind.EAST)
    assert _occurrences("小四喜", hand, ctx) == 1
    assert _occurrences("大四喜", hand, ctx) == 0


def test_big_four_winds() -> None:
    hand = (
        _pung(TileType.WIND_EAST),
        _pung(TileType.WIND_SOUTH),
        _pung(TileType.WIND_WEST),
        _kong(TileType.WIND_NORTH),
        _pair(TileType.SOU_9),
    )
    ctx = _ctx(seat_wind=Wind.SOUTH, prevailing_wind=Wind.EAST)
    assert _occurrences("大四喜", hand, ctx) == 1
    assert _occurrences("小四喜", hand, ctx) == 0


def test_three_wind_pungs_without_wind_pair_is_neither_small_nor_big() -> None:
    hand = (
        _pung(TileType.WIND_EAST),
        _pung(TileType.WIND_SOUTH),
        _pung(TileType.WIND_WEST),
        _chow(TileType.MAN_1),
        _pair(TileType.SOU_9),
    )
    ctx = _ctx(seat_wind=Wind.SOUTH, prevailing_wind=Wind.EAST)
    assert _occurrences("小四喜", hand, ctx) == 0
    assert _occurrences("大四喜", hand, ctx) == 0


def test_seat_wind_still_stacks_with_small_four_winds() -> None:
    """rules.md §7 note ²: 門風/圈風 keep firing on their matching pung even once
    Small/Big Four Winds also fires."""
    hand = (
        _pung(TileType.WIND_EAST),
        _pung(TileType.WIND_SOUTH),
        _pung(TileType.WIND_WEST),
        _chow(TileType.MAN_1),
        _pair(TileType.WIND_NORTH),
    )
    ctx = _ctx(seat_wind=Wind.SOUTH, prevailing_wind=Wind.EAST)
    scored = score_hand(hand, ctx)
    assert scored["小四喜"] == 5
    assert scored["門風"] == 1


# --- Mixed Terminals (混么九) ------------------------------------------------------------------


def test_mixed_terminals() -> None:
    hand = (
        _pung(TileType.MAN_1),
        _pung(TileType.PIN_9),
        _pung(TileType.WIND_EAST),
        _pung(TileType.DRAGON_RED),
        _pair(TileType.DRAGON_GREEN),
    )
    assert _occurrences("混么九", hand, _ctx()) == 1


def test_mixed_terminals_false_with_a_chow() -> None:
    hand = (
        _pung(TileType.MAN_1),
        _chow(TileType.PIN_7),  # 7-8-9: lowest tile isn't terminal, but 8 isn't either
        _pung(TileType.WIND_EAST),
        _pung(TileType.DRAGON_RED),
        _pair(TileType.DRAGON_GREEN),
    )
    assert _occurrences("混么九", hand, _ctx()) == 0


def test_mixed_terminals_false_with_a_middle_tile_pung() -> None:
    hand = (
        _pung(TileType.MAN_1),
        _pung(TileType.PIN_5),
        _pung(TileType.WIND_EAST),
        _pung(TileType.DRAGON_RED),
        _pair(TileType.DRAGON_GREEN),
    )
    assert _occurrences("混么九", hand, _ctx()) == 0


def test_mixed_terminals_false_terminals_only_no_honors() -> None:
    """rules.md §7 note ²: terminals with no honor present is All Terminals (清么九,
    limit, not implemented yet) territory, not 混么九."""
    hand = (
        _pung(TileType.MAN_1),
        _pung(TileType.PIN_9),
        _pung(TileType.SOU_1),
        _pung(TileType.MAN_9),
        _pair(TileType.SOU_9),
    )
    assert _occurrences("混么九", hand, _ctx()) == 0


def test_mixed_terminals_false_honors_only_no_terminals() -> None:
    """rules.md §7 note ²: honors with no terminal present is All Honors (字一色,
    limit, not implemented yet) territory, not 混么九."""
    hand = (
        _pung(TileType.WIND_EAST),
        _pung(TileType.WIND_SOUTH),
        _pung(TileType.WIND_WEST),
        _pung(TileType.DRAGON_RED),
        _pair(TileType.DRAGON_GREEN),
    )
    assert _occurrences("混么九", hand, _ctx()) == 0


def test_mixed_terminals_stacks_with_voided_suit_and_all_pungs() -> None:
    """rules.md §7 note ²: 混么九 stacks with 缺一門/對對糊 when their own conditions
    also hold on the same hand -- nothing forbids the combination."""
    hand = (
        _pung(TileType.MAN_1),
        _pung(TileType.PIN_9),
        _pung(TileType.WIND_EAST),
        _pung(TileType.DRAGON_RED),
        _pair(TileType.DRAGON_GREEN),
    )
    scored = score_hand(hand, _ctx())
    assert scored["混么九"] == 3
    assert scored["缺一門"] == 2
    assert scored["對對糊"] == 3


# --- Combinations, via score_hand -------------------------------------------------------------


def test_full_flush_stacks_with_all_pungs() -> None:
    """rules.md §7: "Faan stack: Full Flush (6) + All Pungs (3) = 9". Two pungs are
    claimed (open) so this fixture stays about Full Flush + All Pungs only, not also Three
    Concealed Pungs (fourth sub-task, needs 3+ concealed) -- see
    `test_three_concealed_pungs_stacks_with_all_pungs` for that combination instead."""
    hand = (
        _pung(TileType.PIN_1),
        _pung(TileType.PIN_3, from_seat=2),
        _pung(TileType.PIN_5, from_seat=3),
        _pung(TileType.PIN_7),
        _pair(TileType.PIN_9),
    )
    ctx = _ctx(seat_wind=Wind.WEST, prevailing_wind=Wind.WEST)
    scored = score_hand(hand, ctx)
    assert scored["清一色"] == 6
    assert scored["對對糊"] == 3
    assert "混一色" not in scored
    assert "缺一門" not in scored
    assert "三暗刻" not in scored
    assert sum(scored.values()) == 9 + scored.get("無花", 0) + scored.get("門前清", 0)


def test_self_draw_all_sequences_no_flowers_combination() -> None:
    hand = (
        _chow(TileType.MAN_1),
        _chow(TileType.MAN_5),
        _chow(TileType.PIN_2),
        _chow(TileType.SOU_7),
        _pair(TileType.SOU_5),
    )
    ctx = _ctx(seat_wind=Wind.WEST, prevailing_wind=Wind.WEST, self_drawn=True, flowers=())
    scored = score_hand(hand, ctx)
    assert scored == {"平糊": 1, "自摸": 1, "無花": 1}


def test_empty_when_no_pattern_matches() -> None:
    hand = (
        _chow(TileType.MAN_1),
        _pung(TileType.PIN_5),
        _chow(TileType.SOU_2),
        _chow(TileType.MAN_5),
        _pair(TileType.SOU_9),
    )
    ctx = _ctx(
        seat_wind=Wind.WEST, prevailing_wind=Wind.WEST, self_drawn=False, flowers=(Flower.FLOWER_1,)
    )
    scored = score_hand(hand, ctx)
    assert "平糊" not in scored
    assert "對對糊" not in scored
    assert "無花" not in scored
    assert "自摸" not in scored


# --- All Honors (字一色) ----------------------------------------------------------------------


def test_all_honors() -> None:
    hand = (
        _pung(TileType.DRAGON_RED),
        _pung(TileType.DRAGON_GREEN),
        _pung(TileType.WIND_EAST),
        _kong(TileType.WIND_SOUTH),
        _pair(TileType.DRAGON_WHITE),
    )
    assert _occurrences("字一色", hand, _ctx()) == 1


def test_all_honors_false_with_a_suited_tile() -> None:
    hand = (
        _pung(TileType.DRAGON_RED),
        _pung(TileType.DRAGON_GREEN),
        _pung(TileType.WIND_EAST),
        _pung(TileType.MAN_1),
        _pair(TileType.DRAGON_WHITE),
    )
    assert _occurrences("字一色", hand, _ctx()) == 0


# --- All Terminals (清么九) --------------------------------------------------------------------


def test_all_terminals() -> None:
    hand = (
        _pung(TileType.MAN_1),
        _pung(TileType.MAN_9),
        _pung(TileType.PIN_1),
        _pung(TileType.SOU_9),
        _pair(TileType.SOU_1),
    )
    assert _occurrences("清么九", hand, _ctx()) == 1


def test_all_terminals_false_with_an_honor() -> None:
    """An honor present is 混么九 (Mixed Terminals) territory, not 清么九 -- see
    `_detect_all_terminals`'s docstring."""
    hand = (
        _pung(TileType.MAN_1),
        _pung(TileType.MAN_9),
        _pung(TileType.PIN_1),
        _pung(TileType.DRAGON_RED),
        _pair(TileType.SOU_1),
    )
    assert _occurrences("清么九", hand, _ctx()) == 0


def test_all_terminals_false_with_a_chow() -> None:
    """Boundary mirrored from 混么九: a 1-2-3 chow's `tile_type` (its lowest tile) reads as
    terminal even though 2m/3m aren't."""
    hand = (
        _pung(TileType.MAN_1),
        _chow(TileType.PIN_1),
        _pung(TileType.SOU_9),
        _pung(TileType.SOU_1),
        _pair(TileType.MAN_9),
    )
    assert _occurrences("清么九", hand, _ctx()) == 0


# --- Nine Gates (九蓮寶燈) ---------------------------------------------------------------------


def _tiles_from_counts(suit_base: TileType, counts: list[int]) -> tuple[TileId, ...]:
    types: list[TileType] = []
    for rank, n in enumerate(counts):
        types.extend([TileType(int(suit_base) + rank)] * n)
    return _tiles(*types)


def _nine_gates_tiles(suit_base: TileType, extra_rank: int) -> tuple[TileId, ...]:
    counts = [3, 1, 1, 1, 1, 1, 1, 1, 3]
    counts[extra_rank] += 1
    return _tiles_from_counts(suit_base, counts)


@pytest.mark.parametrize("extra_rank", range(9))
def test_nine_gates_valid_for_any_extra_tile_rank(extra_rank: int) -> None:
    """The exact tile pattern: 1112345678999 plus one more tile of the same suit, any rank
    1-9 -- the boundary this pattern is defined by."""
    tiles = _nine_gates_tiles(TileType.PIN_1, extra_rank)
    assert _occurrences("九蓮寶燈", (), _ctx(concealed_tiles=tiles)) == 1


def test_nine_gates_false_when_a_rank_is_missing_even_with_14_tiles_one_suit() -> None:
    """One suit, 14 tiles, terminals and middle tiles both present -- but not the exact
    skeleton (rank 8 is entirely absent here, with two extra 1s and 9s instead of one extra
    tile). Proves this is an exact-count check, not "one suit, mostly filled in"."""
    counts = [4, 1, 1, 1, 1, 1, 1, 0, 4]
    tiles = _tiles_from_counts(TileType.SOU_1, counts)
    assert _occurrences("九蓮寶燈", (), _ctx(concealed_tiles=tiles)) == 0


def test_nine_gates_false_with_an_honor_present() -> None:
    counts = [3, 1, 1, 1, 1, 1, 1, 1, 2]
    extra = tile_ids_for_type(TileType.DRAGON_RED)[0]
    tiles = _tiles_from_counts(TileType.MAN_1, counts) + (extra,)
    assert _occurrences("九蓮寶燈", (), _ctx(concealed_tiles=tiles)) == 0


def test_nine_gates_false_across_two_suits() -> None:
    counts = [3, 1, 1, 1, 1, 1, 1, 1, 2]
    tiles = _tiles_from_counts(TileType.MAN_1, counts) + (tile_ids_for_type(TileType.PIN_1)[0],)
    assert _occurrences("九蓮寶燈", (), _ctx(concealed_tiles=tiles)) == 0


def test_nine_gates_false_when_hand_not_fully_concealed() -> None:
    """An open meld shrinks `concealed_tiles` below 14 -- Nine Gates has no claimed-meld
    variant."""
    counts = [3, 1, 1, 1, 1, 1, 1, 1, 3]  # the bare 13-tile skeleton, no 14th tile
    tiles = _tiles_from_counts(TileType.MAN_1, counts)
    assert _occurrences("九蓮寶燈", (), _ctx(concealed_tiles=tiles)) == 0


def test_nine_gates_false_when_hand_is_non_empty_even_if_concealed_tiles_qualify() -> None:
    """Regression: `ctx.concealed_tiles` is the same on every decomposition candidate
    `score_winning_hand` scores for one win (faan.py's own docstring), so without this guard
    九蓮寶燈 would fire on *every* candidate whenever the raw 14 tiles happen to satisfy the
    Nine Gates skeleton -- not just the one raw (`hand == ()`) candidate it's meant for. A
    non-empty `hand` here (an arbitrary real decomposition) must suppress it even though the
    same `concealed_tiles` alone would qualify -- see `_detect_nine_gates`'s docstring."""
    tiles = _nine_gates_tiles(TileType.PIN_1, extra_rank=4)
    hand = (
        _chow(TileType.MAN_1),
        _chow(TileType.MAN_5),
        _chow(TileType.PIN_2),
        _chow(TileType.SOU_7),
        _pair(TileType.DRAGON_GREEN),
    )
    assert _occurrences("九蓮寶燈", (), _ctx(concealed_tiles=tiles)) == 1
    assert _occurrences("九蓮寶燈", hand, _ctx(concealed_tiles=tiles)) == 0


# --- Thirteen Orphans (十三么) -----------------------------------------------------------------

_ORPHAN_TYPE_LIST = [
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


def test_thirteen_orphans() -> None:
    tiles = _tiles(*_ORPHAN_TYPE_LIST, TileType.MAN_1)  # 14th tile duplicates one orphan
    assert _actions_is_thirteen_orphans(tiles) is True
    assert _occurrences("十三么", (), _ctx(concealed_tiles=tiles)) == 1


def test_thirteen_orphans_false_missing_one_type() -> None:
    types = [*_ORPHAN_TYPE_LIST[:-1], TileType.MAN_9, TileType.MAN_1]  # no DRAGON_WHITE at all
    tiles = _tiles(*types)
    assert _actions_is_thirteen_orphans(tiles) is False
    assert _occurrences("十三么", (), _ctx(concealed_tiles=tiles)) == 0


def test_thirteen_orphans_false_for_a_standard_hand_cross_checked_against_actions() -> None:
    """patterns.py mirrors, rather than imports, `actions.py`'s shape check (see
    `_ORPHAN_TYPES`'s docstring in patterns.py) -- cross-validate the two agree on an
    ordinary, nowhere-near-orphans hand so the copies can't silently drift apart."""
    hand = (
        _chow(TileType.MAN_1),
        _chow(TileType.MAN_5),
        _chow(TileType.PIN_2),
        _chow(TileType.SOU_7),
        _pair(TileType.DRAGON_GREEN),
    )
    tiles = tuple(t for m in hand for t in m.tiles)
    assert _actions_is_thirteen_orphans(tiles) is False
    assert _occurrences("十三么", (), _ctx(concealed_tiles=tiles)) == 0


def test_thirteen_orphans_false_when_hand_is_non_empty_even_if_concealed_tiles_qualify() -> None:
    """Regression, same shape as `test_nine_gates_false_when_hand_is_non_empty_...` above --
    see `_detect_nine_gates`'s docstring for why `ctx.concealed_tiles` alone qualifying isn't
    enough once `hand` carries a real (if here unrelated/nonsensical) decomposition."""
    tiles = _tiles(*_ORPHAN_TYPE_LIST, TileType.MAN_1)
    hand = (
        _chow(TileType.MAN_1),
        _chow(TileType.MAN_5),
        _chow(TileType.PIN_2),
        _chow(TileType.SOU_7),
        _pair(TileType.DRAGON_GREEN),
    )
    assert _occurrences("十三么", (), _ctx(concealed_tiles=tiles)) == 1
    assert _occurrences("十三么", hand, _ctx(concealed_tiles=tiles)) == 0


def test_score_hand_thirteen_orphans_includes_the_limit_entry() -> None:
    """`decompose()` never produces a `hand` for this shape (module docstring's "Raw-hand
    access" note) -- `score_hand` is called with an empty `hand` and the concealed tiles on
    `context`. Every decomposition-shaped detector correctly sees no groups and stays silent;
    `無花`/`門前清` still fire since they read only `ctx`, not `hand` -- `score_hand` doesn't
    suppress that (excluding non-limit faan once a limit pattern applies is faan.py's job, see
    rules.md §7 "Limit hands do not stack with anything")."""
    tiles = _tiles(*_ORPHAN_TYPE_LIST, TileType.MAN_1)
    scored = score_hand((), _ctx(concealed_tiles=tiles))
    assert scored["十三么"] == LIMIT_FAAN
    assert set(scored) <= {"十三么", "無花", "門前清"}


# --- Heavenly Hand (天糊) / Earthly Hand (地糊) -------------------------------------------------


def test_heavenly_hand() -> None:
    ctx = _ctx(seat_wind=Wind.EAST, self_drawn=True, won_before_any_discard=True)
    assert _occurrences("天糊", (), ctx) == 1


def test_heavenly_hand_false_for_non_dealer() -> None:
    ctx = _ctx(seat_wind=Wind.SOUTH, won_before_any_discard=True)
    assert _occurrences("天糊", (), ctx) == 0


def test_heavenly_hand_false_once_a_discard_has_happened() -> None:
    ctx = _ctx(seat_wind=Wind.EAST, won_before_any_discard=False)
    assert _occurrences("天糊", (), ctx) == 0


def test_earthly_hand() -> None:
    ctx = _ctx(seat_wind=Wind.SOUTH, self_drawn=False, won_on_dealer_first_discard=True)
    assert _occurrences("地糊", (), ctx) == 1


def test_earthly_hand_false_for_dealer() -> None:
    """The dealer can't claim their own discard."""
    ctx = _ctx(seat_wind=Wind.EAST, won_on_dealer_first_discard=True)
    assert _occurrences("地糊", (), ctx) == 0


def test_earthly_hand_false_when_self_drawn() -> None:
    ctx = _ctx(seat_wind=Wind.SOUTH, self_drawn=True, won_on_dealer_first_discard=True)
    assert _occurrences("地糊", (), ctx) == 0


def test_earthly_hand_false_when_flag_unset() -> None:
    ctx = _ctx(seat_wind=Wind.SOUTH, won_on_dealer_first_discard=False)
    assert _occurrences("地糊", (), ctx) == 0


# --- Win on Last Wall Tile (海底撈月) / Win on Last Discard (河底撈魚) --------------------------
# stub context fields (is_last_tile/is_kong_replacement/is_robbing_kong) exercised directly, same as sub-task 3's Heavenly/Earthly Hand tests.


def test_win_on_last_wall_tile() -> None:
    assert _occurrences("海底撈月", (), _ctx(self_drawn=True, is_last_tile=True)) == 1


def test_win_on_last_wall_tile_false_when_not_self_drawn() -> None:
    """海底撈月 is the self-draw half of the last-tile pair; a claimed win on the same
    circumstance is 河底撈魚 instead."""
    assert _occurrences("海底撈月", (), _ctx(self_drawn=False, is_last_tile=True)) == 0


def test_win_on_last_wall_tile_false_when_flag_unset() -> None:
    assert _occurrences("海底撈月", (), _ctx(self_drawn=True, is_last_tile=False)) == 0


def test_win_on_last_wall_tile_false_for_kong_replacement() -> None:
    """rules.md §7 note ³: a kong replacement that happens to be the wall's last tile
    scores as 槓上開花 only, not also 海底撈月 -- see patterns.py's ladder note."""
    ctx = _ctx(self_drawn=True, is_last_tile=True, is_kong_replacement=True)
    assert _occurrences("海底撈月", (), ctx) == 0
    assert _occurrences("槓上開花", (), ctx) == 1


def test_win_on_last_discard() -> None:
    assert _occurrences("河底撈魚", (), _ctx(self_drawn=False, is_last_tile=True)) == 1


def test_win_on_last_discard_false_when_self_drawn() -> None:
    assert _occurrences("河底撈魚", (), _ctx(self_drawn=True, is_last_tile=True)) == 0


def test_win_on_last_discard_false_when_flag_unset() -> None:
    assert _occurrences("河底撈魚", (), _ctx(self_drawn=False, is_last_tile=False)) == 0


def test_win_on_last_discard_false_when_robbing_kong() -> None:
    ctx = _ctx(self_drawn=False, is_last_tile=True, is_robbing_kong=True)
    assert _occurrences("河底撈魚", (), ctx) == 0


# --- Win on Kong Replacement (槓上開花) ----------------------------------------------------------


def test_win_on_kong_replacement() -> None:
    assert _occurrences("槓上開花", (), _ctx(self_drawn=True, is_kong_replacement=True)) == 1


def test_win_on_kong_replacement_false_when_flag_unset() -> None:
    assert _occurrences("槓上開花", (), _ctx(self_drawn=True, is_kong_replacement=False)) == 0


def test_win_on_kong_replacement_false_when_not_self_drawn() -> None:
    """Defensive-only: a kong-replacement win is always a draw, this flag combination can't
    arise from real play, but the detector checks explicitly anyway (see its docstring)."""
    assert _occurrences("槓上開花", (), _ctx(self_drawn=False, is_kong_replacement=True)) == 0


# --- Robbing the Kong (搶槓) ---------------------------------------------------------------------


def test_robbing_the_kong() -> None:
    assert _occurrences("搶槓", (), _ctx(self_drawn=False, is_robbing_kong=True)) == 1


def test_robbing_the_kong_false_when_flag_unset() -> None:
    assert _occurrences("搶槓", (), _ctx(self_drawn=False, is_robbing_kong=False)) == 0


def test_robbing_the_kong_false_when_self_drawn() -> None:
    """Defensive-only, same reasoning as 槓上開花: a robbed win is always a claim."""
    assert _occurrences("搶槓", (), _ctx(self_drawn=True, is_robbing_kong=True)) == 0


def test_win_timing_patterns_registered_under_new_6() -> None:
    timing_names = {"海底撈月", "河底撈魚", "槓上開花", "搶槓"}
    for pattern in PATTERNS:
        if pattern.name in timing_names:
            assert pattern.hand_set == HandSet.NEW_6
            assert pattern.faan == 1


# --- Seat Flower (座位花) / Flower Set (正花) ----------------------------------------------------


def test_seat_flower_matches_flower_and_season() -> None:
    """East (seat_wind index 0) matches FLOWER_1 (index 0) and SEASON_1 (index 4)."""
    ctx = _ctx(seat_wind=Wind.EAST, flowers=(Flower.FLOWER_1, Flower.SEASON_1))
    assert _occurrences("座位花", (), ctx) == 2


def test_seat_flower_counts_only_matching_seat() -> None:
    ctx = _ctx(seat_wind=Wind.SOUTH, flowers=(Flower.FLOWER_1, Flower.SEASON_2))
    assert _occurrences("座位花", (), ctx) == 1  # only SEASON_2 (index 5) matches South (index 1)


def test_seat_flower_zero_when_no_flowers_held() -> None:
    assert _occurrences("座位花", (), _ctx(seat_wind=Wind.WEST, flowers=())) == 0


def test_seat_flower_gated_by_flowers_score() -> None:
    """`ctx.flowers_score` mirrors `RuleSet.flowers_score` (config.py) -- some tables disable
    seat-flower faan outright."""
    ctx = _ctx(seat_wind=Wind.EAST, flowers=(Flower.FLOWER_1,), flowers_score=False)
    assert _occurrences("座位花", (), ctx) == 0


def test_flower_set_all_flowers() -> None:
    ctx = _ctx(
        flowers=(Flower.FLOWER_1, Flower.FLOWER_2, Flower.FLOWER_3, Flower.FLOWER_4),
    )
    assert _occurrences("正花", (), ctx) == 1


def test_flower_set_all_seasons() -> None:
    ctx = _ctx(
        flowers=(Flower.SEASON_1, Flower.SEASON_2, Flower.SEASON_3, Flower.SEASON_4),
    )
    assert _occurrences("正花", (), ctx) == 1


def test_flower_set_both_complete_sets() -> None:
    ctx = _ctx(flowers=tuple(Flower))  # all 8
    assert _occurrences("正花", (), ctx) == 2


def test_flower_set_false_when_incomplete() -> None:
    ctx = _ctx(flowers=(Flower.FLOWER_1, Flower.FLOWER_2, Flower.FLOWER_3))
    assert _occurrences("正花", (), ctx) == 0


def test_flower_set_not_gated_by_flowers_score() -> None:
    """正花 is a Classic-table pattern, distinct from the `flowers_score`-gated 座位花 -- it
    keeps firing even with `flowers_score=False`."""
    ctx = _ctx(
        flowers=(Flower.FLOWER_1, Flower.FLOWER_2, Flower.FLOWER_3, Flower.FLOWER_4),
        flowers_score=False,
    )
    assert _occurrences("正花", (), ctx) == 1


def test_seat_flower_and_flower_set_registered_under_classic() -> None:
    for name, expected_faan in (("座位花", 1), ("正花", 3)):
        pattern = next(p for p in PATTERNS if p.name == name)
        assert pattern.hand_set == HandSet.CLASSIC
        assert pattern.faan == expected_faan
        assert pattern.is_limit is False


# --- Limit hands don't stack (rules.md §7 "Stacking and caps") -------------------------


def test_limit_patterns_flagged_for_future_non_stacking() -> None:
    """Limit hands don't stack with wind/dragon/flower faan, and only the highest limit
    pattern counts when more than one applies (§7). `score_hand` doesn't implement that rule
    itself -- it's faan.py's job, once that module exists -- so this proves the flag/value it
    will need are set correctly on every limit pattern registered so far."""
    limit_names = {"字一色", "清么九", "九蓮寶燈", "十三么", "天糊", "地糊"}
    for pattern in PATTERNS:
        assert pattern.is_limit == (pattern.name in limit_names)
        if pattern.is_limit:
            assert pattern.faan == LIMIT_FAAN


# --- Seven Pairs (七對子) ----------------------------------------------------------------------


def test_seven_pairs() -> None:
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
    assert _actions_is_seven_pairs(tiles) is True
    assert _occurrences("七對子", (), _ctx(concealed_tiles=tiles)) == 1


def test_seven_pairs_is_not_a_limit_hand() -> None:
    """§7 gives Seven Pairs a plain 4 faan, unlike Thirteen Orphans in the same "raw-hand
    shape" family -- see the note in patterns.py's `_detect_seven_pairs`."""
    pattern = next(p for p in PATTERNS if p.name == "七對子")
    assert pattern.is_limit is False
    assert pattern.faan == 4


def test_seven_pairs_false_with_a_triple() -> None:
    """Three of one type plus a lone extra isn't seven *distinct* pairs."""
    tiles = _tiles(
        TileType.MAN_1,
        TileType.MAN_1,
        TileType.MAN_1,
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
    assert _actions_is_seven_pairs(tiles) is False
    assert _occurrences("七對子", (), _ctx(concealed_tiles=tiles)) == 0


def test_seven_pairs_false_for_a_standard_hand_cross_checked_against_actions() -> None:
    hand = (
        _chow(TileType.MAN_1),
        _chow(TileType.MAN_5),
        _chow(TileType.PIN_2),
        _chow(TileType.SOU_7),
        _pair(TileType.DRAGON_GREEN),
    )
    tiles = tuple(t for m in hand for t in m.tiles)
    assert _actions_is_seven_pairs(tiles) is False
    assert _occurrences("七對子", (), _ctx(concealed_tiles=tiles)) == 0


def test_seven_pairs_false_when_hand_is_non_empty_even_if_concealed_tiles_qualify() -> None:
    """Regression, same shape as the Nine Gates/Thirteen Orphans versions above -- and the one
    that actually matters most in practice: unlike those two, 七對子 isn't a limit pattern, so
    it isn't shielded from double-counting by faan.py's limit-hand non-stacking collapse (see
    `_detect_seven_pairs`'s docstring). A hand whose 14 tiles happen to satisfy Seven Pairs
    *and* have a real standard decomposition (test_faan.py's
    `test_seven_pairs_vs_standard_decomposition_maximizes` has one) would otherwise add 七對子's
    faan on top of that unrelated decomposition's own patterns."""
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
    hand = (
        _chow(TileType.MAN_1),
        _chow(TileType.MAN_5),
        _chow(TileType.PIN_2),
        _chow(TileType.SOU_7),
        _pair(TileType.DRAGON_GREEN),
    )
    assert _occurrences("七對子", (), _ctx(concealed_tiles=tiles)) == 1
    assert _occurrences("七對子", hand, _ctx(concealed_tiles=tiles)) == 0


# --- Three Concealed Pungs (三暗刻) -------------------------------------------------------------


def test_three_concealed_pungs() -> None:
    hand = (
        _pung(TileType.MAN_1),
        _pung(TileType.PIN_5),
        _pung(TileType.SOU_9),
        _chow(TileType.MAN_4, from_seat=3),
        _pair(TileType.DRAGON_RED),
    )
    assert _occurrences("三暗刻", hand, _ctx()) == 1


def test_three_concealed_pungs_counts_a_concealed_kong() -> None:
    hand = (
        _pung(TileType.MAN_1),
        _pung(TileType.PIN_5),
        _concealed_kong(TileType.SOU_9),
        _chow(TileType.MAN_4, from_seat=3),
        _pair(TileType.DRAGON_RED),
    )
    assert _occurrences("三暗刻", hand, _ctx()) == 1


def test_three_concealed_pungs_false_with_only_two() -> None:
    hand = (
        _pung(TileType.MAN_1),
        _pung(TileType.PIN_5, from_seat=2),  # claimed -- open, doesn't count
        _pung(TileType.SOU_9),
        _chow(TileType.MAN_4),
        _pair(TileType.DRAGON_RED),
    )
    assert _occurrences("三暗刻", hand, _ctx()) == 0


def test_three_concealed_pungs_false_with_an_exposed_kong() -> None:
    """An exposed kong is always claimed -- never counts as concealed, even though it's a
    fourth-tile pung in spirit."""
    hand = (
        _pung(TileType.MAN_1),
        _pung(TileType.PIN_5),
        _kong(TileType.SOU_9, from_seat=1),
        _chow(TileType.MAN_4),
        _pair(TileType.DRAGON_RED),
    )
    assert _occurrences("三暗刻", hand, _ctx()) == 0


def test_three_concealed_pungs_stacks_with_all_pungs() -> None:
    """Combination with an earlier batch's pattern (對對糊, sub-task 1): nothing forbids the
    two from firing on the same hand."""
    hand = (
        _pung(TileType.MAN_1),
        _pung(TileType.PIN_5),
        _pung(TileType.SOU_9),
        _pung(TileType.MAN_7, from_seat=3),
        _pair(TileType.DRAGON_RED),
    )
    scored = score_hand(hand, _ctx())
    assert scored["三暗刻"] == 2
    assert scored["對對糊"] == 3


# --- All Revealed (全求人) ----------------------------------------------------------------------


def test_all_revealed() -> None:
    hand = (
        _pung(TileType.MAN_1, from_seat=1),
        _chow(TileType.PIN_5, from_seat=2),
        _pung(TileType.SOU_9, from_seat=3),
        _kong(TileType.WIND_EAST, from_seat=1),
        _pair(TileType.DRAGON_RED),
    )
    assert _occurrences("全求人", hand, _ctx(self_drawn=False)) == 1


def test_all_revealed_false_when_self_drawn() -> None:
    hand = (
        _pung(TileType.MAN_1, from_seat=1),
        _chow(TileType.PIN_5, from_seat=2),
        _pung(TileType.SOU_9, from_seat=3),
        _kong(TileType.WIND_EAST, from_seat=1),
        _pair(TileType.DRAGON_RED),
    )
    assert _occurrences("全求人", hand, _ctx(self_drawn=True)) == 0


def test_all_revealed_false_with_one_concealed_group() -> None:
    hand = (
        _pung(TileType.MAN_1, from_seat=1),
        _chow(TileType.PIN_5, from_seat=2),
        _pung(TileType.SOU_9, from_seat=3),
        _chow(TileType.MAN_5),  # concealed -- breaks "only the pair concealed"
        _pair(TileType.DRAGON_RED),
    )
    assert _occurrences("全求人", hand, _ctx(self_drawn=False)) == 0


def test_all_revealed_mutually_exclusive_with_fully_concealed() -> None:
    hand = (
        _pung(TileType.MAN_1, from_seat=1),
        _chow(TileType.PIN_5, from_seat=2),
        _pung(TileType.SOU_9, from_seat=3),
        _kong(TileType.WIND_EAST, from_seat=1),
        _pair(TileType.DRAGON_RED),
    )
    ctx = _ctx(self_drawn=False)
    assert _occurrences("全求人", hand, ctx) == 1
    assert _occurrences("門前清", hand, ctx) == 0


# --- Two Dragon Pungs (雙箭) --------------------------------------------------------------------


def test_two_dragon_pungs() -> None:
    hand = (
        _pung(TileType.DRAGON_RED),
        _pung(TileType.DRAGON_GREEN),
        _chow(TileType.MAN_1),
        _chow(TileType.PIN_4),
        _pair(TileType.SOU_9),
    )
    assert _occurrences("雙箭", hand, _ctx()) == 1


def test_two_dragon_pungs_false_with_only_one() -> None:
    hand = (
        _pung(TileType.DRAGON_RED),
        _chow(TileType.MAN_1),
        _chow(TileType.PIN_4),
        _chow(TileType.SOU_2),
        _pair(TileType.SOU_9),
    )
    assert _occurrences("雙箭", hand, _ctx()) == 0


def test_two_dragon_pungs_false_with_all_three() -> None:
    """Mutually exclusive with Big Three Dragons by construction -- see the footnote added to
    rules.md §7."""
    hand = (
        _pung(TileType.DRAGON_RED),
        _pung(TileType.DRAGON_GREEN),
        _kong(TileType.DRAGON_WHITE),
        _chow(TileType.MAN_1),
        _pair(TileType.SOU_9),
    )
    assert _occurrences("雙箭", hand, _ctx()) == 0
    assert _occurrences("大三元", hand, _ctx()) == 1


def test_two_dragon_pungs_stacks_with_small_three_dragons_and_dragon_pung() -> None:
    hand = (
        _pung(TileType.DRAGON_RED),
        _pung(TileType.DRAGON_GREEN),
        _chow(TileType.MAN_1),
        _chow(TileType.PIN_4),
        _pair(TileType.DRAGON_WHITE),
    )
    scored = score_hand(hand, _ctx())
    assert scored["雙箭"] == 2
    assert scored["小三元"] == 3
    assert scored["箭刻"] == 2


# --- Two/Three Identical Sequences (一般高/三般高) -----------------------------------------------


def test_two_identical_sequences() -> None:
    hand = (
        _chow(TileType.MAN_1),
        _chow(TileType.MAN_1),
        _chow(TileType.PIN_5),
        _chow(TileType.SOU_2),
        _pair(TileType.DRAGON_RED),
    )
    assert _occurrences("一般高", hand, _ctx()) == 1
    assert _occurrences("三般高", hand, _ctx()) == 0


def test_two_identical_sequences_counts_each_distinct_pair() -> None:
    """Two separate double-chows (123m x2, 456p x2) each count -- "each," like 箭刻."""
    hand = (
        _chow(TileType.MAN_1),
        _chow(TileType.MAN_1),
        _chow(TileType.PIN_4),
        _chow(TileType.PIN_4),
        _pair(TileType.DRAGON_RED),
    )
    assert _occurrences("一般高", hand, _ctx()) == 2


def test_three_identical_sequences() -> None:
    hand = (
        _chow(TileType.MAN_1),
        _chow(TileType.MAN_1),
        _chow(TileType.MAN_1),
        _chow(TileType.PIN_4),
        _pair(TileType.DRAGON_RED),
    )
    assert _occurrences("三般高", hand, _ctx()) == 1


def test_three_identical_sequences_ladder_excludes_two_identical() -> None:
    """Ladder rule (rules.md §7 note ⁷): a run counted at 三般高 never also counts at
    一般高 -- a count can't be both `== 2` and `>= 3`."""
    hand = (
        _chow(TileType.MAN_1),
        _chow(TileType.MAN_1),
        _chow(TileType.MAN_1),
        _chow(TileType.PIN_4),
        _pair(TileType.DRAGON_RED),
    )
    ctx = _ctx()
    assert _occurrences("三般高", hand, ctx) == 1
    assert _occurrences("一般高", hand, ctx) == 0


def test_identical_sequences_not_confused_with_stepped_sequences() -> None:
    """Three *identical* 123m chows is 三般高, not 三步高 -- same starting rank each time,
    not three different ranks spaced two apart. The easy-to-conflate boundary this batch's
    detectors must keep straight."""
    hand = (
        _chow(TileType.MAN_1),
        _chow(TileType.MAN_1),
        _chow(TileType.MAN_1),
        _chow(TileType.PIN_4),
        _pair(TileType.DRAGON_RED),
    )
    ctx = _ctx()
    assert _occurrences("三般高", hand, ctx) == 1
    assert _occurrences("三步高", hand, ctx) == 0


def test_no_identical_or_stepped_sequences_for_unrelated_chows() -> None:
    hand = (
        _chow(TileType.MAN_1),
        _chow(TileType.MAN_5),
        _chow(TileType.PIN_2),
        _chow(TileType.SOU_7),
        _pair(TileType.DRAGON_RED),
    )
    ctx = _ctx()
    assert _occurrences("一般高", hand, ctx) == 0
    assert _occurrences("三般高", hand, ctx) == 0
    assert _occurrences("三步高", hand, ctx) == 0
    assert _occurrences("四步高", hand, ctx) == 0


# --- Three/Four Step Sequences (三步高/四步高) ---------------------------------------------------


def test_three_step_sequences() -> None:
    """123m / 345m / 567m -- starts 0, 2, 4 (ranks), spaced two apart."""
    hand = (
        _chow(TileType.MAN_1),
        _chow(TileType.MAN_3),
        _chow(TileType.MAN_5),
        _chow(TileType.PIN_4),
        _pair(TileType.DRAGON_RED),
    )
    assert _occurrences("三步高", hand, _ctx()) == 1
    assert _occurrences("四步高", hand, _ctx()) == 0


def test_three_step_sequences_false_for_consecutive_not_spaced_by_two() -> None:
    """123m / 234m / 345m are spaced by *one* rank, not two -- not this pattern."""
    hand = (
        _chow(TileType.MAN_1),
        _chow(TileType.MAN_2),
        _chow(TileType.MAN_3),
        _chow(TileType.PIN_4),
        _pair(TileType.DRAGON_RED),
    )
    assert _occurrences("三步高", hand, _ctx()) == 0


def test_three_step_sequences_false_across_different_suits() -> None:
    hand = (
        _chow(TileType.MAN_1),
        _chow(TileType.PIN_3),
        _chow(TileType.SOU_5),
        _chow(TileType.MAN_7),
        _pair(TileType.DRAGON_RED),
    )
    assert _occurrences("三步高", hand, _ctx()) == 0


def test_four_step_sequences() -> None:
    """123m / 345m / 567m / 789m -- the only shape that fits four step-2 runs in one suit."""
    hand = (
        _chow(TileType.MAN_1),
        _chow(TileType.MAN_3),
        _chow(TileType.MAN_5),
        _chow(TileType.MAN_7),
        _pair(TileType.DRAGON_RED),
    )
    assert _occurrences("四步高", hand, _ctx()) == 1


def test_four_step_sequences_ladder_excludes_three_step() -> None:
    """Ladder rule (rules.md §7 note ⁸): 四步高's ranks contain 三步高's own pattern
    twice over, so 三步高 must not also fire on the same hand."""
    hand = (
        _chow(TileType.MAN_1),
        _chow(TileType.MAN_3),
        _chow(TileType.MAN_5),
        _chow(TileType.MAN_7),
        _pair(TileType.DRAGON_RED),
    )
    ctx = _ctx()
    assert _occurrences("四步高", hand, ctx) == 1
    assert _occurrences("三步高", hand, ctx) == 0


def test_stepped_sequences_not_confused_with_identical_sequences() -> None:
    """123m / 345m / 567m are three *different* chows, not identical -- 一般高/三般高 must stay
    silent here even though three chows of the same suit are present."""
    hand = (
        _chow(TileType.MAN_1),
        _chow(TileType.MAN_3),
        _chow(TileType.MAN_5),
        _chow(TileType.PIN_4),
        _pair(TileType.DRAGON_RED),
    )
    ctx = _ctx()
    assert _occurrences("三步高", hand, ctx) == 1
    assert _occurrences("一般高", hand, ctx) == 0
    assert _occurrences("三般高", hand, ctx) == 0


def test_three_step_sequences_stacks_with_half_flush() -> None:
    """Combination with an earlier batch's pattern (混一色, sub-task 1)."""
    hand = (
        _chow(TileType.MAN_1),
        _chow(TileType.MAN_3),
        _chow(TileType.MAN_5),
        _pung(TileType.DRAGON_RED),
        _pair(TileType.DRAGON_GREEN),
    )
    scored = score_hand(hand, _ctx())
    assert scored["三步高"] == 2
    assert scored["混一色"] == 3
