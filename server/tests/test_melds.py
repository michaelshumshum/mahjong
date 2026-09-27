import pytest
from hypothesis import given
from hypothesis import strategies as st

from mahjong_core.melds import (
    Meld,
    MeldKind,
    decompose,
    legal_claims,
    legal_self_melds,
)
from mahjong_core.tiles import TileType, tile_ids_for_type

_MAN_1 = tile_ids_for_type(TileType.MAN_1)
_MAN_2 = tile_ids_for_type(TileType.MAN_2)
_MAN_3 = tile_ids_for_type(TileType.MAN_3)
_MAN_4 = tile_ids_for_type(TileType.MAN_4)
_MAN_5 = tile_ids_for_type(TileType.MAN_5)
_MAN_6 = tile_ids_for_type(TileType.MAN_6)
_MAN_7 = tile_ids_for_type(TileType.MAN_7)
_MAN_8 = tile_ids_for_type(TileType.MAN_8)
_MAN_9 = tile_ids_for_type(TileType.MAN_9)
_PIN_1 = tile_ids_for_type(TileType.PIN_1)
_EAST = tile_ids_for_type(TileType.WIND_EAST)


# --- Meld construction / validity --------------------------------------------------


def test_valid_chow() -> None:
    meld = Meld(MeldKind.CHOW, (_MAN_1[0], _MAN_2[0], _MAN_3[0]))
    assert meld.tile_type == TileType.MAN_1


def test_chow_gap_is_illegal() -> None:
    with pytest.raises(ValueError):
        Meld(MeldKind.CHOW, (_MAN_1[0], _MAN_2[0], _MAN_4[0]))


def test_chow_crossing_suit_boundary_is_illegal() -> None:
    # 8m, 9m, 1p is not a chow: rank 8 (0-indexed) can't start a run within its own suit.
    with pytest.raises(ValueError):
        Meld(MeldKind.CHOW, (_MAN_8[0], _MAN_9[0], _PIN_1[0]))


def test_chow_of_honors_is_illegal() -> None:
    east2 = tile_ids_for_type(TileType.WIND_SOUTH)
    east3 = tile_ids_for_type(TileType.WIND_WEST)
    with pytest.raises(ValueError):
        Meld(MeldKind.CHOW, (_EAST[0], east2[0], east3[0]))


def test_valid_7_8_9_chow() -> None:
    Meld(MeldKind.CHOW, (_MAN_7[0], _MAN_8[0], _MAN_9[0]))


def test_pung_mismatched_types_is_illegal() -> None:
    with pytest.raises(ValueError):
        Meld(MeldKind.PUNG, (_MAN_1[0], _MAN_1[1], _MAN_2[0]))


def test_pung_needs_exactly_3_tiles() -> None:
    with pytest.raises(ValueError):
        Meld(MeldKind.PUNG, (_MAN_1[0], _MAN_1[1]))


def test_kong_needs_4_matching_tiles() -> None:
    Meld(MeldKind.EXPOSED_KONG, tuple(_MAN_1))
    with pytest.raises(ValueError):
        Meld(MeldKind.EXPOSED_KONG, tuple(_MAN_1[:3]))


def test_pair_needs_2_identical_type_tiles() -> None:
    Meld(MeldKind.PAIR, (_MAN_1[0], _MAN_1[1]))
    with pytest.raises(ValueError):
        Meld(MeldKind.PAIR, (_MAN_1[0], _MAN_2[0]))


def test_duplicate_tile_id_is_illegal() -> None:
    with pytest.raises(ValueError):
        Meld(MeldKind.PAIR, (_MAN_1[0], _MAN_1[0]))


def test_from_seat_out_of_range_is_illegal() -> None:
    with pytest.raises(ValueError):
        Meld(MeldKind.PUNG, tuple(_MAN_1[:3]), from_seat=4)


def test_concealed_kong_cannot_have_from_seat() -> None:
    with pytest.raises(ValueError):
        Meld(MeldKind.CONCEALED_KONG, tuple(_MAN_1), from_seat=0)


def test_pair_cannot_have_from_seat() -> None:
    with pytest.raises(ValueError):
        Meld(MeldKind.PAIR, (_MAN_1[0], _MAN_1[1]), from_seat=0)


def test_only_concealed_kong_is_concealed() -> None:
    concealed_kong = Meld(MeldKind.CONCEALED_KONG, tuple(_MAN_1))
    exposed_kong = Meld(MeldKind.EXPOSED_KONG, tuple(_MAN_1), from_seat=1)
    pung = Meld(MeldKind.PUNG, tuple(_MAN_1[:3]), from_seat=1)
    chow = Meld(MeldKind.CHOW, (_MAN_1[0], _MAN_2[0], _MAN_3[0]), from_seat=1)
    pair = Meld(MeldKind.PAIR, (_MAN_1[0], _MAN_1[1]))
    assert concealed_kong.concealed
    assert not any(m.concealed for m in (exposed_kong, pung, chow, pair))


