"""Equivalence of the table-driven winning-shape check with the `decompose`-based reference it
replaced (docs/ml.md §7: behaviour-neutral engine speed-ups)."""

from __future__ import annotations

import dataclasses
import random
from collections.abc import Sequence
from itertools import product

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from mahjong_core.actions import (
    _is_seven_pairs,
    _is_thirteen_orphans,
    _is_winning_shape,
    build_scoring_context,
    hand_is_winning_shape,
    legal_actions,
)
from mahjong_core.config import DEFAULT_RULESET
from mahjong_core.engine import can_win_on, new_hand, reduce
from mahjong_core.melds import _SUIT_SHAPES, Meld, MeldKind, _is_standard_shape, decompose
from mahjong_core.scoring.faan import score_winning_hand
from mahjong_core.state import GameState, Phase, SeatState, Wind
from mahjong_core.tiles import TileId, count_array_from_types, tile_id_type
from tests.test_engine_trajectory_pin import _greedy


def _reference(concealed: Sequence[TileId], *, closed: bool) -> bool:
    """`hand_is_winning_shape` as it was before the speed-up."""
    if closed and (_is_seven_pairs(concealed) or _is_thirteen_orphans(concealed)):
        return True
    return decompose(concealed) != ()


def _suit_tiles(shape: Sequence[int], suit: int = 0) -> list[TileId]:
    return [TileId((suit * 9 + rank) * 4 + k) for rank, c in enumerate(shape) for k in range(c)]


def test_suit_shape_table_matches_decompose_on_every_shape() -> None:
    """exhaustive over every suit shape a <=14-tile hand can hold (~273k)."""
    for shape in product(range(5), repeat=9):
        total = sum(shape)
        if total > 14 or total % 3 == 1:
            continue
        tiles = _suit_tiles(shape)
        needs_pair = total % 3 == 2
        if not needs_pair:
            tiles += [TileId(27 * 4), TileId(27 * 4 + 1)]
        complete = decompose(tiles) != ()
        assert (shape in _SUIT_SHAPES) == complete, shape
        if complete:
            assert _SUIT_SHAPES[shape] == needs_pair, shape


def test_suit_shape_table_has_no_shape_decompose_cannot_reach() -> None:
    assert all(sum(s) <= 14 and max(s) <= 4 and sum(s) % 3 != 1 for s in _SUIT_SHAPES)


_GROUPS = [*((t, t + 1, t + 2) for t in range(27) if t % 9 <= 6), *((t, t, t) for t in range(34))]


@st.composite
def _near_winning(draw: st.DrawFn) -> list[TileId]:
    """a meld+pair hand, then 0-2 tiles swapped out, so both outcomes are well covered."""
    n_melds = draw(st.integers(0, 4))
    types = draw(st.lists(st.sampled_from(_GROUPS), min_size=n_melds, max_size=n_melds))
    flat = [t for g in types for t in g] + [draw(st.integers(0, 33))] * 2
    for _ in range(draw(st.integers(0, 2))):
        flat[draw(st.integers(0, len(flat) - 1))] = draw(st.integers(0, 33))
    return _ids_for(flat)


@st.composite
def _seven_pairs_like(draw: st.DrawFn) -> list[TileId]:
    types = draw(st.lists(st.integers(0, 33), min_size=7, max_size=7))
    flat = [t for t in types for _ in range(2)]
    if draw(st.booleans()):
        flat[draw(st.integers(0, 13))] = draw(st.integers(0, 33))
    return _ids_for(flat)


_ORPHANS = [0, 8, 9, 17, 18, 26, *range(27, 34)]


@st.composite
def _orphans_like(draw: st.DrawFn) -> list[TileId]:
    flat = [*_ORPHANS, draw(st.sampled_from(_ORPHANS))]
    if draw(st.booleans()):
        flat[draw(st.integers(0, 13))] = draw(st.integers(0, 33))
    return _ids_for(flat)


def _ids_for(types: Sequence[int]) -> list[TileId]:
    """physical ids for tile types; a 5th copy can't exist, so it's dropped."""
    used: dict[int, int] = {}
    ids: list[TileId] = []
    for t in types:
        k = used.get(t, 0)
        if k < 4:
            ids.append(TileId(t * 4 + k))
            used[t] = k + 1
    return ids


_HANDS = st.one_of(
    _near_winning(),
    _seven_pairs_like(),
    _orphans_like(),
    st.lists(st.integers(0, 135), max_size=14, unique=True).map(lambda xs: [TileId(x) for x in xs]),
)


@settings(max_examples=3000, deadline=None)
@given(hand=_HANDS, order=st.randoms(use_true_random=False), closed=st.booleans())
def test_is_winning_shape_equals_reference(
    hand: list[TileId], order: random.Random, closed: bool
) -> None:
    order.shuffle(hand)
    assert _is_winning_shape(hand, closed=closed) == _reference(hand, closed=closed)
    counts = count_array_from_types(tile_id_type(t) for t in hand)
    assert _is_standard_shape(counts) == (decompose(hand) != ())


def test_hand_is_winning_shape_reads_melds_for_closed() -> None:
    pairs = _ids_for([t for t in (0, 2, 4, 6, 9, 11, 13) for _ in range(2)])
    pung = Meld(MeldKind.PUNG, (TileId(124), TileId(125), TileId(126)))
    assert hand_is_winning_shape(SeatState(concealed=tuple(pairs)))
    assert not hand_is_winning_shape(SeatState(concealed=tuple(pairs[:11]), melds=(pung,)))
    assert not hand_is_winning_shape(SeatState(concealed=tuple(pairs), melds=(pung,)))


def _reference_can_win_on(
    state: GameState, seat: int, tile: TileId, *, is_robbing_kong: bool, discarder: int
) -> bool:
    """`engine.can_win_on` as it was before the speed-up."""
    seat_state = state.seats[seat]
    candidate = dataclasses.replace(seat_state, concealed=(*seat_state.concealed, tile))
    if not hand_is_winning_shape(candidate):
        return False
    ctx = build_scoring_context(
        state, seat, self_drawn=False, is_robbing_kong=is_robbing_kong, discarder=discarder
    )
    result = score_winning_hand(candidate.concealed, candidate.melds, ctx, state.ruleset)
    return result.clears_min_faan


@pytest.mark.parametrize("min_faan", [0, 3])
def test_can_win_on_equals_reference(min_faan: int) -> None:
    """every (other seat, tile in the mover's hand, rob flag) at every turn of seeded hands."""
    ruleset = dataclasses.replace(DEFAULT_RULESET, min_faan=min_faan)
    wins = 0
    for seed in range(12):
        rng = random.Random(seed)
        state = new_hand(ruleset, seed, dealer=seed % 4, prevailing=Wind.EAST)
        while state.phase != Phase.HAND_OVER:
            if state.phase == Phase.AWAIT_ACTION:
                mover = state.turn
                for seat in range(4):
                    if seat == mover:
                        continue
                    for tile in state.seats[mover].concealed:
                        for rob in (False, True):
                            args = (state, seat, tile)
                            got = can_win_on(*args, is_robbing_kong=rob, discarder=mover)
                            ref = _reference_can_win_on(*args, is_robbing_kong=rob, discarder=mover)
                            assert got == ref
                            wins += got
                seat = mover
            else:
                assert state.claim_window is not None
                window = state.claim_window
                seat = rng.choice([o.seat for o in window.offers if o.seat not in window.responses])
            state, _ = reduce(state, _greedy(state, seat, legal_actions(state, seat), rng))
    assert wins > 0
