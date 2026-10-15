"""Packs `ml.generate_dataset` parquet shards into memory-mappable uint8 `.npy` arrays, one file
per field, so training reads slices instead of decoding parquet lists (docs/ml.md §5).

    python -m ml.pack --src data/danger_v3 --out data/danger_v3_packed

Every field is `(N, ...)`; `split` is the game-level assignment from `ml.splits`. Per-opponent
axes are in relative-seat order, opponents 0..2 = next, across, previous.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from mahjong_core.tiles import N_TILE_TYPES
from ml.encode import MAX_DISCARDS, PAD
from ml.generate_dataset import SCHEMA_VERSION
from ml.splits import DEFAULT_SALT, split_ids

__all__ = ["load_packed", "main", "pack_dataset"]


_FIELDS: dict[str, tuple[int, ...]] = {
    "hand_counts": (N_TILE_TYPES,),
    "meld_counts": (4, N_TILE_TYPES),
    "discard_counts": (4, N_TILE_TYPES),
    "concealed_counts": (4,),
    "concealed_kongs": (4,),
    "flowers": (4,),
    "opponent_is_tenpai": (3,),
    "opponent_winning_tiles_multihot": (3, N_TILE_TYPES),
    "opponent_expected_faan": (3, N_TILE_TYPES),
}
_SCALARS = ("hand_no", "dealer_idx", "prevailing_wind", "seat_wind", "wall_remaining", "seat")


def _fixed(col: pa.ChunkedArray, shape: tuple[int, ...], n: int) -> np.ndarray:
    arr = col.combine_chunks()
    for _ in shape:
        arr = arr.flatten()
    values = arr.to_numpy(zero_copy_only=False)
    if not np.array_equal(values, values.astype(np.uint8)):
        raise ValueError("non-integer or out-of-range value in a uint8 field")
    return values.astype(np.uint8).reshape((n, *shape))


def _padded_seq(col: pa.ChunkedArray, n: int, max_len: int) -> np.ndarray:
    inner = col.combine_chunks().flatten()  # 4n lists
    lengths = pc.list_value_length(inner).to_numpy()
    if lengths.max(initial=0) > max_len:
        raise ValueError(f"discard pool of {lengths.max()} exceeds max_discards={max_len}")
    values = inner.flatten().to_numpy(zero_copy_only=False)
    out = np.full((n * 4, max_len), PAD, dtype=np.uint8)
    starts = np.cumsum(lengths) - lengths
    rows = np.repeat(np.arange(len(lengths)), lengths)
    cols = np.arange(len(values)) - np.repeat(starts, lengths)
    out[rows, cols] = values
    return out.reshape(n, 4, max_len)


def pack_dataset(
    src: Path, dst: Path, *, salt: str = DEFAULT_SALT, max_discards: int = MAX_DISCARDS
) -> dict[str, object]:
    shards = sorted(src.glob("*.parquet"))
    if not shards:
        raise FileNotFoundError(f"no parquet shards under {src}")
    manifest = json.loads((src / "manifest.json").read_text())
    if manifest["schema_version"] != SCHEMA_VERSION:
        raise ValueError(
            f"{src} is schema v{manifest['schema_version']}, expected v{SCHEMA_VERSION}"
        )

    counts = [pq.ParquetFile(s).metadata.num_rows for s in shards]
    total = sum(counts)
    dst.mkdir(parents=True, exist_ok=True)

    shapes: dict[str, tuple[int, ...]] = {
        **{k: (total, *v) for k, v in _FIELDS.items()},
        **{k: (total,) for k in _SCALARS},
        "discard_seq": (total, 4, max_discards),
        "game_seed": (total,),
        "split": (total,),
    }
    out = {
        name: np.lib.format.open_memmap(
            dst / f"{name}.npy",
            mode="w+",
            dtype=np.int64 if name == "game_seed" else np.uint8,
            shape=shape,
        )
        for name, shape in shapes.items()
    }

    at = 0
    for shard, n in zip(shards, counts, strict=True):
        table = pq.read_table(shard)
        sl = slice(at, at + n)
        for name, shape in _FIELDS.items():
            out[name][sl] = _fixed(table.column(name), shape, n)
        for name in _SCALARS:
            out[name][sl] = _fixed(table.column(name), (), n)
        out["discard_seq"][sl] = _padded_seq(table.column("discard_seq"), n, max_discards)
        seeds = table.column("game_seed").to_numpy()
        out["game_seed"][sl] = seeds
        out["split"][sl] = split_ids(seeds, salt)
        at += n

    for arr in out.values():
        arr.flush()
    meta = {
        "rows": total,
        "games": len(np.unique(out["game_seed"])),
        "schema_version": SCHEMA_VERSION,
        "salt": salt,
        "max_discards": max_discards,
        "pad": PAD,
        "fields": {k: list(v) for k, v in shapes.items()},
        "manifest": manifest,
    }
    (dst / "meta.json").write_text(json.dumps(meta, indent=2))
    return meta


def load_packed(dst: Path) -> dict[str, np.ndarray]:
    meta = json.loads((dst / "meta.json").read_text())
    return {name: np.load(dst / f"{name}.npy", mmap_mode="r") for name in meta["fields"]}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m ml.pack", description=__doc__)
    parser.add_argument("--src", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--salt", default=DEFAULT_SALT)
    args = parser.parse_args(argv)
    meta = pack_dataset(args.src, args.out, salt=args.salt)
    print(f"packed {meta['rows']} rows from {meta['games']} games into {args.out}")


if __name__ == "__main__":
    main(sys.argv[1:])
