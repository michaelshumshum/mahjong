"""Unit tests for `bots/safety.py` (docs/04-bots.md §5). Per this sub-task's testing
requirements: enough to prove each signal actually moves the score in the documented direction,
not just that the functions run -- genbutsu/suji/meld/tempo/wall-pressure as soft multipliers
that never reach exactly 0 (except `no_chance`, the one documented hard constraint), each tested
in isolation by holding every other signal fixed.
"""

from __future__ import annotations

from app.views import SeatView
from bots.safety import (
    deal_in_probability,
    expected_cost,
    is_genbutsu,
    no_chance,
    opponent_threat_level,
    tile_risk,
    wall_pressure_multiplier,
)
from mahjong_core.config import RuleSet
from mahjong_core.melds import Meld, MeldKind
from mahjong_core.state import Phase, Wind
from mahjong_core.tiles import TileId, TileType, tile_ids_for_type


def _view(
    *,
    seat: int = 0,
    melds: tuple[tuple[Meld, ...], ...] | None = None,
    discard_pools: tuple[tuple[TileId, ...], ...] | None = None,
    own_hand_types: tuple[TileType, ...] = (),
    wall_remaining: int = 50,
) -> SeatView:
    """A minimal, hand-built `SeatView` carrying exactly what `bots/safety.py` reads --
    `own_hand`, `melds`, `discard_pools`, `wall_remaining`, `seat` -- matching
    `tests/test_efficiency.py`'s `_build_view` convention. `own_hand_types` lets a test put
    tiles in this seat's own concealed hand so `seen34` accounts for them (mirroring
    `bots/features.seen34`'s "your hand... never the wall" contract)."""
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
        ruleset=RuleSet(),
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
    # Evaluated against PIN_6 -- a different middle tile from the one the "settled" opponent
    # just discarded (PIN_4), so genbutsu (a much stronger signal) doesn't dominate what this
    # test is isolating.
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
