"""Rollout throughput of the vector env (docs/ml.md §13, R0).

    uv run python -m ml.bench_env --envs 64 --steps 2000 [--workers 4]

Two legs on the same seeds: `engine` (masked uniform-random actions, no encoding) and
`engine+encode` (observations encoded, then a dummy batched numpy linear policy whose masked
Gumbel-max sample is the action). A decision is one returned (non-auto-played) env step.
"""

from __future__ import annotations

import os

# before numpy loads: idle openblas threads in the parent spin and starve the workers (~3x)
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import argparse
import json
import time
from collections.abc import Sequence

import numpy as np

from ml.env import N_ACTIONS, OBS_DIM
from ml.vec_env import SubprocVecHandEnv, VecHandEnv

__all__ = ["bench", "main"]


def _make(n_envs: int, seed: int, workers: int, encode: bool) -> VecHandEnv | SubprocVecHandEnv:
    if workers > 0:
        return SubprocVecHandEnv(n_envs, seed, n_workers=workers, encode=encode)
    return VecHandEnv(n_envs, seed, encode=encode)


def bench(n_envs: int, steps: int, *, seed: int = 0, workers: int = 0, encode: bool) -> dict:
    rng = np.random.default_rng(seed)
    weights = rng.standard_normal((OBS_DIM, N_ACTIONS)).astype(np.float32) * 0.01
    bias = np.zeros(N_ACTIONS, dtype=np.float32)
    venv = _make(n_envs, seed, workers, encode)
    env_s = policy_s = 0.0
    hands = 0
    try:
        t0 = time.perf_counter()
        _, obs, mask = venv.reset()
        env_s += time.perf_counter() - t0
        for _ in range(steps):
            t0 = time.perf_counter()
            if encode:
                logits = obs @ weights + bias
                logits += rng.gumbel(size=logits.shape).astype(np.float32)
            else:
                logits = rng.random((n_envs, N_ACTIONS), dtype=np.float32)
            actions = np.where(mask, logits, -np.inf).argmax(axis=1).astype(np.int32)
            t1 = time.perf_counter()
            _, obs, mask, done, _ = venv.step(actions)
            t2 = time.perf_counter()
            policy_s += t1 - t0
            env_s += t2 - t1
            hands += int(done.sum())
    finally:
        if isinstance(venv, SubprocVecHandEnv):
            venv.close()
    decisions = n_envs * steps
    total = env_s + policy_s
    return {
        "leg": "engine+encode" if encode else "engine",
        "envs": n_envs,
        "workers": workers,
        "decisions": decisions,
        "hands": hands,
        "decisions_per_s": round(decisions / total, 1),
        "ms_per_decision": round(1000 * total / decisions, 4),
        "env_ms_per_decision": round(1000 * env_s / decisions, 4),
        "policy_ms_per_decision": round(1000 * policy_s / decisions, 4),
    }


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--envs", type=int, default=64)
    parser.add_argument("--steps", type=int, default=1000)
    parser.add_argument("--workers", type=int, default=0, help="0 = in-process vector env")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    for encode in (False, True):
        result = bench(args.envs, args.steps, seed=args.seed, workers=args.workers, encode=encode)
        print(json.dumps(result))


if __name__ == "__main__":
    main()
