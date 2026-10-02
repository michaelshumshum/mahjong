"""Torch-free export of a trained danger model (docs/06-ml.md §5) or `PolicyNet` (§8):

    python -m ml.export --ckpt runs/danger/ckpt_best.pt --out runs/danger/danger.npz
    python -m ml.export --ckpt runs/rl_aux/ckpt_best.pt --out runs/rl_aux/policy.npz

The checkpoint's weights go to a plain `.npz` and `NumpyDangerNet` / `NumpyPolicyNet` re-implement
the forward pass in numpy, so serving needs numpy only, not torch or an ONNX runtime. Parity tests
pin both to torch. Loading needs numpy alone; exporting needs the checkpoint's torch.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from mahjong_core.state import GameState

__all__ = [
    "NumpyDangerNet",
    "NumpyPolicyNet",
    "export_checkpoint",
    "export_policy_state",
    "export_state",
    "main",
    "masked_log_softmax",
    "numpy_trunk",
]

_PADDED_WIDTH = 37
_N_TILE_TYPES = 34
_GROUPS = 8
_EPS = 1e-5
_POSITIONS = np.array([*range(9), *range(10, 19), *range(20, 29), *range(30, 37)])
_MASK = np.zeros((1, 1, _PADDED_WIDTH), dtype=np.float32)
_MASK[..., _POSITIONS] = 1.0
_POLICY_PREFIXES = ("trunk.", "policy_tile.", "policy_global.")


def export_state(state_dict: dict[str, Any], model_config: dict[str, int], path: Path) -> None:
    arrays = {k: v.detach().cpu().numpy().astype(np.float32) for k, v in state_dict.items()}
    np.savez(path, __config__=np.array(json.dumps(model_config)), **arrays)


def export_policy_state(
    state_dict: dict[str, Any], model_config: dict[str, int], path: Path
) -> None:
    """`PolicyNet`'s served path only: trunk + policy head, no auxiliary heads."""
    served = {k: v for k, v in state_dict.items() if k.startswith(_POLICY_PREFIXES)}
    export_state(served, model_config, path)


def export_checkpoint(ckpt_path: Path, path: Path) -> None:
    """A `DangerNet` checkpoint, or a `PolicyNet` one (`algorithm: rl_aux`) via
    `export_policy_state`."""
    import torch

    ckpt = torch.load(ckpt_path, weights_only=False, map_location="cpu")
    if ckpt.get("algorithm") == "rl_aux":
        export_policy_state(ckpt["model"], ckpt["model_config"], path)
    else:
        export_state(ckpt["model"], ckpt["model_config"], path)


def _load_npz(path: Path) -> tuple[dict[str, np.ndarray], dict[str, int]]:
    with np.load(path, allow_pickle=False) as z:
        arrays = {k: z[k] for k in z.files if k != "__config__"}
        config = json.loads(str(z["__config__"]))
    return arrays, config


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


def numpy_trunk(
    w: dict[str, np.ndarray], prefix: str, tiles: np.ndarray, scalars: np.ndarray, blocks: int
) -> np.ndarray:
    """`DangerNet`'s trunk (weights under `prefix`) on `tiles (B, C, 34)`: the final-norm,
    ReLU'd features `(B, channels, 37)`, pad columns zero."""
    b = tiles.shape[0]
    x = np.zeros((b, tiles.shape[1], _PADDED_WIDTH), dtype=np.float32)
    x[:, :, _POSITIONS] = tiles
    scalar_bias = scalars @ w[prefix + "scalar_proj.weight"].T + w[prefix + "scalar_proj.bias"]
    h = _conv3(x, w[prefix + "stem.weight"], w[prefix + "stem.bias"])
    h = (h + scalar_bias[:, :, None]) * _MASK

    for i in range(blocks):
        p = f"{prefix}blocks.{i}."
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

    norm = _group_norm(h, w[prefix + "final_norm.weight"], w[prefix + "final_norm.bias"])
    return np.maximum(norm, 0) * _MASK


class NumpyDangerNet:
    def __init__(self, arrays: dict[str, np.ndarray], config: dict[str, int]) -> None:
        self.w = arrays
        self.config = config

    @classmethod
    def load(cls, path: Path) -> NumpyDangerNet:
        return cls(*_load_npz(path))

    def forward(self, tiles: np.ndarray, scalars: np.ndarray) -> dict[str, np.ndarray]:
        """Logits for `tiles (B, C, 34)` and `scalars (B, S)`: `tenpai (B,)`, `legal_wait` and
        `struct_wait` `(B, 34)`, `faan (B, 34, classes)`."""
        w = self.w
        h = numpy_trunk(w, "", tiles, scalars, self.config["blocks"])
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


class NumpyPolicyNet:
    """`PolicyNet`'s served forward pass: trunk + tile-equivariant policy head -> 109 logits."""

    def __init__(self, arrays: dict[str, np.ndarray], config: dict[str, int]) -> None:
        self.w = arrays
        self.config = config
        self.tile_w = arrays["policy_tile.weight"][:, :, 0]
        self.tile_b = arrays["policy_tile.bias"]
        from ml.encode_v2 import POLICY_CHANNELS

        self.claim_channel = POLICY_CHANNELS["claimable"].start

    @classmethod
    def load(cls, path: Path) -> NumpyPolicyNet:
        return cls(*_load_npz(path))

    def forward(self, tiles: np.ndarray, scalars: np.ndarray) -> np.ndarray:
        """Unmasked logits `(B, 109)` in `mahjong_core.ml` id order, for encoder v2's
        `tiles (B, C, 34)` and `scalars (B, S)`."""
        w = self.w
        h = numpy_trunk(w, "trunk.", tiles, scalars, self.config["blocks"])
        h_tiles = h[:, :, _POSITIONS]
        tile_logits = np.einsum("oc,bct->bot", self.tile_w, h_tiles) + self.tile_b[None, :, None]
        claim = np.einsum("bct,bt->bc", h_tiles, tiles[:, self.claim_channel])
        pooled = np.concatenate(
            [h.sum(-1) / _N_TILE_TYPES, h_tiles.max(-1), scalars, claim], axis=1
        )
        z = np.maximum(pooled @ w["policy_global.0.weight"].T + w["policy_global.0.bias"], 0)
        global_logits = z @ w["policy_global.2.weight"].T + w["policy_global.2.bias"]
        return np.concatenate([tile_logits.reshape(len(h), -1), global_logits], axis=1)

    def state_logits(self, state: GameState, seat: int) -> np.ndarray:
        """`(109,)` logits for `seat` straight from `GameState`, encoding included."""
        from ml.encode_v2 import encode_policy

        tiles, scalars = encode_policy(state, seat)
        return self.forward(tiles[None], scalars[None])[0]


def masked_log_softmax(logits: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Numpy twin of `ml.policy_net.masked_log_softmax`: illegal ids are `-inf`."""
    z = np.where(mask, logits, -np.inf)
    z = z - z.max(-1, keepdims=True)
    return z - np.log(np.exp(z).sum(-1, keepdims=True))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m ml.export", description=__doc__)
    parser.add_argument("--ckpt", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    export_checkpoint(args.ckpt, args.out)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main(sys.argv[1:])
