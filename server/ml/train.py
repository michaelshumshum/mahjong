"""CLI entry point: `python -m ml.train --config ml/configs/danger.yaml [--resume]`
(docker-compose.yml's `trainer` service, this repo's `make train`).

`algorithm: danger` trains the opponent-danger model (`DangerNet`, docs/06-ml.md §5) on a packed
dataset (`ml.pack`). `algorithm: rl_aux` trains `PolicyNet`'s trunk and auxiliary heads
(`ml.aux_train`, §8) on an `ml.aux_data` dataset. Any other algorithm raises
`NotImplementedError`.

A run directory holds `ckpt_last.pt` (resumable), `ckpt_best.pt` (best validation total) and an
append-only `metrics.jsonl`. SIGINT/SIGTERM save a checkpoint after the current step and exit 0.
"""

from __future__ import annotations

import argparse
import json
import math
import signal
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

__all__ = ["ALGORITHMS", "TrainConfig", "build_parser", "load_config", "main", "train"]

ALGORITHMS = ("danger", "rl_aux")


@dataclass
class TrainConfig:
    data: str = "data/danger_v3_packed"
    out: str = "runs/danger"
    seed: int = 0
    threads: int = 10
    channels: int = 96
    blocks: int = 6
    batch_size: int = 512
    steps: int = 36000
    lr: float = 2e-3
    min_lr: float = 2e-5
    warmup: int = 1000
    weight_decay: float = 1e-4
    grad_clip: float = 1.0
    log_every: int = 100
    eval_every: int = 2000
    eval_samples: int = 50000
    save_every: int = 500
    loss_weights: dict[str, float] = field(default_factory=dict)


def load_config(path: Path) -> tuple[str, TrainConfig]:
    raw: dict[str, Any] = yaml.safe_load(path.read_text())
    algorithm = raw.pop("algorithm", None)
    if algorithm not in ALGORITHMS:
        raise NotImplementedError(
            f"ml.train implements {sorted(ALGORITHMS)}, got {algorithm!r} (config={str(path)!r})."
        )
    unknown = set(raw) - set(TrainConfig.__dataclass_fields__)
    if unknown:
        raise ValueError(f"unknown config keys: {sorted(unknown)}")
    return algorithm, TrainConfig(**raw)


def lr_at(step: int, cfg: TrainConfig) -> float:
    if step < cfg.warmup:
        return cfg.lr * (step + 1) / cfg.warmup
    progress = (step - cfg.warmup) / max(1, cfg.steps - cfg.warmup)
    return cfg.min_lr + 0.5 * (cfg.lr - cfg.min_lr) * (1 + math.cos(math.pi * min(1.0, progress)))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ml.train",
        description="Train the opponent-danger model or PolicyNet's auxiliary heads.",
    )
    parser.add_argument("--config", required=True, help="e.g. ml/configs/danger.yaml")
    parser.add_argument("--resume", action="store_true", help="continue from <out>/ckpt_last.pt")
    parser.add_argument("--max-steps", type=int, help="stop after this many total steps")
    parser.add_argument("--out", help="override the config's run directory")
    parser.add_argument("--data", help="override the config's packed dataset directory")
    return parser


def evaluate(model: Any, data: Any, rows: Any, cfg: TrainConfig, weights: Any) -> dict[str, float]:
    import numpy as np
    import torch

    from ml.losses import danger_loss

    n = min(cfg.eval_samples, len(rows) * 3)
    samples = np.random.default_rng(1234).choice(len(rows) * 3, size=n, replace=False)
    model.eval()
    sums: dict[str, float] = {}
    with torch.no_grad():
        for i in range(0, n, 2048):
            chunk = samples[i : i + 2048]
            tiles, scalars, targets = data.batch(rows, chunk)
            losses = danger_loss(model(tiles, scalars), targets, weights)
            for k, v in losses.items():
                sums[k] = sums.get(k, 0.0) + v.item() * len(chunk)
    model.train()
    return {k: v / n for k, v in sums.items()}


def train(cfg: TrainConfig, *, resume: bool = False, max_steps: int | None = None) -> Path:
    import torch

    from ml.danger_model import DangerNet, DangerNetConfig
    from ml.dataset import DangerData
    from ml.losses import LossWeights, danger_loss
    from ml.splits import TRAIN, VAL

    torch.set_num_threads(cfg.threads)
    torch.manual_seed(cfg.seed)
    out = Path(cfg.out)
    out.mkdir(parents=True, exist_ok=True)

    data = DangerData(Path(cfg.data))
    train_rows, val_rows = data.rows_of(TRAIN), data.rows_of(VAL)
    weights = LossWeights(**cfg.loss_weights)
    model = DangerNet(DangerNetConfig(channels=cfg.channels, blocks=cfg.blocks))
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
            },
            tmp,
        )
        tmp.replace(path)

    stop = False

    def request_stop(signum: int, _frame: object) -> None:
        nonlocal stop
        print(f"received signal {signum}, saving after this step", flush=True)
        stop = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    n_samples = len(train_rows) * 3
    steps_per_epoch = n_samples // cfg.batch_size
    if steps_per_epoch == 0:
        raise ValueError(f"{n_samples} train samples is fewer than batch_size={cfg.batch_size}")
    final = cfg.steps if max_steps is None else min(cfg.steps, max_steps)
    metrics = (out / "metrics.jsonl").open("a")
    started, running = time.monotonic(), {}
    model.train()

    while step < final and not stop:
        epoch, k = divmod(step, steps_per_epoch)
        order = data.epoch_order(len(train_rows), cfg.seed, epoch)
        samples = order[k * cfg.batch_size : (k + 1) * cfg.batch_size]
        tiles, scalars, targets = data.batch(train_rows, samples)

        for group in opt.param_groups:
            group["lr"] = lr_at(step, cfg)
        losses = danger_loss(model(tiles, scalars), targets, weights)
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
            val = evaluate(model, data, val_rows, cfg, weights)
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
    metrics.close()
    return out


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    algorithm, cfg = load_config(Path(args.config))
    if args.out:
        cfg.out = args.out
    if args.data:
        cfg.data = args.data
    if algorithm == "rl_aux":
        from ml.aux_train import train_aux

        train_aux(cfg, resume=args.resume, max_steps=args.max_steps)
    else:
        train(cfg, resume=args.resume, max_steps=args.max_steps)


if __name__ == "__main__":
    main(sys.argv[1:])
