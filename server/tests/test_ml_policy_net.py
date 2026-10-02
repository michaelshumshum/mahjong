"""`ml/policy_net.py`: shapes, masking, and the 109-id layout against `mahjong_core.ml`."""

from __future__ import annotations

import random

import pytest

np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")

from mahjong_core.actions import (
    ClaimChow,
    ClaimKong,
    ClaimPung,
    ClaimWin,
    DeclareAddedKong,
    DeclareConcealedKong,
    DeclareWin,
    Discard,
    Pass,
)
from mahjong_core.ml import N_ACTIONS, action_id, decode_action, legal_mask
from mahjong_core.tiles import tile_id_type
from ml.danger_model import N_FAAN_CLASSES
from ml.encode_v2 import N_ORACLE_CHANNELS, N_POLICY_CHANNELS, N_POLICY_SCALARS, encode_policy
from ml.env import HandEnv
from ml.policy_net import (
    GLOBAL_ACTIONS,
    OracleCritic,
    PolicyNet,
    PolicyNetConfig,
    assemble_logits,
    logit_source,
    masked_entropy,
    masked_log_softmax,
)

_SMALL = PolicyNetConfig(channels=16, blocks=2)


def _inputs(b: int, seed: int = 0) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    g = torch.Generator().manual_seed(seed)
    tiles = (torch.rand(b, N_POLICY_CHANNELS, 34, generator=g) < 0.2).float()
    oracle = (torch.rand(b, N_ORACLE_CHANNELS, 34, generator=g) < 0.2).float()
    return tiles, oracle, torch.rand(b, N_POLICY_SCALARS, generator=g)


def test_policy_and_aux_shapes() -> None:
    torch.manual_seed(0)
    net = PolicyNet(_SMALL)
    tiles, _, scalars = _inputs(5)
    out = net(tiles, scalars)
    assert out.logits.shape == (5, N_ACTIONS)
    aux = out.aux
    assert aux is not None
    assert aux.tenpai.shape == (5, 3)
    assert aux.legal_wait.shape == aux.struct_wait.shape == (5, 3, 34)
    assert aux.faan.shape == (5, 3, 34, N_FAAN_CLASSES)
    assert aux.win.shape == aux.deal_in.shape == aux.points.shape == (5,)
    assert aux.hidden.shape == (5, 4, 34)
    assert aux.shanten.shape == aux.ukeire.shape == (5, 34)
    assert net(tiles, scalars, aux=False).aux is None
    assert torch.equal(net(tiles, scalars, aux=False).logits, out.logits)


def test_critic_reads_oracle_channels() -> None:
    torch.manual_seed(0)
    critic = OracleCritic(_SMALL)
    tiles, oracle, scalars = _inputs(4)
    v = critic(tiles, oracle, scalars)
    assert v.shape == (4,)
    assert not torch.allclose(v, critic(tiles, torch.zeros_like(oracle), scalars))


def test_masked_log_softmax_and_entropy() -> None:
    logits = torch.randn(3, N_ACTIONS, requires_grad=True)
    mask = torch.zeros(3, N_ACTIONS, dtype=torch.bool)
    mask[0, [0, 5, 102]] = True
    mask[1, 108] = True
    mask[2, :] = True
    logp = masked_log_softmax(logits, mask)
    assert torch.isinf(logp[~mask]).all() and (logp[~mask] < 0).all()
    assert torch.allclose(logp.exp().sum(-1), torch.ones(3))
    assert logp[1, 108].item() == pytest.approx(0.0, abs=1e-6)
    ent = masked_entropy(logp, mask)
    ref0 = torch.distributions.Categorical(logits=logits[0, [0, 5, 102]]).entropy()
    assert torch.allclose(ent[0], ref0)
    assert ent[1].item() == pytest.approx(0.0, abs=1e-6)
    (logp[0, 5] + ent.sum()).backward()
    assert logits.grad is not None and torch.isfinite(logits.grad).all()
    assert (logits.grad[~mask] == 0).all()


def test_assemble_logits_follows_logit_source() -> None:
    tile = torch.arange(3 * 34, dtype=torch.float32).reshape(1, 3, 34) * 10
    glob = -torch.arange(1, 8, dtype=torch.float32).reshape(1, 7)
    logits = assemble_logits(tile, glob)
    assert logits.shape == (1, N_ACTIONS)
    for aid in range(N_ACTIONS):
        where, i, t = logit_source(aid)
        expected = tile[0, i, t] if where == "tile" else glob[0, i]
        assert logits[0, aid] == expected


def _check_decoded(aid: int, action: object) -> None:
    where, i, t = logit_source(aid)
    if where == "tile":
        if i == 0:
            assert isinstance(action, Discard) and int(tile_id_type(action.tile_id)) == t
        elif i == 1:
            assert isinstance(action, DeclareConcealedKong) and int(action.meld.tile_type) == t
        else:
            assert isinstance(action, DeclareAddedKong) and int(action.meld.tile_type) == t
        return
    name = GLOBAL_ACTIONS[i]
    expected = {
        "pass": Pass,
        "chow_low": ClaimChow,
        "chow_middle": ClaimChow,
        "chow_high": ClaimChow,
        "pung": ClaimPung,
        "kong": ClaimKong,
        "win": (ClaimWin, DeclareWin),
    }[name]
    assert isinstance(action, expected), (aid, name, action)


def test_every_legal_id_decodes_to_the_head_its_logit_comes_from() -> None:
    torch.manual_seed(0)
    net = PolicyNet(_SMALL).eval()
    seen: set[str] = set()
    for seed in range(30):
        env = HandEnv(encode=False)
        rng = random.Random(seed)
        seat, _, mask = env.reset(seed)
        done = False
        while not done:
            state = env.state
            assert state is not None
            assert list(mask) == legal_mask(state, seat)
            tiles, scalars = encode_policy(state, seat)
            with torch.no_grad():
                out = net(torch.from_numpy(tiles[None]), torch.from_numpy(scalars[None]))
            logp = masked_log_softmax(out.logits, torch.from_numpy(mask[None]))
            assert torch.isfinite(logp[0, torch.from_numpy(mask)]).all()
            for aid in np.flatnonzero(mask).tolist():
                action = decode_action(aid, state, seat)
                assert action_id(action, state) == aid
                _check_decoded(aid, action)
                where, i, _ = logit_source(aid)
                seen.add(GLOBAL_ACTIONS[i] if where == "global" else f"tile{i}")
            legal = np.flatnonzero(mask).tolist()
            claims = [a for a in legal if a >= 34]
            seat, _, mask, done, _ = env.step(rng.choice(claims or legal))
    assert {"tile0", "tile1", "pass", "pung", "win"} <= seen
    assert seen & {"chow_low", "chow_middle", "chow_high"}
