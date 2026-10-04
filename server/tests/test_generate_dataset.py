"""Unit tests for `ml/generate_dataset.py` (docs/ml.md §5).
Needs pyarrow (`ml`-extra only, not a base dependency) -- `importorskip` keeps this file a clean
skip, not a collection failure, under `make test-server`'s no-ml-extra environment. Unlike the
encoder, this module doesn't need numpy itself (see its own module docstring).
"""

from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("pyarrow")
ml_generate_dataset = pytest.importorskip("ml.generate_dataset")

import pyarrow.parquet as pq

from bots.arena import BOT_REGISTRY
from bots.faanbot import FaanBot
from mahjong_core.presets import RULESET_PRESETS


def test_make_bots_rejects_wrong_count() -> None:
    with pytest.raises(ValueError, match="exactly 4"):
        ml_generate_dataset._make_bots(["FaanBot", "FaanBot"], seed=0)


def test_make_bots_rejects_unknown_name() -> None:
    with pytest.raises(ValueError, match="unknown bot"):
        ml_generate_dataset._make_bots(["NotABot"] * 4, seed=0)


def test_make_bots_refuses_an_omniscient_bot() -> None:
    with pytest.raises(ValueError, match="omniscient"):
        ml_generate_dataset._make_bots(["ORACLE", "FaanBot", "FaanBot", "FaanBot"], seed=0)


def test_shuffled_roster_is_deterministic_per_seed_and_actually_varies() -> None:
    roster = ["FaanBot", "FaanBotAggressive", "FaanBotDefensive", "FaanBotFlushChasing"]
    assert ml_generate_dataset._shuffled_roster(
        roster, seed=7
    ) == ml_generate_dataset._shuffled_roster(roster, seed=7)
    # every entry from the original roster is present, just reordered
    assert sorted(ml_generate_dataset._shuffled_roster(roster, seed=7)) == sorted(roster)

    orderings = {tuple(ml_generate_dataset._shuffled_roster(roster, seed=s)) for s in range(20)}
    assert len(orderings) > 1, "20 seeds produced only one seat->personality ordering"


def test_play_and_label_emits_one_row_per_turn_decision_with_the_expected_shapes() -> None:
    ruleset = RULESET_PRESETS["hk_classic"]
    roster = ["FaanBot", "FaanBotAggressive", "FaanBotDefensive", "FaanBotFlushChasing"]
    bots = [FaanBot() for _ in range(4)]
    rows = asyncio.run(
        ml_generate_dataset.play_and_label(
            seed=1, ruleset=ruleset, bots=bots, seat_personalities=roster
        )
    )

    assert len(rows) > 0
    row = rows[0]
    assert set(row) == {
        "game_seed",
        "hand_no",
        "seat",
        "seat_personalities",
        "hand_counts",
        "meld_counts",
        "discard_counts",
        "discard_seq",
        "concealed_counts",
        "concealed_kongs",
        "flowers",
        "dealer_idx",
        "prevailing_wind",
        "seat_wind",
        "wall_remaining",
        "opponent_seats",
        "opponent_is_tenpai",
        "opponent_winning_tiles_multihot",
        "opponent_expected_faan",
    }
    assert row["game_seed"] == 1
    assert row["seat"] in range(4)
    assert row["seat_personalities"] == roster
    assert len(row["hand_counts"]) == 34
    assert sum(row["hand_counts"]) == 14  # post-draw, pre-discard -- see docs/bots.md §10
    assert len(row["meld_counts"]) == 4
    assert all(len(m) == 34 for m in row["meld_counts"])
    assert len(row["discard_counts"]) == 4
    assert all(len(d) == 34 for d in row["discard_counts"])
    assert len(row["concealed_counts"]) == 4
    assert len(row["discard_seq"]) == 4
    assert all(len(seq) == sum(d) for seq, d in zip(row["discard_seq"], row["discard_counts"]))
    assert len(row["concealed_kongs"]) == 4
    assert len(row["flowers"]) == 4
    assert row["dealer_idx"] in range(4)
    assert row["prevailing_wind"] in range(4)
    assert row["seat_wind"] in range(4)
    assert row["opponent_seats"] == [
        (row["seat"] + 1) % 4,
        (row["seat"] + 2) % 4,
        (row["seat"] + 3) % 4,
    ]
    assert len(row["opponent_is_tenpai"]) == 3
    assert len(row["opponent_winning_tiles_multihot"]) == 3
    assert all(len(w) == 34 and set(w) <= {0, 1} for w in row["opponent_winning_tiles_multihot"])
    assert len(row["opponent_expected_faan"]) == 3
    assert all(len(f) == 34 for f in row["opponent_expected_faan"])


def test_main_writes_a_parquet_shard_and_manifest(tmp_path) -> None:  # type: ignore[no-untyped-def]
    out_dir = tmp_path / "shards"
    ml_generate_dataset.main(
        [
            "--games",
            "1",
            "--seed-start",
            "5",
            "--shard-games",
            "1",
            "--out",
            str(out_dir),
            "--bots",
            "FaanBot,FaanBot,FaanBot,FaanBot",
        ]
    )

    shards = sorted(out_dir.glob("*.parquet"))
    assert len(shards) == 1
    assert shards[0].name == "shard_00000005_00000005.parquet"

    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["ruleset_preset"] == "hk_classic"
    assert manifest["bot_roster"] == ["FaanBot", "FaanBot", "FaanBot", "FaanBot"]
    assert manifest["n_tile_types"] == 34
    assert manifest["schema_version"] == 3

    table = pq.read_table(shards[0])
    assert table.num_rows > 0
    assert table.column("game_seed").to_pylist() == [5] * table.num_rows


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
