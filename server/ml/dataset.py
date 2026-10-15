"""Samples of the danger model from a packed dataset (`ml.pack`). One sample is a (row, opponent)
pair: sample `s` of a row list `R` is row `R[s // 3]`, opponent `s % 3`."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch

from mahjong_core.config import RuleSet
from ml.encode import N_OPPONENTS, encode_batch, encode_ruleset
from ml.losses import targets_from_raw
from ml.pack import load_packed

__all__ = ["DangerData"]


class DangerData:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.raw = load_packed(path)
        self.meta = json.loads((path / "meta.json").read_text())
        ruleset = RuleSet.from_dict(self.meta["manifest"]["ruleset"])
        self.ruleset_vec = encode_ruleset(ruleset)

    def rows_of(self, split: int) -> np.ndarray:
        return np.flatnonzero(np.asarray(self.raw["split"]) == split)

    @staticmethod
    def epoch_order(n_rows: int, seed: int, epoch: int) -> np.ndarray:
        """Shuffled sample indices for one pass; a pure function of `(seed, epoch)` so a resumed
        run continues the same order."""
        return np.random.default_rng([seed, epoch]).permutation(n_rows * N_OPPONENTS)

    def batch(
        self, rows: np.ndarray, samples: np.ndarray
    ) -> tuple[torch.Tensor, torch.Tensor, dict[str, torch.Tensor]]:
        """Encoded tensors and targets for `samples` (indices into `rows`' sample space)."""
        row_idx = rows[samples // N_OPPONENTS]
        opp = samples % N_OPPONENTS
        needed = {k: np.asarray(v[row_idx]) for k, v in self.raw.items() if k != "split"}
        tiles, scalars = encode_batch(needed, opp, self.ruleset_vec)
        targets = targets_from_raw(needed, np.arange(len(row_idx)), opp)
        return (
            torch.from_numpy(tiles),
            torch.from_numpy(scalars),
            {k: torch.from_numpy(v) for k, v in targets.items()},
        )
