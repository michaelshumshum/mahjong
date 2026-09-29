"""Unit tests for `ml/gbdt_baseline.py`. Needs the `ml` extra (numpy, torch, lightgbm)."""

from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")
pytest.importorskip("lightgbm")
gb = pytest.importorskip("ml.gbdt_baseline")

from ml.danger_model import DangerNet, DangerNetConfig
from ml.dataset import DangerData
from tests.ml_synthetic import synthetic_packed

F = {name: i for i, name in enumerate(gb.FEATURE_NAMES)}


def _raw(n: int = 1) -> dict[str, np.ndarray]:
    return {
        "hand_counts": np.zeros((n, 34), dtype=np.uint8),
        "meld_counts": np.zeros((n, 4, 34), dtype=np.uint8),
        "discard_counts": np.zeros((n, 4, 34), dtype=np.uint8),
        "discard_seq": np.full((n, 4, 32), 255, dtype=np.uint8),
        "concealed_counts": np.full((n, 4), 13, dtype=np.uint8),
        "concealed_kongs": np.zeros((n, 4), dtype=np.uint8),
        "flowers": np.zeros((n, 4), dtype=np.uint8),
        "dealer_idx": np.zeros(n, dtype=np.uint8),
        "prevailing_wind": np.zeros(n, dtype=np.uint8),
        "seat_wind": np.zeros(n, dtype=np.uint8),
        "wall_remaining": np.full(n, 70, dtype=np.uint8),
    }


def test_signals_follow_the_target_opponent_not_the_observer() -> None:
    raw = _raw()
    raw["hand_counts"][0, 4] = 1
    raw["discard_counts"][0, 2, 4] = 2
    raw["discard_seq"][0, 2, :2] = 4
    raw["discard_counts"][0, 1, 5] = 1
    raw["discard_counts"][0, 2, 1] = 1
    feats = gb.candidate_features(raw, np.array([1]))[0]

    assert feats[4, F["own_count"]] == 1
    assert feats[4, F["genbutsu"]] == 1 and feats[4, F["opp_discards_of_tile"]] == 2
    assert feats[4, F["live"]] == 1
    assert feats[4, F["suji"]] == 0  # a middle tile needs both neighbours discarded
    assert feats[1, F["suji"]] == 1
    assert feats[1, F["genbutsu"]] == 1
    assert feats[5, F["genbutsu"]] == 0
    assert feats[7, F["suji"]] == 1
    assert feats[4, F["opp_discard_count"]] == 2
    assert feats[4, F["discard_age"]] == 0
    assert feats[9, F["discard_age"]] == -1
    assert feats[4, F["others_discards_of_tile"]] == 0
    assert feats[5, F["others_discards_of_tile"]] == 1


def test_meld_reads_and_wall_are_reported_for_the_target() -> None:
    raw = _raw()
    raw["meld_counts"][0, 3, [31, 31, 31]] = 3
    raw["meld_counts"][0, 3, 10:13] = 1
    raw["wall_remaining"][0] = 20
    feats = gb.candidate_features(raw, np.array([2]))[0]
    assert feats[0, F["opp_dragon_meld"]] == 1
    assert feats[0, F["opp_meld_count"]] == 2
    assert feats[10, F["opp_suit_melds"]] == 1
    assert feats[0, F["wall_remaining"]] == 20


def test_compare_trains_and_scores_both_models_on_the_same_candidates(tmp_path) -> None:  # type: ignore[no-untyped-def]
    synthetic_packed(tmp_path / "d", n_games=120, rows_per_game=20)
    model = DangerNet(DangerNetConfig(channels=16, blocks=1)).eval()
    result = gb.compare(
        DangerData(tmp_path / "d"),
        model,
        train_samples=3000,
        test_samples=600,
        n_boot=10,
        num_boost_round=5,
    )
    assert result["n_test_candidates"] > 0
    for name in ("gbdt", "model"):
        assert set(result[name]) == {"auc", "logloss", "brier"}
    assert set(result["importance"]) == set(gb.FEATURE_NAMES)
    assert result["model_minus_gbdt"]["logloss"][0] == pytest.approx(
        result["model"]["logloss"][0] - result["gbdt"]["logloss"][0]
    )
