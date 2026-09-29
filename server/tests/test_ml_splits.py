"""Unit tests for `ml/splits.py` -- the game-level train/val/test assignment."""

from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")
ml_splits = pytest.importorskip("ml.splits")


def test_split_is_deterministic_and_salt_dependent() -> None:
    assert ml_splits.split_of(123) == ml_splits.split_of(123)
    a = [ml_splits.split_of(s, "a") for s in range(200)]
    b = [ml_splits.split_of(s, "b") for s in range(200)]
    assert a != b


def test_split_proportions_are_roughly_ten_five_eighty_five_percent() -> None:
    ids = [ml_splits.split_of(s) for s in range(20000)]
    frac = {k: ids.count(k) / len(ids) for k in (ml_splits.TRAIN, ml_splits.VAL, ml_splits.TEST)}
    assert frac[ml_splits.TEST] == pytest.approx(0.10, abs=0.015)
    assert frac[ml_splits.VAL] == pytest.approx(0.05, abs=0.01)
    assert frac[ml_splits.TRAIN] == pytest.approx(0.85, abs=0.02)


def test_split_ids_matches_split_of_row_by_row_and_keeps_a_game_together() -> None:
    seeds = np.array([5, 9, 5, 5, 9, 12], dtype=np.int64)
    got = ml_splits.split_ids(seeds)
    assert list(got) == [ml_splits.split_of(int(s)) for s in seeds]
    assert got[0] == got[2] == got[3]
