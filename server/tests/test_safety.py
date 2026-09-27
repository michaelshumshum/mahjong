"""Unit tests for `bots/safety.py` (docs/04-bots.md §5). Per this sub-task's testing
requirements: enough to prove each signal actually moves the score in the documented direction,
not just that the functions run -- genbutsu/suji/meld/tempo/wall-pressure as soft multipliers
that never reach exactly 0 (except `no_chance`, the one documented hard constraint), each tested
in isolation by holding every other signal fixed.
"""

from __future__ import annotations

from app.views import SeatView
from bots.faanbot import _THREAT_THRESHOLD
from bots.safety import (
    deal_in_probability,
    expected_cost,
    is_genbutsu,
    kong_rob_risk,
    no_chance,
    opponent_threat_level,
    tile_risk,
    wall_pressure_multiplier,
)
from mahjong_core.actions import hand_is_winning_shape
from mahjong_core.config import RuleSet
from mahjong_core.melds import Meld, MeldKind
from mahjong_core.scoring.faan import score_winning_hand
from mahjong_core.scoring.patterns import ScoringContext, seat_wind_for
from mahjong_core.state import Phase, SeatState, Wind
from mahjong_core.tiles import TileId, TileType, tile_ids_for_type


def _view(
    *,
    seat: int = 0,
    melds: tuple[tuple[Meld, ...], ...] | None = None,
    discard_pools: tuple[tuple[TileId, ...], ...] | None = None,
    own_hand_types: tuple[TileType, ...] = (),
    wall_remaining: int = 50,
    hands: tuple[tuple[TileId, ...], ...] | None = None,
    ruleset: RuleSet | None = None,
) -> SeatView:
    """A minimal, hand-built `SeatView` carrying exactly what `bots/safety.py` reads --
    `own_hand`, `melds`, `discard_pools`, `wall_remaining`, `seat` -- matching
    `tests/test_efficiency.py`'s `_build_view` convention. `own_hand_types` lets a test put
    tiles in this seat's own concealed hand so `seen34` accounts for them (mirroring
    `bots/features.seen34`'s "your hand... never the wall" contract). `hands`, when given,
    populates `SeatView.hands` -- the omniscient-view field that flips `tile_risk` onto its
    hands-aware exact path. `ruleset` lets a test override `kong_rob_enabled`/
    `concealed_kong_robbable` for `kong_rob_risk`; defaults to `RuleSet()`."""
    used: dict[TileType, int] = {}
    ids = []
    for t in own_hand_types:
        n = used.get(t, 0)
        ids.append(tile_ids_for_type(t)[n])
        used[t] = n + 1
    return SeatView(
        seat=seat,
        hand_no=1,
        prevailing=Wind.EAST,
        dealer=0,
        turn=seat,
        phase=Phase.AWAIT_ACTION,
        own_hand=tuple(ids),
        concealed_counts=(len(ids), 0, 0, 0),
        melds=melds if melds is not None else ((), (), (), ()),
        discard_pools=discard_pools if discard_pools is not None else ((), (), (), ()),
        flowers=((), (), (), ()),
        wall_remaining=wall_remaining,
        seat_status=("connected", "connected", "connected", "connected"),
        names=(None, None, None, None),
        scores=(0, 0, 0, 0),
        legal_actions=(),
        claim_options=(),
        deadline_ts=None,
        host_seat=None,
        ruleset=ruleset if ruleset is not None else RuleSet(),
        hands=hands,
    )


def _pool(*types: TileType) -> tuple[TileId, ...]:
    used: dict[TileType, int] = {}
    ids = []
    for t in types:
        n = used.get(t, 0)
        ids.append(tile_ids_for_type(t)[n])
        used[t] = n + 1
    return tuple(ids)


def _pung(tile_type: TileType) -> Meld:
    return Meld(MeldKind.PUNG, tile_ids_for_type(tile_type)[:3], from_seat=0)