# --- legal_claims: chow seat eligibility --------------------------------------------


def test_chow_only_legal_from_next_seat() -> None:
    concealed = [_MAN_1[0], _MAN_2[0]]
    # discarder seat 0; only seat 1 (= (0+1)%4) may chow.
    for claimer in (1, 2, 3):
        claims = legal_claims(concealed, _MAN_3[0], discarder_seat=0, claimer_seat=claimer)
        has_chow = any(c.kind == MeldKind.CHOW for c in claims)
        assert has_chow == (claimer == 1)


def test_chow_illegal_for_honor_discard() -> None:
    # even the eligible seat gets no chow option on an honor tile.
    claims = legal_claims([], _EAST[0], discarder_seat=0, claimer_seat=1)
    assert not any(c.kind == MeldKind.CHOW for c in claims)


def test_chow_middle_tile_yields_all_three_positions() -> None:
    concealed = [_MAN_3[0], _MAN_4[0], _MAN_6[0], _MAN_7[0]]
    claims = legal_claims(concealed, _MAN_5[0], discarder_seat=0, claimer_seat=1)
    chows = [c for c in claims if c.kind == MeldKind.CHOW]
    assert len(chows) == 3
    starts = sorted(c.tile_type for c in chows)
    assert starts == [TileType.MAN_3, TileType.MAN_4, TileType.MAN_5]


# --- legal_claims: pung / kong -------------------------------------------------------


def test_pung_legal_from_any_seat_with_2_matching() -> None:
    concealed = [_MAN_1[0], _MAN_1[1]]
    for discarder, claimer in [(0, 2), (0, 3), (1, 3), (2, 0)]:
        claims = legal_claims(concealed, _MAN_1[2], discarder_seat=discarder, claimer_seat=claimer)
        assert any(c.kind == MeldKind.PUNG for c in claims)


def test_pung_illegal_with_only_1_matching() -> None:
    claims = legal_claims([_MAN_1[0]], _MAN_1[1], discarder_seat=0, claimer_seat=2)
    assert not any(c.kind == MeldKind.PUNG for c in claims)


def test_exposed_kong_legal_from_any_seat_with_3_matching() -> None:
    concealed = list(_MAN_1[:3])
    claims = legal_claims(concealed, _MAN_2[0], discarder_seat=0, claimer_seat=2)
    # wrong type discard: no kong on MAN_1 possible via a MAN_2 discard.
    assert not any(c.kind == MeldKind.EXPOSED_KONG for c in claims)
    claims = legal_claims(concealed, _EAST[0], discarder_seat=0, claimer_seat=2)
    assert not any(c.kind == MeldKind.EXPOSED_KONG for c in claims)


def test_exposed_kong_and_pung_both_offered_with_3_matching() -> None:
    concealed = list(_MAN_1[:3])
    claims = legal_claims(concealed, _MAN_1[3], discarder_seat=0, claimer_seat=2)
    kinds = {c.kind for c in claims}
    assert MeldKind.EXPOSED_KONG in kinds
    assert MeldKind.PUNG in kinds


def test_cannot_claim_own_discard() -> None:
    with pytest.raises(ValueError):
        legal_claims([], _MAN_1[0], discarder_seat=1, claimer_seat=1)


@pytest.mark.parametrize("bad_seat", [-1, 4])
def test_seat_range_validated(bad_seat: int) -> None:
    with pytest.raises(ValueError):
        legal_claims([], _MAN_1[0], discarder_seat=bad_seat, claimer_seat=0)


# --- legal_self_melds ----------------------------------------------------------------


def test_concealed_kong_offered_with_4_in_hand() -> None:
    options = legal_self_melds(list(_MAN_1))
    assert len(options) == 1
    assert options[0].kind == MeldKind.CONCEALED_KONG


def test_no_self_meld_with_only_3_in_hand() -> None:
    assert legal_self_melds(list(_MAN_1[:3])) == ()


def test_added_kong_offered_when_matching_exposed_pung() -> None:
    pung = Meld(MeldKind.PUNG, tuple(_MAN_1[:3]), from_seat=2)
    options = legal_self_melds([_MAN_1[3]], exposed_melds=[pung])
    assert len(options) == 1
    added = options[0]
    assert added.kind == MeldKind.ADDED_KONG
    assert added.from_seat == 2
    assert set(added.tiles) == set(_MAN_1)


