"""CPU-path pin for `ml.ppo` (docs/06-ml.md §13): a fixed-seed tiny run (2 updates, then a resume
for 1 more) must keep producing the same metrics and parameters on CPU. Pinned before the device
handling landed, so a mismatch means the CPU path changed behaviour.

Counts (samples, env steps, hands) depend on every sampled action and are compared exactly;
floats to 1e-5 relative, since BLAS kernels may differ in the last bits across CPUs.

Regenerate only for an intended behaviour change:

    uv run --extra ml python -m tests.test_ml_ppo_cpu_pin --write
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")

from ml.ppo import PPOConfig, train_ppo

_COUNTS = ("update", "decisions", "samples", "env_steps", "batch_hands", "aux_rows")


def _cfg(tmp: Path) -> PPOConfig:
    return PPOConfig(
        out=str(tmp / "run"),
        envs=4,
        workers=0,
        batch_size=96,
        minibatch=48,
        aux_rate=0.5,
        save_every=1,
        channels=8,
        blocks=1,
        stage={"min_faan": 0, "learners": 1, "keep_prob": 0.5, "oracle_k": 5, "beta": 1.0},
    )


def _sums(state: Any) -> list[float]:
    if isinstance(state, torch.Tensor):
        t = state.detach().double()
        return [float(t.sum()), float(t.abs().sum())]
    out: list[float] = []
    if isinstance(state, dict):
        for key in sorted(state, key=str):
            out += _sums(state[key])
    elif isinstance(state, list | tuple):
        for v in state:
            out += _sums(v)
    elif isinstance(state, int | float) and not isinstance(state, bool):
        out.append(float(state))
    return out


def fingerprint(tmp: Path) -> dict[str, Any]:
    cfg = _cfg(tmp)
    train_ppo(cfg, max_updates=2)
    train_ppo(cfg, resume=True, max_updates=1)
    out = Path(cfg.out)
    records = [json.loads(x) for x in (out / "metrics.jsonl").read_text().splitlines()]
    metrics = [
        {
            k: v
            for k, v in r.items()
            if isinstance(v, int | float) and not k.endswith(("_s", "per_s"))
        }
        for r in records
    ]
    ckpt = torch.load(out / "ckpt_last.pt", weights_only=False, map_location="cpu")
    params = {name: _sums(ckpt["learner"][name]) for name in sorted(ckpt["learner"])}
    return {"metrics": metrics, "params": params}


PIN = Path(__file__).parent / "pins" / "ml_ppo_cpu.json"


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-5, abs_tol=1e-6)


def test_cpu_ppo_run_matches_the_pre_device_pin(tmp_path):
    got, want = fingerprint(tmp_path), json.loads(PIN.read_text())
    assert len(got["metrics"]) == len(want["metrics"])
    for g, w in zip(got["metrics"], want["metrics"], strict=True):
        assert set(g) == set(w)
        for key in w:
            if key in _COUNTS:
                assert g[key] == w[key], key
            else:
                assert _close(g[key], w[key]), (key, g[key], w[key])
    assert set(got["params"]) == set(want["params"])
    for name, sums in want["params"].items():
        mine = got["params"][name]
        assert len(mine) == len(sums), name
        bad = [
            (i, a, b) for i, (a, b) in enumerate(zip(mine, sums, strict=True)) if not _close(a, b)
        ]
        assert not bad, (name, bad[:5])


if __name__ == "__main__":
    import sys
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        result = json.dumps(fingerprint(Path(d)), separators=(",", ":"))
    if "--write" in sys.argv:
        PIN.write_text(result + "\n")
    print(result)
