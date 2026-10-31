"""Unit tests for `bots/labels.py` -- ground-truth danger labels from a live `GameState`
(docs/ml.md §5). Every faan value asserted below was computed once via the real
`score_winning_hand` against the exact hand-authored scenario (not hand-derived by eyeballing
yaku) -- `平糊`/`無花`/`門前清` stack on nearly any closed hand, so a "boring" hand's real faan is
routinely higher than it looks at a glance; see individual test comments for each hand's real
breakdown.
"""

from __future__ import annotations

import dataclasses

from bots.labels import (
    danger_labels_for_opponents,
    discard_counts34,
    expected_faan_if_won,
    is_tenpai,
    meld_counts34,
    seat_hand34,
    winning_tile_types,
)
from mahjong_core.config import HandSet, RuleSet
from mahjong_core.melds import Meld, MeldKind
from mahjong_core.state import GameState, new_game
from mahjong_core.tiles import TileType, tile_ids_for_type
from tests.game_state import with_seat


def _state(**overrides: object) -> GameState:
    state = new_game(RuleSet(hand_sets=frozenset(HandSet)), game_seed=1)
    return dataclasses.replace(state, **overrides)  # type: ignore[arg-type]


def _tids(tile_type: TileType, n: int = 1, start: int = 0) -> tuple[int, ...]:
    return tuple(tile_ids_for_type(tile_type)[start : start + n])


# 123m 456m 789m 11p + 45s ryanmen (waits SOU_3/SOU_6), fully concealed.
_RYANMEN_HAND = (
    *_tids(TileType.MAN_1),
    *_tids(TileType.MAN_2),
    *_tids(TileType.MAN_3),
    *_tids(TileType.MAN_4),
    *_tids(TileType.MAN_5),
    *_tids(TileType.MAN_6),
    *_tids(TileType.MAN_7),
    *_tids(TileType.MAN_8),
    *_tids(TileType.MAN_9),
    *_tids(TileType.PIN_1, 2),
    *_tids(TileType.SOU_4),
    *_tids(TileType.SOU_5),
)

# 6 pairs + a singleton East wind -- 七對子 tenpai, waiting East to complete the 7th pair.
_SEVEN_PAIRS_HAND = (
    *_tids(TileType.MAN_1, 2),
    *_tids(TileType.MAN_3, 2),
    *_tids(TileType.MAN_5, 2),
    *_tids(TileType.PIN_2, 2),
    *_tids(TileType.PIN_4, 2),
    *_tids(TileType.SOU_6, 2),
    *_tids(TileType.WIND_EAST, 1),
)

# 13 scattered, non-adjacent terminals/honors -- nowhere near tenpai under any parse.
_JUNK_HAND = (
    *_tids(TileType.MAN_1),
    *_tids(TileType.MAN_4),
    *_tids(TileType.MAN_7),
    *_tids(TileType.PIN_1),
    *_tids(TileType.PIN_4),
    *_tids(TileType.PIN_7),
    *_tids(TileType.SOU_1),
    *_tids(TileType.SOU_4),
    *_tids(TileType.SOU_7),
    *_tids(TileType.WIND_EAST),
    *_tids(TileType.WIND_SOUTH),
    *_tids(TileType.WIND_WEST),
    *_tids(TileType.WIND_NORTH),
)


def test_is_tenpai_and_winning_tile_types_for_a_ryanmen_wait() -> None:
    state = with_seat(_state(), 1, concealed=_RYANMEN_HAND, melds=(), flowers=())
    assert is_tenpai(state, 1)
    hand34 = seat_hand34(state.seats[1])
    winners = winning_tile_types(hand34, closed=True, hand_sets=state.ruleset.hand_sets)
    assert winners == [int(TileType.SOU_3), int(TileType.SOU_6)]


def test_expected_faan_if_won_returns_zero_for_a_non_winning_tile_type() -> None:
    state = with_seat(_state(), 1, concealed=_RYANMEN_HAND, melds=(), flowers=())
    assert expected_faan_if_won(state, 1, int(TileType.DRAGON_RED), discarder=2) == 0.0


