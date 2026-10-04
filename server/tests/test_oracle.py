"""The `"ORACLE"` bot tier (docs/bots.md §9, `bots/worker.py`'s `_make_bot`).

**Design history, briefly:** an earlier version of this tier was `bots/oracle.py`'s `OracleBot`,
a full-information determinized-wall rollout search reusing `bots/search.py`'s machinery
(`bots/search.py` no longer exists -- its `SearchBot`/T3 tier was removed for the same structural
reason, docs/decisions/0012-searchbot-removed.md). Two rounds of arena validation found it was *still* statistically
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
docs/bots.md §5 item 1 warns about (genbutsu is not a guarantee in HK -- an opponent can
discard a tile and still legally win on it later); (3) a full self-play smoke test.

Exact per-opponent-danger unit coverage (the win-legality check itself, the min_faan boundary,
the hands-aware/hands-None regression) lives in `tests/test_safety.py`, not here -- this file is
about the `"ORACLE"` tier as a whole, not `tile_risk`'s internals.
"""

from __future__ import annotations

import random

import pytest

from app.views import SeatView, _omniscient_seat_view, seat_view
from bots.faanbot import _ADDED_KONG_BASE, _THREAT_THRESHOLD, FaanBot
from bots.features import own_hand34, seen34
from bots.safety import opponent_threat_level, tile_risk
from bots.worker import _make_bot
from mahjong_core.config import RuleSet
from mahjong_core.engine import new_game, reduce, start_next_hand
from mahjong_core.melds import Meld, MeldKind
from mahjong_core.ml import decode_action, legal_mask
from mahjong_core.shanten import shanten, ukeire
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

# far from tenpai (shanten >= 3) so fold-mode's pure-defence ranking (risk, -tiles,
# terminal_rank) picks the discard on danger alone -- same shape as test_faanbot.py's fold test.
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
    """The concrete case docs/bots.md §5 item 1 warns about: genbutsu is not a guarantee in
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


# --- certain deal-ins: never discarded while a safe tile exists (ADR 0019 §5.1) ----------------

# found by search: 北 is the hands=None discard, and stays the shanten-best one under the omniscient
# view while it deals in.
_NORTH_IS_BEST = [
    TileType.MAN_2,
    TileType.MAN_3,
    TileType.MAN_4,
    TileType.MAN_5,
    TileType.MAN_6,
    TileType.MAN_7,
    TileType.MAN_8,
    TileType.MAN_9,
    TileType.PIN_1,
    TileType.PIN_2,
    TileType.PIN_3,
    TileType.SOU_4,
    TileType.SOU_5,
    TileType.WIND_NORTH,
]

# 9 own discards: mid-game, where w_safety is 0.3.
_MID_GAME_OWN_POOL = _pool(
    TileType.WIND_EAST,
    TileType.WIND_SOUTH,
    TileType.WIND_WEST,
    TileType.DRAGON_WHITE,
    TileType.DRAGON_GREEN,
    TileType.DRAGON_RED,
    TileType.SOU_9,
    TileType.PIN_9,
    TileType.PIN_8,
)

# seven pairs one 北 short.
_SEVEN_PAIRS_ON_NORTH = _pool(
    TileType.SOU_1,
    TileType.SOU_1,
    TileType.SOU_3,
    TileType.SOU_3,
    TileType.PIN_5,
    TileType.PIN_5,
    TileType.PIN_6,
    TileType.PIN_6,
    TileType.SOU_6,
    TileType.SOU_6,
    TileType.PIN_7,
    TileType.PIN_7,
    TileType.WIND_NORTH,
)


async def test_omniscient_view_never_discards_a_certain_deal_in_when_a_safe_tile_exists() -> None:
    discard_pools = (_MID_GAME_OWN_POOL, (), (), ())
    hands = ((), _SEVEN_PAIRS_ON_NORTH, (), ())
    mask = _discard_mask(_NORTH_IS_BEST)
    probabilistic_view = _view(0, _NORTH_IS_BEST, discard_pools=discard_pools)
    omniscient_view = _view(0, _NORTH_IS_BEST, discard_pools=discard_pools, hands=hands)
    north = int(TileType.WIND_NORTH)
    assert tile_risk(omniscient_view, north) > 0.0

    assert await FaanBot().act(probabilistic_view, mask, _NO_DEADLINE) == north, (
        "sanity: hands=None keeps the shanten-best discard"
    )
    chosen = await FaanBot().act(omniscient_view, mask, _NO_DEADLINE)
    assert chosen != north
    assert tile_risk(omniscient_view, chosen) == 0.0


async def test_omniscient_view_discards_the_cheapest_deal_in_when_every_discard_deals_in() -> None:
    """only 北 and 西 are legal; 西 completes two opponents' hands, 北 one."""
    seven_pairs_on_west = (
        _pool(
            TileType.PIN_1,
            TileType.PIN_1,
            TileType.PIN_3,
            TileType.PIN_3,
            TileType.PIN_5,
            TileType.PIN_5,
            TileType.PIN_6,
            TileType.PIN_6,
            TileType.PIN_7,
            TileType.PIN_7,
            TileType.DRAGON_RED,
            TileType.DRAGON_RED,
        )
        + (tile_ids_for_type(TileType.WIND_WEST)[0],),
        _pool(
            TileType.MAN_1,
            TileType.MAN_1,
            TileType.MAN_3,
            TileType.MAN_3,
            TileType.MAN_5,
            TileType.MAN_5,
            TileType.MAN_6,
            TileType.MAN_6,
            TileType.MAN_7,
            TileType.MAN_7,
            TileType.DRAGON_WHITE,
            TileType.DRAGON_WHITE,
        )
        + (tile_ids_for_type(TileType.WIND_WEST)[1],),
    )
    own = [*_NORTH_IS_BEST]
    own[-2] = TileType.WIND_WEST  # both honors isolated: the two discards tie on speed and value
    hands = ((), _SEVEN_PAIRS_ON_NORTH, *seven_pairs_on_west)
    discard_pools = (_MID_GAME_OWN_POOL[:6], (), (), ())
    view = _view(0, own, discard_pools=discard_pools, hands=hands)
    mask = _discard_mask([TileType.WIND_NORTH, TileType.WIND_WEST])
    north, west = int(TileType.WIND_NORTH), int(TileType.WIND_WEST)
    assert 0.0 < tile_risk(view, north) < tile_risk(view, west)

    assert await FaanBot().act(view, mask, _NO_DEADLINE) == north


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
    `_best_discard`'s scoring formula at all -- this is the concrete gap docs/bots.md §9
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


