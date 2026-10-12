"""`ml/train_env.py`: packed PPO rollout rows, in-env tsumogiri opponents (docs/ml.md §9, §10)."""

from __future__ import annotations

import random

import pytest

np = pytest.importorskip("numpy")
# numpy is a base dep; ml.train_env reaches pyarrow (ml extra) via ml.generate_dataset
pytest.importorskip("pyarrow")

from app.views import seat_view
from bots.labels import seat_hand34
from mahjong_core.config import DEFAULT_RULESET
from mahjong_core.engine import reduce
from mahjong_core.ml import decode_action
from mahjong_core.shanten import shanten
from mahjong_core.state import Phase
from ml.encode_v2 import ORACLE_FIELDS, PAD, POLICY_FIELDS, oracle_raw, policy_raw_from_view
from ml.train_env import (
    FROZEN,
    LEARNER,
    ROW_BYTES,
    EnvConfig,
    SubprocVecTrainEnv,
    TrainEnv,
    VecTrainEnv,
    tsumogiri,
    unpack_rows,
    with_min_faan,
)

K = 3
STEPS = 120
_C0 = with_min_faan(EnvConfig(learners=1, aux_rate=0.5), 0)


def _pick(rngs, mask):
    return np.asarray(
        [rngs[i].choice(np.flatnonzero(mask[i]).tolist()) for i in range(len(rngs))],
        dtype=np.int32,
    )


def _drive(venv, steps=STEPS):
    rngs = [random.Random(i) for i in range(venv.num_envs)]
    buf = venv.reset()
    out = [(buf.seat.copy(), buf.mask.copy(), buf.rows.copy())]
    for _ in range(steps):
        buf = venv.step(_pick(rngs, buf.mask))
        out.append(
            (
                buf.seat.copy(),
                buf.mask.copy(),
                buf.rows.copy(),
                buf.done.copy(),
                buf.rewards.copy(),
                buf.info.copy(),
            )
        )
    return out


def _equal(a, b):
    assert len(a) == len(b)
    for x, y in zip(a, b, strict=True):
        for u, v in zip(x, y, strict=True):
            np.testing.assert_array_equal(u, v)


def test_same_seed_same_rows_and_subproc_matches():
    a = _drive(VecTrainEnv(K, 5, _C0))
    b = _drive(VecTrainEnv(K, 5, _C0))
    _equal(a, b)
    with SubprocVecTrainEnv(K, 5, _C0, n_workers=2) as sub:
        _equal(a, _drive(sub))
    assert any(step[3].any() for step in a[1:])  # episodes finished and auto-reset


def test_policy_row_is_the_seat_view_row_and_oracle_is_separate():
    venv = VecTrainEnv(2, 9, EnvConfig(learners=4, aux_rate=0.0))
    buf = venv.reset()
    rngs = [random.Random(i) for i in range(2)]
    for _ in range(150):
        rows = unpack_rows(buf.rows)
        for i, env in enumerate(venv.envs):
            ref = policy_raw_from_view(seat_view(env.env.state, int(buf.seat[i])))
            for name in POLICY_FIELDS:
                np.testing.assert_array_equal(rows[name][i], ref[name])
            hidden = oracle_raw(env.env.state, int(buf.seat[i]))
            for name in ORACLE_FIELDS:
                np.testing.assert_array_equal(rows[name][i], hidden[name])
        buf = venv.step(_pick(rngs, buf.mask))
    assert not set(POLICY_FIELDS) & set(ORACLE_FIELDS)


def test_shanten_potential_and_aux_subsample():
    env = TrainEnv(_C0)
    rng = random.Random(0)
    flagged = rows = 0
    for seed in range(4):
        assert env.reset(seed)
        while True:
            r = unpack_rows(env.row[None])
            st = env.env.state.seats[env.seat]
            sh = shanten(
                seat_hand34(st), closed=not st.melds, hand_sets=env.env.state.ruleset.hand_sets
            )
            assert int(r["cur_shanten"][0]) == sh + 1
            assert int(r["min_faan"][0]) == 0
            assert int(r["role"][0]) == LEARNER
            assert int(r["teacher"][0]) == PAD
            rows += 1
            if r["aux"][0]:
                flagged += 1
            else:
                assert not r["opp_wait"].any() and (r["shanten"] == PAD).all()
            done, _, _ = env.step(rng.choice(np.flatnonzero(env.mask).tolist()))
            if done:
                break
    assert 0.3 < flagged / rows < 0.7


def test_tsumogiri_seats_never_claim_or_win():
    env = TrainEnv(with_min_faan(EnvConfig(learners=1), 0))
    rng = random.Random(1)
    opp_actions = 0
    for seed in range(30):
        assert env.reset(seed)
        learner = env.roles.index(LEARNER)
        while True:
            done, rewards, info = env.step(rng.choice(np.flatnonzero(env.mask).tolist()))
            if done:
                break
        state = env.env.state
        assert info[0] in (-1, learner)
        for s in range(4):
            if s != learner:
                assert rewards[s] <= 0
                assert not state.seats[s].melds
        opp_actions += len(env.env.actions)
    assert opp_actions > 0


def test_tsumogiri_discards_the_drawn_tile_and_passes_claims():
    env = TrainEnv(EnvConfig(learners=4))
    env.reset(3)
    rng = random.Random(3)
    seen_turn = seen_claim = 0
    while not env.env.done:
        state, seat, mask = env.env.state, env.seat, env.mask
        aid = tsumogiri(state, seat, mask)
        assert mask[aid]
        action = decode_action(aid, state, seat)
        if state.phase == Phase.AWAIT_ACTION:
            seen_turn += 1
            assert aid == state.seats[seat].concealed[-1] // 4
        else:
            seen_claim += 1
            assert aid == 102
        reduce(state, action)
        env.step(rng.choice(np.flatnonzero(mask).tolist()))
    assert seen_turn and seen_claim


def test_frozen_seats_surface_with_their_role():
    env = TrainEnv(EnvConfig(learners=1, frozen=1, aux_rate=1.0))
    rng = random.Random(2)
    roles = set()
    env.reset(11)
    while True:
        r = unpack_rows(env.row[None])
        roles.add(int(r["role"][0]))
        if int(r["role"][0]) == FROZEN:
            assert not r["aux"][0]
        done, _, _ = env.step(rng.choice(np.flatnonzero(env.mask).tolist()))
        if done:
            break
    assert roles == {LEARNER, FROZEN}


def test_configure_applies_at_next_episode():
    venv = VecTrainEnv(1, 0, EnvConfig(learners=4))
    buf = venv.reset()
    venv.configure(_C0)
    assert int(unpack_rows(buf.rows)["min_faan"][0]) == DEFAULT_RULESET.min_faan
    rng = [random.Random(0)]
    while not buf.done[0]:
        buf = venv.step(_pick(rng, buf.mask))
    assert int(unpack_rows(buf.rows)["min_faan"][0]) == 0
    assert buf.rows.shape == (1, ROW_BYTES)
