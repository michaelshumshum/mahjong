"""Unit tests for `ml/train.py` and `ml/dataset.py`, on a synthetic packed dataset (random raw
arrays in `ml.pack`'s layout) so no self-play is needed. Needs the `ml` extra."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")
pytest.importorskip("yaml")
ml_train = pytest.importorskip("ml.train")

from ml.dataset import DangerData
from ml.splits import TRAIN, VAL
from tests.ml_synthetic import TILES as _TILES
from tests.ml_synthetic import synthetic_packed


@pytest.fixture(scope="module")
def packed(tmp_path_factory):  # type: ignore[no-untyped-def]
    path = tmp_path_factory.mktemp("packed") / "d"
    synthetic_packed(path)
    return path


def _cfg(packed: Path, out: Path, **over):  # type: ignore[no-untyped-def]
    cfg = ml_train.TrainConfig(
        data=str(packed),
        out=str(out),
        threads=1,
        channels=16,
        blocks=1,
        batch_size=32,
        steps=6,
        warmup=2,
        log_every=2,
        eval_every=3,
        eval_samples=64,
        save_every=2,
    )
    for k, v in over.items():
        setattr(cfg, k, v)
    return cfg


def test_unimplemented_algorithm_still_fails_loudly() -> None:
    with pytest.raises(NotImplementedError):
        ml_train.main(["--config", "ml/configs/bc.yaml"])


def test_shipped_danger_config_loads() -> None:
    algorithm, cfg = ml_train.load_config(Path("ml/configs/danger.yaml"))
    assert algorithm == "danger" and cfg.batch_size == 512


def test_lr_warms_up_then_decays_to_the_floor() -> None:
    cfg = ml_train.TrainConfig(lr=1.0, min_lr=0.1, warmup=10, steps=110)
    assert ml_train.lr_at(0, cfg) == pytest.approx(0.1)
    assert ml_train.lr_at(9, cfg) == pytest.approx(1.0)
    assert ml_train.lr_at(60, cfg) == pytest.approx(0.55)
    assert ml_train.lr_at(110, cfg) == pytest.approx(0.1)


def test_batches_have_the_encoded_shapes_and_are_reproducible(packed) -> None:  # type: ignore[no-untyped-def]
    data = DangerData(packed)
    rows = data.rows_of(TRAIN)
    order = data.epoch_order(len(rows), seed=3, epoch=0)
    assert np.array_equal(order, data.epoch_order(len(rows), seed=3, epoch=0))
    assert not np.array_equal(order, data.epoch_order(len(rows), seed=3, epoch=1))
    tiles, scalars, targets = data.batch(rows, order[:16])
    assert tiles.shape[0] == scalars.shape[0] == 16
    assert targets["legal"].shape == (16, _TILES)
    assert len(data.rows_of(VAL)) > 0


def test_train_writes_checkpoints_and_metrics(packed, tmp_path) -> None:  # type: ignore[no-untyped-def]
    out = ml_train.train(_cfg(packed, tmp_path / "run"))
    assert (out / "ckpt_last.pt").exists() and (out / "ckpt_best.pt").exists()
    lines = [json.loads(x) for x in (out / "metrics.jsonl").read_text().splitlines()]
    assert lines[-1]["step"] == 6
    assert "val_total" in lines[-1] and "train_total" in lines[0]
    assert torch.load(out / "ckpt_last.pt", weights_only=False)["step"] == 6


def test_resume_matches_an_uninterrupted_run(packed, tmp_path) -> None:  # type: ignore[no-untyped-def]
    straight = ml_train.train(_cfg(packed, tmp_path / "a"))
    ml_train.train(_cfg(packed, tmp_path / "b"), max_steps=3)
    resumed = ml_train.train(_cfg(packed, tmp_path / "b"), resume=True)

    a = torch.load(straight / "ckpt_last.pt", weights_only=False)["model"]
    b = torch.load(resumed / "ckpt_last.pt", weights_only=False)["model"]
    assert a.keys() == b.keys()
    for k in a:
        assert torch.allclose(a[k], b[k], atol=1e-6), k


def test_evaluate_reports_metrics_with_intervals_at_candidate_tiles(packed, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from ml.danger_model import DangerNet, DangerNetConfig
    from ml.evaluate import evaluate_model, load_model

    out = ml_train.train(_cfg(packed, tmp_path / "run"))
    model = load_model(out / "ckpt_last.pt")
    assert isinstance(model, DangerNet) and model.config == DangerNetConfig(channels=16, blocks=1)

    data = DangerData(packed)
    result = evaluate_model(model, data, data.rows_of(VAL), n_boot=20)
    assert result["n_samples"] == len(data.rows_of(VAL)) * 3
    for name in ("legal_wait", "struct_wait", "legal_wait_all_tiles", "tenpai"):
        point, lo, hi = result[name]["auc"]
        assert lo <= point <= hi
        assert result[name]["logloss"][0] > 0
    assert 0 < result["base_rate"] < 0.2
    assert sum(n for _, _, n in result["reliability"]) > 0
