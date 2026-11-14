"""Process-pool start method and the shared-memory env worker pool for `ml/` tooling that forks
workers."""

from __future__ import annotations

import itertools
import multiprocessing
import multiprocessing.context
import threading
from collections.abc import Callable
from multiprocessing.connection import Connection
from typing import Any

import numpy as np

__all__ = ["WorkerPool", "mp_context"]


def mp_context() -> multiprocessing.context.BaseContext:
    """`fork` over the platform default (`forkserver` on this interpreter, confirmed via
    `multiprocessing.get_start_method()`): measured directly on this workload (120 games, 12
    workers, `hk_classic`, identical bot roster, both legs run back-to-back in one process) --
    `forkserver` managed 0.860 games/sec, `fork` managed 1.518 games/sec, a ~1.8x difference at
    the same worker count.

    Only safe when the current process is single-threaded at pool-creation time -- a thread other
    than main could hold a lock (import lock, malloc, logging) that the forked child inherits
    already-acquired and can never release, deadlocking the child the first time it needs that
    lock. That's not hypothetical here: running this under pytest triggers Python's own
    `DeprecationWarning` for exactly this condition, because pytest's own process is
    multi-threaded. Checking `threading.active_count()` at call time (not import time, since
    thread state can change) picks the fast path only when it's actually safe."""
    if threading.active_count() > 1:
        return multiprocessing.get_context()
    return multiprocessing.get_context("fork")


class WorkerPool:
    """`n_envs` split into `n_workers` contiguous slices, one daemon process each, driven over a
    pipe per worker. A worker answers every message with `("ok", payload)` or
    `("err", traceback)`; `broadcast` re-raises errors in the parent once every worker answered.

    Two-phase so the caller can allocate shared buffers from `ctx` before `start` forks."""

    def __init__(self, n_envs: int, n_workers: int) -> None:
        if not 1 <= n_workers <= n_envs:
            raise ValueError(f"n_workers must be in 1..{n_envs}, got {n_workers}")
        self.n_envs = n_envs
        self.n_workers = n_workers
        self.ctx = mp_context()
        self._conns: list[Connection] = []
        self._procs: list[Any] = []

    def start(self, target: Callable[..., None], *args: Any) -> None:
        """Run `target(conn, lo, hi, *args)` in one process per slice."""
        bounds = np.linspace(0, self.n_envs, self.n_workers + 1).astype(int)
        for lo, hi in itertools.pairwise(bounds):
            parent, child = self.ctx.Pipe()
            proc = self.ctx.Process(
                target=target, args=(child, int(lo), int(hi), *args), daemon=True
            )
            proc.start()
            child.close()
            self._conns.append(parent)
            self._procs.append(proc)

    def broadcast(
        self, msg: object, name: str, on_ok: Callable[[Any], object] | None = None
    ) -> None:
        for conn in self._conns:
            conn.send(msg)
        errors = []
        for conn in self._conns:
            status, payload = conn.recv()
            if status == "err":
                errors.append(payload)
            elif on_ok is not None:
                on_ok(payload)
        if errors:
            raise RuntimeError(f"{name} worker failed:\n" + "\n".join(errors))

    def close(self, msg: object) -> None:
        for conn in self._conns:
            try:
                conn.send(msg)
            except (BrokenPipeError, OSError):
                pass
        for proc in self._procs:
            proc.join(timeout=5)
        self._conns = []
        self._procs = []
