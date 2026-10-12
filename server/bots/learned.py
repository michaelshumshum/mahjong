"""`LearnedBot`: the self-play RL policy as a live tier (`T4`, "Expert"; docs/bots.md §2,
docs/ml.md §14 R4).

Served path, nothing else: `policy_raw_from_view(view)` -> `encode_policy_batch` ->
`NumpyPolicyNet` (the shipped `.npz`, `bots/weights/`) -> masked argmax. numpy only: torch, the
oracle encoder and the critic are training-time code this module never imports
(`tests/test_learned_bot.py` pins that in a fresh interpreter).
"""

from __future__ import annotations

import os

# a pool worker runs one decision at a time; BLAS threads per worker would oversubscribe the cores
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import functools
import zipfile
from pathlib import Path
from typing import Any

import numpy as np

from app.views import SeatView
from mahjong_core.engine import ENGINE_VERSION
from ml.encode_v2 import encode_policy_batch, policy_raw_from_view, ruleset_features
from ml.export import NumpyPolicyNet, load_meta

__all__ = ["DEFAULT_WEIGHTS", "LearnedBot", "load_policy", "policy_meta", "weights_problem"]

DEFAULT_WEIGHTS = Path(__file__).resolve().parent / "weights" / "learned.npz"


@functools.cache
def load_policy(path: Path = DEFAULT_WEIGHTS) -> NumpyPolicyNet:
    """Once per process: a pool worker builds a fresh bot per decision (`bots/worker.py`)."""
    return NumpyPolicyNet.load(path)


@functools.cache
def policy_meta(path: Path = DEFAULT_WEIGHTS) -> dict[str, Any] | None:
    return load_meta(path)


def weights_problem(path: Path = DEFAULT_WEIGHTS) -> str | None:
    """`None` when `path` loads and was exported for this `ENGINE_VERSION` (docs/bots.md §2), else
    why not. The API's startup check (`app/main.py`'s `lifespan`), not the per-decision path."""
    try:
        meta = policy_meta(path)
        load_policy(path)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        return f"{path.name}: {type(exc).__name__}: {exc}"
    if meta is None:
        return f"{path.name}: no __meta__ provenance"
    if meta.get("engine_version") != ENGINE_VERSION:
        return f"{path.name}: engine_version {meta.get('engine_version')} != {ENGINE_VERSION}"
    return None


class LearnedBot:
    """Greedy over the policy's legal logits. Refuses an omniscient view: the policy is trained
    and gated on public information only (docs/bots.md §9)."""

    def __init__(self, weights: Path = DEFAULT_WEIGHTS) -> None:
        self.net = load_policy(weights)

    def logits(self, view: SeatView) -> np.ndarray:
        if view.hands is not None:
            raise ValueError("LearnedBot acts on a plain seat_view, never an omniscient one")
        row = policy_raw_from_view(view)
        tiles, scalars = encode_policy_batch(
            {k: v[None] for k, v in row.items()}, ruleset_features(view.ruleset)
        )
        return self.net.forward(tiles, scalars)[0]

    async def act(self, view: SeatView, mask: list[bool], deadline: float) -> int:
        del deadline
        legal = np.asarray(mask, dtype=bool)
        return int(np.argmax(np.where(legal, self.logits(view), -np.inf)))
