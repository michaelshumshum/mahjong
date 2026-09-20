"""Per-seat idempotency cache (docs/02-protocol.md §1 "Idempotency"): the last 256 client
`id`s, LRU-evicted, scoped to the seat binding rather than the socket -- a reconnect (a later
sub-task) inherits the same history since `app/table.py`'s `SeatBinding` survives across
sockets, unlike a `Session`.

A repeated `id` with the *same* payload is a genuine retry (e.g. the client resent after a
dropped ack): return the original outcome, never reapply the action. A repeated `id` with a
*different* payload is a client bug, not a retry: reject it, and apply neither the old nor the
new payload as if it were the other.
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
        """Returns `(is_retry, ok, error)`. `is_retry=True` means `id_` was already seen --
        `ok`/`error` are the outcome to re-ack; the caller must not reapply the action, and
        must not call `record()`. `is_retry=False` means this is a fresh id: the caller should
        process it normally and then call `record()` with the real outcome.
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
