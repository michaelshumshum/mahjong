"""Supervised training of `PolicyNet`'s trunk and auxiliary heads (docs/ml.md §8, R1):
`python -m ml.train --config ml/configs/rl_aux.yaml` dispatches here.

Only the trunk and auxiliary heads receive gradient; the policy head has no target (no bot
action is ever a label, §6) and stays at initialisation. Run directory layout, resume and
signal handling as `ml.train.train`.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch

from ml.aux_data import AuxData
from ml.losses import AuxWeights, aux_loss
from ml.policy_net import PolicyNet, PolicyNetConfig
from ml.splits import TRAIN, VAL
from ml.stop_signal import StopSignal
from ml.train import TrainConfig, lr_at

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
    torch.set_num_threads(cfg.threads)
    torch.manual_seed(cfg.seed)
    out = Path(cfg.out)
    out.mkdir(parents=True, exist_ok=True)

    data = AuxData(Path(cfg.data))
    train_rows, val_rows = data.rows_of(TRAIN), data.rows_of(VAL)
    if len(train_rows) < cfg.batch_size:
        raise ValueError(f"{len(train_rows)} train rows is fewer than batch_size={cfg.batch_size}")
    weights = AuxWeights(**cfg.loss_weights)
    model = PolicyNet(PolicyNetConfig(channels=cfg.channels, blocks=cfg.blocks))
    opt = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)

    step, best = 0, float("inf")
    last_path = out / "ckpt_last.pt"
    if resume and last_path.exists():
        ckpt = torch.load(last_path, weights_only=False)
        model.load_state_dict(ckpt["model"])
        opt.load_state_dict(ckpt["opt"])
        step, best = ckpt["step"], ckpt["best"]

    def save(path: Path) -> None:
        tmp = path.with_suffix(".tmp")
        torch.save(
            {
                "model": model.state_dict(),
                "opt": opt.state_dict(),
                "step": step,
                "best": best,
                "config": cfg.__dict__,
                "model_config": model.config.to_dict(),
                "algorithm": "rl_aux",
            },
            tmp,
        )
        tmp.replace(path)

    stop = StopSignal("saving after this step")

    steps_per_epoch = len(train_rows) // cfg.batch_size
    final = cfg.steps if max_steps is None else min(cfg.steps, max_steps)
    started, running = time.monotonic(), {}
    model.train()
    with (out / "metrics.jsonl").open("a") as metrics:
        while step < final and not stop.requested:
            epoch, k = divmod(step, steps_per_epoch)
            order = np.random.default_rng([cfg.seed, epoch]).permutation(len(train_rows))
            batch = train_rows[order[k * cfg.batch_size : (k + 1) * cfg.batch_size]]
            for group in opt.param_groups:
                group["lr"] = lr_at(step, cfg)
            losses = _forward(model, data, batch, weights)
            opt.zero_grad(set_to_none=True)
            losses["total"].backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.grad_clip)
            opt.step()
            step += 1

            for name, value in losses.items():
                running[name] = running.get(name, 0.0) + value.item()
            record: dict[str, Any] = {}
            if step % cfg.log_every == 0:
                record = {f"train_{k}": v / cfg.log_every for k, v in running.items()}
                record["lr"] = lr_at(step, cfg)
                record["elapsed_s"] = round(time.monotonic() - started, 1)
                running = {}
            if step % cfg.eval_every == 0 or step == final:
                val = evaluate_aux(model, data, val_rows, cfg.eval_samples, weights)
                record.update({f"val_{k}": v for k, v in val.items()})
                if val["total"] < best:
                    best = val["total"]
                    save(out / "ckpt_best.pt")
            if record:
                record["step"] = step
                metrics.write(json.dumps(record) + "\n")
                metrics.flush()
                print(json.dumps(record), flush=True)
            if step % cfg.save_every == 0:
                save(last_path)
    save(last_path)
    return out