# --- no_chance: hard constraint --------------------------------------------------------------


def test_no_chance_true_when_all_four_copies_visible() -> None:
    seen = [0] * 34
    seen[int(TileType.PIN_3)] = 4
    assert no_chance(int(TileType.PIN_3), seen)


def test_no_chance_false_with_a_copy_still_unseen() -> None:
    seen = [0] * 34
    seen[int(TileType.PIN_3)] = 3
    assert not no_chance(int(TileType.PIN_3), seen)


def test_deal_in_probability_zero_when_no_chance() -> None:
    # This seat holds all 4 copies of PIN_3 itself -- seen34 counts the seat's own hand, so
    # deal_in_probability must read as a hard 0 regardless of every other signal.
    view = _view(own_hand_types=(TileType.PIN_3,) * 4)
    assert deal_in_probability(view, opponent_seat=1, tile_type=int(TileType.PIN_3)) == 0.0


# --- genbutsu: weak, never a hard zero --------------------------------------------------------


def test_genbutsu_lowers_but_never_zeroes_probability() -> None:
    tile = int(TileType.SOU_5)
    no_read = _view()
    genbutsu = _view(discard_pools=((), _pool(TileType.SOU_5), (), ()))

    p_no_read = deal_in_probability(no_read, opponent_seat=1, tile_type=tile)
    p_genbutsu = deal_in_probability(genbutsu, opponent_seat=1, tile_type=tile)

    assert is_genbutsu(genbutsu, 1, tile)
    assert 0.0 < p_genbutsu < p_no_read


def test_genbutsu_is_per_opponent() -> None:
    """Genbutsu against seat 1 must not make the same tile look safer against seat 2, who
    never discarded it -- each opponent's own discard pool is the only evidence about them."""
    tile = int(TileType.SOU_5)
    view = _view(discard_pools=((), _pool(TileType.SOU_5), (), ()))
    assert is_genbutsu(view, 1, tile)
    assert not is_genbutsu(view, 2, tile)


# --- suji: weaker than genbutsu, still never a hard zero --------------------------------------


def test_suji_lowers_probability_less_than_genbutsu() -> None:
    tile = int(TileType.SOU_5)  # suji of SOU_2 and SOU_8
    no_read = _view()
    suji = _view(discard_pools=((), _pool(TileType.SOU_2), (), ()))
    genbutsu = _view(discard_pools=((), _pool(TileType.SOU_5), (), ()))

    p_no_read = deal_in_probability(no_read, opponent_seat=1, tile_type=tile)
    p_suji = deal_in_probability(suji, opponent_seat=1, tile_type=tile)
    p_genbutsu = deal_in_probability(genbutsu, opponent_seat=1, tile_type=tile)

    assert p_suji < p_no_read
    assert p_genbutsu < p_suji  # genbutsu strictly stronger, docs/04-bots.md §5 item 2


def test_suji_never_applies_to_honors() -> None:
    """Honors have no suit-adjacency -- a wind/dragon discard must never register as a "suji"
    read for another wind/dragon type (docs/04-bots.md §5 item 2 only ever discusses suited
    ranks)."""
    tile = int(TileType.DRAGON_RED)
    no_read = _view()
    other_dragon = _view(discard_pools=((), _pool(TileType.DRAGON_GREEN), (), ()))
    assert deal_in_probability(other_dragon, 1, tile) == deal_in_probability(no_read, 1, tile)


# --- one-chance: soft reduction, distinct from no_chance's hard zero --------------------------


def test_one_chance_lowers_probability_without_zeroing_it() -> None:
    tile = int(TileType.PIN_7)
    plenty_live = _view()  # 0 seen -- 4 live
    one_left = _view(own_hand_types=(TileType.PIN_7,) * 3)  # this seat holds 3 -- 1 live

    p_plenty = deal_in_probability(plenty_live, opponent_seat=1, tile_type=tile)
    p_one_left = deal_in_probability(one_left, opponent_seat=1, tile_type=tile)

    assert 0.0 < p_one_left < p_plenty


