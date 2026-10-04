"""`ml/ppo.py` device handling (docs/ml.md §13): `device` resolution, CPU-saved checkpoints
that load on either device, and old checkpoint formats. `cuda`-marked tests need a GPU and are
skipped without one."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")

from ml.eval_policy import load_candidate
from ml.policy_net import PolicyNet, PolicyNetConfig
from ml.ppo import Learner, PPOConfig, device_info, load_ppo_config, resolve_device, train_ppo

_TINY = {"channels": 8, "blocks": 1}
_HAS_CUDA = torch.cuda.is_available()
needs_cuda = pytest.mark.skipif(not _HAS_CUDA, reason="needs a CUDA GPU")


def _cfg(tmp_path: Path, name: str = "run", **kw) -> PPOConfig:
    base = {
        "out": str(tmp_path / name),
        "envs": 4,
        "workers": 0,
        "batch_size": 96,
        "minibatch": 48,
        "aux_rate": 0.5,
        "save_every": 1,
        "device": "cpu",
        "stage": {"min_faan": 0, "learners": 1, "keep_prob": 0.5, "oracle_k": 5, "beta": 1.0},
        **_TINY,
    }
    return PPOConfig(**{**base, **kw})


def _no_cuda(monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)


def test_device_defaults_to_auto_and_the_c0_config_parses():
    assert PPOConfig().device == "auto" and PPOConfig().amp is False
    import yaml

    raw = yaml.safe_load(Path("ml/configs/rl_ppo_c0.yaml").read_text())
    raw.pop("algorithm")
    assert load_ppo_config(raw).device == "auto"


def test_auto_resolves_to_cpu_without_cuda(monkeypatch):
    _no_cuda(monkeypatch)
    assert resolve_device("auto") == torch.device("cpu")
    assert resolve_device("cpu") == torch.device("cpu")
    assert device_info(torch.device("cpu"))["device"] == "cpu"


@pytest.mark.parametrize("name", ["cuda", "cuda:0"])
def test_explicit_cuda_without_a_gpu_fails_loudly(monkeypatch, name):
    _no_cuda(monkeypatch)
    with pytest.raises(RuntimeError, match=r"torch.cuda.is_available\(\) is False"):
        resolve_device(name)


def test_train_ppo_refuses_cuda_without_a_gpu_before_writing_anything(monkeypatch, tmp_path):
    _no_cuda(monkeypatch)
    with pytest.raises(RuntimeError, match="requested"):
        train_ppo(_cfg(tmp_path, device="cuda"), max_updates=1)
    assert not (tmp_path / "run").exists()


def test_unknown_device_and_cpu_amp_are_rejected():
    with pytest.raises(ValueError, match="device must be"):
        resolve_device("mps")
    with pytest.raises(ValueError, match="amp needs device: cuda"):
        Learner(PPOConfig(amp=True, **_TINY), PolicyNet(PolicyNetConfig(**_TINY)), "cpu")


def test_resolved_device_is_logged_to_meta_and_metrics(tmp_path, capsys):
    out = train_ppo(_cfg(tmp_path), max_updates=1)
    assert json.loads((out / "meta.json").read_text())["device"]["device"] == "cpu"
    rec = json.loads((out / "metrics.jsonl").read_text().splitlines()[0])
    assert rec["device"] == "cpu" and rec["torch"] == torch.__version__
    assert 'device: {"device": "cpu"' in capsys.readouterr().out


def _assert_same_tree(a, b):
    if isinstance(a, torch.Tensor):
        assert isinstance(b, torch.Tensor)
        torch.testing.assert_close(a.cpu(), b.cpu(), rtol=0, atol=0)
    elif isinstance(a, dict):
        assert a.keys() == b.keys()
        for k in a:
            _assert_same_tree(a[k], b[k])
    elif isinstance(a, list | tuple):
        assert len(a) == len(b)
        for x, y in zip(a, b, strict=True):
            _assert_same_tree(x, y)
    else:
        assert a == b


def _tensors(tree):
    if isinstance(tree, torch.Tensor):
        yield tree
    elif isinstance(tree, dict):
        for v in tree.values():
            yield from _tensors(v)
    elif isinstance(tree, list | tuple):
        for v in tree:
            yield from _tensors(v)


def test_checkpoint_is_saved_on_cpu_and_round_trips_with_map_location(tmp_path):
    out = train_ppo(_cfg(tmp_path), max_updates=1)
    ckpt = torch.load(out / "ckpt_last.pt", weights_only=False, map_location="cpu")
    assert all(t.device.type == "cpu" for t in _tensors(ckpt["learner"]))
    assert ckpt["learner"]["opt"]["state"], "optimizer moments are saved"

    cfg = _cfg(tmp_path)
    learner = Learner(cfg, PolicyNet(PolicyNetConfig(**_TINY)), "cpu")
    learner.load_state_dict(ckpt["learner"])
    _assert_same_tree(learner.state_dict(), ckpt["learner"])
    assert load_candidate(str(out / "ckpt_last.pt")).config.channels == 8


def test_init_from_an_r1_rl_aux_checkpoint(tmp_path):
    torch.manual_seed(0)
    r1 = PolicyNet(PolicyNetConfig(**_TINY))
    path = tmp_path / "ckpt_best.pt"
    torch.save({"model": r1.state_dict(), "model_config": r1.config.to_dict(), "step": 1}, path)
    out = train_ppo(_cfg(tmp_path, init_ckpt=str(path), lr=0.0), max_updates=1)
    ckpt = torch.load(out / "ckpt_last.pt", weights_only=False, map_location="cpu")
    for k, v in r1.state_dict().items():
        torch.testing.assert_close(ckpt["learner"]["policy"][k], v, rtol=0, atol=0)


@pytest.mark.cuda
@needs_cuda
@pytest.mark.parametrize("first,second", [("cuda", "cpu"), ("cpu", "cuda")])
def test_checkpoint_resumes_across_devices(tmp_path, first, second):
    out = train_ppo(_cfg(tmp_path, device=first), max_updates=1)
    before = torch.load(out / "ckpt_last.pt", weights_only=False, map_location="cpu")
    assert all(t.device.type == "cpu" for t in _tensors(before["learner"]))
    train_ppo(_cfg(tmp_path, device=second), resume=True, max_updates=1)
    lines = [json.loads(x) for x in (out / "metrics.jsonl").read_text().splitlines()]
    assert [r["device"].split(":")[0] for r in lines] == [first, second]
    assert np.isfinite(lines[-1]["pg"])
    after = torch.load(out / "ckpt_last.pt", weights_only=False, map_location="cpu")
    steps = 2 * len(range(0, lines[-1]["samples"], 48))
    step = lambda c: float(c["learner"]["opt"]["state"][0]["step"])
    assert step(after) == step(before) + steps


def _rows():
    from ml.train_env import EnvConfig, VecTrainEnv, with_min_faan

    venv = VecTrainEnv(8, 0, with_min_faan(EnvConfig(learners=4), 0))
    buf = venv.reset()
    rng = np.random.default_rng(0)
    rows, masks = [], []
    for _ in range(30):
        rows.append(buf.rows.copy())
        masks.append(buf.mask.copy())
        acts = [rng.choice(np.flatnonzero(m)) for m in buf.mask]
        buf = venv.step(np.asarray(acts, dtype=np.int32))
    return np.concatenate(rows), np.concatenate(masks)


@pytest.mark.cuda
@needs_cuda
def test_cuda_learner_matches_cpu_and_keeps_everything_on_the_gpu():
    rows, masks = _rows()
    n = len(rows)
    keep, k = np.full(n, 0.5, dtype=np.float32), np.full(n, 13)
    torch.manual_seed(0)
    policy = PolicyNet(PolicyNetConfig(**_TINY))
    cpu = Learner(PPOConfig(**_TINY), policy, "cpu")
    torch.nn.init.normal_(cpu.adapter.conv.weight, std=0.5)
    gpu = Learner(PPOConfig(**_TINY), PolicyNet(PolicyNetConfig(**_TINY)), "cuda")
    gpu.load_state_dict(cpu.state_dict())
    for module in (gpu.policy, gpu.adapter, gpu.critic, gpu.popart):
        assert all(t.is_cuda for t in [*module.parameters(), *module.buffers()])
    a0, lp0, kb0 = cpu.act(rows, masks, keep, k, np.random.default_rng(1))
    a1, lp1, kb1 = gpu.act(rows, masks, keep, k, np.random.default_rng(1))
    assert isinstance(lp1, np.ndarray)
    np.testing.assert_array_equal(kb0, kb1)
    same = a0 == a1
    assert same.mean() > 0.99
    np.testing.assert_allclose(lp0[same], lp1[same], atol=1e-4)


@pytest.mark.cuda
@needs_cuda
def test_amp_run_is_finite_and_saves_the_grad_scaler(tmp_path):
    cfg = _cfg(tmp_path, device="cuda", amp=True)
    out = train_ppo(cfg, max_updates=2)
    lines = [json.loads(x) for x in (out / "metrics.jsonl").read_text().splitlines()]
    assert all(np.isfinite(r["pg"]) and np.isfinite(r["value"]) for r in lines)
    ckpt = torch.load(out / "ckpt_last.pt", weights_only=False, map_location="cpu")
    assert "scaler" in ckpt["learner"]
    train_ppo(cfg, resume=True, max_updates=1)


@pytest.mark.cuda
@needs_cuda
def test_auto_resolves_to_cuda_with_a_gpu():
    device = resolve_device("auto")
    assert device.type == "cuda"
    assert device_info(device)["gpu_capability"].startswith("sm_")
