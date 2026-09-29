"""Unit tests for `ml/export.py`: the numpy forward pass must match the torch model. Needs the
`ml` extra."""

from __future__ import annotations

import time

import pytest

np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")
export = pytest.importorskip("ml.export")

from ml.danger_model import DangerNet, DangerNetConfig
from ml.encode import N_SCALARS, N_TILE_CHANNELS


def _random_model(config: DangerNetConfig) -> DangerNet:
    torch.manual_seed(0)
    model = DangerNet(config)
    with torch.no_grad():
        for p in model.parameters():
            p.add_(torch.randn_like(p) * 0.1)
    return model.eval()


def _inputs(b: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(1)
    tiles = (rng.random((b, N_TILE_CHANNELS, 34)) < 0.2).astype(np.float32)
    return tiles, rng.random((b, N_SCALARS)).astype(np.float32)


def test_numpy_forward_matches_torch_after_a_round_trip_through_npz(tmp_path) -> None:  # type: ignore[no-untyped-def]
    config = DangerNetConfig(channels=16, blocks=2)
    model = _random_model(config)
    export.export_state(model.state_dict(), config.to_dict(), tmp_path / "m.npz")
    net = export.NumpyDangerNet.load(tmp_path / "m.npz")

    tiles, scalars = _inputs(5)
    with torch.no_grad():
        ref = model(torch.from_numpy(tiles), torch.from_numpy(scalars))
    out = net.forward(tiles, scalars)

    assert np.allclose(out["tenpai"], ref.tenpai.numpy(), atol=1e-4)
    assert np.allclose(out["legal_wait"], ref.legal_wait.numpy(), atol=1e-4)
    assert np.allclose(out["struct_wait"], ref.struct_wait.numpy(), atol=1e-4)
    assert out["faan"].shape == tuple(ref.faan.shape)
    assert np.allclose(out["faan"], ref.faan.numpy(), atol=1e-4)


def test_export_checkpoint_reads_a_training_checkpoint(tmp_path) -> None:  # type: ignore[no-untyped-def]
    config = DangerNetConfig(channels=16, blocks=1)
    model = _random_model(config)
    torch.save({"model": model.state_dict(), "model_config": config.to_dict()}, tmp_path / "c.pt")
    export.export_checkpoint(tmp_path / "c.pt", tmp_path / "m.npz")
    assert export.NumpyDangerNet.load(tmp_path / "m.npz").config == config.to_dict()


@pytest.mark.slow
def test_three_opponents_score_in_under_five_milliseconds(tmp_path) -> None:  # type: ignore[no-untyped-def]
    config = DangerNetConfig()
    model = _random_model(config)
    export.export_state(model.state_dict(), config.to_dict(), tmp_path / "m.npz")
    net = export.NumpyDangerNet.load(tmp_path / "m.npz")
    tiles, scalars = _inputs(3)
    net.forward(tiles, scalars)

    runs = []
    for _ in range(30):
        start = time.perf_counter()
        net.forward(tiles, scalars)
        runs.append(time.perf_counter() - start)
    assert sorted(runs)[len(runs) // 2] < 0.005
