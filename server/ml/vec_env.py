"""K `HandEnv`s stepped together into batched arrays, with auto-reset (docs/ml.md §7).

`VecHandEnv` steps in-process; `SubprocVecHandEnv` splits the K envs across worker processes
that write into shared-memory buffers, so the learner's batched forward reads them without a
copy through a pipe. Both produce identical arrays for the same `(base_seed, actions)`.

Env `i`'s `e`-th episode is seeded `episode_seed(base_seed, i, e)`. Returned arrays are the
env's own buffers, overwritten by the next `step`: copy anything that must outlive it.
"""

from __future__ import annotations

import hashlib
import itertools
import traceback
from dataclasses import dataclass
from multiprocessing.connection import Connection
from typing import Any, Self

import numpy as np

from mahjong_core.config import DEFAULT_RULESET, RuleSet
from ml.env import N_ACTIONS, OBS_DIM, HandEnv, encode_obs
from ml.mp import mp_context

__all__ = ["SubprocVecHandEnv", "VecHandEnv", "VecStep", "episode_seed"]

VecStep = tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]


def episode_seed(base_seed: int, env_index: int, episode: int) -> int:
    digest = hashlib.blake2b(f"{base_seed}:{env_index}:{episode}".encode(), digest_size=8).digest()
    return int.from_bytes(digest) >> 1


@dataclass(frozen=True)
class _Buffers:
    """seat (K,) int32, never -1 since done envs are already reset; obs (K, OBS_DIM) float32, or
    (K, 0) without encoding; mask (K, N_ACTIONS) bool; done (K,) bool; rewards (K, 4) float32."""

    seat: np.ndarray
    obs: np.ndarray
    mask: np.ndarray
    done: np.ndarray
    rewards: np.ndarray

    @staticmethod
    def allocate(n: int, obs_dim: int) -> _Buffers:
        return _Buffers(
            seat=np.zeros(n, dtype=np.int32),
            obs=np.zeros((n, obs_dim), dtype=np.float32),
            mask=np.zeros((n, N_ACTIONS), dtype=bool),
            done=np.zeros(n, dtype=bool),
            rewards=np.zeros((n, 4), dtype=np.float32),
        )

    def out(self) -> VecStep:
        return self.seat, self.obs, self.mask, self.done, self.rewards


