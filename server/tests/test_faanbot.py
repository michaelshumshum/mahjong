"""T2 `FaanBot` (docs/04-bots.md §2/§4/§5).

Three kinds of coverage, matching `tests/test_efficiency.py`'s established convention: (1)
legality -- `FaanBot.act` never returns an id the live mask doesn't mark legal, swept across
real self-play states, and full games actually complete; (2) scripted hands with a known
"obviously correct" value-targeting or fold decision, built directly against `SeatView`; (3) a
value-aware claim test proving T2 declines a claim T1 would take when it would drop the hand
below `min_faan`. Every scripted hand's expected shanten/ukeire/value numbers were computed
directly against `mahjong_core.shanten`/`bots.valuation` before being pinned here -- see
`bots/faanbot.py`'s `_UKEIRE_SCALE` docstring for the derivation of the "commit to the flush"
hand specifically (the same hand this file pins).
"""

from __future__ import annotations

import random
from collections.abc import Iterator

import pytest

from app.views import SeatView, seat_view
from bots.faanbot import FaanBot
from bots.random import random_action
from mahjong_core.config import RuleSet
from mahjong_core.engine import new_game, reduce, start_next_hand
from mahjong_core.melds import Meld, MeldKind
from mahjong_core.ml import decode_action, legal_mask
from mahjong_core.state import GameState, Phase, Wind
from mahjong_core.tiles import TileId, TileType, tile_ids_for_type

_STEP_CAP = 2000
_BOUNDED_RULESET = RuleSet(dealer_repeat_on_win=False, dealer_repeat_on_draw=False)
_NO_DEADLINE = float("inf")
T = TileType


def _build_view(
    seat: int,
    types: list[TileType],
    *,
    phase: Phase = Phase.AWAIT_ACTION,
    turn: int | None = None,
    discard_pools: tuple[tuple[TileId, ...], ...] | None = None,
    melds: tuple[tuple[Meld, ...], ...] | None = None,
) -> SeatView:
    """Same convention as `tests/test_efficiency.py`'s `_build_view`, extended with a `melds`
    override so fold-logic scenarios can put an exposed meld on an opponent (safety module
    reads `view.melds`, T1's version never needed to)."""
    ids = []
    used: dict[TileType, int] = {}
    for t in types:
        n = used.get(t, 0)
        ids.append(tile_ids_for_type(t)[n])
        used[t] = n + 1
    return SeatView(
        seat=seat,
        hand_no=1,
        prevailing=Wind.EAST,
        dealer=0,
        turn=turn if turn is not None else seat,
        phase=phase,
        own_hand=tuple(ids),
        concealed_counts=(len(ids), 0, 0, 0),
        melds=melds if melds is not None else ((), (), (), ()),
        discard_pools=discard_pools if discard_pools is not None else ((), (), (), ()),
        flowers=((), (), (), ()),
        wall_remaining=50,
        seat_status=("connected", "connected", "connected", "connected"),
        scores=(0, 0, 0, 0),
        legal_actions=(),
        claim_options=(),
        deadline_ts=None,
    )


def _discard_mask(types: list[TileType], *, extra: list[int] | None = None) -> list[bool]:
    mask = [False] * 109
    for t in set(types):
        mask[int(t)] = True
    for aid in extra or ():
        mask[aid] = True
    return mask


