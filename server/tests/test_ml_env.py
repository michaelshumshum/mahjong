"""`ml/env.py`: single-hand self-play env (docs/06-ml.md §7)."""

from __future__ import annotations

import random

import pytest

np = pytest.importorskip("numpy")

from mahjong_core.config import RuleSet
from mahjong_core.engine import ENGINE_VERSION, IllegalActionError
from mahjong_core.state import Phase
from ml.env import OBS_DIM, HandEnv, replay_hand
from ml.fast_encode import encode_reference


def _play(env: HandEnv, seed: int, policy_seed: int, actions: list[int] | None = None):
    """Masked uniform-random play (or a fixed action list); returns the full trajectory."""
    rng = random.Random(policy_seed)
    seat, obs, mask = env.reset(seed)
    traj = [(seat, None if obs is None else obs.copy(), mask.copy())]
    chosen: list[int] = []
    done = False
    rewards = None
    while not done:
        legal = np.flatnonzero(mask).tolist()
        aid = actions[len(chosen)] if actions is not None else rng.choice(legal)
        chosen.append(aid)
        seat, obs, mask, done, rewards = env.step(aid)
        traj.append((seat, None if obs is None else obs.copy(), mask.copy()))
    return traj, chosen, rewards


def _same(a, b) -> bool:
    if len(a) != len(b):
        return False
    for (sa, oa, ma), (sb, ob, mb) in zip(a, b, strict=True):
        if sa != sb or not np.array_equal(ma, mb) or not np.array_equal(oa, ob):
            return False
    return True


def test_same_seed_same_actions_same_trajectory():
    traj, chosen, rewards = _play(HandEnv(), seed=11, policy_seed=3)
    again, _, rewards2 = _play(HandEnv(), seed=11, policy_seed=99, actions=chosen)
    assert _same(traj, again)
    assert np.array_equal(rewards, rewards2)
    other, _, _ = _play(HandEnv(), seed=12, policy_seed=3)
    assert not _same(traj, other)


def test_obs_matches_encoder_and_has_fixed_shape():
    env = HandEnv()
    seat, obs, _ = env.reset(5)
    assert obs.shape == (OBS_DIM,) and obs.dtype == np.float32
    assert np.array_equal(obs, encode_reference(env.state, seat))


def test_rewards_zero_sum_and_only_at_hand_end():
    nonzero = 0
    for seed in range(40):
        env = HandEnv(encode=False)
        _, _, mask = env.reset(seed)
        rng = random.Random(seed)
        done = False
        while not done:
            _, _, mask, done, rewards = env.step(rng.choice(np.flatnonzero(mask).tolist()))
            if not done:
                assert not rewards.any()
        assert abs(float(rewards.sum())) < 1e-6
        nonzero += bool(rewards.any())
        hr = env.state.hand_result
        expected = [hr.payments.get(s, 0) / 32 for s in range(4)]
        assert np.allclose(rewards, expected)
    assert nonzero > 0


def test_record_replays_through_reduce():
    env = HandEnv()
    _play(env, seed=21, policy_seed=4)
    record = env.record(players=["a", "b", "c", "d"])
    assert record["engine_version"] == ENGINE_VERSION
    assert record["seed"] == 21
    assert record["result"]["hand_count"] == 1
    assert replay_hand(record) == env.state
    assert RuleSet.from_dict(record["ruleset"]) == env.ruleset


def test_replay_refuses_other_engine_version():
    env = HandEnv(encode=False)
    _play(env, seed=1, policy_seed=1)
    record = env.record() | {"engine_version": "0.0.0"}
    with pytest.raises(ValueError, match="engine_version"):
        replay_hand(record)


def test_random_play_terminates_and_single_action_steps_never_surface():
    auto_played = 0
    # rare under random play: seeds 174, 187, 231, 270 each auto-play once
    for seed in range(300):
        env = HandEnv(encode=False)
        traj, _, _ = _play(env, seed=seed, policy_seed=seed)
        assert env.state.phase in (Phase.HAND_OVER, Phase.GAME_OVER)
        for seat, _, mask in traj[:-1]:
            assert seat in range(4)
            assert mask.sum() >= 2
        auto_played += len(env.actions) - env.decisions
    assert auto_played > 0


def test_illegal_action_raises():
    env = HandEnv(encode=False)
    _, _, mask = env.reset(3)
    illegal = int(np.flatnonzero(~mask)[0])
    with pytest.raises(IllegalActionError):
        env.step(illegal)
    with pytest.raises(IllegalActionError):
        env.step(-1)
    env.step(int(np.flatnonzero(mask)[0]))


def test_step_after_done_raises():
    env = HandEnv(encode=False)
    _play(env, seed=2, policy_seed=2)
    with pytest.raises(RuntimeError):
        env.step(0)
