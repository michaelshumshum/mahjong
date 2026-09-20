"""Bounded per-connection outbound queue (docs/02-protocol.md §9, docs/00-architecture.md
"Outbound backpressure"). Not `asyncio.Queue`: the drop-oldest/collapse-to-`state_sync` policy
needs to inspect and remove from the *middle* of the queue, which `asyncio.Queue` doesn't
support -- so this is a small `deque`-backed queue with its own wakeup event instead.

Overflow policy (both docs agree on the mechanism; docs/02-protocol.md §9 had drifted to a
different default number than docs/00-architecture.md's "Outbound backpressure" subsection --
reconciled to 64, this module's default, in the same change that added this file):

1. Drop the oldest queued frame that isn't `ack`/`error` (`_CRITICAL_TYPES`) -- a stale
   `draw`/`discard`/`turn` is superseded by a fresh snapshot anyway.
2. The instant anything is dropped, stop trying to catch the stream up: clear every remaining
   non-critical frame and ask the caller-supplied `resync` callback to enqueue a fresh
   `state_sync` in its place. `resync` re-enters `push()` (the caller is expected to run the
   real per-seat `seq` allocation through the same path every other frame uses -- see
   `app/table.py`'s `Table.publish_to_seat`/`Session._resync` -- rather than this module
   fabricating a seq number of its own, which could collide with whatever the real stream
   assigns next).
3. If the queue is still over capacity after that (every queued frame was critical, or stayed
   over capacity even after the collapse), the peer is dead, not just slow: `self.dead` flips
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
