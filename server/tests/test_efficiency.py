"""T1 `EfficiencyBot` (docs/bots.md §2/§3).

Two kinds of coverage: (1) legality -- `EfficiencyBot.act` never returns an id the live mask
doesn't mark legal, swept across real self-play states (same machinery as `tests/test_ml.py`),
and full games actually complete; (2) scripted hands with a known "obviously correct" answer,
built directly against `SeatView` rather than through the engine, so each test isolates exactly
the decision under test. Every scripted hand below was verified against
`mahjong_core.shanten`/`ukeire` directly before being pinned as an assertion -- see the sub-task
report for the derivation, not repeated in comments here.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.views import SeatView, seat_view
from bots.base import NO_DEADLINE
from bots.efficiency import EfficiencyBot
from bots.features import after_claim34
from mahjong_core.config import RuleSet
from mahjong_core.melds import Meld, MeldKind
from mahjong_core.ml import (
    CHOW_HIGH_ID,
    CHOW_LOW_ID,
    CHOW_MIDDLE_ID,
    PASS_ID,
    PUNG_ID,
    decode_action,
    legal_mask,
)
from mahjong_core.state import Phase, Wind
from mahjong_core.tiles import TileId, TileType, new_count_array, tile_ids_for_type
from tests.decisions import decision_points, discard_mask

_BOUNDED_RULESET = RuleSet(dealer_repeat_on_win=False, dealer_repeat_on_draw=False)


def _build_view(
    seat: int,
    types: list[TileType],
    *,
    phase: Phase = Phase.AWAIT_ACTION,
    turn: int | None = None,
    discard_pools: tuple[tuple[TileId, ...], ...] | None = None,
    melds: tuple[Meld, ...] = (),
) -> SeatView:
    """A minimal, hand-built `SeatView` carrying exactly what `EfficiencyBot.act` reads:
    `own_hand`, `melds[seat]`, `phase`, `turn`, `discard_pools`. Every other field is a harmless
    placeholder."""
    ids = []
    used: dict[TileType, int] = {}
    for t in types:
        i = used.get(t, 0)
        ids.append(tile_ids_for_type(t)[i])
        used[t] = i + 1
    return SeatView(
        seat=seat,
        hand_no=1,
        prevailing=Wind.EAST,
        dealer=0,
        turn=turn if turn is not None else seat,
        phase=phase,
        own_hand=tuple(ids),
        concealed_counts=(len(ids), 0, 0, 0),
        melds=tuple(melds if s == seat else () for s in range(4)),
        discard_pools=discard_pools if discard_pools is not None else ((), (), (), ()),
        flowers=((), (), (), ()),
        wall_remaining=50,
        seat_status=("connected", "connected", "connected", "connected"),
        names=(None, None, None, None),
        scores=(0, 0, 0, 0),
        legal_actions=(),
        claim_options=(),
        deadline_ts=None,
        host_seat=None,
        ruleset=RuleSet(),
    )


# --- legality: swept across real self-play states -------------------------------------------


@pytest.mark.parametrize("seed", range(5))
async def test_never_returns_an_illegal_id(seed: int) -> None:
    bot = EfficiencyBot()
    for state, seat in decision_points(seed, _BOUNDED_RULESET):
        mask = legal_mask(state, seat)
        view = seat_view(state, seat)
        aid = await bot.act(view, mask, NO_DEADLINE)
        assert mask[aid], f"seed={seed} seat={seat} phase={state.phase}: aid {aid} not legal"
        decode_action(aid, state, seat)  # must not raise


@pytest.mark.slow
@settings(
    max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(seed=st.integers(min_value=0, max_value=2**31 - 1))
async def test_never_returns_an_illegal_id_hypothesis(seed: int) -> None:
    """Slow-tier: broader seed coverage than the fixed parametrize above, same assertion."""
    bot = EfficiencyBot()
    for state, seat in decision_points(seed, _BOUNDED_RULESET):
        mask = legal_mask(state, seat)
        view = seat_view(state, seat)
        aid = await bot.act(view, mask, NO_DEADLINE)
        assert mask[aid]


@pytest.mark.parametrize("seed", range(3))
async def test_full_games_complete_efficiencybot_vs_efficiencybot(seed: int) -> None:
    """Integration-level sanity: four `EfficiencyBot`s can actually finish games end to end
    through `bots/selfplay.py`'s real `(view, mask) -> aid -> decode_action` plumbing."""
    from bots.selfplay import play_game

    bots = [EfficiencyBot() for _ in range(4)]
    state, actions = await play_game(seed, _BOUNDED_RULESET, bots)
    assert state.phase == Phase.GAME_OVER
    assert len(actions) > 0


