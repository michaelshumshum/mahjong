"""`ml/vec_env.py`: batched envs equal K independent `HandEnv`s (docs/ml.md §7)."""

from __future__ import annotations

import random

import pytest

np = pytest.importorskip("numpy")

from ml.env import HandEnv, encode_obs, replay_hand
from ml.vec_env import SubprocVecHandEnv, VecHandEnv, episode_seed

K = 3
BASE = 17
STEPS = 260  # long enough for every env to finish and auto-reset at least once


def _pick(rngs: list[random.Random], mask: np.ndarray) -> np.ndarray:
    return np.asarray(
        [rngs[i].choice(np.flatnonzero(mask[i]).tolist()) for i in range(len(rngs))],
        dtype=np.int32,
    )


def _drive(venv, n: int, steps: int):
    rngs = [random.Random(i) for i in range(n)]
    seat, obs, mask = venv.reset()
    frames = [(seat.copy(), obs.copy(), mask.copy())]
    outs = []
    for _ in range(steps):
        seat, obs, mask, done, rewards = venv.step(_pick(rngs, mask))
        outs.append((seat.copy(), obs.copy(), mask.copy(), done.copy(), rewards.copy()))
    return frames, outs


def test_episode_seed_is_deterministic_and_distinct():
    assert episode_seed(1, 2, 3) == episode_seed(1, 2, 3)
    seeds = {episode_seed(1, i, e) for i in range(8) for e in range(8)}
    assert len(seeds) == 64
    assert all(0 <= s < 2**63 for s in seeds)


def test_vec_env_matches_independent_envs():
    venv = VecHandEnv(K, BASE)
    frames, outs = _drive(venv, K, STEPS)

    rngs = [random.Random(i) for i in range(K)]
    envs = [HandEnv() for _ in range(K)]
    episodes = [0] * K
    seat = np.zeros(K, dtype=np.int32)
    mask = np.zeros_like(frames[0][2])
    for i, env in enumerate(envs):
        s, o, m = env.reset(episode_seed(BASE, i, 0))
        seat[i], mask[i] = s, m
        assert np.array_equal(o, frames[0][1][i])
    assert np.array_equal(seat, frames[0][0]) and np.array_equal(mask, frames[0][2])

    finished = 0
    for v_seat, v_obs, v_mask, v_done, v_rewards in outs:
        actions = _pick(rngs, mask)
        for i, env in enumerate(envs):
            s, o, m, d, r = env.step(int(actions[i]))
            assert d == v_done[i]
            if d:
                finished += 1
                assert np.array_equal(r, v_rewards[i])
                episodes[i] += 1
                s, o, m = env.reset(episode_seed(BASE, i, episodes[i]))
            else:
                assert not v_rewards[i].any()
            assert s == v_seat[i]
            assert np.array_equal(m, v_mask[i])
            assert np.array_equal(o, v_obs[i])
            seat[i], mask[i] = s, m
    assert finished >= K


def test_keep_records_replay():
    venv = VecHandEnv(2, BASE, encode=False, keep_records=True)
    _drive(venv, 2, STEPS)
    assert len(venv.records) >= 2
    for record in venv.records:
        state = replay_hand(record)
        assert list(record["result"]["final_scores"]) == [s.score for s in state.seats]


def test_without_encoding_obs_is_empty():
    venv = VecHandEnv(2, BASE, encode=False)
    _, obs, mask = venv.reset()
    assert obs.shape == (2, 0)
    assert mask.shape == (2, 109)


def test_vec_obs_is_encoder_output():
    venv = VecHandEnv(2, BASE)
    seat, obs, _ = venv.reset()
    for i, env in enumerate(venv._envs):
        assert np.array_equal(obs[i], encode_obs(env.state, int(seat[i])))


def test_subproc_matches_in_process():
    n = 4
    ref = VecHandEnv(n, BASE, keep_records=True)
    frames, outs = _drive(ref, n, 150)
    with SubprocVecHandEnv(n, BASE, n_workers=2, keep_records=True) as sub:
        sub_frames, sub_outs = _drive(sub, n, 150)
        sub_records = sub.records
    for a, b in zip(frames + outs, sub_frames + sub_outs, strict=True):
        for x, y in zip(a, b, strict=True):
            assert np.array_equal(x, y)
    assert sub_records and [r["seed"] for r in sub_records] == [r["seed"] for r in ref.records]


def test_subproc_worker_error_surfaces():
    with SubprocVecHandEnv(2, BASE, n_workers=2, encode=False) as sub:
        _, _, mask = sub.reset()
        bad = np.asarray([int(np.flatnonzero(~mask[i])[0]) for i in range(2)], dtype=np.int32)
        with pytest.raises(RuntimeError, match="IllegalActionError"):
            sub.step(bad)


def test_subproc_rejects_bad_worker_count():
    with pytest.raises(ValueError):
        SubprocVecHandEnv(2, BASE, n_workers=3)
