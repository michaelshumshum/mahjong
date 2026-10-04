"""`ml/fast_encode.py`: bit-equal to `encode_seat_view(seat_view(...))` on every state and seat
swept from real self-play (docs/ml.md §7's leak guard)."""

from __future__ import annotations

import asyncio
import random

import pytest

np = pytest.importorskip("numpy")

from bots.selfplay import play_game
from mahjong_core.config import GameLength, RuleSet
from mahjong_core.engine import new_game, reduce, start_next_hand
from mahjong_core.state import GameState, Phase
from ml.env import HandEnv
from ml.fast_encode import OBS_DIM, encode_reference, encode_state

_MULTI_HAND = RuleSet(
    game_length=GameLength.EAST_SOUTH, dealer_repeat_on_win=False, dealer_repeat_on_draw=False
)
_KONG_IDS = range(34, 102)


def _assert_parity(state: GameState) -> None:
    buf = np.full(OBS_DIM, np.nan, dtype=np.float32)
    for seat in range(4):
        fast = encode_state(state, seat, out=buf)
        assert np.array_equal(fast, encode_reference(state, seat)), (state.phase, seat)


def _hidden_kong(state: GameState) -> bool:
    return any(m.concealed for s in state.seats for m in s.melds)


def _full_game_states(seed: int) -> list[GameState]:
    final, actions = asyncio.run(play_game(seed, _MULTI_HAND))
    state = new_game(_MULTI_HAND, seed)
    states = [state]
    pending = list(actions)
    while state.phase != Phase.GAME_OVER:
        if state.phase == Phase.HAND_OVER:
            state, _ = start_next_hand(state)
        else:
            state, _ = reduce(state, pending.pop(0))
        states.append(state)
    assert state == final
    return states


def test_parity_across_full_random_games():
    dealers, winds = set(), set()
    for seed in range(2):
        for state in _full_game_states(seed):
            if state.phase != Phase.GAME_OVER:
                _assert_parity(state)
            dealers.add(state.dealer)
            winds.add(state.prevailing)
    assert dealers == {0, 1, 2, 3}
    assert len(winds) == 2


def test_parity_with_concealed_kongs():
    """Kong-preferring random play, so other seats' concealed kongs (the redacted case) occur."""
    hidden = 0
    for seed in range(60):
        env = HandEnv(encode=False)
        rng = random.Random(seed)
        _, _, mask = env.reset(seed)
        done = False
        while not done:
            _assert_parity(env.state)
            hidden += _hidden_kong(env.state)
            legal = np.flatnonzero(mask).tolist()
            kongs = [a for a in legal if a in _KONG_IDS]
            _, _, mask, done, _ = env.step(rng.choice(kongs or legal))
        _assert_parity(env.state)
    assert hidden > 0


def test_obs_dim_matches_reference_layout():
    state = new_game(RuleSet(), 0)
    assert encode_reference(state, 0).shape == (OBS_DIM,)