def test_expected_faan_if_won_matches_the_real_scorer_for_a_valuable_hand() -> None:
    """123p 456p 789p + East pair + a 2p/4p kanchan waiting 3p -- a real half-flush. Verified
    breakdown: 混一色 3 + 平糊 1 + 無花 1 + 門前清 1 = 6, clears the default `min_faan=3`."""
    hand = (
        *_tids(TileType.PIN_1),
        *_tids(TileType.PIN_2),
        *_tids(TileType.PIN_3),
        *_tids(TileType.PIN_4),
        *_tids(TileType.PIN_5),
        *_tids(TileType.PIN_6),
        *_tids(TileType.PIN_7),
        *_tids(TileType.PIN_8),
        *_tids(TileType.PIN_9),
        *_tids(TileType.WIND_EAST, 2),
        tile_ids_for_type(TileType.PIN_2)[1],
        tile_ids_for_type(TileType.PIN_4)[1],
    )
    state = with_seat(_state(), 1, concealed=hand, melds=(), flowers=())
    assert expected_faan_if_won(state, 1, int(TileType.PIN_3), discarder=2) == 6.0


def test_expected_faan_if_won_returns_zero_for_a_structurally_complete_sub_minimum_hand() -> None:
    """Same ryanmen shape as the tenpai test above, but with the first sequence claimed (exposed)
    instead of concealed -- kills 門前清, leaving only 平糊 1 + 無花 1 = 2 faan, below the default
    `min_faan=3`. A structurally complete win that can't legally be declared is not a deal-in
    (docs/bots.md §4)."""
    exposed = Meld(
        kind=MeldKind.CHOW,
        tiles=(*_tids(TileType.MAN_1), *_tids(TileType.MAN_2), *_tids(TileType.MAN_3)),
        from_seat=0,
    )
    concealed = (
        *_tids(TileType.MAN_4),
        *_tids(TileType.MAN_5),
        *_tids(TileType.MAN_6),
        *_tids(TileType.MAN_7),
        *_tids(TileType.MAN_8),
        *_tids(TileType.MAN_9),
        *_tids(TileType.PIN_1, 2),
        *_tids(TileType.SOU_4),
        *_tids(TileType.SOU_5),
    )
    state = with_seat(_state(), 1, concealed=concealed, melds=(exposed,), flowers=())
    assert expected_faan_if_won(state, 1, int(TileType.SOU_3), discarder=0) == 0.0
    assert expected_faan_if_won(state, 1, int(TileType.SOU_6), discarder=0) == 0.0


def test_expected_faan_if_won_returns_zero_when_all_four_copies_are_already_held() -> None:
    """A concealed kong already holds all 4 physical copies of its type -- a 5th can't exist, so
    this must return 0.0 rather than raise looking for an unused physical id."""
    kong = Meld(kind=MeldKind.CONCEALED_KONG, tiles=tile_ids_for_type(TileType.DRAGON_WHITE))
    state = with_seat(_state(), 1, concealed=_tids(TileType.MAN_1, 9), melds=(kong,), flowers=())
    assert expected_faan_if_won(state, 1, int(TileType.DRAGON_WHITE), discarder=0) == 0.0


def test_is_tenpai_seven_pairs_gated_by_hand_sets() -> None:
    """Mirrors `tests/test_shanten.py::test_seven_pairs_gated_by_hand_sets` at the labels layer:
    a hand only tenpai via Seven Pairs (NEW_18) must not be reported tenpai once NEW_18 is off
    (docs/bots.md §8)."""
    state = with_seat(_state(), 1, concealed=_SEVEN_PAIRS_HAND, melds=(), flowers=())
    assert is_tenpai(state, 1)

    strict = dataclasses.replace(state, ruleset=RuleSet(hand_sets=frozenset({HandSet.CLASSIC})))
    assert not is_tenpai(strict, 1)


def test_danger_labels_for_opponents_covers_every_seat_but_self_with_real_labels() -> None:
    state = _state()
    state = with_seat(state, 1, concealed=_RYANMEN_HAND, melds=(), flowers=())
    state = with_seat(state, 2, concealed=_SEVEN_PAIRS_HAND, melds=(), flowers=())
    state = with_seat(state, 3, concealed=_JUNK_HAND, melds=(), flowers=())

    labels = danger_labels_for_opponents(state, 0)
    assert set(labels) == {1, 2, 3}

    assert labels[1].is_tenpai
    assert labels[1].winning_tiles == (int(TileType.SOU_3), int(TileType.SOU_6))
    assert labels[1].expected_faan_by_tile_type[int(TileType.SOU_3)] == 3.0
    assert labels[1].expected_faan_by_tile_type[int(TileType.SOU_6)] == 3.0
    assert sum(1 for f in labels[1].expected_faan_by_tile_type if f) == 2

    assert labels[2].is_tenpai
    assert labels[2].winning_tiles == (int(TileType.WIND_EAST),)
    assert labels[2].expected_faan_by_tile_type[int(TileType.WIND_EAST)] == 5.0

    assert not labels[3].is_tenpai
    assert labels[3].winning_tiles == ()
    assert labels[3].expected_faan_by_tile_type == (0.0,) * 34


