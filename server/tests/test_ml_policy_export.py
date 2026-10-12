"""`ml/export.py`'s `NumpyPolicyNet`: numpy logits match torch `PolicyNet` on real encoded states,
and single-sample serving (encode + forward) fits docs/ml.md §6's p99 ≤ 5 ms."""

from __future__ import annotations

import random
import time
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")
export = pytest.importorskip("ml.export")

from mahjong_core.state import GameState
from ml.encode_v2 import POLICY_CHANNELS, encode_policy
from ml.env import HandEnv
from ml.policy_net import PolicyNet, PolicyNetConfig, masked_log_softmax
from tests.latency import check_latency


def _random_model(config: PolicyNetConfig) -> PolicyNet:
    torch.manual_seed(0)
    model = PolicyNet(config)
    with torch.no_grad():
        for p in model.parameters():
            p.add_(torch.randn_like(p) * 0.1)
    return model.eval()


def _states(n_hands: int) -> list[tuple[GameState, int, np.ndarray]]:
    out = []
    for seed in range(n_hands):
        env = HandEnv(encode=False)
        rng = random.Random(seed)
        seat, _, mask = env.reset(seed)
        done = False
        while not done:
            assert env.state is not None
            out.append((env.state, seat, mask))
            legal = np.flatnonzero(mask).tolist()
            claims = [a for a in legal if a >= 102]
            seat, _, mask, done, _ = env.step(rng.choice(claims or legal))
    return out


def test_numpy_policy_matches_torch(tmp_path: Path) -> None:
    config = PolicyNetConfig(channels=16, blocks=2)
    model = _random_model(config)
    export.export_policy_state(model.state_dict(), config.to_dict(), tmp_path / "p.npz")
    with np.load(tmp_path / "p.npz") as z:
        assert not any(k.startswith("aux_") for k in z.files)
    net = export.NumpyPolicyNet.load(tmp_path / "p.npz")

    states = _states(3)
    tiles, scalars = map(np.stack, zip(*(encode_policy(s, seat) for s, seat, _ in states)))
    assert tiles[:, POLICY_CHANNELS["claimable"]].sum() > 0
    with torch.no_grad():
        ref = model(torch.from_numpy(tiles), torch.from_numpy(scalars), aux=False).logits
    out = net.forward(tiles, scalars)
    assert out.shape == tuple(ref.shape)
    assert np.allclose(out, ref.numpy(), atol=1e-4)

    state, seat, _ = states[5]
    assert np.allclose(net.state_logits(state, seat), out[5], atol=1e-5)
    masks = np.stack([m for _, _, m in states])
    ref_logp = masked_log_softmax(ref, torch.from_numpy(masks)).numpy()
    np_logp = export.masked_log_softmax(out, masks)
    assert np.array_equal(np.isinf(np_logp), ~masks)
    assert np.allclose(np_logp[masks], ref_logp[masks], atol=1e-4)


def test_export_checkpoint_strips_aux_heads(tmp_path: Path) -> None:
    config = PolicyNetConfig(channels=16, blocks=1)
    model = _random_model(config)
    ckpt = {"model": model.state_dict(), "model_config": config.to_dict(), "algorithm": "rl_aux"}
    torch.save(ckpt, tmp_path / "c.pt")
    export.export_checkpoint(tmp_path / "c.pt", tmp_path / "p.npz")
    net = export.NumpyPolicyNet.load(tmp_path / "p.npz")
    assert net.config == config.to_dict()
    assert all(k.startswith(("trunk.", "policy_")) for k in net.w)


def test_sigmoid_does_not_overflow() -> None:
    """the SE gate saw logits far below -88, where float32 exp(-x) overflows and warns."""
    with np.errstate(over="raise"):
        out = export._sigmoid(np.array([-1000.0, 0.0, 1000.0], dtype=np.float32))
    assert np.allclose(out, [0.0, 0.5, 1.0])


def test_export_ppo_checkpoint_records_provenance(tmp_path: Path) -> None:
    """`ml.ppo` / league checkpoints keep the policy under `learner.policy`."""
    config = PolicyNetConfig(channels=16, blocks=1)
    model = _random_model(config)
    ckpt = {
        "learner": {"policy": model.state_dict(), "critic": {}},
        "model_config": config.to_dict(),
        "algorithm": "ppo",
        "decisions": 1234,
        "updates": 5,
        "engine_version": "1.3.0",
    }
    torch.save(ckpt, tmp_path / "ckpt_L1.2K.pt")
    export.export_checkpoint(tmp_path / "ckpt_L1.2K.pt", tmp_path / "p.npz")
    net = export.NumpyPolicyNet.load(tmp_path / "p.npz")
    assert all(k.startswith(("trunk.", "policy_")) for k in net.w)
    meta = export.load_meta(tmp_path / "p.npz")
    assert meta is not None
    assert meta["source"] == "ckpt_L1.2K.pt"
    assert meta["decisions"] == 1234
    assert meta["export_version"] == export.EXPORT_VERSION
    assert len(meta["source_sha256"]) == 64
    export.export_policy_state(model.state_dict(), config.to_dict(), tmp_path / "bare.npz")
    assert export.load_meta(tmp_path / "bare.npz") is None


@pytest.mark.slow
@pytest.mark.latency
def test_single_sample_latency_with_encoding(tmp_path: Path) -> None:
    """Full-size serving (encode + forward) costs less than a `FaanBot` decision at p99 on the
    same states. The absolute 5 ms is `make bench-latency` (`tests/latency.py`)."""
    import asyncio

    from app.views import seat_view
    from bots.faanbot import FaanBot

    config = PolicyNetConfig()
    export.export_policy_state(
        _random_model(config).state_dict(), config.to_dict(), tmp_path / "p.npz"
    )
    net = export.NumpyPolicyNet.load(tmp_path / "p.npz")
    states = _states(4)[:300]
    bot = FaanBot()
    for state, seat, mask in states[:20]:
        net.state_logits(state, seat)
        asyncio.run(bot.act(seat_view(state, seat), mask.tolist(), 0.0))
    serve, faan = [], []
    for state, seat, mask in states:
        view, m = seat_view(state, seat), mask.tolist()
        start = time.perf_counter()
        export.masked_log_softmax(net.state_logits(state, seat), mask)
        mid = time.perf_counter()
        asyncio.run(bot.act(view, m, 0.0))
        serve.append(mid - start)
        faan.append(time.perf_counter() - mid)
    check_latency("policy serve", serve, "FaanBot", faan)
