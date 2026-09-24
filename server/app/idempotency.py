"""Per-seat idempotency cache: last 256 client `id`s, LRU-evicted, scoped to the seat binding
(survives reconnect) rather than the socket.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

_MAXLEN = 256


class IdempotencyCache:
    def __init__(self, maxlen: int = _MAXLEN) -> None:
        self._maxlen = maxlen
        self._entries: OrderedDict[str, tuple[Any, bool, str | None]] = OrderedDict()

    def check(self, id_: str, payload: Any) -> tuple[bool, bool, str | None]:
        """Returns `(is_retry, ok, error)`. If `is_retry`, don't reapply the action or call
        `record()` -- `ok`/`error` is the outcome to re-ack. Otherwise process normally, then
        call `record()`.
        """
        seen = self._entries.get(id_)
        if seen is None:
            return False, True, None
        seen_payload, ok, error = seen
        if seen_payload == payload:
            self._entries.move_to_end(id_)
            return True, ok, error
        return True, False, "id_conflict"

    def record(self, id_: str, payload: Any, *, ok: bool, error: str | None = None) -> None:
        self._entries[id_] = (payload, ok, error)
        self._entries.move_to_end(id_)
        if len(self._entries) > self._maxlen:
            self._entries.popitem(last=False)