# --- meld reading: danger multiplier, not a verdict --------------------------------------------


def test_suit_concentrated_melds_raise_danger_for_that_suit() -> None:
    tile = int(TileType.PIN_4)
    no_melds = _view()
    two_pin_melds = _view(melds=((), (_pung(TileType.PIN_1), _pung(TileType.PIN_9)), (), ()))

    p_baseline = deal_in_probability(no_melds, opponent_seat=1, tile_type=tile)
    p_with_melds = deal_in_probability(two_pin_melds, opponent_seat=1, tile_type=tile)

    assert p_with_melds > p_baseline


def test_suit_concentrated_melds_do_not_raise_danger_for_other_suits() -> None:
    """Two pin melds shouldn't bump danger on an unrelated sou tile."""
    tile = int(TileType.SOU_4)
    no_melds = _view()
    two_pin_melds = _view(melds=((), (_pung(TileType.PIN_1), _pung(TileType.PIN_9)), (), ()))

    p_baseline = deal_in_probability(no_melds, opponent_seat=1, tile_type=tile)
    p_with_melds = deal_in_probability(two_pin_melds, opponent_seat=1, tile_type=tile)

    assert p_with_melds == p_baseline


def test_dragon_pung_raises_danger_for_the_other_dragons() -> None:
    tile = int(TileType.DRAGON_WHITE)
    no_melds = _view()
    dragon_pung = _view(melds=((), (_pung(TileType.DRAGON_RED),), (), ()))

    p_baseline = deal_in_probability(no_melds, opponent_seat=1, tile_type=tile)
    p_with_pung = deal_in_probability(dragon_pung, opponent_seat=1, tile_type=tile)

    assert p_with_pung > p_baseline


def test_expected_cost_bumped_by_meld_reads() -> None:
    tile = int(TileType.DRAGON_WHITE)
    no_melds = _view()
    dragon_pung = _view(melds=((), (_pung(TileType.DRAGON_RED),), (), ()))

    cost_baseline = expected_cost(no_melds, opponent_seat=1, tile_type=tile)
    cost_bumped = expected_cost(dragon_pung, opponent_seat=1, tile_type=tile)

    assert cost_bumped > cost_baseline


# --- discard tempo: a settling-into-tenpai tell -------------------------------------------------


def test_tempo_shift_raises_threat_and_probability() -> None:
    # evaluated against PIN_6, not the opponent's just-discarded PIN_4, so genbutsu (a
    # stronger signal) doesn't dominate what this test isolates.
    tile = int(TileType.PIN_6)
    steady = _view(
        discard_pools=(
            (),
            _pool(TileType.WIND_EAST, TileType.WIND_SOUTH, TileType.WIND_WEST, TileType.SOU_1),
            (),
            (),
        )
    )
    settled = _view(
        discard_pools=(
            (),
            _pool(TileType.WIND_EAST, TileType.WIND_SOUTH, TileType.WIND_WEST, TileType.PIN_4),
            (),
            (),
        )
    )

    p_steady = deal_in_probability(steady, opponent_seat=1, tile_type=tile)
    p_settled = deal_in_probability(settled, opponent_seat=1, tile_type=tile)
    assert p_settled > p_steady

    assert opponent_threat_level(settled, 1) > opponent_threat_level(steady, 1)


def test_tempo_shift_needs_a_string_of_terminal_honor_discards_first() -> None:
    """Too few prior discards to establish a "tempo" at all -- no shift detected."""
    tile = int(TileType.PIN_4)
    short_history = _view(discard_pools=((), _pool(TileType.WIND_EAST, TileType.PIN_4), (), ()))
    no_history = _view(discard_pools=((), _pool(TileType.PIN_4), (), ()))
    assert deal_in_probability(short_history, 1, tile) == deal_in_probability(no_history, 1, tile)


