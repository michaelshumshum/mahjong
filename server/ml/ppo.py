"""PPO for the cold-start curriculum (docs/06-ml.md §9, §10). `ml`-extra only.

    python -m ml.train --config ml/configs/rl_ppo_c0.yaml [--resume] [--max-steps N] [--max-minutes M]

`ml.train` dispatches `algorithm: ppo` here (`train_ppo`). One update = collect at least
`batch_size` learner decisions from `ml.train_env`, then `epochs` passes of clipped PPO over them:

- masking only through `legal_mask` (`masked_log_softmax`, `masked_entropy`);
- reward = own payment / 32 at hand end, unclipped; potential shaping Φ = −β·shanten, Φ(end) = 0;
- per-seat GAE with γ = 1 over each seat's decisions in a hand; values are recomputed by the
  critic at update time, so samples from hands that straddled an update are still consistent;
- asymmetric critic (`OracleCritic`: policy tiles + all oracle channels) with PopArt;
- oracle dropout: oracle channels (opponents' hands, wall, next `k` draws) reach the policy only
  through `OracleAdapter`, multiplied by a per-element Bernoulli keep mask that is stored per
  sample so the update replays the exact behaviour input. It has no bias, so keep prob 0 adds
  exactly zero and the served `PolicyNet` never needs it;
- auxiliary losses (`ml.losses.aux_loss`) on the `aux_rate` subsample, weight annealed, never 0.

A run directory holds `meta.json` (pins `ENGINE_VERSION`), `ckpt_last.pt`, `metrics.jsonl`.
SIGINT/SIGTERM save after the current update and exit 0. Resume refuses a different engine.

`device` (`auto` | `cpu` | `cuda`) places the learner and the batched rollout forward; envs and
encoding stay numpy on CPU. Checkpoints are saved on CPU and load onto either device.
"""

from __future__ import annotations

import os

# before numpy loads: idle openblas threads spin and starve the env workers (§13)
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import json
import math
import signal
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import torch
import torch.nn.functional as F
import yaml
from torch import nn

from mahjong_core.config import RuleSet
from mahjong_core.engine import ENGINE_VERSION
from mahjong_core.presets import RULESET_PRESETS
from ml.aux_data import aux_targets
from ml.danger_model import _PADDED_WIDTH, _padded_positions
from ml.encode_v2 import (
    N_ORACLE_CHANNELS,
    ORACLE_CHANNELS,
    ORACLE_FIELDS,
    ORACLE_MAX_DRAWS,
    PAD,
    POLICY_FIELDS,
    encode_oracle_batch,
    encode_policy_batch,
    ruleset_features,
)
from ml.losses import AuxWeights, aux_loss
from ml.policy_net import (
    AuxOutput,
    OracleCritic,
    PolicyNet,
    PolicyNetConfig,
    PolicyOutput,
    masked_entropy,
    masked_log_softmax,
)
from ml.train_env import (
    INFO_FIELDS,
    LEARNER,
    EnvConfig,
    SubprocVecTrainEnv,
    VecTrainEnv,
    unpack_rows,
    with_min_faan,
)

__all__ = [
    "Episode",
    "FixedSchedule",
    "HandStat",
    "OracleAdapter",
    "PPOConfig",
    "PopArt",
    "Schedule",
    "StageParams",
    "critic_from_policy",
    "device_info",
    "gae",
    "load_ppo_config",
    "ppo_policy_loss",
    "resolve_device",
    "shaped_rewards",
    "train_ppo",
]

_KEEP_BITS = N_ORACLE_CHANNELS * 34
_DRAWS = ORACLE_CHANNELS["next_draws"]


@dataclass(frozen=True)
class StageParams:
    """What one curriculum point fixes: env seating and rules, oracle exposure, shaping."""

    name: str = "fixed"
    min_faan: int = 0
    learners: int = 1
    opponent: str = "tsumogiri"
    oracle_k: int = ORACLE_MAX_DRAWS
    keep_prob: float = 1.0
    beta: float = 1.0


@dataclass(frozen=True)
class HandStat:
    """One learner seat's finished hand."""

    won: bool
    dealt_in: bool
    blind: bool
    draw: bool
    tenpai_at_draw: bool
    sub_min_tenpai: bool
    points: float
    min_faan: int


class Schedule(Protocol):
    def params(self, decisions: int) -> StageParams: ...
    def observe(self, stats: list[HandStat]) -> None: ...
    def advance(self, decisions: int) -> str | None: ...
    def complete(self) -> bool: ...
    def clone_coef(self, decisions: int) -> float: ...
    def teacher(self) -> str | None: ...
    def snapshot_due(self, decisions: int) -> str | None: ...
    def metrics(self) -> dict[str, float]: ...
    def state_dict(self) -> dict[str, Any]: ...
    def load_state_dict(self, state: dict[str, Any]) -> None: ...


