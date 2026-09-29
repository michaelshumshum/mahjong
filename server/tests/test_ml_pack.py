"""Unit tests for `ml/pack.py` -- parquet shards to memory-mapped uint8 arrays. Needs the `ml`
extra (numpy + pyarrow); skips cleanly without it."""

from __future__ import annotations

import json

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("pyarrow")
ml_pack = pytest.importorskip("ml.pack")
ml_generate_dataset = pytest.importorskip("ml.generate_dataset")

import pyarrow.parquet as pq

from ml.splits import split_of


@pytest.fixture(scope="module")
def shard_dir(tmp_path_factory):  # type: ignore[no-untyped-def]
    out = tmp_path_factory.mktemp("shards")
    ml_generate_dataset.main(
        ["--games", "3", "--seed-start", "40", "--shard-games", "2", "--out", str(out)]
    )
    return out


def test_pack_matches_the_parquet_rows_field_by_field(shard_dir, tmp_path) -> None:  # type: ignore[no-untyped-def]
    meta = ml_pack.pack_dataset(shard_dir, tmp_path / "packed")
    packed = ml_pack.load_packed(tmp_path / "packed")

    tables = [pq.read_table(s).to_pylist() for s in sorted(shard_dir.glob("*.parquet"))]
    rows = [r for t in tables for r in t]
    assert meta["rows"] == len(rows) == len(packed["hand_counts"])
    assert meta["games"] == 3

    for i in (0, len(rows) // 2, len(rows) - 1):
        r = rows[i]
        assert list(packed["hand_counts"][i]) == r["hand_counts"]
        assert np.array_equal(packed["meld_counts"][i], np.array(r["meld_counts"]))
        assert np.array_equal(
            packed["opponent_expected_faan"][i], np.array(r["opponent_expected_faan"])
        )
        assert list(packed["opponent_is_tenpai"][i]) == [int(x) for x in r["opponent_is_tenpai"]]
        assert packed["wall_remaining"][i] == r["wall_remaining"]
        assert packed["game_seed"][i] == r["game_seed"]
        assert packed["split"][i] == split_of(r["game_seed"])
        for slot, seq in enumerate(r["discard_seq"]):
            got = packed["discard_seq"][i, slot]
            assert list(got[: len(seq)]) == seq
            assert (got[len(seq) :] == ml_pack.PAD).all()


def test_pack_rejects_a_discard_pool_longer_than_the_pad(shard_dir, tmp_path) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError, match="max_discards"):
        ml_pack.pack_dataset(shard_dir, tmp_path / "packed", max_discards=2)


def test_pack_rejects_other_schema_versions(shard_dir, tmp_path) -> None:  # type: ignore[no-untyped-def]
    old = tmp_path / "old"
    old.mkdir()
    for shard in shard_dir.glob("*.parquet"):
        (old / shard.name).write_bytes(shard.read_bytes())
    manifest = json.loads((shard_dir / "manifest.json").read_text())
    manifest["schema_version"] = 2
    (old / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="schema v2"):
        ml_pack.pack_dataset(old, tmp_path / "packed")
