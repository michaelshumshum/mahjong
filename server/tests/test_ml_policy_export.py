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


@pytest.mark.slow
def test_single_sample_latency_with_encoding(tmp_path: Path) -> None:
    """Flaky under parallel CPU load (`-n`); run alone. p99 over 300 decisions."""
    config = PolicyNetConfig()
    export.export_policy_state(
        _random_model(config).state_dict(), config.to_dict(), tmp_path / "p.npz"
    )
    net = export.NumpyPolicyNet.load(tmp_path / "p.npz")
    states = _states(4)[:300]
    for state, seat, _ in states[:20]:
        net.state_logits(state, seat)
    runs = []
    for state, seat, mask in states:
        start = time.perf_counter()
        export.masked_log_softmax(net.state_logits(state, seat), mask)
        runs.append(time.perf_counter() - start)
    p50, p99 = np.percentile(runs, [50, 99])
    print(f"policy serve: p50 {p50 * 1e3:.2f} ms, p99 {p99 * 1e3:.2f} ms over {len(runs)}")
    assert p99 < 0.005