# --- scripted hands: discard rule -------------------------------------------------------------

T = TileType


async def test_discard_keeps_tenpai_over_breaking_a_complete_meld() -> None:
    """123m 456p 789s 123s + 5m (tanki) + a spare 9m: the only shanten-preserving discard is
    the spare 9m (or symmetrically 5m); discarding into a complete meld is strictly worse."""
    hand = [
        T.MAN_1,
        T.MAN_2,
        T.MAN_3,
        T.PIN_4,
        T.PIN_5,
        T.PIN_6,
        T.SOU_7,
        T.SOU_8,
        T.SOU_9,
        T.SOU_1,
        T.SOU_2,
        T.SOU_3,
        T.MAN_5,
        T.MAN_9,
    ]
    view = _build_view(0, hand)
    mask = discard_mask(hand, extra=[102])
    aid = await EfficiencyBot().act(view, mask, NO_DEADLINE)
    assert aid == int(T.MAN_9)


async def test_discard_prefers_honor_on_an_exact_tie() -> None:
    """3 melds + pair(White) + two floaters (East, Pin5) with identical live-tile counts:
    discarding either floater leaves an identical (shanten, tiles_accepted, kinds_accepted) --
    only the terminal/honor tiebreak distinguishes them, and it must prefer East."""
    hand = [
        T.MAN_1,
        T.MAN_2,
        T.MAN_3,
        T.PIN_1,
        T.PIN_2,
        T.PIN_3,
        T.SOU_7,
        T.SOU_8,
        T.SOU_9,
        T.DRAGON_WHITE,
        T.DRAGON_WHITE,
        T.DRAGON_WHITE,
        T.WIND_EAST,
        T.PIN_5,
    ]
    view = _build_view(0, hand)
    mask = discard_mask(hand, extra=[102])
    aid = await EfficiencyBot().act(view, mask, NO_DEADLINE)
    assert aid == int(T.WIND_EAST)


# --- scripted hands: claim rule ("only if it strictly reduces shanten") -----------------------


async def test_claims_pung_when_it_strictly_reduces_shanten() -> None:
    """3 melds + pair(Red) + a 4th-meld tatsu, 13 tiles, 2-shanten. Claiming a pung of Red
    strictly improves this (verified directly against mahjong_core.shanten: 2 -> 1)."""
    hand = [
        T.MAN_1,
        T.MAN_2,
        T.MAN_3,
        T.PIN_4,
        T.PIN_5,
        T.PIN_6,
        T.DRAGON_RED,
        T.DRAGON_RED,
        T.SOU_1,
        T.SOU_1,
        T.WIND_EAST,
        T.WIND_SOUTH,
        T.WIND_WEST,
    ]
    discard_pools = ((), (), (), tuple(tile_ids_for_type(T.SOU_1)[2:3]))
    view = _build_view(0, hand, phase=Phase.AWAIT_CLAIMS, turn=3, discard_pools=discard_pools)
    mask = [False] * 109
    mask[102] = True
    mask[106] = True  # pung
    aid = await EfficiencyBot().act(view, mask, NO_DEADLINE)
    assert aid == 106


async def test_declines_pung_when_it_does_not_strictly_reduce_shanten() -> None:
    """3 melds + pair(Red) + tatsu(4s5s): already tenpai. Claiming pung of Red still leaves
    tenpai after the best follow-up discard (0 -> 0, verified directly) -- not strictly
    better, so the rule says pass, not "any legal pung is free value."""
    hand = [
        T.MAN_1,
        T.MAN_2,
        T.MAN_3,
        T.PIN_4,
        T.PIN_5,
        T.PIN_6,
        T.SOU_7,
        T.SOU_8,
        T.SOU_9,
        T.DRAGON_RED,
        T.DRAGON_RED,
        T.SOU_4,
        T.SOU_5,
    ]
    discard_pools = ((), (), (), tuple(tile_ids_for_type(T.DRAGON_RED)[2:3]))
    view = _build_view(0, hand, phase=Phase.AWAIT_CLAIMS, turn=3, discard_pools=discard_pools)
    mask = [False] * 109
    mask[102] = True
    mask[106] = True
    aid = await EfficiencyBot().act(view, mask, NO_DEADLINE)
    assert aid == 102


