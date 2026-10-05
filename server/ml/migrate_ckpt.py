"""Carry an engine-1.0.0 checkpoint onto the engine-1.3.0 ruleset encoding (docs/ml.md §9).

ADR 0020 removed, renamed, added and revalued scoring patterns and took `NEW_18` out of
`hk_classic`. The policy input changed only in the ruleset block at the end of the scalars
(`ml.encode.encode_ruleset`). Within one ruleset that block is constant except for `min_faan`, so
every layer reading it is rewritten with its pattern columns remapped by rule (new patterns
zero) and the constant difference folded into the bias: the migrated network computes exactly
what the old one did on `hk_classic` at every `min_faan`. Rewards still change with the engine;
only the starting point is preserved.

    uv run --extra ml python -m ml.migrate_ckpt runs/ppo_c0/ckpt_last.pt runs/ppo_c1/ckpt_last.pt

Takes a PPO run checkpoint (`learner`) or an R1 `rl_aux` checkpoint (`model`); AdamW moments
are remapped with the weights.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import torch

from mahjong_core.engine import ENGINE_VERSION
from mahjong_core.presets import RULESET_PRESETS
from mahjong_core.scoring.patterns import PATTERNS
from ml.encode import N_RULESET_FEATURES
from ml.encode_v2 import N_POLICY_SCALARS, ruleset_features
from ml.policy_net import PolicyNet, PolicyNetConfig
from ml.ppo import OracleAdapter, critic_from_policy

__all__ = ["SOURCE_ENGINE_VERSION", "migrate", "source_ruleset_features"]

SOURCE_ENGINE_VERSION = "1.0.0"
RULESET = "hk_classic"

# `PATTERNS` registry order and base faan at engine 1.0.0
_SOURCE_PATTERNS: tuple[tuple[str, int], ...] = (
    ("平糊", 1), ("對對糊", 3), ("缺一門", 2), ("混一色", 3), ("清一色", 6), ("無花", 1),
    ("自摸", 1), ("門前清", 1), ("門風", 1), ("圈風", 1), ("箭刻", 1), ("小三元", 3),
    ("大三元", 7), ("小四喜", 5), ("大四喜", 8), ("混么九", 3), ("海底撈月", 1), ("河底撈魚", 1),
    ("槓上開花", 1), ("搶槓", 1), ("座位花", 1), ("正花", 3), ("字一色", 13), ("清么九", 13),
    ("九蓮寶燈", 13), ("十三么", 13), ("天糊", 13), ("地糊", 13), ("七對子", 4), ("三暗刻", 2),
    ("全求人", 2), ("雙箭", 2), ("一般高", 1), ("三般高", 6), ("三步高", 2), ("四步高", 6),
)  # fmt: skip
# hk_classic at 1.0.0: CLASSIC, NEW_6, NEW_18 all on, wall_reserve 0, no overrides
_SOURCE_HAND_SETS = (1.0, 1.0, 1.0)
# 1.3.0 name -> 1.0.0 name of the same rule (ADR 0020)
_RENAMED = {"正花": "座位花", "一台花": "正花", "花么九": "混么九"}

_N_SOURCE_RULESET = 2 + len(_SOURCE_HAND_SETS) + len(_SOURCE_PATTERNS)
_PREFIX = N_POLICY_SCALARS - N_RULESET_FEATURES  # scalars before the ruleset block, unchanged
N_SOURCE_SCALARS = _PREFIX + _N_SOURCE_RULESET


def source_ruleset_features(min_faan: int) -> np.ndarray:
    """1.0.0 `hk_classic`'s ruleset block, scaled as `ruleset_features` scales it."""
    faan = [f / 10.0 for _, f in _SOURCE_PATTERNS]
    return np.asarray([min_faan / 10.0, 0.0, *_SOURCE_HAND_SETS, *faan], dtype=np.float32)


def _target_ruleset_features(min_faan: int) -> np.ndarray:
    return ruleset_features(replace(RULESET_PRESETS[RULESET], min_faan=min_faan)).copy()


def _column_map() -> list[int | None]:
    """Per 1.3.0 ruleset column, the 1.0.0 column it inherits weights from (None: new rule)."""
    source = {name: 5 + i for i, (name, _) in enumerate(_SOURCE_PATTERNS)}
    return [0, 1, 2, 3, 4, *(source.get(_RENAMED.get(p.name, p.name)) for p in PATTERNS)]


def _remap(t: torch.Tensor, start: int, cols: list[int | None]) -> torch.Tensor:
    block = t[:, start : start + _N_SOURCE_RULESET]
    new = block.new_zeros(t.shape[0], len(cols))
    for j, i in enumerate(cols):
        if i is not None:
            new[:, j] = block[:, i]
    return torch.cat([t[:, :start], new, t[:, start + _N_SOURCE_RULESET :]], dim=1)


