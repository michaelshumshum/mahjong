"""Packed auxiliary-head dataset (docs/ml.md §8): `ml.generate_aux` shards -> one memory-mapped
`.npy` per field, plus the game-level split (`ml.splits`).

    python -m ml.aux_data --src data/rl_aux --out data/rl_aux_packed

`AuxData.batch` encodes rows with encoder v2 and builds every auxiliary target. `danger_raw`
re-expresses rows in the v3 layout `ml.encode.encode_batch` reads, so `DangerNet` can be scored on
the same states.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from mahjong_core.config import RuleSet
from ml.encode import encode_ruleset
from ml.encode_v2 import (
    ORACLE_FIELDS,
    PAD,
    POLICY_FIELDS,
    encode_oracle_batch,
    encode_policy_batch,
    ruleset_features,
)
from ml.generate_aux import SCHEMA_VERSION
from ml.splits import DEFAULT_SALT, split_ids

__all__ = ["AuxData", "aux_targets", "danger_raw", "hidden_counts", "main", "pack_aux"]

_TILES = 34


def pack_aux(src: Path, dst: Path, *, salt: str = DEFAULT_SALT) -> dict[str, object]:
    shards = sorted(src.glob("*.npz"))
    if not shards:
        raise FileNotFoundError(f"no .npz shards under {src}")
    manifest = json.loads((src / "manifest.json").read_text())
    if manifest["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"{src} is schema v{manifest['schema_version']}, not v{SCHEMA_VERSION}")
    with np.load(shards[0]) as z:
        specs = {k: (z[k].shape[1:], z[k].dtype) for k in z.files}
    sizes = []
    for s in shards:
        with np.load(s) as z:
            sizes.append(len(z["seat"]))
    total = sum(sizes)
    dst.mkdir(parents=True, exist_ok=True)
    out = {
        k: np.lib.format.open_memmap(dst / f"{k}.npy", mode="w+", dtype=dt, shape=(total, *sh))
        for k, (sh, dt) in specs.items()
    }
    out["split"] = np.lib.format.open_memmap(
        dst / "split.npy", mode="w+", dtype=np.uint8, shape=(total,)
    )
    at = 0
    for s, n in zip(shards, sizes, strict=True):
        with np.load(s) as z:
            for k in specs:
                out[k][at : at + n] = z[k]
            out["split"][at : at + n] = split_ids(z["game_seed"], salt)
        at += n
    for arr in out.values():
        arr.flush()
    meta = {
        "rows": total,
        "games": len(np.unique(out["game_seed"])),
        "schema_version": SCHEMA_VERSION,
        "salt": salt,
        "fields": sorted(out),
        "manifest": manifest,
    }
    (dst / "meta.json").write_text(json.dumps(meta, indent=2))
    return meta


def hidden_counts(raw: dict[str, np.ndarray]) -> np.ndarray:
    """`(B, 4, 34)` true location of every unseen copy: next/across/previous opponent's
    concealed tiles, live wall. Concealed kongs are public, so not unseen."""
    opp = raw["opp_concealed"].astype(np.int64)
    return np.concatenate([opp, raw["wall_counts"].astype(np.int64)[:, None]], axis=1)


def hidden_slots(raw: dict[str, np.ndarray], total_hidden: np.ndarray) -> np.ndarray:
    """`(B, 4)` hidden non-flower tile slots per location, from public counts only: each
    opponent's concealed tiles, the rest in the wall."""
    opp = raw["concealed_counts"][:, 1:].astype(np.int64)
    wall = total_hidden - opp.sum(axis=1)
    return np.concatenate([opp, wall[:, None]], axis=1)


def aux_targets(raw: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    faan = raw["opp_faan"].astype(np.int64)
    sh = raw["shanten"]
    hidden = hidden_counts(raw)
    return {
        "tenpai": raw["opp_tenpai"].astype(np.float32),
        "legal": (faan > 0).astype(np.float32),
        "struct": raw["opp_wait"].astype(np.float32),
        "faan": faan,
        "win": raw["win"].astype(np.float32),
        "deal_in": raw["deal_in"].astype(np.float32),
        "points": raw["payment"].astype(np.float32) / 32.0,
        "hidden": hidden.astype(np.float32),
        "slots": hidden_slots(raw, hidden.sum(axis=(1, 2))).astype(np.float32),
        "shanten_mask": (sh != PAD).astype(np.float32),
        "shanten": np.where(sh != PAD, sh, 0).astype(np.float32),
        "ukeire": raw["ukeire"].astype(np.float32) / 10.0,
    }


def danger_raw(raw: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Rows in the v3 `ml.pack` layout that `ml.encode.encode_batch` reads."""
    seq = raw["discard_seq"]
    disc = np.eye(_TILES + 1, dtype=np.uint8)[np.minimum(seq, _TILES)].sum(axis=2, dtype=np.uint8)
    return {
        "hand_counts": raw["concealed"] + raw["melds"][:, 0],
        "meld_counts": raw["melds"],
        "discard_counts": disc[..., :_TILES],
        "discard_seq": seq,
        "concealed_counts": raw["concealed_counts"],
        "concealed_kongs": raw["concealed_kongs"],
        "flowers": raw["flowers"],
        "dealer_idx": raw["dealer"],
        "prevailing_wind": raw["prevailing"],
        "seat_wind": raw["seat_wind"],
        "wall_remaining": raw["wall_remaining"],
    }


class AuxData:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.meta = json.loads((path / "meta.json").read_text())
        self.raw = {k: np.load(path / f"{k}.npy", mmap_mode="r") for k in self.meta["fields"]}
        self.ruleset = RuleSet.from_dict(self.meta["manifest"]["ruleset"])
        self.ruleset_vec = ruleset_features(self.ruleset).copy()
        self.danger_ruleset_vec = encode_ruleset(self.ruleset)

    def rows_of(self, split: int) -> np.ndarray:
        return np.flatnonzero(np.asarray(self.raw["split"]) == split)

    def take(self, rows: np.ndarray) -> dict[str, np.ndarray]:
        idx = np.sort(rows)
        order = np.argsort(np.argsort(rows))
        return {k: np.asarray(v[idx])[order] for k, v in self.raw.items()}

    def arrays(
        self, rows: np.ndarray, *, oracle: bool = False
    ) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray], dict[str, np.ndarray]]:
        """Encoded inputs (`tiles`, `scalars`, optionally `oracle`), targets, and the raw rows."""
        raw = self.take(rows)
        tiles, scalars = encode_policy_batch({k: raw[k] for k in POLICY_FIELDS}, self.ruleset_vec)
        inputs = {"tiles": tiles, "scalars": scalars}
        if oracle:
            inputs["oracle"] = encode_oracle_batch({k: raw[k] for k in ORACLE_FIELDS})
        return inputs, aux_targets(raw), raw


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m ml.aux_data", description=__doc__)
    parser.add_argument("--src", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--salt", default=DEFAULT_SALT)
    args = parser.parse_args(argv)
    meta = pack_aux(args.src, args.out, salt=args.salt)
    print(f"packed {meta['rows']} rows from {meta['games']} games into {args.out}")


if __name__ == "__main__":
    main(sys.argv[1:])
