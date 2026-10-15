"""Offline evaluation of a danger checkpoint (docs/ml.md §5):

    python -m ml.evaluate --ckpt runs/danger/ckpt_best.pt --data data/danger_v3_packed --split test
    python -m ml.evaluate --ckpt ... --data data/danger_v3_heldout_eff --split all

Wait metrics are computed at candidate-discard positions -- tiles the observer holds -- since
those are the only tiles `tile_risk` ever prices. Intervals resample games, not samples.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import torch

from ml.danger_model import DangerNet, DangerNetConfig
from ml.dataset import DangerData
from ml.encode import N_OPPONENTS
from ml.metrics import (
    add_stats,
    game_bootstrap,
    game_stats,
    metric_fns,
    reliability_sums,
    reliability_table,
)
from ml.splits import SPLITS

__all__ = ["evaluate_model", "legal_wait_probs", "load_model", "main"]


def load_model(ckpt_path: Path) -> DangerNet:
    ckpt = torch.load(ckpt_path, weights_only=False, map_location="cpu")
    model = DangerNet(DangerNetConfig(**ckpt["model_config"]))
    model.load_state_dict(ckpt["model"])
    return model.eval()


def _sigmoid(x: torch.Tensor) -> np.ndarray:
    return torch.sigmoid(x).numpy().astype(np.float64)


def legal_wait_probs(
    model: DangerNet, data: DangerData, rows: np.ndarray, chunk: int = 2048
) -> np.ndarray:
    """`(len(rows), 3, 34)` legal-wait probabilities for every (row, opponent, tile)."""
    n = len(rows) * N_OPPONENTS
    out = np.empty((n, 34), dtype=np.float32)
    with torch.no_grad():
        for i in range(0, n, chunk):
            idx = np.arange(i, min(i + chunk, n))
            tiles, scalars, _ = data.batch(rows, idx)
            out[idx] = torch.sigmoid(model(tiles, scalars).legal_wait).numpy()
    return out.reshape(len(rows), N_OPPONENTS, 34)


def evaluate_model(
    model: DangerNet,
    data: DangerData,
    rows: np.ndarray,
    *,
    max_samples: int | None = None,
    chunk: int = 2048,
    n_boot: int = 500,
    seed: int = 0,
) -> dict[str, Any]:
    """Metrics of `model` over `rows`' (row, opponent) samples. Keys: `legal_wait` and
    `struct_wait` at candidate-discard tiles, `legal_wait_all_tiles`, `tenpai`; each maps metric
    name to `(point, lo, hi)`. `base_rate` and `reliability` describe the legal-wait candidates."""
    n_samples = len(rows) * N_OPPONENTS
    samples = np.arange(n_samples)
    if max_samples is not None and max_samples < n_samples:
        samples = np.sort(np.random.default_rng(seed).choice(n_samples, max_samples, replace=False))

    seeds = np.asarray(data.raw["game_seed"])[rows]
    games, game_of_row = np.unique(seeds, return_inverse=True)
    n_games = len(games)

    acc: dict[str, Any] = {}
    rel = np.zeros((10, 3))
    with torch.no_grad():
        for i in range(0, len(samples), chunk):
            idx = samples[i : i + chunk]
            tiles, scalars, targets = data.batch(rows, idx)
            out = model(tiles, scalars)
            row_idx = rows[idx // N_OPPONENTS]
            cand = np.asarray(data.raw["hand_counts"][row_idx]) > 0
            g = game_of_row[idx // N_OPPONENTS]
            g_tiles = np.broadcast_to(g[:, None], cand.shape)

            legal_p, legal_y = _sigmoid(out.legal_wait), targets["legal"].numpy()
            struct_p, struct_y = _sigmoid(out.struct_wait), targets["struct"].numpy()
            parts = {
                "legal_wait": (legal_p[cand], legal_y[cand], g_tiles[cand]),
                "struct_wait": (struct_p[cand], struct_y[cand], g_tiles[cand]),
                "legal_wait_all_tiles": (legal_p.ravel(), legal_y.ravel(), g_tiles.ravel()),
                "tenpai": (_sigmoid(out.tenpai), targets["tenpai"].numpy(), g),
            }
            for name, (p, y, gi) in parts.items():
                stats = game_stats(p, y, gi, n_games)
                acc[name] = stats if name not in acc else add_stats(acc[name], stats)
            rel += reliability_sums(*parts["legal_wait"][:2])

    result: dict[str, Any] = {"n_samples": len(samples), "n_games": n_games}
    for name, stats in acc.items():
        result[name] = {
            m: game_bootstrap({"m": stats}, lambda s, fn=fn: fn(s["m"]), n_boot, seed)
            for m, fn in metric_fns.items()
        }
    result["base_rate"] = float(rel[:, 1].sum() / rel[:, 2].sum())
    result["reliability"] = reliability_table(rel)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m ml.evaluate", description=__doc__)
    parser.add_argument("--ckpt", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--split", choices=[*SPLITS, "all"], default="test")
    parser.add_argument("--max-samples", type=int)
    parser.add_argument("--n-boot", type=int, default=500)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--out", type=Path, help="also write the result as JSON")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    torch.set_num_threads(args.threads)
    data = DangerData(args.data)
    if args.split == "all":
        rows = np.arange(data.meta["rows"])
    else:
        rows = data.rows_of(SPLITS[args.split])
    result = evaluate_model(
        load_model(args.ckpt), data, rows, max_samples=args.max_samples, n_boot=args.n_boot
    )
    text = json.dumps(result, indent=2)
    if args.out:
        args.out.write_text(text)
    print(text)


if __name__ == "__main__":
    main(sys.argv[1:])