def _ruleset_starts(prefix: str, channels: int) -> dict[str, int]:
    """Linear layers reading the scalars -> column where the ruleset block starts."""
    pooled = 2 * channels  # `Trunk.pooled`: mean, max, then the scalars
    layers = {
        "policy": {"trunk.scalar_proj": 0, "policy_global.0": pooled, "aux_global.0": pooled},
        "critic": {"trunk.scalar_proj": 0, "value.0": pooled},
    }[prefix]
    return {name: off + _PREFIX for name, off in layers.items()}


def _migrate_state(state: dict[str, Any], starts: dict[str, int]) -> dict[str, Any]:
    cols = _column_map()
    # min_faan has the same column, scale and weights on both sides, so it cancels in the fold
    src = torch.from_numpy(source_ruleset_features(0)).double()
    dst = torch.from_numpy(_target_ruleset_features(0)).double()
    out = dict(state)
    for name, start in starts.items():
        w, b = state[f"{name}.weight"], state[f"{name}.bias"]
        new_w = _remap(w, start, cols)
        old_block = w[:, start : start + _N_SOURCE_RULESET].double()
        new_block = new_w[:, start : start + len(cols)].double()
        out[f"{name}.bias"] = (b.double() + old_block @ src - new_block @ dst).to(b.dtype)
        out[f"{name}.weight"] = new_w
    return out


def _migrate_opt(opt: dict[str, Any], names: list[str], starts: dict[str, int]) -> dict[str, Any]:
    """AdamW moments follow their weight's columns; new columns start at zero."""
    ids = [i for group in opt["param_groups"] for i in group["params"]]
    if len(ids) != len(names):
        raise ValueError(f"optimizer holds {len(ids)} params, model has {len(names)}")
    cols = _column_map()
    state = {}
    for pid, moments in opt["state"].items():
        start = starts.get(names[ids.index(pid)].removesuffix(".weight"))
        state[pid] = (
            moments
            if start is None
            else {
                k: _remap(v, start, cols) if k.startswith("exp_avg") else v
                for k, v in moments.items()
            }
        )
    return {**opt, "state": state}


def _param_names(config: PolicyNetConfig, critic: bool) -> list[str]:
    policy = PolicyNet(config)
    names = [f"policy.{n}" for n, _ in policy.named_parameters()]
    if critic:
        names += [f"adapter.{n}" for n, _ in OracleAdapter(config.channels).named_parameters()]
        names += [f"critic.{n}" for n, _ in critic_from_policy(policy).named_parameters()]
    return names


def migrate(ckpt: dict[str, Any]) -> dict[str, Any]:
    """A PPO or R1 checkpoint at 1.0.0 -> the same checkpoint at the current engine."""
    # rl_aux checkpoints don't pin the engine; in_scalars is the check that matters
    version = ckpt.get("engine_version", SOURCE_ENGINE_VERSION)
    if version != SOURCE_ENGINE_VERSION:
        raise ValueError(f"checkpoint engine {version!r}, migrates from {SOURCE_ENGINE_VERSION!r}")
    config = PolicyNetConfig(**ckpt["model_config"])
    if config.in_scalars != N_SOURCE_SCALARS:
        raise ValueError(f"in_scalars {config.in_scalars}, expected {N_SOURCE_SCALARS}")
    policy_starts = {
        f"policy.{k}": v for k, v in _ruleset_starts("policy", config.channels).items()
    }
    out = {
        **ckpt,
        "model_config": {**ckpt["model_config"], "in_scalars": N_POLICY_SCALARS},
        "engine_version": ENGINE_VERSION,
        "migrated_from": SOURCE_ENGINE_VERSION,
    }
    if "learner" in ckpt:
        learner = dict(ckpt["learner"])
        learner["policy"] = _migrate_state(
            learner["policy"], _ruleset_starts("policy", config.channels)
        )
        learner["critic"] = _migrate_state(
            learner["critic"], _ruleset_starts("critic", config.channels)
        )
        starts = {
            **policy_starts,
            **{f"critic.{k}": v for k, v in _ruleset_starts("critic", config.channels).items()},
        }
        learner["opt"] = _migrate_opt(learner["opt"], _param_names(config, critic=True), starts)
        out["learner"] = learner
    else:
        out["model"] = _migrate_state(ckpt["model"], _ruleset_starts("policy", config.channels))
        if "opt" in ckpt:
            out["opt"] = _migrate_opt(
                ckpt["opt"], _param_names(config, critic=False), policy_starts
            )
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("src", type=Path)
    parser.add_argument("dst", type=Path)
    args = parser.parse_args(argv)
    if args.dst.exists():
        raise SystemExit(f"{args.dst} exists")
    ckpt = torch.load(args.src, weights_only=False, map_location="cpu")
    args.dst.parent.mkdir(parents=True, exist_ok=True)
    torch.save(migrate(ckpt), args.dst)
    print(f"{args.src} ({SOURCE_ENGINE_VERSION}) -> {args.dst} ({ENGINE_VERSION})")


if __name__ == "__main__":
    main()
