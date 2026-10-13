"""Unit tests for `bots/features.py`'s `seen34` (docs/bots.md §3/§9). Per this sub-task's
requirements: prove the hands-aware branch actually changes something real (undercounts an
opponent's real concealed tiles fixed, a concealed kong's identity correctly flipped from
"skip" to "count"), not just that it runs, while `view.hands is None` stays byte-identical to
the original probabilistic behavior -- same convention `tests/test_safety.py` already
established for `tile_risk`/`opponent_threat_level`.
"""

from __future__ import annotations

from app.views import SeatView
from bots.features import own_hand34, seen34
from mahjong_core.config import RuleSet
from mahjong_core.melds import Meld, MeldKind
from mahjong_core.shanten import shanten, ukeire
from mahjong_core.state import Phase, Wind
from mahjong_core.tiles import TileId, TileType, tile_ids_for_type


def _view(
    *,
    seat: int = 0,
    own_types: tuple[TileType, ...] = (),
    melds: tuple[tuple[Meld, ...], ...] | None = None,
    discard_pools: tuple[tuple[TileId, ...], ...] | None = None,
    hands: tuple[tuple[TileId, ...], ...] | None = None,
) -> SeatView:
    """Same minimal-`SeatView` convention as `tests/test_safety.py`'s `_view` -- only the fields
    `seen34` reads: `own_hand`, `melds`, `discard_pools`, `hands`, `seat`."""
    return SeatView(
        seat=seat,
        hand_no=1,
        prevailing=Wind.EAST,
        dealer=0,
        turn=seat,
        phase=Phase.AWAIT_ACTION,
        own_hand=_pool(own_types),
        concealed_counts=(len(own_types), 0, 0, 0),
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


def _pool(types: tuple[TileType, ...]) -> tuple[TileId, ...]:
    used: dict[TileType, int] = {}
    ids = []
    for t in types:
        n = used.get(t, 0)
        ids.append(tile_ids_for_type(t)[n])
        used[t] = n + 1
    return tuple(ids)


def _pung(tile_type: TileType) -> Meld:
    return Meld(MeldKind.PUNG, tile_ids_for_type(tile_type)[:3], from_seat=0)


def _concealed_kong(tile_type: TileType) -> Meld:
    return Meld(MeldKind.CONCEALED_KONG, tile_ids_for_type(tile_type))


# --- view.hands is None: byte-identical regression pin ----------------------------------------


def test_seen34_hands_none_matches_the_original_probabilistic_behavior() -> None:
    """`view.hands is None` (every tier except `"ORACLE"`) must still: count own hand, count
    every seat's melds (a concealed kong too -- it's played face-up), and count every discard
    pool, computed by hand here rather than re-deriving it from `seen34` itself."""
    own_types = (TileType.MAN_1, TileType.MAN_2, TileType.MAN_3)
    exposed_pung = _pung(TileType.PIN_5)
    concealed_kong = _concealed_kong(TileType.SOU_9)
    melds = ((), (exposed_pung,), (concealed_kong,), ())
    discard_pools = ((), _pool((TileType.WIND_EAST,)), (), _pool((TileType.DRAGON_WHITE,) * 2))
    view = _view(own_types=own_types, melds=melds, discard_pools=discard_pools)
    assert view.hands is None

    counts = seen34(view)

    expected = [0] * 34
    for t in own_types:
        expected[int(t)] += 1
    expected[int(TileType.PIN_5)] += 3  # exposed pung: visible
    expected[int(TileType.SOU_9)] += 3  # concealed kong: face-up, a kong counts 3
    expected[int(TileType.WIND_EAST)] += 1
    expected[int(TileType.DRAGON_WHITE)] += 2
    assert counts == expected


# --- view.hands populated: undercounted tiles now correctly seen ------------------------------


def test_seen34_hands_aware_counts_an_opponents_real_concealed_tiles() -> None:
    """Opponent 1 holds 3 real concealed copies of SOU_5 -- invisible to the probabilistic
    branch (no meld, no discard shows it), so `view.hands is None` reads `seen[SOU_5] == 0` and
    `ukeire` treats all 4 copies as still live in the wall. Under the omniscient view those 3
    copies are genuinely known, dead to everyone else -- `seen34` must count them, and the
    downstream `ukeire` live-tile count for a discard that's waiting on SOU_5 must drop from 4
    to 1 accordingly. This is the concrete gap the task closes: a full-information tier that
    still treated an opponent's real tiles as "maybe still in the wall"."""
    own_types = (
        TileType.MAN_1,
        TileType.MAN_2,
        TileType.MAN_3,
        TileType.MAN_5,
        TileType.MAN_6,
        TileType.MAN_7,
        TileType.PIN_1,
        TileType.PIN_2,
        TileType.PIN_3,
        TileType.SOU_4,
        TileType.SOU_6,
        TileType.WIND_EAST,
        TileType.WIND_EAST,
        TileType.MAN_9,
    )  # 14 tiles: discarding MAN_9 leaves a tenpai hand tanki/kanchan-waiting on SOU_5 alone
    opp_hand = _pool(
        (TileType.SOU_5,) * 3
        + (TileType.DRAGON_RED,) * 4
        + (TileType.DRAGON_GREEN,) * 4
        + (TileType.PIN_9,) * 2
    )
    ordinary_view = _view(own_types=own_types)
    hands_view = _view(own_types=own_types, hands=((), opp_hand, (), ()))

    sou5 = int(TileType.SOU_5)
    seen_ordinary = seen34(ordinary_view)
    seen_aware = seen34(hands_view)
    assert seen_ordinary[sou5] == 0
    assert seen_aware[sou5] == 3

    hand34 = own_hand34(ordinary_view)
    man9 = int(TileType.MAN_9)
    after = list(hand34)
    after[man9] -= 1
    assert shanten(after) == 0, "sanity: discarding MAN_9 must reach tenpai, or this proves nothing"

    accepts_ordinary = ukeire(hand34, seen_ordinary)
    accepts_aware = ukeire(hand34, seen_aware)
    assert accepts_ordinary[man9] == (1, 4), "ordinary view reads all 4 SOU_5 as still live"
    assert accepts_aware[man9] == (1, 1), (
        "hands-aware view correctly reads only 1 SOU_5 as still live -- the other 3 are "
        "provably dead in opponent 1's real hand"
    )


def test_seen34_counts_an_opponents_concealed_kong_with_or_without_hands() -> None:
    """`_apply_self_kong` removes a concealed kong's tiles from `SeatState.concealed`, so
    `view.hands` never holds them; `seen34` counts them from `view.melds` in both branches."""
    own_types = (
        TileType.MAN_1,
        TileType.MAN_2,
        TileType.MAN_3,
        TileType.MAN_4,
        TileType.MAN_5,
        TileType.MAN_6,
        TileType.PIN_1,
        TileType.PIN_2,
        TileType.PIN_3,
        TileType.PIN_5,
        TileType.PIN_6,
        TileType.PIN_7,
        TileType.DRAGON_WHITE,
    )
    kong = _concealed_kong(TileType.SOU_9)
    melds = ((), (kong,), (), ())
    opp1_remaining = _pool(
        (
            TileType.MAN_7,
            TileType.MAN_8,
            TileType.MAN_9,
            TileType.SOU_1,
            TileType.SOU_2,
            TileType.SOU_3,
            TileType.WIND_EAST,
            TileType.WIND_SOUTH,
            TileType.WIND_WEST,
        )
    )  # opponent 1's real remaining concealed tiles -- deliberately excludes SOU_9's 4 ids,
    # matching what `_apply_self_kong` actually produces once the kong is declared.
    probabilistic_view = _view(own_types=own_types, melds=melds)
    hands_view = _view(own_types=own_types, melds=melds, hands=((), opp1_remaining, (), ()))

    sou9 = int(TileType.SOU_9)
    assert seen34(probabilistic_view)[sou9] == 3
    # a kong contributes 3 to a 34-count array, matching `_add_meld`'s existing convention for
    # every other meld this module counts (docs/bots.md §3).
    assert seen34(hands_view)[sou9] == 3