class FixedSchedule:
    """One stage forever; no advancement, no contingency."""

    def __init__(self, params: StageParams) -> None:
        self._params = params

    def params(self, decisions: int) -> StageParams:
        return self._params

    def observe(self, stats: list[HandStat]) -> None:
        pass

    def advance(self, decisions: int) -> str | None:
        return None

    def complete(self) -> bool:
        return False

    def clone_coef(self, decisions: int) -> float:
        return 0.0

    def teacher(self) -> str | None:
        return None

    def snapshot_due(self, decisions: int) -> str | None:
        return None

    def metrics(self) -> dict[str, float]:
        return {}

    def state_dict(self) -> dict[str, Any]:
        return {}

    def load_state_dict(self, state: dict[str, Any]) -> None:
        pass


@dataclass
class PPOConfig:
    out: str = "runs/ppo_c0"
    init_ckpt: str | None = None
    ruleset: str = "hk_classic"
    seed: int = 0
    threads: int = 2
    device: str = "auto"
    amp: bool = False
    envs: int = 64
    workers: int = 4
    blind_frac: float = 0.125
    channels: int = 96
    blocks: int = 6
    batch_size: int = 4096
    minibatch: int = 512
    epochs: int = 2
    lr: float = 3e-4
    weight_decay: float = 0.0
    clip: float = 0.2
    gae_lambda: float = 0.95
    entropy_coef: float = 0.01
    value_coef: float = 0.5
    grad_clip: float = 0.5
    popart_beta: float = 0.1
    aux_rate: float = 0.1
    aux_coef_start: float = 1.0
    aux_coef_end: float = 0.05
    aux_anneal_decisions: int = 50_000_000
    total_decisions: int = 1_000_000_000
    save_every: int = 20
    stage: dict[str, Any] = field(default_factory=dict)
    curriculum: dict[str, Any] | None = None

    def base_ruleset(self) -> RuleSet:
        return RULESET_PRESETS[self.ruleset]


def load_ppo_config(raw: dict[str, Any]) -> PPOConfig:
    unknown = set(raw) - {f.name for f in fields(PPOConfig)}
    if unknown:
        raise ValueError(f"unknown ppo config keys: {sorted(unknown)}")
    return PPOConfig(**raw)


def resolve_device(name: str) -> torch.device:
    """`auto` is CUDA when available, else CPU. An explicit `cuda` never falls back."""
    if name == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    device = torch.device(name)
    if device.type == "cpu":
        return device
    if device.type != "cuda":
        raise ValueError(f"device must be auto, cpu or cuda[:N], got {name!r}")
    if not torch.cuda.is_available():
        raise RuntimeError(
            f"device: {name} requested but torch.cuda.is_available() is False "
            f"(torch {torch.__version__}, built for CUDA {torch.version.cuda}); "
            "check the NVIDIA driver (`nvidia-smi`) or set device: cpu / auto"
        )
    if device.index is not None and device.index >= torch.cuda.device_count():
        raise RuntimeError(f"device: {name} requested, {torch.cuda.device_count()} GPU(s) visible")
    return device


def device_info(device: torch.device) -> dict[str, str]:
    """Strings only: they go into `meta.json` and every `metrics.jsonl` record."""
    info = {"device": str(device), "torch": torch.__version__}
    if device.type == "cuda":
        major, minor = torch.cuda.get_device_capability(device)
        info.update(
            {
                "gpu": torch.cuda.get_device_name(device),
                "gpu_capability": f"sm_{major}{minor}",
                "cuda": str(torch.version.cuda),
            }
        )
    return info


def to_cpu(state: Any) -> Any:
    """`state_dict` trees with every tensor on CPU, so a checkpoint loads without a GPU."""
    if isinstance(state, torch.Tensor):
        return state.cpu()
    if isinstance(state, dict):
        return {k: to_cpu(v) for k, v in state.items()}
    if isinstance(state, list | tuple):
        return type(state)(to_cpu(v) for v in state)
    return state


def shaped_rewards(final: float, potentials: np.ndarray) -> np.ndarray:
    """Per decision: Φ(next) − Φ(this), with Φ(terminal) = 0, plus `final` on the last one. Sums to
    `final − Φ(first)`, so the optimal policy is unchanged (Ng et al. 1999)."""
    phi = np.asarray(potentials, dtype=np.float64)
    r = np.append(phi[1:], 0.0) - phi
    r[-1] += final
    return r.astype(np.float32)


