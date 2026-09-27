"""The `"ORACLE"` bot tier (docs/04-bots.md §10, `bots/worker.py`'s `_make_bot`).

**Design history, briefly:** an earlier version of this tier was `bots/oracle.py`'s `OracleBot`,
a full-information determinized-wall rollout search reusing `bots/search.py`'s machinery
(`bots/search.py` no longer exists -- its `SearchBot`/T3 tier was removed for the same structural
reason, docs/04-bots.md §6). Two rounds of arena validation found it was *still* statistically
worse than plain `FaanBot` despite full information, because full information was only ever used
to pick which worlds got sampled -- every candidate was still evaluated through the same noisy
few-sample `FaanBot`-driven rollout that gave `SearchBot` its own ceiling. The actual fix needed
no search at all: `bots/safety.py`'s
`tile_risk` is now hands-aware (checks `view.hands` directly, no rollout, no sampling), so a
*plain* `FaanBot()` handed an omniscient view (`app.views._omniscient_seat_view`) already computes
exact per-opponent deal-in danger through its existing `_best_discard` scoring, with zero changes
to `faanbot.py`. `bots/oracle.py` is deleted; `_make_bot("ORACLE", seed)` now just returns
`FaanBot()`.

This file covers: (1) the dispatch wiring (`_make_bot` builds a plain `FaanBot`); (2) a scripted
behavioral proof that an omniscient view changes `FaanBot`'s real discard choice -- avoiding a
real deal-in the probabilistic-only view walks straight into, the concrete case
docs/04-bots.md §5 item 1 warns about (genbutsu is not a guarantee in HK -- an opponent can
discard a tile and still legally win on it later); (3) a full self-play smoke test.

Exact per-opponent-danger unit coverage (the win-legality check itself, the min_faan boundary,
the hands-aware/hands-None regression) lives in `tests/test_safety.py`, not here -- this file is
about the `"ORACLE"` tier as a whole, not `tile_risk`'s internals.
"""

from __future__ import annotations

import random

import pytest

from app.views import SeatView, _omniscient_seat_view, seat_view
from bots.faanbot import _THREAT_THRESHOLD, FaanBot
from bots.safety import opponent_threat_level
from bots.worker import _make_bot
from mahjong_core.config import RuleSet
from mahjong_core.engine import new_game, reduce, start_next_hand
from mahjong_core.melds import Meld, MeldKind
from mahjong_core.ml import decode_action, legal_mask
from mahjong_core.state import GameState, Phase, Wind
from mahjong_core.tiles import TileId, TileType, tile_ids_for_type

_NO_DEADLINE = float("inf")
_STEP_CAP = 2000


def _pool(*types: TileType) -> tuple[TileId, ...]:
    used: dict[TileType, int] = {}
    ids = []
    for t in types:
        n = used.get(t, 0)
        ids.append(tile_ids_for_type(t)[n])
        used[t] = n + 1
    return tuple(ids)


def _view(
    seat: int,
    types: list[TileType],
    *,
    turn: int | None = None,
    discard_pools: tuple[tuple[TileId, ...], ...] | None = None,
    melds: tuple[tuple[Meld, ...], ...] | None = None,
    hands: tuple[tuple[TileId, ...], ...] | None = None,
) -> SeatView:
    """Same convention as `tests/test_faanbot.py`'s `_build_view`, duplicated for independence
    (existing repo convention -- each bot-tier test module stays separately editable), plus a
    `hands` override to build the omniscient view this file's own tests need."""
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
        phase=Phase.AWAIT_ACTION,
        own_hand=tuple(ids),
        concealed_counts=(len(ids), 0, 0, 0),
        melds=melds if melds is not None else ((), (), (), ()),
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
        hands=hands,
    )


def _discard_mask(types: list[TileType]) -> list[bool]:
    mask = [False] * 109
    for t in set(types):
        mask[int(t)] = True
    return mask


# --- dispatch wiring: "ORACLE" builds a plain FaanBot, nothing else --------------------------


def test_make_bot_oracle_tier_builds_a_plain_faanbot() -> None:
    """No dedicated class, no rollout: `bots/worker.py`'s `_make_bot("ORACLE", seed)` must
    return an ordinary `FaanBot` instance. `seed` is accepted (matches every other tier's
    signature) but unused -- `FaanBot` is stateless."""
    bot = _make_bot("ORACLE", 0)
    assert isinstance(bot, FaanBot)
    assert type(bot) is FaanBot  # not a subclass standing in for a since-deleted OracleBot


# --- behavioral proof: an omniscient view changes the real discard choice ---------------------

# A hand far from tenpai (shanten >= 3) so fold-mode's pure-defence ranking
# (`key = (risk, -tiles, terminal_rank)`) picks the discard on danger alone -- same fixture shape
# as tests/test_faanbot.py's test_folds_to_a_safe_tile_late_against_a_threatening_opponent.
_FOLD_HAND = [
    TileType.MAN_1,
    TileType.MAN_4,
    TileType.MAN_7,
    TileType.PIN_2,
    TileType.PIN_6,
    TileType.SOU_3,
    TileType.SOU_8,
    TileType.WIND_EAST,
    TileType.WIND_SOUTH,
    TileType.WIND_WEST,
    TileType.WIND_NORTH,
    TileType.DRAGON_WHITE,
    TileType.DRAGON_GREEN,
]

