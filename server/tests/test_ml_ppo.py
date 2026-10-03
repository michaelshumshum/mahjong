"""`ml/ppo.py`: GAE, shaping, PopArt, masking, oracle dropout and the learner loop
(docs/06-ml.md §9)."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")

from torch import nn

from ml.encode_v2 import ORACLE_FIELDS
from ml.policy_net import PolicyNet, PolicyNetConfig
from ml.ppo import (
    Learner,
    OracleAdapter,
    PopArt,
    PPOConfig,
    critic_from_policy,
    gae,
    ppo_policy_loss,
    shaped_rewards,
    train_ppo,
)
from ml.train_env import EnvConfig, VecTrainEnv, unpack_rows, with_min_faan

_TINY = {"channels": 8, "blocks": 1}


def test_gae_on_hand_built_trajectory():
    r = np.array([0.0, 0.0, 1.0], dtype=np.float32)
    v = np.array([0.5, 0.2, 0.4], dtype=np.float32)
    adv, ret = gae(r, v, 1.0)
    np.testing.assert_allclose(adv, [0.5, 0.8, 0.6], atol=1e-6)
    np.testing.assert_allclose(ret, [1.0, 1.0, 1.0], atol=1e-6)
    adv, _ = gae(r, v, 0.0)
    np.testing.assert_allclose(adv, [-0.3, 0.2, 0.6], atol=1e-6)
    adv, ret = gae(r, v, 0.5)
    np.testing.assert_allclose(adv, [-0.05, 0.5, 0.6], atol=1e-6)
    np.testing.assert_allclose(ret, adv + v, atol=1e-6)


def test_potential_shaping_telescopes():
    rng = np.random.default_rng(0)
    for n in (1, 2, 7, 40):
        phi = -rng.integers(-1, 7, size=n).astype(np.float32)
        final = float(rng.normal())
        r = shaped_rewards(final, phi)
        for t in range(n):
            assert r[t:].sum() == pytest.approx(final - phi[t], abs=1e-5)


def test_popart_update_preserves_outputs():
    torch.manual_seed(0)
    layer = nn.Linear(6, 1)
    popart = PopArt(beta=0.5)
    x = torch.randn(32, 6)
    before = popart.denormalize(layer(x).squeeze(-1)).detach()
    for targets in (torch.randn(100) * 7 + 3, torch.randn(100) * 0.1 - 2):
        popart.update(targets, layer)
        after = popart.denormalize(layer(x).squeeze(-1)).detach()
        torch.testing.assert_close(after, before, atol=1e-4, rtol=1e-4)
    assert float(popart.mu) != 0.0 and float(popart.sigma) != 1.0


def test_masked_policy_loss_ignores_illegal_ids():
    torch.manual_seed(1)
    logits = torch.randn(5, 109, requires_grad=True)
    mask = torch.zeros(5, 109, dtype=torch.bool)
    for i in range(5):
        mask[i, torch.randperm(109)[: 2 + i]] = True
    actions = mask.float().argmax(1)
    out = ppo_policy_loss(logits, mask, actions, torch.zeros(5), torch.ones(5), 0.2)
    probs = out["logp_all"].exp()
    assert (probs[~mask] == 0).all()
    torch.testing.assert_close(probs.sum(1), torch.ones(5))
    ref = []
    for i in range(5):
        p = torch.softmax(logits[i][mask[i]], 0)
        ref.append(-(p * p.log()).sum())
    torch.testing.assert_close(out["entropy"], torch.stack(ref).mean())
    (out["pg"] - out["entropy"]).backward()
    assert torch.isfinite(logits.grad).all()
    assert (logits.grad[~mask] == 0).all()


def _rows(n_steps=40, seed=0):
    venv = VecTrainEnv(4, seed, with_min_faan(EnvConfig(learners=4), 0))
    buf = venv.reset()
    rngs = [random.Random(i) for i in range(4)]
    rows, masks = [], []
    for _ in range(n_steps):
        rows.append(buf.rows.copy())
        masks.append(buf.mask.copy())
        acts = [rngs[i].choice(np.flatnonzero(buf.mask[i]).tolist()) for i in range(4)]
        buf = venv.step(np.asarray(acts, dtype=np.int32))
    return np.concatenate(rows), np.concatenate(masks)


def _learner():
    torch.manual_seed(0)
    learner = Learner(PPOConfig(**_TINY), PolicyNet(PolicyNetConfig(**_TINY)))
    nn.init.normal_(learner.adapter.conv.weight, std=0.5)
    return learner


def test_act_samples_only_legal_ids_and_oracle_reaches_policy_only_through_keep_mask():
    rows, masks = _rows()
    learner = _learner()
    n = len(rows)
    k = np.full(n, 13)
    perturbed = rows.copy()
    u = unpack_rows(perturbed, tuple(ORACLE_FIELDS))
    rng = np.random.default_rng(3)
    for name in ORACLE_FIELDS:
        u[name][...] = rng.integers(0, 4, size=u[name].shape)

    def run(r, p):
        return learner.act(r, masks, np.full(n, p, dtype=np.float32), k, np.random.default_rng(7))

    a0, lp0, keep0 = run(rows, 0.0)
    a1, lp1, _ = run(perturbed, 0.0)
    assert masks[np.arange(n), a0].all()
    np.testing.assert_array_equal(a0, a1)
    np.testing.assert_allclose(lp0, lp1)
    assert not keep0.any()
    _, lp2, keep2 = run(rows, 1.0)
    _, lp3, _ = run(perturbed, 1.0)
    assert np.unpackbits(keep2, axis=1)[:, : 32 * 34].all()
    assert not np.allclose(lp2, lp3)


def test_adapter_contributes_zero_without_oracle_and_critic_starts_from_policy_trunk():
    adapter = OracleAdapter(8)
    nn.init.normal_(adapter.conv.weight)
    assert not adapter(torch.zeros(3, 32, 34)).any()
    policy = PolicyNet(PolicyNetConfig(**_TINY))
    critic = critic_from_policy(policy)
    w = critic.trunk.stem.weight
    torch.testing.assert_close(w[:, :70], policy.trunk.stem.weight)
    assert not w[:, 70:].any()


def test_ppo_improves_a_toy_credit_assignment_task():
    """3 decisions per episode, a masked 5-way choice each; reward only at the end = fraction
    of decisions that picked the context's target. Random play scores ~0.3."""
    torch.manual_seed(0)
    rng = np.random.default_rng(0)
    n_ctx, steps, n_act = 4, 3, 5
    policy = nn.Sequential(nn.Linear(n_ctx * steps, 32), nn.Tanh(), nn.Linear(32, n_act))
    value = nn.Sequential(nn.Linear(n_ctx * steps, 32), nn.Tanh(), nn.Linear(32, 1))
    popart = PopArt(beta=0.1)
    opt = torch.optim.Adam([*policy.parameters(), *value.parameters()], lr=1e-2)

    def target(c, t):
        return (c + 2 * t) % n_act

    def batch(n_eps):
        obs = np.zeros((n_eps, steps, n_ctx * steps), dtype=np.float32)
        masks = rng.random((n_eps, steps, n_act)) < 0.6
        ctx = rng.integers(0, n_ctx, n_eps)
        for t in range(steps):
            obs[np.arange(n_eps), t, ctx * steps + t] = 1.0
            masks[np.arange(n_eps), t, target(ctx, t)] = True
        return obs, masks, ctx

    def score(n_eps=512):
        obs, masks, ctx = batch(n_eps)
        with torch.no_grad():
            lg = policy(torch.from_numpy(obs)).masked_fill(~torch.from_numpy(masks), -1e9)
        hits = lg.argmax(-1).numpy() == np.stack([target(ctx, t) for t in range(steps)], 1)
        return hits.mean()

    start = score()
    for _ in range(150):
        obs, masks, ctx = batch(64)
        o, m = (
            torch.from_numpy(obs.reshape(-1, n_ctx * steps)),
            torch.from_numpy(masks.reshape(-1, n_act)),
        )
        with torch.no_grad():
            logp_all = torch.log_softmax(policy(o).masked_fill(~m, float("-inf")), -1)
            acts = torch.multinomial(logp_all.exp(), 1).squeeze(1)
            old = logp_all.gather(1, acts[:, None]).squeeze(1)
            v = popart.denormalize(value(o).squeeze(-1)).numpy()
        hits = acts.numpy().reshape(64, steps) == np.stack(
            [target(ctx, t) for t in range(steps)], 1
        )
        adv = np.zeros(64 * steps, dtype=np.float32)
        ret = np.zeros(64 * steps, dtype=np.float32)
        for e in range(64):
            sl = slice(e * steps, (e + 1) * steps)
            r = shaped_rewards(hits[e].mean(), np.zeros(steps, dtype=np.float32))
            adv[sl], ret[sl] = gae(r, v[sl], 0.95)
        t_ret = torch.from_numpy(ret)
        popart.update(t_ret, value[-1])
        t_adv = torch.from_numpy((adv - adv.mean()) / (adv.std() + 1e-8))
        for _ in range(2):
            out = ppo_policy_loss(policy(o), m, acts, old, t_adv, 0.2)
            v_loss = 0.5 * ((value(o).squeeze(-1) - popart.normalize(t_ret)) ** 2).mean()
            loss = out["pg"] + 0.5 * v_loss - 0.01 * out["entropy"]
            opt.zero_grad()
            loss.backward()
            opt.step()
    end = score()
    assert start < 0.5
    assert end > 0.9