def gae(rewards: np.ndarray, values: np.ndarray, lam: float) -> tuple[np.ndarray, np.ndarray]:
    """γ = 1, V(terminal) = 0. Returns `(advantages, returns = advantages + values)`."""
    n = len(rewards)
    adv = np.zeros(n, dtype=np.float32)
    last = 0.0
    for t in range(n - 1, -1, -1):
        nxt = values[t + 1] if t + 1 < n else 0.0
        last = rewards[t] + nxt - values[t] + lam * last
        adv[t] = last
    return adv, adv + np.asarray(values, dtype=np.float32)


class PopArt(nn.Module):
    """Running mean/scale of value targets; `update` rescales the critic's last linear layer so
    its denormalised outputs are unchanged (van Hasselt et al. 2016)."""

    def __init__(self, beta: float, eps: float = 1e-4) -> None:
        super().__init__()
        self.beta = beta
        self.eps = eps
        self.register_buffer("mu", torch.zeros(()))
        self.register_buffer("nu", torch.ones(()))

    @property
    def sigma(self) -> torch.Tensor:
        return (self.nu - self.mu**2).clamp(min=self.eps**2).sqrt()

    @torch.no_grad()
    def update(self, targets: torch.Tensor, layer: nn.Linear) -> None:
        old_mu, old_sigma = self.mu.clone(), self.sigma.clone()
        self.mu.mul_(1 - self.beta).add_(self.beta * targets.mean())
        self.nu.mul_(1 - self.beta).add_(self.beta * (targets**2).mean())
        sigma = self.sigma
        layer.weight.mul_(old_sigma / sigma)
        layer.bias.mul_(old_sigma).add_(old_mu - self.mu).div_(sigma)

    def normalize(self, x: torch.Tensor) -> torch.Tensor:
        return (x - self.mu) / self.sigma

    def denormalize(self, x: torch.Tensor) -> torch.Tensor:
        return x * self.sigma + self.mu


class OracleAdapter(nn.Module):
    """Masked oracle channels -> a stem bias for `PolicyNet`'s trunk. Zero-initialised."""

    def __init__(self, channels: int) -> None:
        super().__init__()
        self.conv = nn.Conv1d(N_ORACLE_CHANNELS, channels, 3, padding=1, bias=False)
        nn.init.zeros_(self.conv.weight)
        self.register_buffer("positions", _padded_positions(), persistent=False)

    def forward(self, masked_oracle: torch.Tensor) -> torch.Tensor:
        x = masked_oracle.new_zeros(masked_oracle.shape[0], N_ORACLE_CHANNELS, _PADDED_WIDTH)
        x[:, :, self.positions] = masked_oracle
        return self.conv(x)


def critic_from_policy(policy: PolicyNet) -> OracleCritic:
    """`OracleCritic` whose trunk starts as the policy trunk, oracle stem inputs zero."""
    critic = OracleCritic(policy.config)
    state = {k: v.clone() for k, v in policy.trunk.state_dict().items()}
    w = state["stem.weight"]
    state["stem.weight"] = torch.cat(
        [w, w.new_zeros(w.shape[0], N_ORACLE_CHANNELS, w.shape[2])], dim=1
    )
    critic.trunk.load_state_dict(state)
    return critic


def ppo_policy_loss(
    logits: torch.Tensor,
    mask: torch.Tensor,
    actions: torch.Tensor,
    old_logp: torch.Tensor,
    adv: torch.Tensor,
    clip: float,
) -> dict[str, torch.Tensor]:
    """Clipped surrogate (to minimise), masked entropy, approx KL and clip fraction."""
    logp_all = masked_log_softmax(logits, mask)
    logp = logp_all.gather(1, actions[:, None]).squeeze(1)
    ratio = (logp - old_logp).exp()
    surrogate = torch.min(ratio * adv, ratio.clamp(1 - clip, 1 + clip) * adv)
    return {
        "pg": -surrogate.mean(),
        "entropy": masked_entropy(logp_all, mask).mean(),
        "approx_kl": (old_logp - logp).mean().detach(),
        "clip_frac": ((ratio - 1).abs() > clip).float().mean().detach(),
        "logp_all": logp_all,
    }


@dataclass
class Episode:
    """One finished hand's learner samples, in decision order."""

    rows: np.ndarray
    masks: np.ndarray
    actions: np.ndarray
    logp: np.ndarray
    keep: np.ndarray
    k: np.ndarray
    seats: np.ndarray
    rewards: np.ndarray
    info: np.ndarray
    blind: bool


