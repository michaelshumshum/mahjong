"""Unit tests for `ml/encode.py` (docs/ml.md §5
encoding"). `ml.encode` needs numpy, which isn't a base dependency (`server/AGENTS.md`) --
`importorskip` keeps this file a clean skip, not a collection failure, under `make test-server`'s
no-ml-extra environment; it runs for real wherever the `ml` extra is installed.
"""

from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")
ml_encode = pytest.importorskip("ml.encode")

from app.views import SeatView
from bots.features import own_hand34
from mahjong_core.config import HandSet, RuleSet
from mahjong_core.melds import Meld, MeldKind
from mahjong_core.scoring.patterns import PATTERNS
from mahjong_core.state import Phase, Wind
from mahjong_core.tiles import TileId, TileType, tile_ids_for_type


def _view(
    *,
    seat: int = 0,
    dealer: int = 0,
    turn: int | None = None,
    prevailing: Wind = Wind.EAST,
    phase: Phase = Phase.AWAIT_ACTION,
    melds: tuple[tuple[Meld, ...], ...] | None = None,
    discard_pools: tuple[tuple[TileId, ...], ...] | None = None,
    own_hand_types: tuple[TileType, ...] = (),
    wall_remaining: int = 50,
    ruleset: RuleSet | None = None,
) -> SeatView:
    """Mirrors `tests/test_safety.py`'s `_view` convention -- a minimal, hand-built `SeatView`
    carrying exactly what `ml/encode.py` reads."""
    used: dict[TileType, int] = {}
    ids = []
    for t in own_hand_types:
        n = used.get(t, 0)
        ids.append(tile_ids_for_type(t)[n])
        used[t] = n + 1
    return SeatView(
        seat=seat,
        hand_no=1,
        prevailing=prevailing,
        dealer=dealer,
        turn=turn if turn is not None else seat,
        phase=phase,
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
        hands=None,
    )


def test_encode_seat_view_rejects_a_spectator_view() -> None:
    spectator_view = SeatView(
        seat=None,
        hand_no=1,
        prevailing=Wind.EAST,
        dealer=0,
        turn=0,
        phase=Phase.AWAIT_ACTION,
        own_hand=(),
        concealed_counts=(0, 0, 0, 0),
        melds=((), (), (), ()),
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
        hands=None,
    )
    with pytest.raises(ValueError, match="spectator"):
        ml_encode.encode_seat_view(spectator_view)


def test_hand_thermometer_plane_matches_tile_counts_one_through_four() -> None:
    view = _view(
        own_hand_types=(
            TileType.MAN_1,
            TileType.MAN_2,
            TileType.MAN_2,
            TileType.MAN_3,
            TileType.MAN_3,
            TileType.MAN_3,
            TileType.MAN_4,
            TileType.MAN_4,
            TileType.MAN_4,
            TileType.MAN_4,
        )
    )
    encoded = ml_encode.encode_seat_view(view)
    assert encoded.hand.shape == (ml_encode.N_THERMOMETER, ml_encode.N_TILE_TYPES)
    # count 0 (MAN_5, unheld) -> every plane 0; count 1/2/3/4 -> exactly that many planes lit
    for tile_type, count in (
        (TileType.MAN_5, 0),
        (TileType.MAN_1, 1),
        (TileType.MAN_2, 2),
        (TileType.MAN_3, 3),
        (TileType.MAN_4, 4),
    ):
        lit = encoded.hand[:, int(tile_type)]
        assert lit.sum() == count
        assert list(lit) == [1.0] * count + [0.0] * (ml_encode.N_THERMOMETER - count)


def test_meld_kong_counts_as_three_tiles_not_four() -> None:
    kong = Meld(
        kind=MeldKind.EXPOSED_KONG,
        tiles=tile_ids_for_type(TileType.DRAGON_RED),
        from_seat=1,
    )
    view = _view(seat=0, melds=((kong,), (), (), ()))
    encoded = ml_encode.encode_seat_view(view)
    lit = encoded.melds[0, :, int(TileType.DRAGON_RED)]  # relative seat 0 == absolute seat 0
    assert lit.sum() == 3


def test_opponent_concealed_kong_tile_type_is_not_encoded_but_own_is() -> None:
    kong = Meld(kind=MeldKind.CONCEALED_KONG, tiles=tile_ids_for_type(TileType.DRAGON_RED))
    view = _view(seat=0, melds=((kong,), (kong,), (), ()))
    encoded = ml_encode.encode_seat_view(view)
    assert encoded.melds[0, :, int(TileType.DRAGON_RED)].sum() == 3  # own, relative slot 0
    assert encoded.melds[1].sum() == 0  # next seat's concealed kong: hidden


