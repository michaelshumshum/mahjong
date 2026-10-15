"""Synthetic packed dataset (random raw arrays in `ml.pack`'s layout) for ml tests that need
data but not self-play. Import only after `pytest.importorskip("numpy")`."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from mahjong_core.presets import RULESET_PRESETS
from mahjong_core.tiles import N_TILE_TYPES
from ml.splits import split_ids

TILES = N_TILE_TYPES


def synthetic_packed(path: Path, n_games: int = 60, rows_per_game: int = 20) -> None:
    rng = np.random.default_rng(0)
    n = n_games * rows_per_game
    seeds = np.repeat(np.arange(n_games, dtype=np.int64), rows_per_game)
    tenpai = rng.random((n, 3)) < 0.2
    multihot = (rng.random((n, 3, TILES)) < 0.05).astype(np.uint8) * tenpai[:, :, None]
    faan = multihot * rng.integers(3, 11, size=(n, 3, TILES)).astype(np.uint8)
    fields = {
        "hand_counts": rng.integers(0, 3, size=(n, TILES)),
        "meld_counts": rng.integers(0, 2, size=(n, 4, TILES)),
        "discard_counts": rng.integers(0, 3, size=(n, 4, TILES)),
        "discard_seq": np.full((n, 4, 32), 255),
        "concealed_counts": rng.integers(1, 14, size=(n, 4)),
        "concealed_kongs": np.zeros((n, 4)),
        "flowers": rng.integers(0, 3, size=(n, 4)),
        "dealer_idx": rng.integers(0, 4, size=n),
        "prevailing_wind": np.zeros(n),
        "seat_wind": rng.integers(0, 4, size=n),
        "wall_remaining": rng.integers(0, 90, size=n),
        "opponent_is_tenpai": tenpai,
        "opponent_winning_tiles_multihot": multihot,
        "opponent_expected_faan": faan,
    }
    path.mkdir(parents=True)
    shapes = {}
    for name, arr in fields.items():
        arr = arr.astype(np.uint8)
        np.save(path / f"{name}.npy", arr)
        shapes[name] = list(arr.shape)
    np.save(path / "game_seed.npy", seeds)
    np.save(path / "split.npy", split_ids(seeds))
    shapes["game_seed"] = [n]
    shapes["split"] = [n]
    manifest = {"ruleset": RULESET_PRESETS["hk_classic"].to_dict()}
    (path / "meta.json").write_text(json.dumps({"fields": shapes, "manifest": manifest}))
