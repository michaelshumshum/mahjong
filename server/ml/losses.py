"""Masked losses for the opponent-danger model (docs/06-ml.md §5) and `PolicyNet`'s auxiliary
heads (§8), which follow the same wait/faan conventions.

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
from ml.policy_net import AuxOutput

__all__ = ["AuxWeights", "LossWeights", "aux_loss", "danger_loss", "targets_from_raw"]


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


@dataclass(frozen=True)
class AuxWeights:
    tenpai: float = 0.5
    legal: float = 1.0
    struct: float = 0.25
    faan: float = 0.25
    win: float = 0.5
    deal_in: float = 0.5
    points: float = 0.25
    hidden: float = 1.0
    shanten: float = 0.25
    ukeire: float = 0.25


def _masked_mean(x: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    return (x * mask).sum() / mask.sum().clamp(min=1.0)


def aux_loss(
    out: AuxOutput, t: dict[str, torch.Tensor], weights: AuxWeights | None = None
) -> dict[str, torch.Tensor]:
    """`PolicyNet` auxiliary losses against `ml.aux_data.aux_targets`. `hidden` is the mean
    negative log-likelihood of each unseen copy's true location; `points` is fitted on won hands
    only; shanten/ukeire only at tiles the seat could discard on its own turn."""
    w = weights or AuxWeights()
    losses = {
        "tenpai": F.binary_cross_entropy_with_logits(out.tenpai, t["tenpai"]),
        "legal": F.binary_cross_entropy_with_logits(out.legal_wait, t["legal"]),
        "struct": F.binary_cross_entropy_with_logits(out.struct_wait, t["struct"]),
        "win": F.binary_cross_entropy_with_logits(out.win, t["win"]),
        "deal_in": F.binary_cross_entropy_with_logits(out.deal_in, t["deal_in"]),
    }
    legal = t["legal"] > 0
    if legal.any():
        classes = t["faan"][legal].long().clamp(max=N_FAAN_CLASSES) - 1
        losses["faan"] = F.cross_entropy(out.faan[legal], classes)
    else:
        losses["faan"] = out.faan.sum() * 0.0
    won = t["win"] > 0
    if won.any():
        losses["points"] = F.smooth_l1_loss(out.points[won], t["points"][won])
    else:
        losses["points"] = out.points.sum() * 0.0
    logp = out.hidden.log_softmax(dim=1)
    losses["hidden"] = -(t["hidden"] * logp).sum() / t["hidden"].sum().clamp(min=1.0)
    m = t["shanten_mask"]
    for name in ("shanten", "ukeire"):
        err = F.smooth_l1_loss(getattr(out, name), t[name], reduction="none")
        losses[name] = _masked_mean(err, m)
    total = sum(getattr(w, k) * v for k, v in losses.items())
    return {"total": total, **losses}  # type: ignore[dict-item]
