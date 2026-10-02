"""Masked losses for the opponent-danger model (docs/06-ml.md §5).

Wait heads are trained unconditionally on every tile, not only when the opponent is tenpai: the
model is used to price a discard, so it has to say "safe" for non-tenpai opponents too. The
primary target is a *legal* win (`expected_faan > 0`); the structural wait is auxiliary. Faan is
only defined where a legal win exists, so its cross-entropy is masked to those tiles. No
`pos_weight`: reweighting positives would break the probability calibration `tile_risk` needs.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch
import torch.nn.functional as F

from ml.danger_model import N_FAAN_CLASSES, DangerOutput

__all__ = ["LossWeights", "danger_loss", "targets_from_raw"]


@dataclass(frozen=True)
class LossWeights:
    tenpai: float = 0.5
    legal: float = 1.0
    struct: float = 0.25
    faan: float = 0.25


def targets_from_raw(
    raw: dict[str, np.ndarray], rows: np.ndarray, opp: np.ndarray
) -> dict[str, np.ndarray]:
    """Label arrays for `(rows[i], opp[i])` samples from `ml.pack` fields. `faan` is 0 where no
    legal win exists, else the class index + 1 (clipped to `N_FAAN_CLASSES`)."""
    faan = raw["opponent_expected_faan"][rows, opp].astype(np.int64)
    return {
        "tenpai": raw["opponent_is_tenpai"][rows, opp].astype(np.float32),
        "struct": raw["opponent_winning_tiles_multihot"][rows, opp].astype(np.float32),
        "legal": (faan > 0).astype(np.float32),
        "faan": np.clip(faan, 0, N_FAAN_CLASSES),
    }


def danger_loss(
    out: DangerOutput, targets: dict[str, torch.Tensor], weights: LossWeights | None = None
) -> dict[str, torch.Tensor]:
    w = weights or LossWeights()
    tenpai = F.binary_cross_entropy_with_logits(out.tenpai, targets["tenpai"])
    legal = F.binary_cross_entropy_with_logits(out.legal_wait, targets["legal"])
    struct = F.binary_cross_entropy_with_logits(out.struct_wait, targets["struct"])

    mask = targets["legal"] > 0
    if mask.any():
        classes = targets["faan"][mask].long() - 1
        faan = F.cross_entropy(out.faan[mask], classes)
    else:
        faan = out.faan.sum() * 0.0
    total = w.tenpai * tenpai + w.legal * legal + w.struct * struct + w.faan * faan
    return {"total": total, "tenpai": tenpai, "legal": legal, "struct": struct, "faan": faan}
