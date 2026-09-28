"""Unit tests for `ml/generate_dataset.py` (docs/06-ml.md §6.2's Phase 1 dataset generation).
Needs numpy/pyarrow (`ml`-extra only, not a base dependency) -- `importorskip` keeps this file a
clean skip, not a collection failure, under `make test-server`'s no-ml-extra environment.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("numpy")
pytest.importorskip("pyarrow")
ml_generate_dataset = pytest.importorskip("ml.generate_dataset")

import pyarrow.parquet as pq

from bots.arena import BOT_REGISTRY
from bots.faanbot import FaanBot
from mahjong_core.presets import RULESET_PRESETS
from ml.encode import N_THERMOMETER


def test_make_bots_rejects_wrong_count() -> None:
    with pytest.raises(ValueError, match="exactly 4"):
        ml_generate_dataset._make_bots(["FaanBot", "FaanBot"], seed=0)


def test_make_bots_rejects_unknown_name() -> None:
    with pytest.raises(ValueError, match="unknown bot"):
        ml_generate_dataset._make_bots(["NotABot"] * 4, seed=0)


def test_play_and_label_emits_one_row_per_turn_decision_with_the_expected_shapes() -> None:
    ruleset = RULESET_PRESETS["hk_classic"]
    bots = [FaanBot() for _ in range(4)]
    rows = asyncio.run(ml_generate_dataset.play_and_label(seed=1, ruleset=ruleset, bots=bots))

    assert len(rows) > 0
    row = rows[0]
    assert set(row) == {
        "game_seed",
        "hand_no",
        "seat",
        "hand",
        "melds",
        "discards",
        "concealed_counts",
        "context",
        "wall_remaining",
        "ruleset",
        "opponent_seats",
        "opponent_is_tenpai",
        "opponent_winning_tiles",
        "opponent_expected_faan",
    }
    assert row["game_seed"] == 1
    assert row["seat"] in range(4)
    assert len(row["hand"]) == N_THERMOMETER
    assert len(row["melds"]) == 4
    assert len(row["discards"]) == 4
    assert len(row["concealed_counts"]) == 4
    assert len(row["ruleset"]) == 41
    assert row["opponent_seats"] == [
        (row["seat"] + 1) % 4,
        (row["seat"] + 2) % 4,
        (row["seat"] + 3) % 4,
    ]
    assert len(row["opponent_is_tenpai"]) == 3
    assert len(row["opponent_winning_tiles"]) == 3
    assert len(row["opponent_expected_faan"]) == 3
    assert all(len(f) == 34 for f in row["opponent_expected_faan"])


def test_main_writes_a_parquet_shard_matching_play_and_label(tmp_path) -> None:  # type: ignore[no-untyped-def]
    ruleset = RULESET_PRESETS["hk_classic"]
    bots = [FaanBot() for _ in range(4)]
    expected_rows = asyncio.run(
        ml_generate_dataset.play_and_label(seed=5, ruleset=ruleset, bots=bots)
    )

    out_dir = tmp_path / "shards"
    ml_generate_dataset.main(
        ["--games", "1", "--seed-start", "5", "--shard-games", "1", "--out", str(out_dir)]
    )

    shards = sorted(out_dir.glob("*.parquet"))
    assert len(shards) == 1
    assert shards[0].name == "shard_00000005_00000005.parquet"
    table = pq.read_table(shards[0])
    assert table.num_rows == len(expected_rows)


def test_bot_registry_names_are_valid_choices_for_the_cli() -> None:
    parser = ml_generate_dataset.build_parser()
    name = min(BOT_REGISTRY)
    args = parser.parse_args(["--bots", ",".join([name] * 4)])
    assert args.bots.split(",") == [name] * 4


def test_parallel_run_covers_every_seed_exactly_once(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """`--parallel` games complete out of seed order -- this pins that shard filenames still use
    the real min/max seed *of that shard's rows* (not an assumed-contiguous range), and that no
    seed is silently dropped or doubled across shard boundaries."""
    out_dir = tmp_path / "shards"
    ml_generate_dataset.main(
        [
            "--games",
            "6",
            "--seed-start",
            "100",
            "--shard-games",
            "3",
            "--parallel",
            "3",
            "--out",
            str(out_dir),
        ]
    )

    shards = sorted(out_dir.glob("*.parquet"))
    assert len(shards) == 2
    all_seeds: list[int] = []
    for shard in shards:
        table = pq.read_table(shard, columns=["game_seed"])
        seeds = table.column("game_seed").to_pylist()
        assert len(set(seeds)) == 3  # exactly one shard's worth of distinct games
        all_seeds.extend(seeds)
    assert sorted(set(all_seeds)) == list(range(100, 106))