def _dummy_pool(n: int, *, base_type: int = 18) -> tuple[TileId, ...]:
    """`n` (<= 9) placeholder discards, one distinct rank each -- used only to control `turn`
    (own discard-pool length) in scripted tests. `base_type` picks which 9-rank suit band
    (18 = sou by default) to draw from; callers must pick a band their candidate hand never
    touches AND keep `n <= 9`, so no rank repeats -- a repeated rank would add a *second* copy
    to `seen34` and could spuriously trigger the one-chance signal on an unrelated tile (see
    `_FOLD_HAND_OWN_POOL`, which needs `n=13` and so cannot use this helper)."""
    assert n <= 9, "one entry per rank only -- see docstring; use an explicit pool above 9"
    ids = []
    for i in range(n):
        rank = i % 9
        ids.append(tile_ids_for_type(TileType(base_type + rank))[(i // 9) % 4])
    return tuple(ids)


# --- legality: swept across real self-play states -------------------------------------------


def _decision_points(seed: int, ruleset: RuleSet) -> Iterator[tuple[GameState, int]]:
    """Same traversal as `tests/test_efficiency.py`'s helper of the same name."""
    rng = random.Random(seed)
    state = new_game(ruleset, seed)
    steps = 0
    while state.phase != Phase.GAME_OVER:
        steps += 1
        assert steps <= _STEP_CAP, f"seed={seed}: exceeded {_STEP_CAP} steps"

        if state.phase == Phase.HAND_OVER:
            state, _ = start_next_hand(state)
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

        yield state, seat
        action = random_action(state, seat, rng)
        state, _ = reduce(state, action)


@pytest.mark.parametrize("seed", range(5))
async def test_never_returns_an_illegal_id(seed: int) -> None:
    bot = FaanBot()
    for state, seat in _decision_points(seed, _BOUNDED_RULESET):
        mask = legal_mask(state, seat)
        view = seat_view(state, seat)
        aid = await bot.act(view, mask, _NO_DEADLINE)
        assert mask[aid], f"seed={seed} seat={seat} phase={state.phase}: aid {aid} not legal"
        decode_action(aid, state, seat)  # must not raise


@pytest.mark.parametrize("seed", range(3))
async def test_full_games_complete_faanbot_vs_faanbot(seed: int) -> None:
    """Integration-level sanity: four `FaanBot`s can actually finish games end to end through
    `bots/selfplay.py`'s real `(view, mask) -> aid -> decode_action` plumbing."""
    from bots.selfplay import play_game

    bots = [FaanBot() for _ in range(4)]
    state, actions = await play_game(seed, _BOUNDED_RULESET, bots)
    assert state.phase == Phase.GAME_OVER
    assert len(actions) > 0


# --- scripted hand: commit to the flush mid-game, chase speed early --------------------------
#
# 9 man tiles (3 complete chows: 123m 456m 789m) + a wind pair (東東) + one off-suit floater
# (5p) + two more isolated honor floaters (南, 西) -- 14 tiles. Discarding 5p reaches shanten 1
# with suits_present={man} and honors present -> half_flush reachable (9 man + 3 honor >= 7,
# docs/04-bots.md §4's threshold), estimate 3+2(closed)=5. Discarding 南 (or 西) also reaches
# shanten 1 but leaves 5p in hand -> two suits present -> only voided_suit (2+2=4), with far
# more ukeire (an isolated *numbered* floater like 5p accepts many more draws than an isolated
# honor floater, which can only ever pair) -- 24 tiles accepted vs 8. Both numbers were computed
# directly against `mahjong_core.shanten`/`ukeire` and `bots.valuation.estimate_best_faan` while
# authoring this test (see `bots/faanbot.py`'s `_UKEIRE_SCALE` docstring for the exact figures).
# At early-game weights (turns <=6, w_speed=1.0/w_value=0.4) the ukeire gap dominates and 南/西
# win; at mid-game weights (turns 6-12, w_speed=0.5/w_value=1.5) the value gap flips it to 5p.

_FLUSH_HAND = [
    T.MAN_1,
    T.MAN_2,
    T.MAN_3,
    T.MAN_4,
    T.MAN_5,
    T.MAN_6,
    T.MAN_7,
    T.MAN_8,
    T.MAN_9,
    T.WIND_EAST,
    T.WIND_EAST,
    T.PIN_5,
    T.WIND_SOUTH,
    T.WIND_WEST,
]


async def test_chases_speed_early_over_committing_to_the_flush() -> None:
    view = _build_view(0, _FLUSH_HAND, turn=3, discard_pools=(_dummy_pool(3), (), (), ()))
    mask = _discard_mask(_FLUSH_HAND)
    aid = await FaanBot().act(view, mask, _NO_DEADLINE)
    assert aid == int(T.WIND_SOUTH)


async def test_commits_to_the_flush_mid_game_over_raw_ukeire() -> None:
    view = _build_view(0, _FLUSH_HAND, turn=8, discard_pools=(_dummy_pool(8), (), (), ()))
    mask = _discard_mask(_FLUSH_HAND)
    aid = await FaanBot().act(view, mask, _NO_DEADLINE)
    assert aid == int(T.PIN_5)


# --- scripted hand: fold to a safe tile late, far from tenpai, against a threat ---------------
#
# 13 fully scattered tiles (isolated singles across every suit and every honor -- deliberately
# no chow/pung shape at all) is far past 3-shanten. Turn 13 (>= `_LATE_TURN`). Seat 1 holds an
# exposed 中(DRAGON_RED) pung (`opponent_threat_level` = 1 meld * 0.3 = 0.3, at the
# `_THREAT_THRESHOLD`) and has 北(WIND_NORTH) sitting in *this seat's* own hand as a candidate
# discard that is genbutsu against seat 1 (already in seat 1's discard pool) -- weak evidence,
# but the only real read available -- while 發(DRAGON_GREEN) is a live dragon type seat 1's
# pung makes structurally pricier (`bots.safety`'s meld-danger multiplier). Fold mode should
# discard the genbutsu tile over the meld-flagged dragon even though it's not the ukeire-best
# option, matching docs/04-bots.md §4's "at 3+ shanten on turn 12 against a threatening
# opponent, discard safe tiles rather than chasing."

_FOLD_HAND = [
    T.MAN_1,
    T.MAN_4,
    T.MAN_7,
    T.PIN_2,
    T.PIN_6,
    T.SOU_3,
    T.SOU_8,
    T.WIND_EAST,
    T.WIND_SOUTH,
    T.WIND_WEST,
    T.WIND_NORTH,
    T.DRAGON_WHITE,
    T.DRAGON_GREEN,
]


_FOLD_HAND_OWN_POOL = (
    # 13 distinct types none of `_FOLD_HAND` touches (one physical tile each) -- deliberately
    # not `_dummy_pool` here: that helper cycles one suit's 9 ranks and wraps around past 9
    # entries, which would put a *second* copy of some rank into `seen34` and could spuriously
    # trigger the one-chance signal on a tile this test cares about (caught by this test itself
    # while authoring it -- see the module docstring's "verified directly" convention).
    tile_ids_for_type(T.MAN_2)[0],
    tile_ids_for_type(T.MAN_3)[0],
    tile_ids_for_type(T.MAN_5)[0],
    tile_ids_for_type(T.MAN_6)[0],
    tile_ids_for_type(T.MAN_8)[0],
    tile_ids_for_type(T.MAN_9)[0],
    tile_ids_for_type(T.PIN_1)[0],
    tile_ids_for_type(T.PIN_3)[0],
    tile_ids_for_type(T.PIN_4)[0],
    tile_ids_for_type(T.PIN_7)[0],
    tile_ids_for_type(T.PIN_8)[0],
    tile_ids_for_type(T.PIN_9)[0],
    tile_ids_for_type(T.SOU_1)[0],
)


async def test_folds_to_a_safe_tile_late_against_a_threatening_opponent() -> None:
    seat1_pung = Meld(MeldKind.PUNG, tile_ids_for_type(T.DRAGON_RED)[:3], from_seat=2)
    seat1_pool = (tile_ids_for_type(T.WIND_NORTH)[3],)  # genbutsu source for 北
    view = _build_view(
        0,
        _FOLD_HAND,
        turn=13,
        discard_pools=(_FOLD_HAND_OWN_POOL, seat1_pool, (), ()),
        melds=((), (seat1_pung,), (), ()),
    )
    mask = _discard_mask(_FOLD_HAND)
    aid = await FaanBot().act(view, mask, _NO_DEADLINE)
    assert aid == int(T.WIND_NORTH)


# --- scripted claim: value-aware guard beyond "strictly reduces shanten" ----------------------


async def test_declines_a_claim_that_would_drop_the_hand_below_min_faan() -> None:
    """7 man singles (123456 7m) + 99m + EE + 55p (13 tiles): closed Voided Suit already
    (man+pin present, +2 closed bonus = 4, verified directly against `bots.valuation` -- above
    `min_faan=3`), 1-shanten. An offered pung of 5p would strictly reduce shanten (verified:
    1 -> 0, tenpai) but the claim opens the hand -- the resulting best 13-tile shape scores only
    Voided Suit *open* (2, no closed bonus, verified directly), below `min_faan`. T1's "only if
    it strictly reduces shanten" rule alone would take this claim (it even reaches tenpai); T2's
    value guard must still decline it -- reaching tenpai on a hand that can no longer clear
    `min_faan` is exactly the failure mode docs/04-bots.md §4 exists to prevent, not a reason to
    let speed override the value check (see `_should_claim`'s docstring)."""
    hand = [
        T.MAN_1,
        T.MAN_2,
        T.MAN_3,
        T.MAN_4,
        T.MAN_5,
        T.MAN_6,
        T.MAN_7,
        T.MAN_9,
        T.MAN_9,
        T.WIND_EAST,
        T.WIND_EAST,
        T.PIN_5,
        T.PIN_5,
    ]
    discard_pools = ((), (), (), tuple(tile_ids_for_type(T.PIN_5)[2:3]))
    view = _build_view(0, hand, phase=Phase.AWAIT_CLAIMS, turn=3, discard_pools=discard_pools)
    mask = [False] * 109
    mask[102] = True
    mask[106] = True  # pung
    aid = await FaanBot().act(view, mask, _NO_DEADLINE)
    assert aid == 102  # pass
