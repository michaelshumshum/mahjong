"""Device check and PPO throughput benchmark (docs/ml.md §13). `ml`-extra only.

    uv run --extra ml python -m ml.check_device [--updates 3] [--workers 6] [--envs 96]

1. torch / CUDA build, driver, GPU name and capability, and whether the wheel has kernels for it;
2. learner update on CPU and CUDA side by side, on one real batch (`batch_size` learner decisions
   from the C0 env, full-size nets from the config), plus the per-step rollout forward;
3. end-to-end `train_ppo` for `--updates` updates per device: decisions/s, updates/s.

CUDA legs are skipped (and say so) when `torch.cuda.is_available()` is false.
"""

from __future__ import annotations

import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import argparse
import json
import platform
import shutil
import statistics
import subprocess
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import torch

from ml.policy_net import PolicyNet, PolicyNetConfig
from ml.ppo import (
    Collector,
    Episode,
    Learner,
    PPOConfig,
    _env_config,
    build_schedule,
    device_info,
    main_config,
    train_ppo,
)
from ml.train_env import VecTrainEnv

__all__ = ["main"]

_DEFAULT_CONFIG = Path(__file__).parent / "configs" / "rl_ppo_c0.yaml"
# the windows driver mounts it here; not on a non-interactive WSL PATH
_WSL_NVIDIA_SMI = "/usr/lib/wsl/lib/nvidia-smi"


def _on(cfg: PPOConfig, device: torch.device) -> PPOConfig:
    """`cfg` for `device`: amp is cuda-only, so a cpu leg runs without it."""
    return replace(cfg, device=str(device), amp=cfg.amp and device.type == "cuda")