def _chow(*types: TileType, copy: int) -> Meld:
    return Meld(
        kind=MeldKind.CHOW, tiles=tuple(tile_ids_for_type(t)[copy] for t in types), from_seat=0
    )


_PIN_CHOWS = (
    _chow(TileType.PIN_1, TileType.PIN_2, TileType.PIN_3, copy=3),
    _chow(TileType.PIN_2, TileType.PIN_3, TileType.PIN_4, copy=2),
    _chow(TileType.PIN_7, TileType.PIN_8, TileType.PIN_9, copy=3),
)


def test_is_tenpai_holds_exposed_melds_fixed() -> None:
    """11p 4p 9m beside chows 123p 234p 789p is 1-shanten. The whole-hand parse regroups the
    chows into 111p 234p 234p 789p and reads a 9m tanki; that form stays for the ML labels."""
    concealed = (*_tids(TileType.PIN_1, 2), *_tids(TileType.PIN_4), *_tids(TileType.MAN_9))
    state = with_seat(_state(), 1, concealed=concealed, melds=_PIN_CHOWS, flowers=())
    assert not is_tenpai(state, 1)
    assert is_tenpai(state, 1, melds_fixed=False)
    assert danger_labels_for_opponents(state, 0)[1].is_tenpai  # pinned ML form


def test_winning_tile_types_does_not_borrow_tiles_from_exposed_melds() -> None:
    """Concealed 1666p beside chows 123p 234p 789p waits on 1p only; the whole-hand parse also
    reads 4p/5p by regrouping the chows (docs/bots.md §3)."""
    concealed = (*_tids(TileType.PIN_1), *_tids(TileType.PIN_6, 3))
    state = with_seat(_state(), 1, concealed=concealed, melds=_PIN_CHOWS, flowers=())
    seat = state.seats[1]
    hand34 = seat_hand34(seat)
    sets = state.ruleset.hand_sets
    melds34 = meld_counts34(seat.melds)
    exact = winning_tile_types(hand34, closed=False, hand_sets=sets, melds34=melds34)
    whole = winning_tile_types(hand34, closed=False, hand_sets=sets)
    assert exact == [int(TileType.PIN_1)]
    assert {int(TileType.PIN_4), int(TileType.PIN_5)} <= set(whole)


def test_meld_counts34_matches_seat_hand34_when_concealed_is_empty() -> None:
    """`meld_counts34` is `seat_hand34` restricted to melds only -- with an empty concealed hand
    they must agree exactly."""
    kong = Meld(
        kind=MeldKind.EXPOSED_KONG, tiles=tile_ids_for_type(TileType.DRAGON_RED), from_seat=1
    )
    pung = Meld(kind=MeldKind.PUNG, tiles=tile_ids_for_type(TileType.WIND_EAST)[:3], from_seat=2)
    state = with_seat(_state(), 1, concealed=(), melds=(kong, pung), flowers=())
    assert meld_counts34(state.seats[1].melds) == seat_hand34(state.seats[1])
    # kong contributes 3, not 4 -- matches mahjong_core.shanten's convention
    assert meld_counts34(state.seats[1].melds)[int(TileType.DRAGON_RED)] == 3
    assert meld_counts34(state.seats[1].melds)[int(TileType.WIND_EAST)] == 3


def test_discard_counts34_counts_each_physical_tile_once() -> None:
    pool = (
        tile_ids_for_type(TileType.MAN_1)[0],
        tile_ids_for_type(TileType.MAN_1)[1],
        tile_ids_for_type(TileType.PIN_9)[0],
    )
    counts = discard_counts34(pool)
    assert counts[int(TileType.MAN_1)] == 2
    assert counts[int(TileType.PIN_9)] == 1
    assert sum(counts) == 3