class VecHandEnv:
    """`reset() -> (seat, obs, mask)`; `step(actions) -> (seat, obs, mask, done, rewards)`.

    Where `done[i]`, `rewards[i]` belongs to the episode that just ended and `seat/obs/mask[i]`
    to the next one. With `keep_records`, finished episodes' `HandEnv.record()`s collect in
    `records` for the caller to drain.
    """

    def __init__(
        self,
        n_envs: int,
        base_seed: int,
        ruleset: RuleSet = DEFAULT_RULESET,
        *,
        encode: bool = True,
        keep_records: bool = False,
        first_index: int = 0,
        buffers: _Buffers | None = None,
    ) -> None:
        self.num_envs = n_envs
        self.base_seed = base_seed
        self.encode = encode
        self.keep_records = keep_records
        self.records: list[dict[str, Any]] = []
        self._first = first_index
        self._envs = [HandEnv(ruleset, encode=False) for _ in range(n_envs)]
        self._episodes = [0] * n_envs
        self._buf = buffers or _Buffers.allocate(n_envs, OBS_DIM if encode else 0)

    def reset(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        self._episodes = [0] * self.num_envs
        self.records = []
        self._buf.done[:] = False
        self._buf.rewards[:] = 0.0
        for i in range(self.num_envs):
            self._reset_one(i)
        return self._buf.seat, self._buf.obs, self._buf.mask

    def step(self, actions: np.ndarray) -> VecStep:
        buf = self._buf
        for i, env in enumerate(self._envs):
            seat, _, mask, done, rewards = env.step(int(actions[i]))
            buf.done[i] = done
            if done:
                buf.rewards[i] = rewards
                if self.keep_records:
                    self.records.append(env.record())
                self._episodes[i] += 1
                self._reset_one(i)
            else:
                buf.rewards[i] = 0.0
                buf.seat[i] = seat
                buf.mask[i] = mask
                if self.encode:
                    assert env.state is not None
                    encode_obs(env.state, seat, out=buf.obs[i])
        return buf.out()

    def _reset_one(self, i: int) -> None:
        env = self._envs[i]
        seed = episode_seed(self.base_seed, self._first + i, self._episodes[i])
        seat, _, mask = env.reset(seed)
        self._buf.seat[i] = seat
        self._buf.mask[i] = mask
        if self.encode:
            assert env.state is not None
            encode_obs(env.state, seat, out=self._buf.obs[i])


def _shared(ctx: Any, n: int, obs_dim: int) -> dict[str, Any]:
    return {
        "seat": ctx.RawArray("i", n),
        "obs": ctx.RawArray("f", max(n * obs_dim, 1)),
        "mask": ctx.RawArray("b", n * N_ACTIONS),
        "done": ctx.RawArray("b", n),
        "rewards": ctx.RawArray("f", n * 4),
        "actions": ctx.RawArray("i", n),
    }


def _views(raw: dict[str, Any], n: int, obs_dim: int) -> tuple[_Buffers, np.ndarray]:
    buf = _Buffers(
        seat=np.frombuffer(raw["seat"], dtype=np.int32),
        obs=np.frombuffer(raw["obs"], dtype=np.float32)[: n * obs_dim].reshape(n, obs_dim),
        mask=np.frombuffer(raw["mask"], dtype=bool).reshape(n, N_ACTIONS),
        done=np.frombuffer(raw["done"], dtype=bool),
        rewards=np.frombuffer(raw["rewards"], dtype=np.float32).reshape(n, 4),
    )
    return buf, np.frombuffer(raw["actions"], dtype=np.int32)


def _worker(
    conn: Connection,
    lo: int,
    hi: int,
    n: int,
    obs_dim: int,
    raw: dict[str, Any],
    base_seed: int,
    ruleset_dict: dict[str, Any],
    encode: bool,
    keep_records: bool,
) -> None:
    full, actions = _views(raw, n, obs_dim)
    part = _Buffers(
        seat=full.seat[lo:hi],
        obs=full.obs[lo:hi],
        mask=full.mask[lo:hi],
        done=full.done[lo:hi],
        rewards=full.rewards[lo:hi],
    )
    venv = VecHandEnv(
        hi - lo,
        base_seed,
        RuleSet.from_dict(ruleset_dict),
        encode=encode,
        keep_records=keep_records,
        first_index=lo,
        buffers=part,
    )
    while True:
        cmd = conn.recv()
        try:
            if cmd == "reset":
                venv.reset()
            elif cmd == "step":
                venv.step(actions[lo:hi])
            else:
                return
            conn.send(("ok", venv.records))
            venv.records = []
        except Exception:  # noqa: BLE001 -- re-raised in the parent with this traceback
            conn.send(("err", traceback.format_exc()))


class SubprocVecHandEnv:
    """`VecHandEnv`'s API, the K envs split into `n_workers` contiguous slices, one process each.
    Use as a context manager, or call `close()`."""

    def __init__(
        self,
        n_envs: int,
        base_seed: int,
        ruleset: RuleSet = DEFAULT_RULESET,
        *,
        n_workers: int,
        encode: bool = True,
        keep_records: bool = False,
    ) -> None:
        if not 1 <= n_workers <= n_envs:
            raise ValueError(f"n_workers must be in 1..{n_envs}, got {n_workers}")
        self.num_envs = n_envs
        self.records: list[dict[str, Any]] = []
        obs_dim = OBS_DIM if encode else 0
        ctx = mp_context()
        raw = _shared(ctx, n_envs, obs_dim)
        self._buf, self._actions = _views(raw, n_envs, obs_dim)
        bounds = np.linspace(0, n_envs, n_workers + 1).astype(int)
        self._conns: list[Connection] = []
        self._procs = []
        for lo, hi in itertools.pairwise(bounds):
            parent, child = ctx.Pipe()
            proc = ctx.Process(
                target=_worker,
                args=(
                    child,
                    int(lo),
                    int(hi),
                    n_envs,
                    obs_dim,
                    raw,
                    base_seed,
                    ruleset.to_dict(),
                    encode,
                    keep_records,
                ),
                daemon=True,
            )
            proc.start()
            child.close()
            self._conns.append(parent)
            self._procs.append(proc)

    def reset(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        self.records = []
        self._broadcast("reset")
        return self._buf.seat, self._buf.obs, self._buf.mask

    def step(self, actions: np.ndarray) -> VecStep:
        self._actions[:] = actions
        self._broadcast("step")
        return self._buf.out()

    def close(self) -> None:
        for conn in self._conns:
            try:
                conn.send("close")
            except (BrokenPipeError, OSError):
                pass
        for proc in self._procs:
            proc.join(timeout=5)
        self._conns = []
        self._procs = []

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _broadcast(self, cmd: str) -> None:
        for conn in self._conns:
            conn.send(cmd)
        errors = []
        for conn in self._conns:
            status, payload = conn.recv()
            if status == "err":
                errors.append(payload)
            else:
                self.records.extend(payload)
        if errors:
            raise RuntimeError("vec env worker failed:\n" + "\n".join(errors))
