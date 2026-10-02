"""Torch-free export of a trained danger model (docs/06-ml.md §5):

    python -m ml.export --ckpt runs/danger/ckpt_best.pt --out runs/danger/danger.npz

The checkpoint's weights go to a plain `.npz` and `NumpyDangerNet` re-implements the forward pass
in numpy, so serving needs numpy only, not torch or an ONNX runtime. A parity test pins it to the
torch model. Loading needs numpy alone; exporting needs the checkpoint's torch.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

__all__ = ["NumpyDangerNet", "export_checkpoint", "export_state", "main"]

_PADDED_WIDTH = 37
_N_TILE_TYPES = 34
_GROUPS = 8
_EPS = 1e-5
_POSITIONS = np.array([*range(9), *range(10, 19), *range(20, 29), *range(30, 37)])
_MASK = np.zeros((1, 1, _PADDED_WIDTH), dtype=np.float32)
_MASK[..., _POSITIONS] = 1.0


def export_state(state_dict: dict[str, Any], model_config: dict[str, int], path: Path) -> None:
    arrays = {k: v.detach().cpu().numpy().astype(np.float32) for k, v in state_dict.items()}
    np.savez(path, __config__=np.array(json.dumps(model_config)), **arrays)


def export_checkpoint(ckpt_path: Path, path: Path) -> None:
    import torch

    ckpt = torch.load(ckpt_path, weights_only=False, map_location="cpu")
    export_state(ckpt["model"], ckpt["model_config"], path)


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def _group_norm(x: np.ndarray, weight: np.ndarray, bias: np.ndarray) -> np.ndarray:
    b, ch, w = x.shape
    g = x.reshape(b, _GROUPS, (ch // _GROUPS) * w)
    g = (g - g.mean(-1, keepdims=True)) / np.sqrt(g.var(-1, keepdims=True) + _EPS)
    return g.reshape(b, ch, w) * weight[None, :, None] + bias[None, :, None]


def _conv3(x: np.ndarray, weight: np.ndarray, bias: np.ndarray) -> np.ndarray:
    """Kernel-3, zero-padded-by-1 conv as one matmul over the three shifted copies."""
    _, ch, w = x.shape
    p = np.pad(x, ((0, 0), (0, 0), (1, 1)))
    stacked = np.concatenate([p[:, :, k : k + w] for k in range(3)], axis=1)
    flat = weight.transpose(0, 2, 1).reshape(weight.shape[0], 3 * ch)
    return flat @ stacked + bias[None, :, None]


class NumpyDangerNet:
    def __init__(self, arrays: dict[str, np.ndarray], config: dict[str, int]) -> None:
        self.w = arrays
        self.config = config

    @classmethod
    def load(cls, path: Path) -> NumpyDangerNet:
        with np.load(path, allow_pickle=False) as z:
            arrays = {k: z[k] for k in z.files if k != "__config__"}
            config = json.loads(str(z["__config__"]))
        return cls(arrays, config)

    def forward(self, tiles: np.ndarray, scalars: np.ndarray) -> dict[str, np.ndarray]:
        """Logits for `tiles (B, C, 34)` and `scalars (B, S)`: `tenpai (B,)`, `legal_wait` and
        `struct_wait` `(B, 34)`, `faan (B, 34, classes)`."""
        w = self.w
        b = tiles.shape[0]
        x = np.zeros((b, tiles.shape[1], _PADDED_WIDTH), dtype=np.float32)
        x[:, :, _POSITIONS] = tiles
        scalar_bias = scalars @ w["scalar_proj.weight"].T + w["scalar_proj.bias"]
        h = (_conv3(x, w["stem.weight"], w["stem.bias"]) + scalar_bias[:, :, None]) * _MASK

        for i in range(self.config["blocks"]):
            p = f"blocks.{i}."
            r = _conv3(
                np.maximum(_group_norm(h, w[p + "norm1.weight"], w[p + "norm1.bias"]), 0) * _MASK,
                w[p + "conv1.weight"],
                w[p + "conv1.bias"],
            )
            r = _conv3(
                np.maximum(_group_norm(r, w[p + "norm2.weight"], w[p + "norm2.bias"]), 0) * _MASK,
                w[p + "conv2.weight"],
                w[p + "conv2.bias"],
            )
            pooled = (r * _MASK).sum(-1) / _N_TILE_TYPES
            hidden = np.maximum(pooled @ w[p + "se1.weight"].T + w[p + "se1.bias"], 0)
            gate = _sigmoid(hidden @ w[p + "se2.weight"].T + w[p + "se2.bias"])
            h = (h + r * gate[:, :, None]) * _MASK

        h = np.maximum(_group_norm(h, w["final_norm.weight"], w["final_norm.bias"]), 0) * _MASK
        head = np.einsum("oc,bcw->bow", w["tile_head.weight"][:, :, 0], h)
        per_tile = (head + w["tile_head.bias"][None, :, None])[:, :, _POSITIONS]

        pooled = np.concatenate(
            [h.sum(-1) / _N_TILE_TYPES, h[:, :, _POSITIONS].max(-1), scalars], axis=1
        )
        z = np.maximum(pooled @ w["tenpai_head.0.weight"].T + w["tenpai_head.0.bias"], 0)
        tenpai = (z @ w["tenpai_head.2.weight"].T + w["tenpai_head.2.bias"])[:, 0]
        return {
            "tenpai": tenpai,
            "legal_wait": per_tile[:, 0],
            "struct_wait": per_tile[:, 1],
            "faan": per_tile[:, 2:].transpose(0, 2, 1),
        }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m ml.export", description=__doc__)
    parser.add_argument("--ckpt", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    export_checkpoint(args.ckpt, args.out)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main(sys.argv[1:])