async def test_never_declares_a_self_kong() -> None:
    """Holding all 4 copies of a tile concealed never strictly helps (a kong always counts as
    exactly 3 tiles in the shanten array, same as a plain triplet) -- see bots/efficiency.py's
    module docstring. The bot must discard instead of declaring the legal concealed kong."""
    hand = [
        T.MAN_1,
        T.MAN_1,
        T.MAN_1,
        T.MAN_1,
        T.PIN_4,
        T.PIN_5,
        T.PIN_6,
        T.SOU_7,
        T.SOU_8,
        T.SOU_9,
        T.SOU_1,
        T.SOU_2,
        T.SOU_3,
        T.WIND_EAST,
    ]
    view = _build_view(0, hand)
    mask = discard_mask(hand, extra=[102, 34 + int(T.MAN_1)])
    aid = await EfficiencyBot().act(view, mask, NO_DEADLINE)
    assert aid != 34 + int(T.MAN_1)
    assert aid < 34  # took a discard, not the kong


def _chow(*types: TileType, copy: int) -> Meld:
    return Meld(MeldKind.CHOW, tuple(tile_ids_for_type(t)[copy] for t in types), from_seat=3)


_THREE_PIN_CHOWS = (
    _chow(T.PIN_1, T.PIN_2, T.PIN_3, copy=3),
    _chow(T.PIN_2, T.PIN_3, T.PIN_4, copy=2),
    _chow(T.PIN_7, T.PIN_8, T.PIN_9, copy=3),
)


async def test_discard_does_not_count_waits_borrowed_from_exposed_melds() -> None:
    """Concealed 1p 666p 1m beside chows 123p 234p 789p. Discarding 1m leaves 1666p, whose only
    real wait is 1p (2 live); the whole-hand parse regroups the chows and also reads 4p/5p (9
    live). Discarding 1p leaves a 1m tanki (3 live), the better real wait."""
    hand = [T.PIN_1, T.PIN_6, T.PIN_6, T.PIN_6, T.MAN_1]
    view = _build_view(0, hand, melds=_THREE_PIN_CHOWS)
    aid = await EfficiencyBot().act(view, discard_mask(hand), NO_DEADLINE)
    assert aid == int(T.PIN_1)


async def test_claim_scores_each_chow_variant_on_the_tiles_it_locks() -> None:
    """5p is discarded to a 1-shanten hand holding 1p 4p 6p 77p. 456p (middle) locks 4p6p and
    leaves 77p beside 123m 123s EE: tenpai after dropping 1p. 567p (low, listed first) breaks the
    77p pair and stays 1-shanten. The whole-hand form scored every variant alike and took low."""
    hand = [
        T.MAN_1, T.MAN_2, T.MAN_3, T.SOU_1, T.SOU_2, T.SOU_3, T.WIND_EAST, T.WIND_EAST,
        T.PIN_1, T.PIN_4, T.PIN_6, T.PIN_7, T.PIN_7,
    ]  # fmt: skip
    pools = ((), (), (), (tile_ids_for_type(T.PIN_5)[0],))
    view = _build_view(0, hand, phase=Phase.AWAIT_CLAIMS, turn=3, discard_pools=pools)
    mask = [False] * 109
    mask[PASS_ID] = mask[CHOW_LOW_ID] = mask[CHOW_MIDDLE_ID] = True
    assert await EfficiencyBot().act(view, mask, NO_DEADLINE) == CHOW_MIDDLE_ID


def test_after_claim34_removes_the_locked_tiles_not_the_claimed_one() -> None:
    """Claimed 5p: low chow is 567p, middle 456p, high 345p."""
    concealed = new_count_array()
    for t in (T.PIN_3, T.PIN_4, T.PIN_6, T.PIN_7, T.PIN_5):
        concealed[int(t)] += 1
    claimed = int(T.PIN_5)
    low = after_claim34(concealed, claimed, CHOW_LOW_ID)
    middle = after_claim34(concealed, claimed, CHOW_MIDDLE_ID)
    high = after_claim34(concealed, claimed, CHOW_HIGH_ID)
    pung = after_claim34([*concealed[:claimed], 2, *concealed[claimed + 1 :]], claimed, PUNG_ID)
    assert (low[int(T.PIN_6)], low[int(T.PIN_7)], low[claimed]) == (0, 0, 1)
    assert (middle[int(T.PIN_4)], middle[int(T.PIN_6)], middle[claimed]) == (0, 0, 1)
    assert (high[int(T.PIN_3)], high[int(T.PIN_4)], high[claimed]) == (0, 0, 1)
    assert pung[claimed] == 0


async def test_win_always_takes_priority() -> None:
    view = _build_view(0, [T.MAN_1] * 4)
    mask = [False] * 109
    mask[0] = True
    mask[108] = True
    aid = await EfficiencyBot().act(view, mask, NO_DEADLINE)
    assert aid == 108
