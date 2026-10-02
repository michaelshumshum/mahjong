"""Process-pool start method shared by `ml/` tooling that forks workers."""

from __future__ import annotations

import multiprocessing
import multiprocessing.context
import threading

__all__ = ["mp_context"]


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