# --- wall pressure: scales expected cost, not probability ---------------------------------------


def test_wall_pressure_increases_with_fewer_tiles_remaining() -> None:
    assert (
        wall_pressure_multiplier(60) < wall_pressure_multiplier(35) < wall_pressure_multiplier(10)
    )


def test_wall_pressure_scales_expected_cost() -> None:
    tile = int(TileType.PIN_4)
    early = _view(wall_remaining=60)
    late = _view(wall_remaining=10)
    assert expected_cost(late, opponent_seat=1, tile_type=tile) > expected_cost(
        early, opponent_seat=1, tile_type=tile
    )


# --- opponent_threat_level: melds bump it too --------------------------------------------------


def test_more_melds_raise_threat_level() -> None:
    no_melds = _view()
    one_meld = _view(melds=((), (_pung(TileType.PIN_1),), (), ()))
    two_melds = _view(melds=((), (_pung(TileType.PIN_1), _pung(TileType.SOU_1)), (), ()))
    assert opponent_threat_level(no_melds, 1) < opponent_threat_level(one_meld, 1)
    assert opponent_threat_level(one_meld, 1) < opponent_threat_level(two_melds, 1)


# --- opponent_threat_level: hands-aware exact path (view.hands populated, the "ORACLE" tier) ----


def test_opponent_threat_level_hands_none_matches_the_original_probabilistic_formula() -> None:
    """`view.hands is None` (every tier except `"ORACLE"`) must still be exactly
    `melds * 0.3 + tempo_bump` -- the hands-aware path is a strict override for an omniscient
    view, not a behavior change for every other tier. Two exposed melds, empty discard pool (no
    tempo shift): the formula's original, hand-computed value."""
    view = _view(melds=((), (_pung(TileType.PIN_1), _pung(TileType.SOU_1)), (), ()))
    assert view.hands is None
    assert opponent_threat_level(view, 1) == 2 * 0.3


def test_opponent_threat_level_hands_aware_flags_a_near_tenpai_opponent_the_proxy_misses() -> None:
    """Opponent 1 holds no melds and an empty discard pool -- too short to raise the tempo
    signal even if it held one -- so the probabilistic proxy reads them as zero threat, well
    below `_THREAT_THRESHOLD` (`bots/faanbot.py`). Their real hand (omniscient view, same
    melds/discards) is genuinely tenpai (shanten 0: three concealed sequences plus a closed run,
    tanki wait on 5s). Hands-aware `opponent_threat_level` must flag them as threatening; the
    probabilistic proxy on the exact same position must not -- proving the fix catches a real
    threat the proxy misses, not just adding an unused code path."""
    tenpai_hand = _pool(
        TileType.MAN_1,
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
        TileType.SOU_5,
    )
    proxy_view = _view()
    hands_view = _view(hands=((), tenpai_hand, (), ()))

    proxy_threat = opponent_threat_level(proxy_view, 1)
    real_threat = opponent_threat_level(hands_view, 1)

    assert proxy_threat < _THREAT_THRESHOLD
    assert real_threat >= _THREAT_THRESHOLD