def test_relative_seat_ordering_puts_self_first_and_rotates_the_rest() -> None:
    pools = (
        (tile_ids_for_type(TileType.MAN_1)[0],),
        (tile_ids_for_type(TileType.MAN_2)[0],),
        (tile_ids_for_type(TileType.MAN_3)[0],),
        (tile_ids_for_type(TileType.MAN_4)[0],),
    )
    view = _view(seat=2, discard_pools=pools)
    encoded = ml_encode.encode_seat_view(view)
    # order for seat 2 is (2, 3, 0, 1) -> relative 0 sees MAN_3, 1 sees MAN_4, 2 sees MAN_1, 3 sees MAN_2
    expected = [TileType.MAN_3, TileType.MAN_4, TileType.MAN_1, TileType.MAN_2]
    for rel, tile_type in enumerate(expected):
        assert encoded.discards[rel, :, int(tile_type)].sum() == 1
        assert encoded.discards[rel].sum() == 1  # nothing else lit for that relative seat


def test_context_one_hots_encode_turn_dealer_wind_and_phase() -> None:
    view = _view(seat=1, dealer=3, turn=1, prevailing=Wind.SOUTH, phase=Phase.AWAIT_CLAIMS)
    encoded = ml_encode.encode_seat_view(view)
    turn, dealer, prevailing, seat_wind, phase = np.split(encoded.context, [4, 8, 12, 16])
    assert list(turn) == [1.0, 0.0, 0.0, 0.0]  # relative 0: turn holder is this seat itself
    # dealer=3, self=1 -> relative offset (3-1)%4 = 2
    assert list(dealer) == [0.0, 0.0, 1.0, 0.0]
    assert list(prevailing) == [0.0, 1.0, 0.0, 0.0]  # Wind.SOUTH == 1
    # seat_wind_for(1, dealer=3) == Wind((1-3) % 4) == Wind(2) == Wind.WEST
    assert list(seat_wind) == [0.0, 0.0, 1.0, 0.0]
    assert list(phase) == [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0]  # AWAIT_CLAIMS is index 2


def test_wall_remaining_passes_through() -> None:
    encoded = ml_encode.encode_seat_view(_view(wall_remaining=17))
    assert list(encoded.wall_remaining) == [17.0]


def test_encode_ruleset_default_hand_sets_all_on_and_faan_overrides_unapplied() -> None:
    encoded = ml_encode.encode_ruleset(RuleSet())
    assert encoded.shape == (ml_encode.N_RULESET_FEATURES,)
    assert encoded[0] == RuleSet().min_faan
    assert encoded[1] == RuleSet().wall_reserve
    assert list(encoded[2:5]) == [1.0, 1.0, 1.0]  # CLASSIC, NEW_6, NEW_18 all on by default
    effective_faan = encoded[5:]
    assert len(effective_faan) == len(PATTERNS)
    assert list(effective_faan) == [float(p.faan) for p in PATTERNS]


def test_encode_ruleset_reflects_narrower_hand_sets_and_overrides() -> None:
    ruleset = RuleSet(
        hand_sets=frozenset({HandSet.CLASSIC}),
        faan_overrides={"混一色": 15},
        min_faan=1,
        wall_reserve=40,
    )
    encoded = ml_encode.encode_ruleset(ruleset)
    assert encoded[0] == 1
    assert encoded[1] == 40
    assert list(encoded[2:5]) == [1.0, 0.0, 0.0]  # only CLASSIC on
    override_index = next(i for i, p in enumerate(PATTERNS) if p.name == "混一色")
    assert encoded[5 + override_index] == 15.0
    other_index = next(i for i, p in enumerate(PATTERNS) if p.name == "清一色")
    assert encoded[5 + other_index] == next(p.faan for p in PATTERNS if p.name == "清一色")


def _row(**over):  # type: ignore[no-untyped-def]
    row = {
        "hand_counts": [0] * 34,
        "meld_counts": [[0] * 34 for _ in range(4)],
        "discard_counts": [[0] * 34 for _ in range(4)],
        "discard_seq": [[], [], [], []],
        "concealed_counts": [13, 13, 13, 13],
        "concealed_kongs": [0, 0, 0, 0],
        "flowers": [0, 0, 0, 0],
        "dealer_idx": 0,
        "prevailing_wind": 0,
        "seat_wind": 0,
        "wall_remaining": 70,
    }
    row.update(over)
    return row


