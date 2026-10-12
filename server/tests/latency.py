"""Shared check for the `latency`-marked tests (docs/testing.md §1 "Latency tests").

The gate is a ratio: `samples` against `reference`, timed back to back on the same inputs, so it
holds on any CPU and under `-n`. `LATENCY_BUDGET_MS` adds docs/ml.md §6's absolute budget, meant
for the target CPU (`make bench-latency`). Absolute numbers also go to `$GITHUB_STEP_SUMMARY`.
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import numpy as np

__all__ = ["check_latency"]


def check_latency(
    name: str,
    samples: Sequence[float],
    reference_name: str,
    reference: Sequence[float],
    *,
    max_ratio: float = 1.0,
    q: float = 99,
) -> None:
    """Asserts `percentile(samples, q) < max_ratio * percentile(reference, q)`, plus
    `percentile(samples, q) < LATENCY_BUDGET_MS` when that is set."""
    p50, pq = np.percentile(samples, [50, q])
    r50, rq = np.percentile(reference, [50, q])
    tail, rtail = (
        ("", "") if q == 50 else (f", p{q:g} {pq * 1e3:.2f} ms", f", p{q:g} {rq * 1e3:.2f} ms")
    )
    line = (
        f"{name}: p50 {p50 * 1e3:.2f} ms{tail}; "
        f"{reference_name} p50 {r50 * 1e3:.2f} ms{rtail}; n={len(samples)}"
    )
    print(line)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(f"- {line}\n")
    assert pq < max_ratio * rq, line
    budget = os.environ.get("LATENCY_BUDGET_MS")
    if budget:
        assert pq * 1e3 < float(budget), f"{line}; budget {budget} ms"