# --- behavioral proof: hands-aware seen34 changes a real offense-side discard choice ----------

# 13 distinct singles, found by direct search over FaanBot.act (verified against seen34/ukeire
# below): 2-shanten, with PIN_9's ukeire unusually wide (16 kinds/58 tiles) among candidates.
_UKEIRE_HAND = [
    TileType.MAN_3,
    TileType.WIND_NORTH,
    TileType.PIN_7,
    TileType.SOU_6,
    TileType.SOU_8,
    TileType.PIN_4,
    TileType.PIN_5,
    TileType.SOU_4,
    TileType.MAN_6,
    TileType.PIN_3,
    TileType.PIN_9,
    TileType.SOU_5,
    TileType.SOU_9,
]


async def test_omniscient_view_prefers_a_discard_with_more_real_live_tiles() -> None:
    """`seen34` becoming hands-aware (docs/bots.md §9) closes an offense-side gap distinct
    from `tile_risk`/`opponent_threat_level`'s defense-side fixes above. Turn 3 (well before
    `late_turn`) keeps `fold_mode` off entirely, isolating this from both of those fixes.

    Seat 1 holds 3 of 東's (`WIND_EAST`) 4 real copies in their concealed hand -- genuinely dead
    to the wall, not drawable by anyone. Under the probabilistic view none of that is visible, so
    discarding 9筒 (`PIN_9`) reads as the speed-maximising choice (16 kinds/58 tiles of ukeire,
    all 4 WIND_EAST copies counted as still live). Under the omniscient view, `seen34` correctly
    counts seat 1's 3 real copies as seen, PIN_9's ukeire drops to 14 kinds/51 tiles, and
    `FaanBot`'s composite score (docs/bots.md §4) picks a different discard (北, `WIND_NORTH`)
    instead. `tile_risk` is not the mechanism flipping this choice -- it reads identically for
    both candidate discards within each view (0.9 probabilistic / 0.0 exact, checked below), so
    it cannot be what tips PIN_9 below WIND_NORTH; the only thing that differs between the two
    views for these two specific candidates is PIN_9's own ukeire count.
    """
    hidden_type = TileType.WIND_EAST
    opp1_hand = _pool(
        hidden_type,
        hidden_type,
        hidden_type,
        TileType.WIND_SOUTH,
        TileType.WIND_SOUTH,
        TileType.WIND_SOUTH,
        TileType.WIND_SOUTH,
        TileType.WIND_WEST,
        TileType.WIND_WEST,
        TileType.WIND_WEST,
        TileType.WIND_WEST,
        TileType.DRAGON_RED,
        TileType.DRAGON_RED,
    )
    opp2_hand = _pool(
        TileType.WIND_NORTH,
        TileType.WIND_NORTH,
        TileType.WIND_NORTH,
        TileType.WIND_NORTH,
        TileType.DRAGON_WHITE,
        TileType.DRAGON_WHITE,
        TileType.DRAGON_WHITE,
        TileType.DRAGON_WHITE,
        TileType.DRAGON_GREEN,
        TileType.DRAGON_GREEN,
        TileType.DRAGON_GREEN,
        TileType.DRAGON_GREEN,
        TileType.MAN_1,
    )
    opp3_hand = _pool(
        TileType.PIN_9,
        TileType.PIN_9,
        TileType.PIN_9,
        TileType.PIN_9,
        TileType.SOU_9,
        TileType.SOU_9,
        TileType.SOU_9,
        TileType.SOU_9,
        TileType.MAN_9,
        TileType.MAN_9,
        TileType.MAN_9,
        TileType.MAN_9,
        TileType.PIN_1,
    )
    hands = ((), opp1_hand, opp2_hand, opp3_hand)
    mask = _discard_mask(_UKEIRE_HAND)

    probabilistic_view = _view(0, _UKEIRE_HAND, turn=3)
    omniscient_view = _view(0, _UKEIRE_HAND, turn=3, hands=hands)

    hand34 = own_hand34(probabilistic_view)
    pin9, wind_north = int(TileType.PIN_9), int(TileType.WIND_NORTH)
    accepts_ordinary = ukeire(hand34, seen34(probabilistic_view))
    accepts_aware = ukeire(hand34, seen34(omniscient_view))
    assert accepts_ordinary[pin9] == (16, 58), (
        "sanity: the probabilistic view must read PIN_9's ukeire this wide, or this proves nothing"
    )
    assert accepts_aware[pin9] == (14, 51), (
        "hands-aware seen34 must shrink PIN_9's ukeire once WIND_EAST's hidden copies count as seen"
    )
    assert accepts_ordinary[wind_north] == accepts_aware[wind_north], (
        "sanity: WIND_NORTH's own ukeire must be unaffected -- isolates the effect to PIN_9's "
        "accepting set specifically"
    )
    assert tile_risk(probabilistic_view, pin9) == tile_risk(probabilistic_view, wind_north), (
        "sanity: tile_risk must not itself distinguish these two candidates under the "
        "probabilistic view"
    )
    assert tile_risk(omniscient_view, pin9) == tile_risk(omniscient_view, wind_north), (
        "sanity: tile_risk must not itself distinguish these two candidates under the "
        "omniscient view either -- the flip below is seen34's doing, not tile_risk's"
    )

    probabilistic_result = await FaanBot().act(probabilistic_view, mask, _NO_DEADLINE)
    omniscient_result = await FaanBot().act(omniscient_view, mask, _NO_DEADLINE)

    assert probabilistic_result == int(TileType.PIN_9), (
        "sanity: the probabilistic view must actually pick PIN_9, or the rest of this test "
        "proves nothing"
    )
    assert omniscient_result == int(TileType.WIND_NORTH), (
        "the omniscient view's corrected ukeire count must change the actual discard chosen"
    )


