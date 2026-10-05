"""`ml/migrate_ckpt.py`: an engine-1.0.0 checkpoint computes the same outputs at 1.3.0
(docs/ml.md §9)."""

from __future__ import annotations

from dataclasses import replace

import pytest

np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")

from torch import nn

from mahjong_core.presets import RULESET_PRESETS
from ml.encode_v2 import N_ORACLE_CHANNELS, ruleset_features
from ml.migrate_ckpt import N_SOURCE_SCALARS, migrate, source_ruleset_features
from ml.policy_net import OracleCritic, PolicyNet, PolicyNetConfig
from ml.ppo import Learner, OracleAdapter, PopArt, PPOConfig, critic_from_policy

_TINY = {"channels": 8, "blocks": 1}
_B = 16


def _source_ckpt() -> dict:
    torch.manual_seed(0)
    policy = PolicyNet(PolicyNetConfig(**_TINY, in_scalars=N_SOURCE_SCALARS))
    adapter = OracleAdapter(8)
    critic = critic_from_policy(policy)
    for p in [*policy.parameters(), *adapter.parameters(), *critic.parameters()]:
        nn.init.normal_(p, std=0.3)
    params = [*policy.parameters(), *adapter.parameters(), *critic.parameters()]
    opt = torch.optim.AdamW(params)
    tiles = torch.randn(4, policy.config.in_tiles, 34)
    scalars = torch.randn(4, N_SOURCE_SCALARS)
    loss = (
        policy(tiles, scalars).logits.square().mean()
        + critic(tiles, torch.randn(4, N_ORACLE_CHANNELS, 34), scalars).square().mean()
    )
    loss.backward()
    opt.step()
    return {
        "learner": {
            "policy": policy.state_dict(),
            "adapter": adapter.state_dict(),
            "critic": critic.state_dict(),
            "popart": PopArt(0.1).state_dict(),
            "opt": opt.state_dict(),
        },
        "engine_version": "1.0.0",
        "model_config": policy.config.to_dict(),
        "decisions": 7,
    }


def _inputs(in_tiles: int, min_faan: int) -> tuple[torch.Tensor, ...]:
    g = torch.Generator().manual_seed(min_faan)
    tiles = torch.randn(_B, in_tiles, 34, generator=g)
    oracle = torch.randn(_B, N_ORACLE_CHANNELS, 34, generator=g)
    prefix = torch.randn(_B, N_SOURCE_SCALARS - len(source_ruleset_features(0)), generator=g)
    target = ruleset_features(replace(RULESET_PRESETS["hk_classic"], min_faan=min_faan))
    src = torch.cat([prefix, torch.from_numpy(source_ruleset_features(min_faan)).expand(_B, -1)], 1)
    dst = torch.cat([prefix, torch.from_numpy(target.copy()).expand(_B, -1)], 1)
    return tiles, oracle, src, dst


def _outputs(policy, critic, tiles, oracle, scalars) -> dict[str, torch.Tensor]:
    out = policy(tiles, scalars)
    values = {f"aux.{k}": v for k, v in vars(out.aux).items()}
    return {"logits": out.logits, "value": critic(tiles, oracle, scalars), **values}


@pytest.mark.parametrize("min_faan", [0, 1, 3])
def test_migrated_ppo_checkpoint_matches_on_hk_classic(min_faan):
    ckpt = _source_ckpt()
    old_cfg = PolicyNetConfig(**ckpt["model_config"])
    old_policy, old_critic = PolicyNet(old_cfg), OracleCritic(old_cfg)
    old_policy.load_state_dict(ckpt["learner"]["policy"])
    old_critic.load_state_dict(ckpt["learner"]["critic"])

    new = migrate(ckpt)
    assert new["engine_version"] != "1.0.0" and new["decisions"] == 7
    new_cfg = PolicyNetConfig(**new["model_config"])
    assert new_cfg.in_scalars == PolicyNetConfig().in_scalars != N_SOURCE_SCALARS
    new_policy, new_critic = PolicyNet(new_cfg), OracleCritic(new_cfg)
    new_policy.load_state_dict(new["learner"]["policy"])
    new_critic.load_state_dict(new["learner"]["critic"])

    tiles, oracle, src, dst = _inputs(old_cfg.in_tiles, min_faan)
    with torch.no_grad():
        before = _outputs(old_policy, old_critic, tiles, oracle, src)
        after = _outputs(new_policy, new_critic, tiles, oracle, dst)
    for name, value in before.items():
        torch.testing.assert_close(after[name], value, atol=1e-5, rtol=1e-5, msg=name)


def test_migrated_learner_state_loads_and_keeps_moments():
    ckpt = _source_ckpt()
    new = migrate(ckpt)
    learner = Learner(PPOConfig(**_TINY), PolicyNet(PolicyNetConfig(**new["model_config"])))
    learner.load_state_dict(new["learner"])
    remapped = [
        learner.policy.trunk.scalar_proj.weight,
        learner.policy.policy_global[0].weight,
        learner.critic.trunk.scalar_proj.weight,
        learner.critic.value[0].weight,
    ]
    for p in remapped:
        assert learner.opt.state[p]["exp_avg"].shape == p.shape
    # moments of untouched columns are carried over unchanged
    old_m = ckpt["learner"]["opt"]["state"]
    new_m = new["learner"]["opt"]["state"]
    first = min(old_m)  # trunk.stem.weight: not a scalar layer
    torch.testing.assert_close(new_m[first]["exp_avg"], old_m[first]["exp_avg"])


def test_migrates_r1_checkpoint():
    ckpt = _source_ckpt()
    policy = ckpt["learner"]["policy"]
    r1 = {"model": policy, "model_config": ckpt["model_config"], "algorithm": "rl_aux"}
    new = migrate(r1)
    model = PolicyNet(PolicyNetConfig(**new["model_config"]))
    model.load_state_dict(new["model"])
    old = PolicyNet(PolicyNetConfig(**ckpt["model_config"]))
    old.load_state_dict(policy)
    tiles, _, src, dst = _inputs(old.config.in_tiles, 3)
    with torch.no_grad():
        torch.testing.assert_close(model(tiles, dst).logits, old(tiles, src).logits)


def test_refuses_other_engines_and_shapes():
    ckpt = _source_ckpt()
    with pytest.raises(ValueError, match="engine"):
        migrate({**ckpt, "engine_version": "1.3.0"})
    with pytest.raises(ValueError, match="in_scalars"):
        migrate({**ckpt, "model_config": {**ckpt["model_config"], "in_scalars": 3}})
