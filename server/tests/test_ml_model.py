"""Unit tests for `ml/danger_model.py` and `ml/losses.py`. Needs torch (`ml` extra)."""

from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")
ml_model = pytest.importorskip("ml.danger_model")
ml_losses = pytest.importorskip("ml.losses")

from ml.encode import N_SCALARS, N_TILE_CHANNELS


def _inputs(b: int = 4) -> tuple[torch.Tensor, torch.Tensor]:
    g = torch.Generator().manual_seed(0)
    return torch.rand(b, N_TILE_CHANNELS, 34, generator=g), torch.rand(b, N_SCALARS, generator=g)


def _small() -> ml_model.DangerNet:
    torch.manual_seed(0)
    return ml_model.DangerNet(ml_model.DangerNetConfig(channels=16, blocks=2))


def test_output_shapes() -> None:
    tiles, scalars = _inputs()
    out = _small()(tiles, scalars)
    assert out.tenpai.shape == (4,)
    assert out.legal_wait.shape == out.struct_wait.shape == (4, 34)
    assert out.faan.shape == (4, 34, ml_model.N_FAAN_CLASSES)


def test_default_size_is_about_four_hundred_thousand_parameters() -> None:
    n = ml_model.n_parameters(ml_model.DangerNet())
    assert 300_000 < n < 600_000


def test_samples_are_independent_of_batch_mates() -> None:
    model = _small().eval()
    tiles, scalars = _inputs()
    full = model(tiles, scalars)
    alone = model(tiles[1:2], scalars[1:2])
    assert torch.allclose(full.legal_wait[1], alone.legal_wait[0], atol=1e-5)
    assert torch.allclose(full.tenpai[1], alone.tenpai[0], atol=1e-5)


def test_suit_boundaries_do_not_leak_across_pad_columns() -> None:
    # stem alone (norm removed: GroupNorm statistics are global by design) has receptive field 3
    model = ml_model.DangerNet(ml_model.DangerNetConfig(channels=16, blocks=0)).eval()
    model.final_norm = torch.nn.Identity()
    tiles = torch.zeros(1, N_TILE_CHANNELS, 34)
    scalars = torch.zeros(1, N_SCALARS)
    base = model(tiles, scalars).legal_wait
    tiles[0, 0, 8] = 1.0  # 9m
    moved = model(tiles, scalars).legal_wait
    diff = (moved - base).abs()[0]
    assert diff[8] > 0 and diff[7] > 0
    assert diff[9] == 0  # 1p: separated by the zero column


def test_a_few_gradient_steps_reduce_the_loss_on_a_fixed_batch() -> None:
    model = _small()
    tiles, scalars = _inputs(16)
    g = torch.Generator().manual_seed(1)
    struct = (torch.rand(16, 34, generator=g) < 0.1).float()
    faan = struct.long() * 4
    targets = {
        "tenpai": struct.amax(1),
        "struct": struct,
        "legal": struct,
        "faan": faan,
    }
    opt = torch.optim.Adam(model.parameters(), lr=1e-2)
    first = None
    for _ in range(30):
        loss = ml_losses.danger_loss(model(tiles, scalars), targets)["total"]
        first = first if first is not None else loss.item()
        opt.zero_grad()
        loss.backward()
        opt.step()
    assert loss.item() < first * 0.7


def test_faan_loss_ignores_tiles_without_a_legal_win() -> None:
    out = ml_model.DangerOutput(
        tenpai=torch.zeros(1),
        legal_wait=torch.zeros(1, 34),
        struct_wait=torch.zeros(1, 34),
        faan=torch.zeros(1, 34, ml_model.N_FAAN_CLASSES),
    )
    targets = {
        "tenpai": torch.zeros(1),
        "struct": torch.zeros(1, 34),
        "legal": torch.zeros(1, 34),
        "faan": torch.zeros(1, 34, dtype=torch.long),
    }
    losses = ml_losses.danger_loss(out, targets)
    assert losses["faan"].item() == 0.0

    targets["legal"][0, 5] = 1.0
    targets["faan"][0, 5] = 3
    losses = ml_losses.danger_loss(out, targets)
    assert losses["faan"].item() == pytest.approx(np.log(ml_model.N_FAAN_CLASSES), rel=1e-5)


def test_total_is_the_weighted_sum() -> None:
    tiles, scalars = _inputs(2)
    targets = {
        "tenpai": torch.tensor([1.0, 0.0]),
        "struct": torch.zeros(2, 34),
        "legal": torch.zeros(2, 34),
        "faan": torch.zeros(2, 34, dtype=torch.long),
    }
    w = ml_losses.LossWeights(tenpai=2.0, legal=3.0, struct=5.0, faan=7.0)
    parts = ml_losses.danger_loss(_small()(tiles, scalars), targets, w)
    expect = 2 * parts["tenpai"] + 3 * parts["legal"] + 5 * parts["struct"] + 7 * parts["faan"]
    assert torch.allclose(parts["total"], expect)


def test_targets_from_raw_maps_faan_to_legal_and_clips_classes() -> None:
    faan = np.zeros((2, 3, 34), dtype=np.uint8)
    faan[1, 2, 7] = 13
    faan[0, 0, 3] = 4
    multihot = np.zeros((2, 3, 34), dtype=np.uint8)
    multihot[1, 2, 7] = multihot[1, 2, 8] = 1
    raw = {
        "opponent_expected_faan": faan,
        "opponent_winning_tiles_multihot": multihot,
        "opponent_is_tenpai": np.array([[0, 0, 0], [0, 0, 1]], dtype=np.uint8),
    }
    t = ml_losses.targets_from_raw(raw, np.array([1]), np.array([2]))
    assert t["tenpai"][0] == 1.0
    assert t["legal"][0, 7] == 1.0 and t["legal"][0, 8] == 0.0  # struct-only wait is not legal
    assert t["struct"][0, 8] == 1.0
    assert t["faan"][0, 7] == ml_model.N_FAAN_CLASSES