def test_opponent_threat_level_hands_aware_clears_an_opponent_that_looks_threatening_by_proxy() -> (
    None
):
    """Opponent 1 holds two exposed melds plus a settled discard tempo -- the probabilistic
    proxy reads them as clearly threatening, well above `_THREAT_THRESHOLD`. Their real hand
    (omniscient view, same melds/discards) is nowhere near tenpai (shanten 4: two gapped-pair
    fragments, three lone honors, nothing beyond the two exposed pungs already on the table).
    Hands-aware `opponent_threat_level` must read them as clearly safe (0.0); the probabilistic
    proxy on the exact same position must not -- proving the fix lets `FaanBot` keep pushing
    instead of folding against a false alarm."""
    melds = ((), (_pung(TileType.PIN_1), _pung(TileType.PIN_9)), (), ())
    discard_pools = (
        (),
        _pool(TileType.WIND_EAST, TileType.WIND_SOUTH, TileType.WIND_WEST, TileType.PIN_4),
        (),
        (),
    )
    proxy_view = _view(melds=melds, discard_pools=discard_pools)
    assert opponent_threat_level(proxy_view, 1) > _THREAT_THRESHOLD

    far_hand = _pool(
        TileType.MAN_2,
        TileType.MAN_6,
        TileType.SOU_2,
        TileType.SOU_6,
        TileType.WIND_EAST,
        TileType.WIND_SOUTH,
        TileType.DRAGON_WHITE,
    )
    hands_view = _view(melds=melds, discard_pools=discard_pools, hands=((), far_hand, (), ()))
    assert opponent_threat_level(hands_view, 1) == 0.0


# --- tile_risk: aggregates across every opponent -------------------------------------------------


def test_tile_risk_sums_danger_across_opponents() -> None:
    tile = int(TileType.DRAGON_WHITE)
    one_threat = _view(melds=((), (_pung(TileType.DRAGON_RED),), (), ()))
    two_threats = _view(
        melds=((), (_pung(TileType.DRAGON_RED),), (_pung(TileType.DRAGON_RED),), ())
    )
    assert tile_risk(two_threats, tile) > tile_risk(one_threat, tile)


def test_tile_risk_excludes_own_seat() -> None:
    """A seat is never a "threat" to itself -- `tile_risk` must only ever sum over the other
    three seats."""
    tile = int(TileType.PIN_4)
    view = _view(seat=2)
    # Should not raise, and should be a finite non-negative float.
    risk = tile_risk(view, tile)
    assert risk >= 0.0


# --- tile_risk: hands-aware exact path (view.hands populated, the "ORACLE" tier) ----------------


def test_tile_risk_hands_aware_flags_an_exact_deal_in() -> None:
    """Opponent 1's real 13-tile hand is one tile short of Seven Pairs (default ruleset: NEW_18
    on, min_faan=3) -- adding SOU_9 completes it. `tile_risk` under an omniscient view must
    report exactly the real faan the scorer computes, not `_ASSUMED_DEALIN_FAAN`'s 5.0 proxy."""
    tile_type = int(TileType.SOU_9)
    opp_seat = 1
    opp_hand = _pool(
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
        TileType.SOU_9,
    )
    # a prior discard from this seat means the candidate discard isn't the dealer's first --
    # avoids entangling with the 地糊 timing bonus, tested separately.
    view = _view(
        hands=((), opp_hand, (), ()), discard_pools=(_pool(TileType.WIND_EAST), (), (), ())
    )

    candidate = (*opp_hand, TileId(int(TileType.SOU_9) * 4 + 1))
    assert hand_is_winning_shape(SeatState(concealed=candidate))
    ctx = ScoringContext(
        seat_wind=seat_wind_for(opp_seat, view.dealer),
        prevailing_wind=view.prevailing,
        self_drawn=False,
        flowers=(),
        flowers_score=view.ruleset.flowers_score,
    )
    expected = score_winning_hand(candidate, (), ctx, view.ruleset)
    assert expected.clears_min_faan  # sanity: this really is a live deal-in, not a sub-minimum win

    assert tile_risk(view, tile_type) == expected.total_faan


