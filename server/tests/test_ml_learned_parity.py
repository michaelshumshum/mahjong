"""The shipped `bots/weights/learned.npz` loaded into torch `PolicyNet` gives the same logits and
the same greedy actions as `LearnedBot`'s numpy path (docs/ml.md §14 R4). `ml` extra only; the
source checkpoint is gitignored, so torch gets the weights from the `.npz` itself."""

from __future__ import annotations

import asyncio

import pytest

np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")

from app.views import seat_view
from bots.learned import DEFAULT_WEIGHTS, LearnedBot
from ml.encode_v2 import encode_policy_batch, policy_raw_from_view, ruleset_features
from ml.env import HandEnv
from ml.eval_policy import PolicyBot
from ml.export import _load_npz
from ml.policy_net import PolicyNet, PolicyNetConfig


def _torch_model() -> PolicyNet:
    arrays, config = _load_npz(DEFAULT_WEIGHTS)
    model = PolicyNet(PolicyNetConfig(**config))
    missing, unexpected = model.load_state_dict(
        {k: torch.from_numpy(v) for k, v in arrays.items()}, strict=False
    )
    assert not unexpected
    assert all(k.startswith("aux") for k in missing), missing
    return model.eval()


def test_shipped_weights_match_torch() -> None:
    torch.set_num_threads(1)
    model = _torch_model()
    learned = LearnedBot()
    reference = PolicyBot(model)
    n = 0
    for seed in range(6):
        env = HandEnv(encode=False)
        seat, _, mask = env.reset(seed)
        while not env.done:
            assert env.state is not None
            view = seat_view(env.state, seat)
            row = policy_raw_from_view(view)
            tiles, scalars = encode_policy_batch(
                {k: v[None] for k, v in row.items()}, ruleset_features(view.ruleset)
            )
            with torch.no_grad():
                ref = model(torch.from_numpy(tiles), torch.from_numpy(scalars), aux=False).logits
            assert np.allclose(learned.logits(view), ref[0].numpy(), atol=2e-4)
            m = mask.tolist()
            aid = asyncio.run(learned.act(view, m, 0.0))
            assert aid == asyncio.run(reference.act(view, m, 0.0))
            seat, _, mask, _, _ = env.step(aid)
            n += 1
    assert n > 300
