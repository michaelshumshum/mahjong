"""Supervised training loop shared by `ml.train.train` (danger) and `ml.aux_train.train_aux`:
resume from and save `ckpt_last.pt`, AdamW step with the `lr_at` schedule and grad clipping,
`metrics.jsonl` records and `ckpt_best.pt` on the lowest validation `total`.

The checkpoint keys (`model`, `opt`, `step`, `best`, `config`, `model_config`, plus each caller's
`extra`) are read by `ml.export`, `ml.migrate_ckpt` and existing runs; don't rename them."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import torch

from ml.stop_signal import StopSignal
from ml.train import TrainConfig, lr_at

__all__ = ["fit", "start_run"]


def start_run(cfg: TrainConfig) -> Path:
    """Threads, seed and run directory; call before building the model so its init is seeded."""
    torch.set_num_threads(cfg.threads)
    torch.manual_seed(cfg.seed)
    out = Path(cfg.out)
    out.mkdir(parents=True, exist_ok=True)
    return out


def fit(
    cfg: TrainConfig,
    out: Path,
    model: Any,
    opt: torch.optim.Optimizer,
    *,
    steps_per_epoch: int,
    batch_losses: Callable[[int, int], dict[str, torch.Tensor]],
    evaluate: Callable[[], dict[str, float]],
    extra: dict[str, Any] | None = None,
    resume: bool = False,
    max_steps: int | None = None,
) -> Path:
    """`batch_losses(epoch, k)` returns the loss dict (with `total`) of the epoch's `k`-th batch;
    `evaluate()` the validation means of the same keys."""
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
                **(extra or {}),
            },
            tmp,
        )
        tmp.replace(path)

    stop = StopSignal("saving after this step")

    final = cfg.steps if max_steps is None else min(cfg.steps, max_steps)
    started, running = time.monotonic(), {}
    model.train()
    with (out / "metrics.jsonl").open("a") as metrics:
        while step < final and not stop.requested:
            for group in opt.param_groups:
                group["lr"] = lr_at(step, cfg)
            losses = batch_losses(*divmod(step, steps_per_epoch))
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
                val = evaluate()
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