def test_tile_risk_hands_aware_clears_a_tile_that_looks_dangerous_by_probabilistic_signals() -> (
    None
):
    """Two same-suit melds bump this tile's danger under the probabilistic model
    (`_meld_danger_multiplier`), but opponent 1's real hand (omniscient view) is nowhere near
    tenpai on it. The hands-aware path must return exactly 0.0 for that opponent -- proof it is
    actually using the real hand, not just inheriting the probabilistic estimate."""
    tile_type = int(TileType.PIN_4)
    melds = ((), (_pung(TileType.PIN_1), _pung(TileType.PIN_9)), (), ())
    probabilistic_view = _view(melds=melds)
    assert deal_in_probability(probabilistic_view, opponent_seat=1, tile_type=tile_type) > 0.0

    far_hand = _pool(
        TileType.MAN_2,
        TileType.MAN_4,
        TileType.MAN_6,
        TileType.MAN_8,
        TileType.SOU_2,
        TileType.SOU_4,
        TileType.SOU_6,
        TileType.SOU_8,
        TileType.WIND_EAST,
        TileType.WIND_SOUTH,
        TileType.WIND_WEST,
        TileType.WIND_NORTH,
        TileType.DRAGON_RED,
    )
    hands_view = _view(melds=melds, hands=((), far_hand, (), ()))
    assert tile_risk(hands_view, tile_type) == 0.0


def test_tile_risk_hands_aware_does_not_flag_a_sub_minimum_structural_win() -> None:
    """Opponent 1's real hand structurally completes on PIN_9 (three sequences + a pair, plus one
    already-exposed chow) but the real scorer puts it below the default ruleset's `min_faan=3` --
    losing 門前清 (not fully concealed) leaves it a bare all-sequence hand. A sub-minimum
    structural win is not a deal-in (docs/04-bots.md §4), so the hands-aware path must return
    0.0, not the real (sub-minimum) faan value."""
    tile_type = int(TileType.PIN_9)
    opp_seat = 1
    exposed_chow = Meld(
        MeldKind.CHOW,
        tile_ids_for_type(TileType.MAN_1)[:1]
        + (
            tile_ids_for_type(TileType.MAN_2)[0],
            tile_ids_for_type(TileType.MAN_3)[0],
        ),
        from_seat=2,
    )
    opp_hand = _pool(
        TileType.MAN_4,
        TileType.MAN_5,
        TileType.MAN_6,
        TileType.PIN_1,
        TileType.PIN_2,
        TileType.PIN_3,
        TileType.PIN_7,
        TileType.PIN_8,
        TileType.SOU_5,
        TileType.SOU_5,
    )
    melds = ((), (exposed_chow,), (), ())
    # a prior discard from this seat -- same "not the dealer's first discard" fixture hygiene as
    # test_tile_risk_hands_aware_flags_an_exact_deal_in, above.
    view = _view(
        hands=((), opp_hand, (), ()),
        melds=melds,
        discard_pools=(_pool(TileType.WIND_EAST), (), (), ()),
    )

    candidate = (*opp_hand, TileId(int(TileType.PIN_9) * 4))
    assert hand_is_winning_shape(SeatState(concealed=candidate, melds=(exposed_chow,)))
    ctx = ScoringContext(
        seat_wind=seat_wind_for(opp_seat, view.dealer),
        prevailing_wind=view.prevailing,
        self_drawn=False,
        flowers=(),
        flowers_score=view.ruleset.flowers_score,
    )
    expected = score_winning_hand(candidate, (exposed_chow,), ctx, view.ruleset)
    assert not expected.clears_min_faan  # sanity: genuinely sub-minimum, not a mistaken fixture

    assert tile_risk(view, tile_type) == 0.0


def test_tile_risk_hands_none_matches_the_original_probabilistic_formula() -> None:
    """`view.hands is None` (every tier except `"ORACLE"`) must reproduce the original
    `P(deal_in) * expected_cost` sum byte-for-byte -- the hands-aware path is a strict override
    for an omniscient view, not a behavior change for every other tier."""
    tile = int(TileType.DRAGON_WHITE)
    view = _view(melds=((), (_pung(TileType.DRAGON_RED),), (_pung(TileType.DRAGON_RED),), ()))
    assert view.hands is None

    expected = sum(
        deal_in_probability(view, opp, tile) * expected_cost(view, opp, tile)
        for opp in range(4)
        if opp != view.seat
    )
    assert tile_risk(view, tile) == expected