def _tiny_cfg(tmp_path: Path, **kw) -> PPOConfig:
    base = {
        "out": str(tmp_path / "run"),
        "envs": 4,
        "workers": 0,
        "batch_size": 96,
        "minibatch": 48,
        "aux_rate": 0.5,
        "save_every": 1,
        "stage": {"min_faan": 0, "learners": 1, "keep_prob": 0.5, "oracle_k": 5, "beta": 1.0},
        **_TINY,
    }
    return PPOConfig(**{**base, **kw})


def test_train_ppo_runs_resumes_and_pins_engine_version(tmp_path):
    cfg = _tiny_cfg(tmp_path)
    out = train_ppo(cfg, max_updates=2)
    lines = [json.loads(x) for x in (out / "metrics.jsonl").read_text().splitlines()]
    assert [r["update"] for r in lines] == [1, 2]
    assert all(r["samples"] >= 96 and np.isfinite(r["pg"]) for r in lines)
    assert any("aux" in r for r in lines)
    train_ppo(cfg, resume=True, max_updates=1)
    lines = [json.loads(x) for x in (out / "metrics.jsonl").read_text().splitlines()]
    assert lines[-1]["update"] == 3
    meta = json.loads((out / "meta.json").read_text())
    meta["engine_version"] = "not-this-engine"
    (out / "meta.json").write_text(json.dumps(meta))
    with pytest.raises(RuntimeError, match="ENGINE_VERSION"):
        train_ppo(cfg, resume=True, max_updates=1)


def test_train_ppo_is_deterministic(tmp_path):
    def run(name):
        cfg = _tiny_cfg(tmp_path, out=str(tmp_path / name))
        out = train_ppo(cfg, max_updates=1)
        rec = json.loads((out / "metrics.jsonl").read_text().splitlines()[0])
        return {k: v for k, v in rec.items() if not k.endswith("_s") and "per_s" not in k}

    assert run("a") == run("b")