_FOLD_HAND_OWN_POOL = (
    tile_ids_for_type(TileType.MAN_2)[0],
    tile_ids_for_type(TileType.MAN_3)[0],
    tile_ids_for_type(TileType.MAN_5)[0],
    tile_ids_for_type(TileType.MAN_6)[0],
    tile_ids_for_type(TileType.MAN_8)[0],
    tile_ids_for_type(TileType.MAN_9)[0],
    tile_ids_for_type(TileType.PIN_1)[0],
    tile_ids_for_type(TileType.PIN_3)[0],
    tile_ids_for_type(TileType.PIN_4)[0],
    tile_ids_for_type(TileType.PIN_7)[0],
    tile_ids_for_type(TileType.PIN_8)[0],
    tile_ids_for_type(TileType.PIN_9)[0],
    tile_ids_for_type(TileType.SOU_1)[0],
)


async def test_omniscient_view_avoids_a_real_deal_in_the_probabilistic_view_walks_into() -> None:
    """The concrete case docs/04-bots.md §5 item 1 warns about: genbutsu is not a guarantee in
    HK. Seat 1 already discarded 北 (`WIND_NORTH`) -- the probabilistic model reads that as
    (weak) evidence 北 is safe against them -- but their real hand (reshaped since that discard)
    is one 北 away from a live Seven Pairs, clearing the default `min_faan=3`. Seat 2 separately
    holds an exposed 中 (`DRAGON_RED`) pung, which bumps every dragon's probabilistic danger
    (`bots/safety.py`'s meld-danger multiplier applies to any dragon once any dragon pung is
    visible) -- including 發 (`DRAGON_GREEN`), which seat 2's own real hand can't actually use.

    Under the ordinary (probabilistic-only) view, `FaanBot` reads 北 as the safest discard and
    plays straight into the real deal-in. Under the omniscient view -- same table, `.hands`
    populated -- `tile_risk` computes 北's real danger exactly and `FaanBot` must avoid it,
    with zero changes to `faanbot.py` itself.
    """
    dragon_pung = Meld(MeldKind.PUNG, tile_ids_for_type(TileType.DRAGON_RED)[:3], from_seat=0)
    seat1_pool = (tile_ids_for_type(TileType.WIND_NORTH)[3],)  # genbutsu source for 北
    melds = ((), (), (dragon_pung,), ())
    discard_pools = (_FOLD_HAND_OWN_POOL, seat1_pool, (), ())

    probabilistic_view = _view(0, _FOLD_HAND, turn=13, discard_pools=discard_pools, melds=melds)
    mask = _discard_mask(_FOLD_HAND)

    # seat 1's real hand: Seven Pairs, one 北 short of completing it (4 faan, clears min_faan=3)
    # -- reshaped since discarding their first 北, legal under HK's no-furiten rule.
    seat1_hand = _pool(
        TileType.MAN_2,
        TileType.MAN_2,
        TileType.MAN_3,
        TileType.MAN_3,
        TileType.MAN_5,
        TileType.MAN_5,
        TileType.PIN_1,
        TileType.PIN_1,
        TileType.PIN_3,
        TileType.PIN_3,
        TileType.PIN_5,
        TileType.PIN_5,
        TileType.WIND_NORTH,
    )
    # seat 2's real hand: nowhere near tenpai on anything, including 發 -- the exposed 中 pung
    # bumped 發's probabilistic reading, but the real hand can't back it up.
    seat2_hand = _pool(
        TileType.MAN_2,
        TileType.MAN_4,
        TileType.MAN_6,
        TileType.MAN_8,
        TileType.SOU_2,
        TileType.SOU_4,
        TileType.SOU_6,
        TileType.WIND_EAST,
        TileType.WIND_SOUTH,
        TileType.WIND_WEST,
    )
    hands = ((), seat1_hand, seat2_hand, ())
    omniscient_view = _view(
        0, _FOLD_HAND, turn=13, discard_pools=discard_pools, melds=melds, hands=hands
    )

    probabilistic_result = await FaanBot().act(probabilistic_view, mask, _NO_DEADLINE)
    omniscient_result = await FaanBot().act(omniscient_view, mask, _NO_DEADLINE)

    assert probabilistic_result == int(TileType.WIND_NORTH), (
        "sanity: the probabilistic-only view must actually walk into this deal-in, or the rest "
        "of this test proves nothing"
    )
    assert omniscient_result != int(TileType.WIND_NORTH), (
        "the omniscient view must avoid the real deal-in the probabilistic view missed"
    )


# --- behavioral proof: real shanten (not the meld/tempo proxy) decides whether to fold --------