def test_tile_risk_hands_aware_handles_a_concealed_kong_of_the_candidate_type() -> None:
    """Regression: opponent 1's real hand already holds all 4 physical copies of PIN_5
    (a concealed kong candidate) -- a naive synthetic id (`tile_type * 4`, always the block's
    first id) collides with a real id already in the hand once `decompose` materializes a
    candidate `Meld`, and `Meld.__post_init__` (mahjong_core/melds.py) raises on a meld built
    from two equal physical ids. `_synthetic_tile_id` must recognize no 5th-copy placeholder id
    is available and return `None` instead -- `_exact_deal_in_faan` must then read that as 0.0,
    not propagate a crash: a 5th physical PIN_5 can't exist, so this discard provably can't deal
    in via it, the same fact the probabilistic `no_chance` signal captures for the non-hands-aware
    path."""
    tile_type = int(TileType.PIN_5)
    opp_hand = _pool(
        TileType.PIN_5,
        TileType.PIN_5,
        TileType.PIN_5,
        TileType.PIN_5,
        TileType.MAN_1,
        TileType.MAN_2,
        TileType.MAN_3,
        TileType.MAN_5,
        TileType.MAN_6,
        TileType.MAN_7,
        TileType.SOU_1,
        TileType.SOU_1,
        TileType.SOU_2,
    )
    view = _view(hands=((), opp_hand, (), ()))
    assert tile_risk(view, tile_type) == 0.0


# --- kong_rob_risk: exact 搶槓 danger of declaring a kong (docs/04-bots.md §10) ----------------


def test_kong_rob_risk_added_kong_flags_a_real_deal_in() -> None:
    """An added kong exposes the tile completing the existing pung to *any* opponent win --
    reuses the identical exact-deal-in fixture as `test_tile_risk_hands_aware_flags_an_exact_
    deal_in`, since an added-kong 搶槓 check is structurally the same win check as an ordinary
    discard's, just triggered by exposing a tile instead of discarding one."""
    tile_type = int(TileType.SOU_9)
    opp_seat = 1
    opp_hand = _pool(
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
        TileType.SOU_9,
    )
    view = _view(
        hands=((), opp_hand, (), ()), discard_pools=(_pool(TileType.WIND_EAST), (), (), ())
    )

    candidate = (*opp_hand, TileId(int(TileType.SOU_9) * 4 + 1))
    ctx = ScoringContext(
        seat_wind=seat_wind_for(opp_seat, view.dealer),
        prevailing_wind=view.prevailing,
        self_drawn=False,
        flowers=(),
        flowers_score=view.ruleset.flowers_score,
    )
    expected = score_winning_hand(candidate, (), ctx, view.ruleset)
    assert expected.clears_min_faan  # sanity: a real deal-in, not a sub-minimum win

    assert kong_rob_risk(view, tile_type, concealed=False) == expected.total_faan


def test_kong_rob_risk_added_kong_clears_a_safe_tile() -> None:
    """Opponent 1's real hand is nowhere near tenpai on this tile -- added-kong risk must read
    0.0, same convention as `tile_risk`'s own safe-tile test."""
    tile_type = int(TileType.PIN_4)
    far_hand = _pool(
        TileType.MAN_2,
        TileType.MAN_4,
        TileType.MAN_6,
        TileType.MAN_8,
        TileType.SOU_2,
        TileType.SOU_4,
        TileType.SOU_6,
        TileType.SOU_8,
        TileType.WIND_EAST,
        TileType.WIND_SOUTH,
        TileType.WIND_WEST,
        TileType.WIND_NORTH,
        TileType.DRAGON_RED,
    )
    view = _view(hands=((), far_hand, (), ()))
    assert kong_rob_risk(view, tile_type, concealed=False) == 0.0