def _driver() -> str | None:
    exe = shutil.which("nvidia-smi")
    if exe is None and os.path.isfile(_WSL_NVIDIA_SMI):
        exe = _WSL_NVIDIA_SMI
    if exe is None:
        return None
    try:
        out = subprocess.run(
            [exe, "--query-gpu=driver_version", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def environment() -> dict[str, Any]:
    env: dict[str, Any] = {
        "python": platform.python_version(),
        "torch": torch.__version__,
        "torch_cuda": torch.version.cuda,
        "cudnn": torch.backends.cudnn.version() if torch.backends.cudnn.is_available() else None,
        "cuda_available": torch.cuda.is_available(),
        "arch_list": torch.cuda.get_arch_list(),
        "driver": _driver(),
        "cpu_count": os.cpu_count(),
        "torch_threads": torch.get_num_threads(),
        "OPENBLAS_NUM_THREADS": os.environ.get("OPENBLAS_NUM_THREADS"),
    }
    if env["cuda_available"]:
        major, minor = torch.cuda.get_device_capability(0)
        props = torch.cuda.get_device_properties(0)
        sm = f"sm_{major}{minor}"
        env.update(
            {
                "device_count": torch.cuda.device_count(),
                "gpu": torch.cuda.get_device_name(0),
                "capability": f"{major}.{minor}",
                "gpu_memory_gb": round(props.total_memory / 2**30, 2),
                "wheel_has_kernels": sm in env["arch_list"],
            }
        )
    return env


def _sync(device: torch.device) -> None:
    if device.type == "cuda":
        torch.cuda.synchronize(device)


def _batch(cfg: PPOConfig) -> tuple[list[Episode], np.ndarray, np.ndarray]:
    """One update's worth of real C0 hands (CPU, in-process), plus one step of rows/masks."""
    schedule = build_schedule(cfg)
    params = schedule.params(0)
    venv = VecTrainEnv(cfg.envs, cfg.seed, _env_config(cfg, params, None))
    torch.manual_seed(cfg.seed)
    cpu = torch.device("cpu")
    policy = PolicyNet(PolicyNetConfig(channels=cfg.channels, blocks=cfg.blocks))
    learner = Learner(_on(cfg, cpu), policy, cpu)
    collector = Collector(venv, round(cfg.envs * cfg.blind_frac), np.random.default_rng(cfg.seed))
    step_rows, step_masks = collector.buf.rows.copy(), collector.buf.mask.copy()
    episodes, _, _ = collector.collect(learner, params, cfg.batch_size)
    return episodes, step_rows, step_masks


def bench_learner(
    cfg: PPOConfig, devices: list[torch.device], updates: int, steps: int
) -> dict[str, Any]:
    episodes, rows, masks = _batch(cfg)
    n = sum(len(e.rows) for e in episodes)
    schedule = build_schedule(cfg)
    params = schedule.params(0)
    keep = np.full(len(rows), params.keep_prob, dtype=np.float32)
    k = np.full(len(rows), params.oracle_k, dtype=np.int64)
    out: dict[str, Any] = {"samples": n}
    for device in devices:
        torch.manual_seed(cfg.seed)
        policy = PolicyNet(PolicyNetConfig(channels=cfg.channels, blocks=cfg.blocks))
        learner = Learner(_on(cfg, device), policy, device)
        rng = np.random.default_rng(0)
        learner.act(rows, masks, keep, k, rng)
        learner.update(episodes, params, 0, 0.0)
        _sync(device)
        t0 = time.perf_counter()
        for _ in range(steps):
            learner.act(rows, masks, keep, k, rng)
        _sync(device)
        t1 = time.perf_counter()
        for _ in range(updates):
            learner.update(episodes, params, 0, 0.0)
        _sync(device)
        t2 = time.perf_counter()
        per_update = (t2 - t1) / updates
        out[str(device)] = {
            "update_s": round(per_update, 3),
            "learner_decisions_per_s": round(n / per_update, 1),
            "act_ms_per_step": round(1000 * (t1 - t0) / steps, 2),
            "envs_per_step": len(rows),
            "amp": learner.cfg.amp,
        }
        if device.type == "cuda":
            out[str(device)]["max_memory_gb"] = round(torch.cuda.max_memory_allocated() / 2**30, 2)
    return out


def bench_transfer(cfg: PPOConfig, device: torch.device, reps: int = 200) -> dict[str, float]:
    """Host->device copy of one rollout step's inputs, pageable vs pinned."""
    tiles = np.random.default_rng(0).random((cfg.envs, 70 + 32, 34), dtype=np.float32)
    out = {}
    for name, src in (
        ("pageable_ms", torch.from_numpy(tiles)),
        ("pinned_ms", torch.from_numpy(tiles).pin_memory()),
    ):
        src.to(device)
        _sync(device)
        t0 = time.perf_counter()
        for _ in range(reps):
            src.to(device, non_blocking=src.is_pinned())
        _sync(device)
        out[name] = round(1000 * (time.perf_counter() - t0) / reps, 4)
    return out


def bench_end_to_end(cfg: PPOConfig, devices: list[torch.device], updates: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for device in devices:
        records: list[dict[str, Any]] = []
        with tempfile.TemporaryDirectory() as d:
            run = replace(_on(cfg, device), out=str(Path(d) / "run"), save_every=10**9)
            t0 = time.perf_counter()
            train_ppo(run, max_updates=updates, on_update=records.append)
            wall = time.perf_counter() - t0
        # the first update pays for worker start-up and lazy cuda init
        steady = records[1:] or records
        decisions = sum(r["samples"] for r in steady)
        busy = sum(r["rollout_s"] + r["update_s"] for r in steady)
        out[str(device)] = {
            "updates": len(records),
            "wall_s": round(wall, 1),
            "rollout_decisions_per_s": round(
                statistics.median(r["rollout_decisions_per_s"] for r in steady), 1
            ),
            "learner_decisions_per_s": round(
                statistics.median(r["learner_decisions_per_s"] for r in steady), 1
            ),
            "decisions_per_s": round(decisions / busy, 1),
            "updates_per_s": round(len(steady) / busy, 4),
            "learner_share": round(sum(r["update_s"] for r in steady) / busy, 3),
        }
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m ml.check_device", description=__doc__)
    p.add_argument("--config", type=Path, default=_DEFAULT_CONFIG)
    p.add_argument("--devices", default=None, help="comma list; default cpu + cuda if available")
    p.add_argument("--bench-updates", type=int, default=3, help="timed learner updates/device")
    p.add_argument("--act-steps", type=int, default=50, help="timed rollout forwards/device")
    p.add_argument("--updates", type=int, default=3, help="end-to-end updates/device; 0 skips")
    p.add_argument("--envs", type=int, default=None)
    p.add_argument("--workers", type=int, default=None)
    p.add_argument("--batch-size", type=int, default=None)
    p.add_argument("--channels", type=int, default=None)
    p.add_argument("--blocks", type=int, default=None)
    p.add_argument(
        "--amp", action="store_true", help="fp16 autocast on cuda legs (cpu legs ignore it)"
    )
    p.add_argument("--json", type=Path, default=None, help="also write the report here")
    return p


def main(argv: list[str] | None = None) -> dict[str, Any]:
    args = build_parser().parse_args(argv)
    cfg = replace(main_config(args.config), init_ckpt=None)
    overrides = {
        "envs": args.envs,
        "workers": args.workers,
        "batch_size": args.batch_size,
        "channels": args.channels,
        "blocks": args.blocks,
    }
    cfg = replace(cfg, **{k: v for k, v in overrides.items() if v is not None})
    cfg = replace(cfg, minibatch=min(cfg.minibatch, cfg.batch_size), amp=cfg.amp or args.amp)
    torch.set_num_threads(cfg.threads)

    report: dict[str, Any] = {"environment": environment()}
    print(json.dumps(report["environment"], indent=2), flush=True)
    names = args.devices.split(",") if args.devices else ["cpu", "cuda"]
    devices: list[torch.device] = []
    for name in names:
        device = torch.device(name)
        if device.type == "cuda" and not torch.cuda.is_available():
            print(f"skipping {name}: torch.cuda.is_available() is False", flush=True)
            continue
        devices.append(device)
    report["devices"] = {str(d): device_info(d) for d in devices}
    report["config"] = {
        k: getattr(cfg, k)
        for k in ("envs", "workers", "threads", "batch_size", "minibatch", "epochs")
    } | {"channels": cfg.channels, "blocks": cfg.blocks, "amp": cfg.amp}

    report["learner"] = bench_learner(cfg, devices, args.bench_updates, args.act_steps)
    print(json.dumps({"learner": report["learner"]}, indent=2), flush=True)
    cuda = [d for d in devices if d.type == "cuda"]
    if cuda:
        report["transfer"] = bench_transfer(cfg, cuda[0])
        print(json.dumps({"transfer": report["transfer"]}, indent=2), flush=True)
    if args.updates > 0:
        report["end_to_end"] = bench_end_to_end(cfg, devices, args.updates)
        print(json.dumps({"end_to_end": report["end_to_end"]}, indent=2), flush=True)
    if args.json is not None:
        args.json.write_text(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    main()