class Encoder:
    def __init__(self, base: RuleSet) -> None:
        self.base = base
        self._vecs: dict[int, np.ndarray] = {}

    def _ruleset(self, min_faan: np.ndarray) -> np.ndarray:
        out = np.empty((len(min_faan), len(ruleset_features(self.base))), dtype=np.float32)
        for m in np.unique(min_faan):
            m = int(m)
            if m not in self._vecs:
                rs = RuleSet.from_dict({**self.base.to_dict(), "min_faan": m})
                self._vecs[m] = ruleset_features(rs).copy()
            out[min_faan == m] = self._vecs[m]
        return out

    def policy(self, u: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
        return encode_policy_batch({k: u[k] for k in POLICY_FIELDS}, self._ruleset(u["min_faan"]))

    def oracle(self, u: dict[str, np.ndarray], k: np.ndarray | None = None) -> np.ndarray:
        """`k` per row: draw planes `k..` zeroed (all 13 kept when `None`)."""
        out = encode_oracle_batch({f: u[f] for f in ORACLE_FIELDS})
        if k is not None:
            cut = np.arange(ORACLE_MAX_DRAWS)[None] >= np.asarray(k)[:, None]
            draws = out[:, _DRAWS]
            draws[cut] = 0.0
            out[:, _DRAWS] = draws
        return out


class Learner:
    """Models, optimiser and the update step; independent of how samples were collected. Every
    module and update-time tensor lives on `device`; inputs and outputs are numpy on CPU."""

    def __init__(
        self, cfg: PPOConfig, policy: PolicyNet, device: torch.device | str = "cpu"
    ) -> None:
        self.cfg = cfg
        self.device = torch.device(device)
        if cfg.amp and self.device.type != "cuda":
            raise ValueError("amp needs device: cuda (fp16 autocast + GradScaler)")
        self.policy = policy.to(self.device)
        self.adapter = OracleAdapter(policy.config.channels).to(self.device)
        self.critic = critic_from_policy(policy).to(self.device)
        self.popart = PopArt(cfg.popart_beta).to(self.device)
        self.scaler = torch.amp.GradScaler("cuda", enabled=cfg.amp)
        params = [
            *self.policy.parameters(),
            *self.adapter.parameters(),
            *self.critic.parameters(),
        ]
        self.opt = torch.optim.AdamW(params, lr=cfg.lr, weight_decay=cfg.weight_decay)
        self.encoder = Encoder(cfg.base_ruleset())

    def state_dict(self) -> dict[str, Any]:
        """On CPU whatever the device."""
        state = {
            "policy": self.policy.state_dict(),
            "adapter": self.adapter.state_dict(),
            "critic": self.critic.state_dict(),
            "popart": self.popart.state_dict(),
            "opt": self.opt.state_dict(),
        }
        if self.cfg.amp:
            state["scaler"] = self.scaler.state_dict()
        return to_cpu(state)

    def load_state_dict(self, state: dict[str, Any]) -> None:
        """From either device; `Optimizer.load_state_dict` moves its moments onto the params'."""
        self.policy.load_state_dict(state["policy"])
        self.adapter.load_state_dict(state["adapter"])
        self.critic.load_state_dict(state["critic"])
        self.popart.load_state_dict(state["popart"])
        self.opt.load_state_dict(state["opt"])
        if self.cfg.amp and "scaler" in state:
            self.scaler.load_state_dict(state["scaler"])

    def _to(self, x: np.ndarray) -> torch.Tensor:
        return torch.from_numpy(np.ascontiguousarray(x)).to(self.device)

    def _autocast(self) -> torch.autocast:
        return torch.autocast(self.device.type, dtype=torch.float16, enabled=self.cfg.amp)

    def stem_bias(self, masked_oracle: np.ndarray | None) -> torch.Tensor | None:
        if masked_oracle is None or not masked_oracle.any():
            return None
        return self.adapter(self._to(masked_oracle))

    @torch.no_grad()
    def act(
        self, rows: np.ndarray, masks: np.ndarray, keep_prob: np.ndarray, k: np.ndarray, rng: Any
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Sample actions for packed rows. Returns `(actions, logp, packed keep bits)`."""
        u = unpack_rows(rows)
        tiles, scalars = self.encoder.policy(u)
        b = len(rows)
        keep = np.zeros((b, N_ORACLE_CHANNELS, 34), dtype=bool)
        masked = None
        if keep_prob.any():
            p = keep_prob[:, None, None]
            keep = np.where(p >= 1.0, True, rng.random(keep.shape) < p)
            masked = self.encoder.oracle(u, k) * keep
        with self._autocast():
            logits = self.policy(
                self._to(tiles), self._to(scalars), aux=False, stem_bias=self.stem_bias(masked)
            ).logits
        logp_all = masked_log_softmax(logits.float(), self._to(masks)).cpu().numpy()
        gumbel = -np.log(-np.log(rng.random(logp_all.shape).clip(1e-12, 1.0)))
        actions = np.argmax(logp_all + gumbel, axis=1)
        logp = logp_all[np.arange(b), actions]
        return actions, logp, np.packbits(keep.reshape(b, -1), axis=1)

    def aux_coef(self, decisions: int) -> float:
        c = self.cfg
        u = min(1.0, decisions / max(1, c.aux_anneal_decisions))
        return c.aux_coef_start + (c.aux_coef_end - c.aux_coef_start) * u

    def update(
        self, episodes: list[Episode], params: StageParams, decisions: int, clone_coef: float
    ) -> dict[str, float]:
        c = self.cfg
        rows = np.concatenate([e.rows for e in episodes])
        masks = np.concatenate([e.masks for e in episodes])
        actions = np.concatenate([e.actions for e in episodes]).astype(np.int64)
        old_logp = np.concatenate([e.logp for e in episodes]).astype(np.float32)
        keep = np.unpackbits(np.concatenate([e.keep for e in episodes]), axis=1)[:, :_KEEP_BITS]
        k = np.concatenate([e.k for e in episodes])
        n = len(rows)
        u = unpack_rows(rows)
        tiles, scalars = self.encoder.policy(u)
        oracle_full = self.encoder.oracle(u)
        pol_oracle = self.encoder.oracle(u, k) * keep.reshape(n, N_ORACLE_CHANNELS, 34)
        has_oracle = pol_oracle.reshape(n, -1).any(axis=1)

        t_tiles, t_scalars, t_oracle = self._to(tiles), self._to(scalars), self._to(oracle_full)
        with torch.no_grad(), self._autocast():
            v_norm = torch.cat(
                [
                    self.critic(
                        t_tiles[i : i + 1024], t_oracle[i : i + 1024], t_scalars[i : i + 1024]
                    )
                    for i in range(0, n, 1024)
                ]
            )
            values = self.popart.denormalize(v_norm.float()).cpu().numpy()

        adv = np.zeros(n, dtype=np.float32)
        ret = np.zeros(n, dtype=np.float32)
        shanten_now = u["cur_shanten"].astype(np.float32) - 1.0
        payment = np.zeros(n, dtype=np.int64)
        won = np.zeros(n, dtype=np.uint8)
        dealt = np.zeros(n, dtype=np.uint8)
        at = 0
        for e in episodes:
            m = len(e.rows)
            winner, discarder = int(e.info[0]), int(e.info[1])
            for s in np.unique(e.seats):
                idx = at + np.flatnonzero(e.seats == s)
                r = shaped_rewards(float(e.rewards[s]), -params.beta * shanten_now[idx])
                adv[idx], ret[idx] = gae(r, values[idx], c.gae_lambda)
                payment[idx] = round(float(e.rewards[s]) * 32)
                won[idx] = winner == s
                dealt[idx] = discarder == s and winner != s
            at += m

        t_ret = self._to(ret)
        self.popart.update(t_ret, self.critic.value[-1])
        target_n = self.popart.normalize(t_ret)
        adv_n = (adv - adv.mean()) / (adv.std() + 1e-8)

        aux_rows = u["aux"].astype(bool)
        aux_raw = {name: u[name] for name in u}
        aux_raw.update({"win": won, "deal_in": dealt, "payment": payment})
        targets = {key: self._to(v) for key, v in aux_targets(aux_raw).items()}
        teacher = u["teacher"].astype(np.int64)
        aux_coef = self.aux_coef(decisions)

        t_masks, t_actions, t_old = self._to(masks), self._to(actions), self._to(old_logp)
        t_adv, t_pol_oracle = self._to(adv_n.astype(np.float32)), self._to(pol_oracle)
        t_teacher = self._to(teacher)
        rng = np.random.default_rng([c.seed, decisions])
        sums: dict[str, float] = {}
        n_mb = 0
        for _ in range(c.epochs):
            order = rng.permutation(n)
            for lo in range(0, n, c.minibatch):
                mb = order[lo : lo + c.minibatch]
                mb_t = self._to(mb)
                with self._autocast():
                    bias = self.adapter(t_pol_oracle[mb_t]) if has_oracle[mb].any() else None
                    out = self.policy(t_tiles[mb_t], t_scalars[mb_t], aux=True, stem_bias=bias)
                    v = self.critic(t_tiles[mb_t], t_oracle[mb_t], t_scalars[mb_t])
                if c.amp:
                    out = _float_output(out)
                    v = v.float()
                pl = ppo_policy_loss(
                    out.logits, t_masks[mb_t], t_actions[mb_t], t_old[mb_t], t_adv[mb_t], c.clip
                )
                v_loss = 0.5 * F.mse_loss(v, target_n[mb_t])
                loss = pl["pg"] + c.value_coef * v_loss - c.entropy_coef * pl["entropy"]
                logs = {
                    "pg": pl["pg"].item(),
                    "value": v_loss.item(),
                    "entropy": pl["entropy"].item(),
                    "approx_kl": pl["approx_kl"].item(),
                    "clip_frac": pl["clip_frac"].item(),
                }
                sel = mb[aux_rows[mb]]
                if len(sel):
                    assert out.aux is not None
                    pos = self._to(np.flatnonzero(aux_rows[mb]))
                    sub = AuxOutput(
                        **{f.name: getattr(out.aux, f.name)[pos] for f in fields(AuxOutput)}
                    )
                    sel_t = self._to(sel)
                    al = aux_loss(sub, {key: v[sel_t] for key, v in targets.items()}, AuxWeights())
                    loss = loss + aux_coef * al["total"]
                    logs["aux"] = al["total"].item()
                if clone_coef > 0:
                    has = t_teacher[mb_t] != PAD
                    if has.any():
                        ce = -pl["logp_all"][has].gather(1, t_teacher[mb_t][has][:, None]).mean()
                        loss = loss + clone_coef * ce
                        logs["clone_ce"] = ce.item()
                self.opt.zero_grad(set_to_none=True)
                if c.amp:
                    self.scaler.scale(loss).backward()
                    self.scaler.unscale_(self.opt)
                else:
                    loss.backward()
                nn.utils.clip_grad_norm_(
                    [p for g in self.opt.param_groups for p in g["params"]], c.grad_clip
                )
                if c.amp:
                    self.scaler.step(self.opt)
                    self.scaler.update()
                else:
                    self.opt.step()
                for key, val in logs.items():
                    sums[key] = sums.get(key, 0.0) + val
                n_mb += 1
        var = float(np.var(ret))
        out_metrics = {key: v / n_mb for key, v in sums.items()}
        out_metrics.update(
            {
                "samples": n,
                "explained_var": 1.0 - float(np.var(ret - values)) / var if var > 0 else 0.0,
                "return_mean": float(ret.mean()),
                "popart_mu": float(self.popart.mu),
                "popart_sigma": float(self.popart.sigma),
                "aux_coef": aux_coef,
                "clone_coef": clone_coef,
                "aux_rows": int(aux_rows.sum()),
            }
        )
        return out_metrics


def _float_output(out: PolicyOutput) -> PolicyOutput:
    aux = None
    if out.aux is not None:
        aux = AuxOutput(**{f.name: getattr(out.aux, f.name).float() for f in fields(AuxOutput)})
    return PolicyOutput(out.logits.float(), aux)


class Collector:
    """Steps the train env with the learner's policy and groups samples into finished hands."""

    def __init__(self, venv: VecTrainEnv | SubprocVecTrainEnv, n_blind: int, rng: Any) -> None:
        self.venv = venv
        self.n = venv.num_envs
        self.n_blind = n_blind
        self.rng = rng
        self.buf = venv.reset()
        self.pending: list[list[tuple[Any, ...]]] = [[] for _ in range(self.n)]

    def collect(
        self, learner: Learner, params: StageParams, min_samples: int
    ) -> tuple[list[Episode], list[HandStat], int]:
        episodes: list[Episode] = []
        stats: list[HandStat] = []
        ready = steps = 0
        keep_prob = np.full(self.n, params.keep_prob, dtype=np.float32)
        k = np.full(self.n, params.oracle_k, dtype=np.int64)
        keep_prob[: self.n_blind] = 0.0
        k[: self.n_blind] = 0
        while ready < min_samples:
            buf = self.buf
            rows, masks, seats = buf.rows.copy(), buf.mask.copy(), buf.seat.copy()
            actions, logp, keep = learner.act(rows, masks, keep_prob, k, self.rng)
            roles = unpack_rows(rows, ("role",))["role"]
            for i in range(self.n):
                if roles[i] == LEARNER:
                    self.pending[i].append(
                        (rows[i], masks[i], actions[i], logp[i], keep[i], k[i], seats[i])
                    )
            self.buf = buf = self.venv.step(actions.astype(np.int32))
            steps += 1
            for i in np.flatnonzero(buf.done):
                ep = self._finish(int(i), buf.rewards[i].copy(), buf.info[i].copy())
                if ep is not None:
                    episodes.append(ep)
                    ready += len(ep.rows)
                    stats += _hand_stats(ep)
        return episodes, stats, steps

    def _finish(self, i: int, rewards: np.ndarray, info: np.ndarray) -> Episode | None:
        samples, self.pending[i] = self.pending[i], []
        if not samples:
            return None
        cols = list(zip(*samples, strict=True))
        return Episode(
            rows=np.stack(cols[0]),
            masks=np.stack(cols[1]),
            actions=np.asarray(cols[2], dtype=np.int64),
            logp=np.asarray(cols[3], dtype=np.float32),
            keep=np.stack(cols[4]),
            k=np.asarray(cols[5], dtype=np.uint8),
            seats=np.asarray(cols[6], dtype=np.int8),
            rewards=rewards,
            info=info,
            blind=i < self.n_blind,
        )


def _hand_stats(ep: Episode) -> list[HandStat]:
    info = dict(zip(INFO_FIELDS, (int(x) for x in ep.info), strict=True))
    min_faan = int(unpack_rows(ep.rows[:1], ("min_faan",))["min_faan"][0])
    out = []
    for s in range(4):
        if not info["learners"] >> s & 1:
            continue
        out.append(
            HandStat(
                won=info["winner"] == s,
                dealt_in=info["discarder"] == s and info["winner"] != s,
                blind=ep.blind,
                draw=info["winner"] < 0,
                tenpai_at_draw=bool(info["tenpai_at_draw"] >> s & 1),
                sub_min_tenpai=bool(info["sub_min_tenpai"] >> s & 1),
                points=float(ep.rewards[s]),
                min_faan=min_faan,
            )
        )
    return out


def _summarise(stats: list[HandStat]) -> dict[str, float]:
    if not stats:
        return {}
    n = len(stats)
    blind = [s for s in stats if s.blind]
    tenpai = [s for s in stats if s.tenpai_at_draw]
    out = {
        "hands": n,
        "win_rate": sum(s.won for s in stats) / n,
        "deal_in_rate": sum(s.dealt_in for s in stats) / n,
        "draw_rate": sum(s.draw for s in stats) / n,
        "points_per_hand": sum(s.points for s in stats) / n,
    }
    if blind:
        out["blind_win_rate"] = sum(s.won for s in blind) / len(blind)
    if tenpai:
        out["sub_min_tenpai_rate"] = sum(s.sub_min_tenpai for s in tenpai) / len(tenpai)
    return out


def build_schedule(cfg: PPOConfig) -> Schedule:
    if cfg.curriculum is not None:
        from ml.curriculum import Curriculum

        return Curriculum.from_config(cfg.curriculum)
    return FixedSchedule(StageParams(**cfg.stage))


def _env_config(cfg: PPOConfig, params: StageParams, teacher: str | None) -> EnvConfig:
    base = EnvConfig(
        ruleset=cfg.base_ruleset(),
        learners=params.learners,
        opponent=params.opponent,
        aux_rate=cfg.aux_rate,
        teacher=teacher,
    )
    return with_min_faan(base, params.min_faan)


def load_policy(cfg: PPOConfig) -> PolicyNet:
    """From the R1 checkpoint (`init_ckpt`: trunk + aux heads; the policy head is untrained) or
    freshly initialised."""
    if cfg.init_ckpt is None:
        return PolicyNet(PolicyNetConfig(channels=cfg.channels, blocks=cfg.blocks))
    ckpt = torch.load(cfg.init_ckpt, weights_only=False, map_location="cpu")
    state = ckpt["policy"] if "policy" in ckpt else ckpt["model"]
    model = PolicyNet(PolicyNetConfig(**ckpt["model_config"]))
    model.load_state_dict(state)
    return model


def _check_meta(out: Path, cfg: PPOConfig, resume: bool, info: dict[str, str]) -> None:
    path = out / "meta.json"
    if resume and path.exists():
        meta = json.loads(path.read_text())
        if meta["engine_version"] != ENGINE_VERSION:
            raise RuntimeError(
                f"run {out} pins ENGINE_VERSION {meta['engine_version']!r}, "
                f"engine is {ENGINE_VERSION!r}; refusing to resume"
            )
        return
    meta = {"engine_version": ENGINE_VERSION, "config": asdict(cfg), "device": info}
    path.write_text(json.dumps(meta, indent=2))


def train_ppo(
    cfg: PPOConfig,
    *,
    resume: bool = False,
    max_updates: int | None = None,
    max_minutes: float | None = None,
    on_update: Callable[[dict[str, Any]], None] | None = None,
) -> Path:
    # also on cuda: host threads only feed the GPU and contend with the env workers
    torch.set_num_threads(cfg.threads)
    torch.manual_seed(cfg.seed)
    device = resolve_device(cfg.device)
    info = device_info(device)
    print(f"device: {json.dumps(info)}", flush=True)
    out = Path(cfg.out)
    out.mkdir(parents=True, exist_ok=True)
    _check_meta(out, cfg, resume, info)

    schedule = build_schedule(cfg)
    decisions = updates = 0
    rng = np.random.default_rng(cfg.seed)
    last_path = out / "ckpt_last.pt"
    ckpt = None
    if resume and last_path.exists():
        ckpt = torch.load(last_path, weights_only=False, map_location="cpu")
        if ckpt["engine_version"] != ENGINE_VERSION:
            raise RuntimeError(
                f"checkpoint ENGINE_VERSION {ckpt['engine_version']!r} != {ENGINE_VERSION!r}"
            )
        decisions, updates = ckpt["decisions"], ckpt["updates"]
        schedule.load_state_dict(ckpt["schedule"])
        rng.bit_generator.state = ckpt["rng"]

    params = schedule.params(decisions)
    env_cfg = _env_config(cfg, params, schedule.teacher())
    # env seeds move on at each resume: a resumed run is a new, still deterministic, stream
    base_seed = cfg.seed * 1_000_003 + updates
    venv: VecTrainEnv | SubprocVecTrainEnv
    if cfg.workers > 0:
        venv = SubprocVecTrainEnv(cfg.envs, base_seed, env_cfg, n_workers=cfg.workers)
    else:
        venv = VecTrainEnv(cfg.envs, base_seed, env_cfg)

    learner = Learner(cfg, load_policy(cfg), device)
    if ckpt is not None:
        learner.load_state_dict(ckpt["learner"])
    collector = Collector(venv, round(cfg.envs * cfg.blind_frac), rng)

    def save(path: Path = last_path) -> None:
        tmp = path.with_suffix(".tmp")
        torch.save(
            {
                "learner": learner.state_dict(),
                "schedule": schedule.state_dict(),
                "rng": rng.bit_generator.state,
                "decisions": decisions,
                "updates": updates,
                "engine_version": ENGINE_VERSION,
                "config": asdict(cfg),
                "model_config": learner.policy.config.to_dict(),
                "algorithm": "ppo",
            },
            tmp,
        )
        tmp.replace(path)

    stop = False

    def request_stop(signum: int, _frame: object) -> None:
        nonlocal stop
        print(f"received signal {signum}, saving after this update", flush=True)
        stop = True

    previous = {sig: signal.signal(sig, request_stop) for sig in (signal.SIGINT, signal.SIGTERM)}

    started = time.monotonic()
    deadline = math.inf if max_minutes is None else started + 60 * max_minutes
    final = math.inf if max_updates is None else updates + max_updates
    try:
        with (out / "metrics.jsonl").open("a") as metrics:
            while (
                decisions < cfg.total_decisions
                and updates < final
                and time.monotonic() < deadline
                and not stop
                and not schedule.complete()
            ):
                t0 = time.monotonic()
                episodes, stats, steps = collector.collect(learner, params, cfg.batch_size)
                t1 = time.monotonic()
                n = sum(len(e.rows) for e in episodes)
                record = learner.update(episodes, params, decisions, schedule.clone_coef(decisions))
                t2 = time.monotonic()
                decisions += n
                updates += 1
                schedule.observe(stats)
                advanced = schedule.advance(decisions)
                new_params = schedule.params(decisions)
                if _env_config(cfg, new_params, schedule.teacher()) != env_cfg:
                    env_cfg = _env_config(cfg, new_params, schedule.teacher())
                    venv.configure(env_cfg)
                record.update({f"batch_{k}": v for k, v in _summarise(stats).items()})
                record.update(schedule.metrics())
                record.update(
                    {
                        "update": updates,
                        "decisions": decisions,
                        "stage": params.name,
                        "min_faan": params.min_faan,
                        "oracle_k": params.oracle_k,
                        "keep_prob": params.keep_prob,
                        "beta": params.beta,
                        "rollout_s": round(t1 - t0, 3),
                        "update_s": round(t2 - t1, 3),
                        "rollout_decisions_per_s": round(n / max(t1 - t0, 1e-9), 1),
                        "learner_decisions_per_s": round(n / max(t2 - t1, 1e-9), 1),
                        "decisions_per_s": round(n / max(t2 - t0, 1e-9), 1),
                        "env_steps": steps,
                        "elapsed_s": round(time.monotonic() - started, 1),
                        **info,
                    }
                )
                if advanced:
                    record["advanced_to"] = advanced
                params = new_params
                metrics.write(json.dumps(record) + "\n")
                metrics.flush()
                print(json.dumps(record), flush=True)
                if on_update is not None:
                    on_update(record)
                if updates % cfg.save_every == 0:
                    save()
                snapshot = schedule.snapshot_due(decisions)
                if snapshot is not None:
                    save(out / f"ckpt_{snapshot}.pt")
        save()
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        if isinstance(venv, SubprocVecTrainEnv):
            venv.close()
    return out


def main_config(path: Path) -> PPOConfig:
    raw = yaml.safe_load(path.read_text())
    raw.pop("algorithm", None)
    return load_ppo_config(raw)
