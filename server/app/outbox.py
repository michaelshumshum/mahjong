"""Bounded per-connection outbound queue. Not `asyncio.Queue`: the drop-oldest/collapse-to-
`state_sync` overflow policy needs to remove from the middle of the queue.

Overflow: drop the oldest non-`ack`/`error` frame; if still over capacity, clear every
remaining non-critical frame and call the caller-supplied `resync` (re-enters `push()` so the
real per-seat `seq` allocator stamps it, rather than this module fabricating one that could
collide); if still over capacity after that, the peer is dead, not slow -- `self.dead` flips
true and the caller closes the connection.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from typing import Any

_CRITICAL_TYPES = frozenset({"ack", "error"})


class BoundedOutbox:
    def __init__(self, maxsize: int = 64, resync: Callable[[], None] | None = None) -> None:
        self.maxsize = maxsize
        self.dead = False
        self._frames: deque[dict[str, Any]] = deque()
        self._resync = resync
        self._event = asyncio.Event()
        self._closing = False

    def push(self, frame: dict[str, Any]) -> None:
        if self.dead:
            return
        self._frames.append(frame)
        if len(self._frames) > self.maxsize:
            self._overflow()
        if self._frames:
            self._event.set()

    def _overflow(self) -> None:
        if not any(f.get("t") not in _CRITICAL_TYPES for f in self._frames):
            self.dead = True  # every queued frame is critical -- nothing left to drop
            return
        self._frames = deque(f for f in self._frames if f.get("t") in _CRITICAL_TYPES)
        if self._resync is not None:
            self._resync()  # re-enters push() with a freshly, correctly-seq'd state_sync
        if len(self._frames) > self.maxsize:
            self.dead = True  # still over capacity post-collapse -- a dead peer, not a slow one

    def close(self) -> None:
        """Let a pending/future `get()` drain what's queued, then return `None` instead of
        blocking forever -- the writer loop's signal to stop (`ws.py`'s `Session.writer`)."""
        self._closing = True
        self._event.set()

    async def get(self) -> dict[str, Any] | None:
        while not self._frames:
            if self._closing:
                return None
            self._event.clear()
            await self._event.wait()
        return self._frames.popleft()