async def test_omniscient_view_folds_against_a_tenpai_opponent_the_proxy_reads_as_safe() -> None:
    """Isolates the fold-*timing* fix (`opponent_threat_level`'s hands-aware branch,
    `bots/safety.py`) from the deal-in-*avoidance* fix (`tile_risk`'s, already proven above):
    seat 1 holds zero melds and an empty discard pool -- the probabilistic proxy reads them as
    zero threat, well below `_THREAT_THRESHOLD`, so `_best_discard`'s `fold_mode` gate never
    engages under the ordinary view even though this seat's own hand is far past `_FOLD_SHANTEN`
    on a late turn. Seat 1's real hand (omniscient view) is genuinely tenpai, tanki-waiting on
    4萬 (`MAN_4`) -- exactly the tile `_best_discard`'s ordinary value-weighted scoring picks
    anyway (highest ukeire among the candidates, nothing telling it otherwise). Under the
    ordinary view `FaanBot` walks straight into it, same as it would with no threat model at
    all. Under the omniscient view, real shanten correctly flags seat 1 as threatening, fold
    mode engages, and -- now combined with `tile_risk`'s own hands-aware exact danger --
    `FaanBot` avoids 4萬 specifically. Both mechanisms have to fire for this outcome: fold mode
    alone (a threat flag with no exact per-tile danger) wouldn't single out 4萬 over any other
    candidate, and exact `tile_risk` alone with fold mode never engaging wouldn't change
    `_best_discard`'s scoring formula at all -- this is the concrete gap docs/04-bots.md §10
    names as the reason `opponent_threat_level` needed the same hands-aware treatment
    `tile_risk` already got."""
    tenpai_hand = _pool(
        TileType.PIN_1,
        TileType.PIN_2,
        TileType.PIN_3,
        TileType.PIN_4,
        TileType.PIN_5,
        TileType.PIN_6,
        TileType.PIN_7,
        TileType.PIN_8,
        TileType.PIN_9,
        TileType.SOU_1,
        TileType.SOU_2,
        TileType.SOU_3,
        TileType.MAN_4,
    )
    discard_pools = (_FOLD_HAND_OWN_POOL, (), (), ())
    mask = _discard_mask(_FOLD_HAND)

    probabilistic_view = _view(0, _FOLD_HAND, turn=13, discard_pools=discard_pools)
    omniscient_view = _view(
        0, _FOLD_HAND, turn=13, discard_pools=discard_pools, hands=((), tenpai_hand, (), ())
    )

    assert opponent_threat_level(probabilistic_view, 1) < _THREAT_THRESHOLD, (
        "sanity: the probabilistic proxy must genuinely read seat 1 as not-threatening here"
    )
    assert opponent_threat_level(omniscient_view, 1) >= _THREAT_THRESHOLD, (
        "sanity: seat 1's real tenpai hand must genuinely flag as threatening"
    )

    probabilistic_result = await FaanBot().act(probabilistic_view, mask, _NO_DEADLINE)
    omniscient_result = await FaanBot().act(omniscient_view, mask, _NO_DEADLINE)

    assert probabilistic_result == int(TileType.MAN_4), (
        "sanity: the ordinary view must actually walk into this deal-in, or the rest of this "
        "test proves nothing"
    )
    assert omniscient_result != int(TileType.MAN_4), (
        "the omniscient view's corrected fold-timing must avoid the real deal-in the ordinary "
        "view's fold gate never even considered"
    )


# --- self-play smoke test ----------------------------------------------------------------------


async def _play_oracle_tier_vs_faanbot(seed: int, ruleset: RuleSet) -> GameState:
    """`_make_bot("ORACLE", seed)`'s seat gets a real omniscient view every decision -- unlike
    `bots/selfplay.py`'s `play_game`, which only ever builds ordinary views -- so this exercises
    the real dispatch shape (`_omniscient_seat_view` + a plain `FaanBot`) rather than a fallback."""
    oracle_seat = 0
    bots = [_make_bot("ORACLE", seed), FaanBot(), FaanBot(), FaanBot()]
    rng = random.Random(seed)
    state = new_game(ruleset, seed)
    steps = 0
    while state.phase != Phase.GAME_OVER:
        steps += 1
        if steps > _STEP_CAP:
            raise RuntimeError(f"seed={seed}: exceeded {_STEP_CAP} steps -- possible deadlock")
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
        view = _omniscient_seat_view(state, seat) if seat == oracle_seat else seat_view(state, seat)
        mask = legal_mask(state, seat)
        aid = await bots[seat].act(view, mask, _NO_DEADLINE)
        action = decode_action(aid, state, seat)
        state, _ = reduce(state, action)
    return state


@pytest.mark.slow
@pytest.mark.parametrize("seed", range(2))
async def test_full_games_complete_oracle_tier_vs_faanbot(seed: int) -> None:
    _BOUNDED_RULESET = RuleSet(dealer_repeat_on_win=False, dealer_repeat_on_draw=False)
    state = await _play_oracle_tier_vs_faanbot(seed, _BOUNDED_RULESET)
    assert state.phase == Phase.GAME_OVER