def test_kong_rob_risk_respects_kong_rob_enabled_false() -> None:
    """Mirrors `mahjong_core.engine._kong_rob_offers`'s own gate: with `kong_rob_enabled=False`
    the engine never opens a robbing window at all, so this must read 0.0 even for a tile that
    would otherwise be a certain deal-in."""
    tile_type = int(TileType.SOU_9)
    opp_hand = _pool(
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
        TileType.SOU_9,
    )
    view = _view(
        hands=((), opp_hand, (), ()),
        discard_pools=(_pool(TileType.WIND_EAST), (), (), ()),
        ruleset=RuleSet(kong_rob_enabled=False),
    )
    assert kong_rob_risk(view, tile_type, concealed=False) == 0.0


def test_kong_rob_risk_concealed_kong_unreachable_under_default_ruleset() -> None:
    """`RuleSet.concealed_kong_robbable` defaults to `False` -- real HK convention only opens a
    concealed-kong robbing window on some tables, never by default (`mahjong_core/config.py`).
    Even an opponent one tile from completing Thirteen Orphans on this exact tile must read 0.0
    under the default ruleset -- the engine itself would never open a claim window here either
    (`_kong_rob_offers`'s own early return)."""
    tile_type = int(TileType.DRAGON_WHITE)
    thirteen_orphans_wait = _pool(
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
        TileType.MAN_1,
    )
    view = _view(hands=((), thirteen_orphans_wait, (), ()))
    assert view.ruleset.concealed_kong_robbable is False  # sanity: exercising the real default
    assert kong_rob_risk(view, tile_type, concealed=True) == 0.0


def test_kong_rob_risk_concealed_kong_flags_a_real_thirteen_orphans_completion() -> None:
    """With `concealed_kong_robbable=True` explicitly on, a concealed kong exposing the exact
    tile that completes an opponent's real Thirteen Orphans wait must flag it -- the one case
    real HK convention actually allows a concealed-kong robbing claim."""
    tile_type = int(TileType.DRAGON_WHITE)
    opp_seat = 1
    thirteen_orphans_wait = _pool(
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
        TileType.MAN_1,
    )
    view = _view(
        hands=((), thirteen_orphans_wait, (), ()),
        ruleset=RuleSet(concealed_kong_robbable=True),
    )

    candidate = (*thirteen_orphans_wait, TileId(int(TileType.DRAGON_WHITE) * 4))
    assert hand_is_winning_shape(SeatState(concealed=candidate))
    ctx = ScoringContext(
        seat_wind=seat_wind_for(opp_seat, view.dealer),
        prevailing_wind=view.prevailing,
        self_drawn=False,
        flowers=(),
        flowers_score=view.ruleset.flowers_score,
    )
    expected = score_winning_hand(candidate, (), ctx, view.ruleset)
    assert expected.clears_min_faan  # sanity: Thirteen Orphans is a limit hand

    assert kong_rob_risk(view, tile_type, concealed=True) == expected.total_faan


def test_kong_rob_risk_concealed_kong_ignores_a_non_thirteen_orphans_completion() -> None:
    """Even with `concealed_kong_robbable=True`, real HK convention restricts a concealed-kong
    robbing claim to Thirteen Orphans specifically (`mahjong_core.engine._kong_rob_offers`'s own
    docstring) -- an opponent completing an ordinary Seven Pairs hand on this exact tile must
    still read 0.0 for the concealed-kong path, even though the identical tile/hand is a real
    flagged deal-in for an *added* kong (`test_kong_rob_risk_added_kong_flags_a_real_deal_in`)."""
    tile_type = int(TileType.SOU_9)
    opp_hand = _pool(
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
        TileType.SOU_9,
    )
    view = _view(
        hands=((), opp_hand, (), ()),
        discard_pools=(_pool(TileType.WIND_EAST), (), (), ()),
        ruleset=RuleSet(concealed_kong_robbable=True),
    )
    assert kong_rob_risk(view, tile_type, concealed=True) == 0.0
