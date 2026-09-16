"""Golden fixtures for mahjong_core/scoring/patterns.py (docs/05-roadmap.md §3: "Golden
fixtures, one per faan pattern plus combinations"). Fixtures are (hand melds, context) ->
expected faan at the `score_hand`/detector layer -- `faan.py`'s decomposition-maximisation,
`min_faan` gate, caps, and `payout.py`'s points/payments (docs/01-rules-spec.md §8) don't exist
yet (see the M2 sub-task breakdown), so there's no ruleset/payments axis to fixture here yet;
that's the shape a later sub-task's golden suite adds.
"""

from __future__ import annotations

import pytest

from mahjong_core.melds import Meld, MeldKind
from mahjong_core.scoring.patterns import PATTERNS, ScoringContext, score_hand, seat_wind_for
from mahjong_core.state import Wind
from mahjong_core.tiles import Flower, TileType, tile_ids_for_type


def _chow(low: TileType, from_seat: int | None = None) -> Meld:
    ids = tuple(tile_ids_for_type(TileType(int(low) + k))[0] for k in range(3))
    return Meld(MeldKind.CHOW, ids, from_seat=from_seat)


def _pung(tile_type: TileType, from_seat: int | None = None) -> Meld:
    return Meld(MeldKind.PUNG, tile_ids_for_type(tile_type)[:3], from_seat=from_seat)


def _kong(tile_type: TileType, from_seat: int | None = None) -> Meld:
    return Meld(MeldKind.EXPOSED_KONG, tile_ids_for_type(tile_type), from_seat=from_seat)


def _pair(tile_type: TileType) -> Meld:
    return Meld(MeldKind.PAIR, tile_ids_for_type(tile_type)[:2])


def _ctx(
    *,
    seat_wind: Wind = Wind.SOUTH,
    prevailing_wind: Wind = Wind.SOUTH,
    self_drawn: bool = False,
    flowers: tuple[Flower, ...] = (),
) -> ScoringContext:
    return ScoringContext(
        seat_wind=seat_wind, prevailing_wind=prevailing_wind, self_drawn=self_drawn, flowers=flowers
    )


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
    win never gets it, even fully concealed; it gets 自摸 instead (01-rules-spec.md §7)."""
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
    """Dealer's seat wind is always East (01-rules-spec.md §2); in the East round the
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
    """01-rules-spec.md §7 note ²: 箭刻 keeps firing per dragon pung even once Small/Big Three
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
    """01-rules-spec.md §7 note ²: 門風/圈風 keep firing on their matching pung even once
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
    """01-rules-spec.md §7 note ²: terminals with no honor present is All Terminals (清么九,
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
    """01-rules-spec.md §7 note ²: honors with no terminal present is All Honors (字一色,
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
    """01-rules-spec.md §7 note ²: 混么九 stacks with 缺一門/對對糊 when their own conditions
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
    """01-rules-spec.md §7: "Faan stack: Full Flush (6) + All Pungs (3) = 9"."""
    hand = (
        _pung(TileType.PIN_1),
        _pung(TileType.PIN_3),
        _pung(TileType.PIN_5),
        _pung(TileType.PIN_7),
        _pair(TileType.PIN_9),
    )
    ctx = _ctx(seat_wind=Wind.WEST, prevailing_wind=Wind.WEST)
    scored = score_hand(hand, ctx)
    assert scored["清一色"] == 6
    assert scored["對對糊"] == 3
    assert "混一色" not in scored
    assert "缺一門" not in scored
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
