"""Per-client sliding-window rate limit for `POST /tables`, keyed on `app/limits.py`'s
`client_ip` (docs/architecture.md §8.3). In-process like everything else: one worker, no shared
store."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

__all__ = ["RateLimiter"]

_DEFAULT_MAX_TRACKED = 4096


class RateLimiter:
    """At most `limit` hits per `window_seconds` per key. Past `max_tracked` keys, every key
    whose window has emptied is dropped, so memory follows active clients, not every client
    ever seen."""

    def __init__(
        self,
        *,
        limit: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        max_tracked: int = _DEFAULT_MAX_TRACKED,
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._max_tracked = max_tracked
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        """Record a hit for `key` and say whether it's within the limit. A refused hit isn't
        recorded, so a client hammering past the limit doesn't extend its own lockout."""
        now = self._clock()
        hits = self._hits.get(key)
        if hits is None:
            if len(self._hits) >= self._max_tracked:
                self._prune(now)
            hits = self._hits[key] = deque()
        while hits and hits[0] <= now - self._window:
            hits.popleft()
        if len(hits) >= self._limit:
            return False
        hits.append(now)
        return True

    def retry_after(self, key: str) -> int:
        """Whole seconds until `key`'s oldest hit leaves the window."""
        hits = self._hits.get(key)
        if not hits:
            return 0
        return max(1, int(hits[0] + self._window - self._clock()) + 1)

    def _prune(self, now: float) -> None:
        cutoff = now - self._window
        for key in [k for k, hits in self._hits.items() if not hits or hits[-1] <= cutoff]:
            del self._hits[key]

    def __len__(self) -> int:
        return len(self._hits)
