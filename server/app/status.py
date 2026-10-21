"""In-process load and performance numbers behind `GET /status` (docs/infra.md §8): bot decision
latency, event-loop lag and a 24h history ring. Nothing persists -- a restart starts empty, like
the registry, and `app/main.py`'s `lifespan` swaps in a fresh `ServerStats` per startup.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from app.clock import now_ms

__all__ = ["LoadPoint", "ServerStats", "reset_stats", "stats"]

LATENCY_WINDOW_SECONDS = 300.0
# bounds memory under load; past it the window is just the most recent decisions
_LATENCY_SAMPLE_CAP = 4096
LAG_TICK_SECONDS = 1.0
_LAG_SAMPLES = 60
HISTORY_INTERVAL_SECONDS = 300.0
HISTORY_POINTS = 288  # 24h at HISTORY_INTERVAL_SECONDS


@dataclass(frozen=True, slots=True)
class LoadPoint:
    ts: int
    players: int
    tables: int
    bot_p95_ms: float | None
    loop_lag_ms: float


def _percentile(sorted_samples: list[float], q: float) -> float:
    return sorted_samples[min(len(sorted_samples) - 1, int(q * len(sorted_samples)))]


class ServerStats:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._started_at = clock()
        self._bot_ms: deque[tuple[float, float]] = deque(maxlen=_LATENCY_SAMPLE_CAP)
        self._lag_ms: deque[float] = deque(maxlen=_LAG_SAMPLES)
        self.history: deque[LoadPoint] = deque(maxlen=HISTORY_POINTS)

    def uptime_seconds(self) -> int:
        return int(self._clock() - self._started_at)

    def record_bot_decision(self, seconds: float) -> None:
        """Submit-to-answer time of one bot pool job, queueing included, think delay excluded."""
        self._bot_ms.append((self._clock(), seconds * 1000))

    def bot_decision_ms(self) -> tuple[float, float] | None:
        """(p50, p95) over the last `LATENCY_WINDOW_SECONDS`; `None` with no decision in it."""
        cutoff = self._clock() - LATENCY_WINDOW_SECONDS
        samples = sorted(ms for t, ms in self._bot_ms if t >= cutoff)
        if not samples:
            return None
        return _percentile(samples, 0.5), _percentile(samples, 0.95)

    def record_loop_lag(self, seconds: float) -> None:
        self._lag_ms.append(seconds * 1000)

    def loop_lag_ms(self) -> float:
        """Worst lag over the last `_LAG_SAMPLES` sampler ticks."""
        return max(self._lag_ms, default=0.0)

    def add_history_point(self, players: int, tables: int) -> None:
        bot = self.bot_decision_ms()
        self.history.append(
            LoadPoint(
                ts=now_ms(),
                players=players,
                tables=tables,
                bot_p95_ms=bot[1] if bot is not None else None,
                loop_lag_ms=self.loop_lag_ms(),
            )
        )

    async def run_sampler(self, load: Callable[[], tuple[int, int]]) -> None:
        """Until cancelled: every `LAG_TICK_SECONDS`, record how late the sleep woke (event-loop
        lag); every `HISTORY_INTERVAL_SECONDS`, append a history point from `load()`'s
        `(players, tables)`. The first point lands on the first tick."""
        loop = asyncio.get_running_loop()
        next_point = loop.time()
        while True:
            before = loop.time()
            await asyncio.sleep(LAG_TICK_SECONDS)
            woke = loop.time()
            self.record_loop_lag(max(0.0, woke - before - LAG_TICK_SECONDS))
            if woke >= next_point:
                self.add_history_point(*load())
                next_point = woke + HISTORY_INTERVAL_SECONDS


_stats = ServerStats()


def stats() -> ServerStats:
    return _stats


def reset_stats() -> ServerStats:
    global _stats
    _stats = ServerStats()
    return _stats