def _batch(rows, opp):  # type: ignore[no-untyped-def]
    raw = ml_encode.rows_to_arrays(rows)
    return ml_encode.encode_batch(raw, np.asarray(opp), ml_encode.encode_ruleset(RuleSet()))


def test_encode_batch_shapes_and_finite_values() -> None:
    tiles, scalars = _batch([_row(), _row()], [0, 2])
    assert tiles.shape == (2, ml_encode.N_TILE_CHANNELS, 34)
    assert scalars.shape == (2, ml_encode.N_SCALARS)
    assert tiles.dtype == scalars.dtype == np.float32
    assert np.isfinite(tiles).all() and np.isfinite(scalars).all()


def test_encode_batch_rotates_so_the_target_opponent_comes_first() -> None:
    discards = [[0] * 34 for _ in range(4)]
    for slot in range(4):
        discards[slot][slot] = 1  # observer-relative slot k discarded tile type k
    row = _row(discard_counts=discards)
    # channels: hand 0-3, melds 4-19, discards 20-35 (4 per seat, target first)
    for opp in range(3):
        tiles, _ = _batch([row], [opp])
        target_slot = opp + 1
        for pos in range(4):
            slot = (target_slot + pos) % 4
            plane = tiles[0, 20 + 4 * pos]
            assert plane[slot] == 1.0 and plane.sum() == 1.0


def test_encode_batch_hand_planes_match_the_seat_view_encoder() -> None:
    view = _view(own_hand_types=(TileType.MAN_1, TileType.MAN_1, TileType.PIN_5))
    row = _row(hand_counts=own_hand34(view))
    tiles, _ = _batch([row], [0])
    assert np.array_equal(tiles[0, :4], ml_encode.encode_seat_view(view).hand)


def test_encode_batch_discard_age_buckets_track_recency_for_the_target_only() -> None:
    m1, m2, m3, m9 = (int(TileType.MAN_1), int(TileType.MAN_2), int(TileType.MAN_3), 8)
    seq = [[], [m9, m1, m2, m2, m3, m3, m3, m3], [], []]  # opponent 0 (slot 1)
    counts = [[0] * 34 for _ in range(4)]
    for tile in seq[1]:
        counts[1][tile] += 1
    tiles, _ = _batch([_row(discard_counts=counts, discard_seq=seq)], [0])
    age = tiles[0, 36:40]  # buckets: age 0, 1-2, 3-5, 6+
    assert age[0, m3] == 1 and age[0, m2] == 0
    assert age[1, m2] == 0 and age[2, m2] == 1  # m2 is 3 turns old
    assert age[3, m9] == 1
    assert tiles[0, 40:44].sum() == 0  # no other seat discarded anything


def test_encode_batch_unseen_uses_own_hand_once_and_counts_other_seats_melds() -> None:
    m1 = int(TileType.MAN_1)
    hand = [0] * 34
    hand[m1] = 3
    melds = [[0] * 34 for _ in range(4)]
    melds[0][m1] = 3  # observer's own meld: already inside hand_counts, must not double count
    melds[2][int(TileType.MAN_2)] = 3
    tiles, _ = _batch([_row(hand_counts=hand, meld_counts=melds)], [0])
    unseen = tiles[0, 44]
    assert unseen[m1] == pytest.approx(0.25)
    assert unseen[int(TileType.MAN_2)] == pytest.approx(0.25)
    assert unseen[int(TileType.MAN_3)] == 1.0


def test_encode_batch_suji_channel_needs_both_sides_for_middle_ranks() -> None:
    def suji(discarded: list[int]) -> np.ndarray:
        counts = [[0] * 34 for _ in range(4)]
        for t in discarded:
            counts[1][t] = 1
        tiles, _ = _batch([_row(discard_counts=counts)], [0])
        return tiles[0, -1]

    man = lambda rank: rank - 1
    assert suji([man(4)])[man(1)] == 1  # 1m is suji of a discarded 4m
    assert suji([man(6)])[man(9)] == 1
    assert suji([man(1)])[man(4)] == 0  # 4m needs 1m and 7m
    assert suji([man(1), man(7)])[man(4)] == 1
    assert suji([man(7)])[man(4)] == 0
    assert suji([man(1)])[int(TileType.PIN_1) + 3] == 0  # no leaking across suits
    assert suji([int(TileType.WIND_EAST)]).sum() == 0