# --- behavioral proof: an omniscient view avoids declaring a kong that would be robbed --------


async def test_omniscient_view_avoids_a_kong_that_would_be_robbed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`bots/faanbot.py`'s kong loop (`_act_on_turn`) declares whichever legal self-kong strictly
    reduces shanten furthest -- with no safety check at all before this fix, docs/bots.md §9.

    Provable, pre-existing fact about `mahjong_core.shanten.shanten`, unrelated to this fix:
    removing a redundant 4th copy from an already-complete group (exactly what declaring a
    self-kong does to the 34-array) can never *lower* shanten -- `shanten` is monotonic in any
    single tile type's count, confirmed by exhaustive random search (0 counterexamples across
    500,000 random hands, both kong kinds). So the kong loop's own `s < best_kong_shanten`
    comparison can never actually be won by a real hand, making `best_kong_aid` always `None` in
    practice regardless of this fix. This test stubs `shanten` -- transparently: every call
    except the exact post-kong candidate array falls through to the real function -- purely to
    force that otherwise-unreachable precondition so this fix's own gating logic, which sits
    *inside* that loop, can be exercised at all.

    Seat 0 holds an exposed 中 (`DRAGON_RED`) pung plus its 4th copy concealed -- a legal added
    kong exposing 中. Seat 1's real hand (omniscient view) is one 中 short of Seven Pairs (4 faan,
    clears the default min_faan=3) -- declaring the kong would hand seat 1 an immediate 搶槓 win.
    Under the ordinary view (`hands=None`), this fix's gate never runs at all and the (forced)
    kong is declared -- the regression pin, proving `view.hands is None` behavior is untouched.
    Under the omniscient view, the gate must skip it, falling back to a discard instead.
    """
    kong_type = int(TileType.DRAGON_RED)
    pung = Meld(MeldKind.PUNG, tile_ids_for_type(TileType.DRAGON_RED)[:3], from_seat=0)
    own_kong_tile = tile_ids_for_type(TileType.DRAGON_RED)[3]
    filler_types = [
        TileType.MAN_1,
        TileType.MAN_2,
        TileType.MAN_4,
        TileType.MAN_5,
        TileType.MAN_7,
        TileType.MAN_8,
        TileType.PIN_2,
        TileType.PIN_3,
        TileType.SOU_2,
        TileType.SOU_3,
    ]
    own_hand = (own_kong_tile, *(tile_ids_for_type(t)[0] for t in filler_types))

    def _build(hands: tuple[tuple[TileId, ...], ...] | None) -> SeatView:
        return SeatView(
            seat=0,
            hand_no=1,
            prevailing=Wind.EAST,
            dealer=0,
            turn=0,
            phase=Phase.AWAIT_ACTION,
            own_hand=own_hand,
            concealed_counts=(len(own_hand), 0, 0, 0),
            melds=((pung,), (), (), ()),
            discard_pools=((), (), (), ()),
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

    probabilistic_view = _build(None)
    hand34 = own_hand34(probabilistic_view)
    after_kong = list(hand34)
    after_kong[kong_type] -= 1

    def _fake_shanten(
        tiles: list[int], *, closed: bool = True, hand_sets: frozenset = frozenset()
    ) -> int:
        if not closed and list(tiles) == after_kong:
            return 0  # pretend this exact candidate is a huge improvement
        return shanten(tiles, closed=closed, hand_sets=hand_sets)

    monkeypatch.setattr("bots.faanbot.shanten", _fake_shanten)

    mask = [False] * 109
    kong_aid = _ADDED_KONG_BASE + kong_type
    mask[kong_aid] = True
    for t in filler_types:
        mask[int(t)] = True

    # seat 1's real hand: one 中 short of Seven Pairs.
    seat1_hand = _pool(
        TileType.MAN_1,
        TileType.MAN_1,
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
        TileType.DRAGON_RED,
    )
    omniscient_view = _build(((), seat1_hand, (), ()))

    probabilistic_result = await FaanBot().act(probabilistic_view, mask, _NO_DEADLINE)
    omniscient_result = await FaanBot().act(omniscient_view, mask, _NO_DEADLINE)

    assert probabilistic_result == kong_aid, (
        "sanity: the forced shanten-improvement precondition must actually make the unfixed "
        "path declare this kong, or the rest of this test proves nothing"
    )
    assert omniscient_result != kong_aid, (
        "the omniscient view must avoid declaring a kong that would be robbed for a real win"
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
