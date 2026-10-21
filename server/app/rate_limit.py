"""Per-client sliding-window rate limit for `POST /tables`, and the client-IP rule it keys on
(docs/architecture.md §8.3). In-process like everything else: one worker, no shared store."""

from __future__ import annotations

import ipaddress
import time
from collections import deque
from collections.abc import Callable, Sequence

__all__ = ["ProxyNetwork", "RateLimiter", "client_ip", "parse_trusted_proxies"]

type ProxyNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

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


def parse_trusted_proxies(raw: str) -> tuple[ProxyNetwork, ...]:
    """`TRUSTED_PROXY_IPS`: comma-separated IPs/CIDRs. An unparseable entry (`*` included) is
    skipped, trusting nothing extra."""
    networks: list[ProxyNetwork] = []
    for entry in raw.split(","):
        try:
            networks.append(ipaddress.ip_network(entry.strip(), strict=False))
        except ValueError:
            continue
    return tuple(networks)


def _is_trusted(peer: str, trusted: Sequence[ProxyNetwork]) -> bool:
    try:
        address = ipaddress.ip_address(peer)
    except ValueError:
        return False
    return any(address in network for network in trusted)


def client_ip(
    peer: str | None, cf_connecting_ip: str | None, trusted: Sequence[ProxyNetwork]
) -> str:
    """The rate-limit key for one request. `CF-Connecting-IP` counts only when the TCP peer is
    a trusted proxy (the tunnel connector); from anyone else it's client-controlled. With
    uvicorn's `--proxy-headers`, `peer` is already the forwarded client, which is never trusted,
    so the header is ignored and that address is used."""
    if peer is None:
        return "unknown"
    if cf_connecting_ip and _is_trusted(peer, trusted):
        try:
            return str(ipaddress.ip_address(cf_connecting_ip.strip()))
        except ValueError:
            pass
    return peer
