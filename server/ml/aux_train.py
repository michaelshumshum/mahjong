"""Supervised training of `PolicyNet`'s trunk and auxiliary heads (docs/ml.md §8, R1):
`python -m ml.train --config ml/configs/rl_aux.yaml` dispatches here.

Only the trunk and auxiliary heads receive gradient; the policy head has no target (no bot
action is ever a label, §6) and stays at initialisation. Run directory layout, resume and
signal handling as `ml.train.train`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import torch

from ml.aux_data import AuxData
from ml.losses import AuxWeights, aux_loss
from ml.policy_net import PolicyNet, PolicyNetConfig
from ml.splits import TRAIN, VAL
from ml.train import TrainConfig
from ml.train_loop import fit, start_run

__all__ = ["evaluate_aux", "to_tensors", "train_aux"]


def to_tensors(arrays: dict[str, np.ndarray]) -> dict[str, torch.Tensor]:
    return {k: torch.from_numpy(np.ascontiguousarray(v)) for k, v in arrays.items()}


def _forward(model: PolicyNet, data: AuxData, rows: np.ndarray, weights: AuxWeights) -> Any:
    inputs, targets, _ = data.arrays(rows)
    x = to_tensors(inputs)
    out = model(x["tiles"], x["scalars"])
    assert out.aux is not None
    return aux_loss(out.aux, to_tensors(targets), weights)


def evaluate_aux(
    model: PolicyNet, data: AuxData, rows: np.ndarray, n: int, weights: AuxWeights
) -> dict[str, float]:
    picked = np.random.default_rng(1234).choice(len(rows), size=min(n, len(rows)), replace=False)
    sums: dict[str, float] = {}
    model.eval()
    with torch.no_grad():
        for i in range(0, len(picked), 2048):
            chunk = rows[picked[i : i + 2048]]
            for k, v in _forward(model, data, chunk, weights).items():
                sums[k] = sums.get(k, 0.0) + v.item() * len(chunk)
    model.train()
    return {k: v / len(picked) for k, v in sums.items()}


def train_aux(cfg: TrainConfig, *, resume: bool = False, max_steps: int | None = None) -> Path:
    out = start_run(cfg)
    data = AuxData(Path(cfg.data))
    train_rows, val_rows = data.rows_of(TRAIN), data.rows_of(VAL)
    if len(train_rows) < cfg.batch_size:
        raise ValueError(f"{len(train_rows)} train rows is fewer than batch_size={cfg.batch_size}")
    weights = AuxWeights(**cfg.loss_weights)
    model = PolicyNet(PolicyNetConfig(channels=cfg.channels, blocks=cfg.blocks))
    opt = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)

    def batch_losses(epoch: int, k: int) -> dict[str, torch.Tensor]:
        order = np.random.default_rng([cfg.seed, epoch]).permutation(len(train_rows))
        batch = train_rows[order[k * cfg.batch_size : (k + 1) * cfg.batch_size]]
        return _forward(model, data, batch, weights)

    return fit(
        cfg,
        out,
        model,
        opt,
        steps_per_epoch=len(train_rows) // cfg.batch_size,
        batch_losses=batch_losses,
        evaluate=lambda: evaluate_aux(model, data, val_rows, cfg.eval_samples, weights),
        extra={"algorithm": "rl_aux"},
        resume=resume,
        max_steps=max_steps,
    )
