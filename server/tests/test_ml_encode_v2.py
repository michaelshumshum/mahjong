"""`ml/encode_v2.py`: the fast `GameState` path equals the `seat_view` reference on every swept
state and seat, and the policy input never moves when hidden information does (docs/06-ml.md §8)."""

from __future__ import annotations

import dataclasses
import random

import pytest

np = pytest.importorskip("numpy")

from app.views import seat_view
from mahjong_core.state import GameState, Phase
from mahjong_core.tiles import Flower
from mahjong_core.wall import Wall
from ml.encode_v2 import (
    N_ORACLE_CHANNELS,
    N_POLICY_CHANNELS,
    N_POLICY_SCALARS,
    ORACLE_CHANNELS,
    ORACLE_MAX_DRAWS,
    POLICY_CHANNELS,
    POLICY_FIELDS,
    encode_oracle,
    encode_oracle_batch,
    encode_policy,
    oracle_raw,
    policy_raw,
    policy_raw_from_view,
    stack_rows,
)
from ml.env import HandEnv
from ml.fast_encode import encode_state

_KONG_IDS = range(34, 102)
_CLAIM_IDS = range(102, 109)


def _hand_states(seed: int, prefer: range | None = None) -> list[GameState]:
    env = HandEnv(encode=False)
    rng = random.Random(seed)
    _, _, mask = env.reset(seed)
    states = []
    done = False
    while not done:
        assert env.state is not None
        states.append(env.state)
        legal = np.flatnonzero(mask).tolist()
        preferred = [a for a in legal if prefer is not None and a in prefer]
        _, _, mask, done, _ = env.step(rng.choice(preferred or legal))
    return states


def _sweep() -> list[GameState]:
    states = []
    for seed in range(40):
        states += _hand_states(seed, _KONG_IDS if seed % 2 else _CLAIM_IDS)
    return states


@pytest.fixture(scope="module")
def states() -> list[GameState]:
    return _sweep()


def test_fast_raw_equals_seat_view_reference(states: list[GameState]) -> None:
    claimable = hidden_kongs = 0
    for state in states:
        for seat in range(4):
            fast = policy_raw(state, seat)
            ref = policy_raw_from_view(seat_view(state, seat))
            assert fast.keys() == ref.keys() == POLICY_FIELDS.keys()
            for k in fast:
                assert np.array_equal(fast[k], ref[k]), (k, state.phase, seat)
            claimable += int(fast["claim_tile"]) != 255
        hidden_kongs += any(m.concealed for s in state.seats for m in s.melds)
    assert claimable > 0
    assert hidden_kongs > 0


def test_shapes_and_claim_plane(states: list[GameState]) -> None:
    for state in states[:200]:
        tiles, scalars = encode_policy(state, state.turn)
        assert tiles.shape == (N_POLICY_CHANNELS, 34)
        assert scalars.shape == (N_POLICY_SCALARS,)
        assert tiles.dtype == scalars.dtype == np.float32
        window = state.claim_window
        for seat in range(4):
            plane = encode_policy(state, seat)[0][POLICY_CHANNELS["claimable"]][0]
            offered = window is not None and any(o.seat == seat for o in window.offers)
            if offered:
                assert window is not None
                assert plane[window.tile // 4] == 1.0 and plane.sum() == 1.0
            else:
                assert plane.sum() == 0.0


def test_first_planes_are_the_v1_layout(states: list[GameState]) -> None:
    n = POLICY_CHANNELS["discards"].stop
    for state in states[::13]:
        for seat in range(4):
            v1 = encode_state(state, seat)[: n * 34].reshape(n, 34)
            assert np.array_equal(encode_policy(state, seat)[0][:n], v1)


def _reshuffle_hidden(state: GameState, seat: int, rng: random.Random) -> GameState:
    """Same public table, different hidden deal: opponents' concealed tiles and the wall's
    non-flower tiles are pooled, shuffled and dealt back into the same slots."""
    opps = [(seat + r) % 4 for r in (1, 2, 3)]
    wall = list(state.wall.tiles)
    wall_slots = [i for i, t in enumerate(wall) if not isinstance(t, Flower)]
    pool = [t for o in opps for t in state.seats[o].concealed] + [wall[i] for i in wall_slots]
    rng.shuffle(pool)
    seats = list(state.seats)
    at = 0
    for o in opps:
        n = len(seats[o].concealed)
        seats[o] = dataclasses.replace(seats[o], concealed=tuple(pool[at : at + n]))
        at += n
    for i in wall_slots:
        wall[i] = pool[at]
        at += 1
    return dataclasses.replace(state, seats=tuple(seats), wall=Wall(tuple(wall)))


def test_policy_input_ignores_hidden_information(states: list[GameState]) -> None:
    rng = random.Random(0)
    oracle_moved = 0
    for state in states[::7]:
        if state.phase in (Phase.HAND_OVER, Phase.GAME_OVER):
            continue
        for seat in range(4):
            other = _reshuffle_hidden(state, seat, rng)
            a, b = encode_policy(state, seat), encode_policy(other, seat)
            assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1]), (state.phase, seat)
            oracle_moved += not np.array_equal(
                encode_oracle(state, seat), encode_oracle(other, seat)
            )
    assert oracle_moved > 0


def test_oracle_rows_account_for_every_hidden_tile(states: list[GameState]) -> None:
    for state in states[::11]:
        for seat in range(4):
            row = oracle_raw(state, seat)
            for i, rel in enumerate((1, 2, 3)):
                s = state.seats[(seat + rel) % 4]
                assert row["opp_concealed"][i].sum() == len(s.concealed)
                assert row["opp_concealed_kongs"][i].sum() == sum(m.concealed for m in s.melds)
            flowers = sum(isinstance(t, Flower) for t in state.wall.tiles)
            assert row["wall_counts"].sum() + flowers == len(state.wall.tiles)
            seen = (
                policy_raw(state, seat)["concealed"].astype(int)
                + sum(row["opp_concealed"].astype(int))
                + row["wall_counts"]
            )
            assert seen.max() <= 4


def test_oracle_draw_planes_zero_past_k(states: list[GameState]) -> None:
    row = stack_rows([oracle_raw(states[0], 0)])
    full = encode_oracle_batch(row)
    assert full.shape == (1, N_ORACLE_CHANNELS, 34)
    draws = ORACLE_CHANNELS["next_draws"]
    assert full[0, draws].sum() > 0
    for k in (0, 3):
        part = encode_oracle_batch(row, k)
        assert np.array_equal(part[0, draws][:k], full[0, draws][:k])
        assert part[0, draws][k:].sum() == 0
        assert np.array_equal(part[0, : draws.start], full[0, : draws.start])
    with pytest.raises(ValueError):
        encode_oracle_batch(row, ORACLE_MAX_DRAWS + 1)
