"""Unit tests for `ml/heuristic_baseline.py`: replaying real self-play games to score the shipped
deal-in heuristic. Needs the `ml` extra."""

from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("pyarrow")
torch = pytest.importorskip("torch")
hb = pytest.importorskip("ml.heuristic_baseline")

from ml.danger_model import DangerNet, DangerNetConfig
from ml.dataset import DangerData
from ml.generate_dataset import main as generate
from ml.pack import pack_dataset
from ml.splits import TEST, VAL, split_of

pytestmark = pytest.mark.slow

_SEEDS = {2: VAL, 6: TEST}


@pytest.fixture(scope="module")
def data(tmp_path_factory):  # type: ignore[no-untyped-def]
    assert {s: split_of(s) for s in _SEEDS} == _SEEDS
    root = tmp_path_factory.mktemp("hb")
    generate(["--games", "5", "--seed-start", "2", "--out", str(root / "shards")])
    pack_dataset(root / "shards", root / "packed")
    return DangerData(root / "packed")


def test_replay_reproduces_the_packed_rows_and_scores_every_tile(data) -> None:  # type: ignore[no-untyped-def]
    scores = hb.score_games(data, [2], workers=1)[2]
    rows = hb.game_rows(data, [2])[2]
    assert scores.shape == (len(rows), 3, 34)
    assert 0.0 <= scores.min() and scores.max() <= 1.0
    assert scores.max() > 0.0


def test_a_mismatched_replay_is_rejected(data, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    real = hb.replay_scores

    def drifted(seed, ruleset, roster):  # type: ignore[no-untyped-def]
        scores, hands, faan = real(seed, ruleset, roster)
        hands[0, 0] ^= 1
        return scores, hands, faan

    monkeypatch.setattr(hb, "replay_scores", drifted)
    with pytest.raises(ValueError, match="does not match"):
        hb.score_games(data, [2], workers=1)


def test_compare_reports_all_three_scorers_with_paired_differences(data) -> None:  # type: ignore[no-untyped-def]
    model = DangerNet(DangerNetConfig(channels=16, blocks=1)).eval()
    result = hb.compare(data, model, calib_games=1, test_games=1, workers=1, n_boot=10)
    assert result["n_val_games"] == result["n_test_games"] == 1
    for name in ("heuristic_raw", "heuristic_platt", "model"):
        assert set(result[name]) == {"auc", "logloss", "brier"}
    diff = result["model_minus_heuristic_platt"]["logloss"]
    assert diff[0] == pytest.approx(
        result["model"]["logloss"][0] - result["heuristic_platt"]["logloss"][0]
    )