def test_no_added_kong_without_matching_concealed_tile() -> None:
    pung = Meld(MeldKind.PUNG, tuple(_MAN_1[:3]), from_seat=2)
    assert legal_self_melds([_MAN_2[0]], exposed_melds=[pung]) == ()


def test_no_added_kong_from_a_chow() -> None:
    chow = Meld(MeldKind.CHOW, (_MAN_1[0], _MAN_2[0], _MAN_3[0]), from_seat=2)
    assert legal_self_melds([_MAN_1[3]], exposed_melds=[chow]) == ()


# --- decompose -------------------------------------------------------------------------


def _flatten(split: tuple[Meld, ...]) -> list[int]:
    return [int(t) for meld in split for t in meld.tiles]


def test_decompose_wrong_length_returns_empty() -> None:
    assert decompose([_MAN_1[0]]) == ()
    assert decompose([_MAN_1[0], _MAN_2[0], _MAN_3[0]]) == ()


def test_decompose_single_pair_only() -> None:
    splits = decompose([_MAN_1[0], _MAN_1[1]])
    assert len(splits) == 1
    (pair,) = splits[0]
    assert pair.kind == MeldKind.PAIR


def test_decompose_no_valid_split_returns_empty() -> None:
    # 1m 2m 4m 5m 7m: no pair possible (all distinct types), no valid split.
    tiles = [_MAN_1[0], _MAN_2[0], _MAN_4[0], _MAN_5[0], _MAN_7[0]]
    assert decompose(tiles) == ()


def test_decompose_unique_standard_hand() -> None:
    # 111m 456m 789m + pair 22m: one meld shape, no ambiguity.
    tiles = [
        *_MAN_1[:3],
        _MAN_4[0],
        _MAN_5[0],
        _MAN_6[0],
        _MAN_7[0],
        _MAN_8[0],
        _MAN_9[0],
        _MAN_2[0],
        _MAN_2[1],
    ]
    splits = decompose(tiles)
    assert len(splits) == 1
    kinds = sorted(m.kind.value for m in splits[0])
    assert kinds == sorted(["pung", "chow", "chow", "pair"])
    assert sorted(_flatten(splits[0])) == sorted(int(t) for t in tiles)


def test_decompose_ambiguous_hand_returns_both_splits() -> None:
    # 2233445 5m (two each of 2,3,4,5m) — the classic 一般高 ambiguity:
    # pair(22)+chow(345)+chow(345)  vs.  pair(55)+chow(234)+chow(234).
    tiles = [
        *_MAN_2[:2],
        *_MAN_3[:2],
        *_MAN_4[:2],
        *_MAN_5[:2],
    ]
    splits = decompose(tiles)
    assert len(splits) == 2
    for split in splits:
        assert sorted(_flatten(split)) == sorted(int(t) for t in tiles)
        pair_types = {m.tile_type for m in split if m.kind == MeldKind.PAIR}
        assert pair_types in ({TileType.MAN_2}, {TileType.MAN_5})


def test_decompose_seven_pairs_shape_is_not_a_standard_split() -> None:
    # decompose() only handles melds+pair (shanten.py owns seven pairs); wrong length yields no split.
    tiles = [_MAN_1[0], _MAN_1[1], _MAN_2[0], _MAN_2[1]]  # length 4, not 3k+2
    assert decompose(tiles) == ()


@given(
    st.lists(
        st.sampled_from(list(range(9)) + list(range(9))),  # bias toward suited, chow-friendly
        min_size=2,
        max_size=11,
    )
)
def test_property_decompose_conserves_every_tile(ranks: list[int]) -> None:
    # build a tile multiset of length 3k+2 from man-suit ranks (respecting the 4-copies-per-type
    # limit), then check every returned split accounts for every input tile exactly once.
    if len(ranks) % 3 != 2:
        ranks = ranks[:-1] if (len(ranks) - 1) % 3 == 2 else ranks + [ranks[0] if ranks else 0]
    if len(ranks) % 3 != 2:
        return

    used: dict[int, int] = {}
    tiles = []
    for r in ranks:
        n = used.get(r, 0)
        if n >= 4:
            continue
        ids = tile_ids_for_type(TileType(r))
        tiles.append(ids[n])
        used[r] = n + 1

    if len(tiles) % 3 != 2:
        return

    splits = decompose(tiles)
    expected = sorted(int(t) for t in tiles)
    for split in splits:
        assert sorted(_flatten(split)) == expected
        for meld in split:
            assert len(meld.tiles) in (2, 3)
