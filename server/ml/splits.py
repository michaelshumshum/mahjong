"""Game-level train/val/test assignment. Rows within a game are correlated (same hands, same
opponents), so a row-level split would leak; the split is a pure function of the game seed."""

from __future__ import annotations

import hashlib

import numpy as np

__all__ = ["DEFAULT_SALT", "SPLITS", "TEST", "TRAIN", "VAL", "split_ids", "split_of"]

TRAIN, VAL, TEST = 0, 1, 2
SPLITS = {"train": TRAIN, "val": VAL, "test": TEST}
DEFAULT_SALT = "danger-v1"
_BUCKETS = 20  # 2/20 test, 1/20 val, rest train


def split_of(game_seed: int, salt: str = DEFAULT_SALT) -> int:
    digest = hashlib.blake2b(f"{salt}:{game_seed}".encode(), digest_size=8).digest()
    bucket = int.from_bytes(digest, "big") % _BUCKETS
    if bucket < 2:
        return TEST
    if bucket == 2:
        return VAL
    return TRAIN


def split_ids(game_seeds: np.ndarray, salt: str = DEFAULT_SALT) -> np.ndarray:
    """`split_of` per row, hashing each distinct seed once."""
    seeds, inverse = np.unique(game_seeds, return_inverse=True)
    per_seed = np.fromiter(
        (split_of(int(s), salt) for s in seeds), dtype=np.uint8, count=len(seeds)
    )
    return per_seed[inverse]
