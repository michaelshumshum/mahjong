"""Per-seat idempotency cache: last 256 client `id`s, LRU-evicted, scoped to the seat binding
(survives reconnect) rather than the socket.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from typing import Any

_MAXLEN = 256


def _digest(payload: Any) -> bytes:
    # a digest, not the payload: retaining 256 client-controlled payloads per seat is a memory dos
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).digest()


class IdempotencyCache:
    def __init__(self, maxlen: int = _MAXLEN) -> None:
        self._maxlen = maxlen
        self._entries: OrderedDict[str, tuple[bytes, bool, str | None]] = OrderedDict()

    def check(self, id_: str, payload: Any) -> tuple[bool, bool, str | None]:
        """Returns `(is_retry, ok, error)`. If `is_retry`, don't reapply the action or call
        `record()` -- `ok`/`error` is the outcome to re-ack. Otherwise process normally, then
        call `record()`.
        """
        seen = self._entries.get(id_)
        if seen is None:
            return False, True, None
        seen_digest, ok, error = seen
        if seen_digest == _digest(payload):
            self._entries.move_to_end(id_)
            return True, ok, error
        return True, False, "id_conflict"

    def record(self, id_: str, payload: Any, *, ok: bool, error: str | None = None) -> None:
        self._entries[id_] = (_digest(payload), ok, error)
        self._entries.move_to_end(id_)
        if len(self._entries) > self._maxlen:
            self._entries.popitem(last=False)
