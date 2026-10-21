"""`/ws` abuse caps (docs/protocol.md §11; env vars docs/infra.md §2): per-IP connection
count, spectators per table, per-connection inbound token bucket. Read once per ASGI startup
(`app/ws.py`'s `reset_registry`)."""

from __future__ import annotations

import ipaddress
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

type IpNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


@dataclass(frozen=True)
class WsLimits:
    max_connections_per_ip: int = 16
    max_spectators_per_table: int = 50
    msg_rate: float = 20.0
    msg_burst: int = 40
    trusted_proxies: tuple[IpNetwork, ...] = ()

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> WsLimits:
        """Unset or empty (the prod overlay's `${VAR:-}` passthrough) keeps the default."""
        env = os.environ if env is None else env
        default = cls()

        def get(key: str, fallback: float) -> str:
            return env.get(key) or str(fallback)

        return cls(
            max_connections_per_ip=int(
                get("WS_MAX_CONNECTIONS_PER_IP", default.max_connections_per_ip)
            ),
            max_spectators_per_table=int(
                get("WS_MAX_SPECTATORS_PER_TABLE", default.max_spectators_per_table)
            ),
            msg_rate=float(get("WS_MSG_RATE", default.msg_rate)),
            msg_burst=int(get("WS_MSG_BURST", default.msg_burst)),
            trusted_proxies=parse_trusted_proxies(env.get("TRUSTED_PROXY_IPS")),
        )


def parse_trusted_proxies(raw: str | None) -> tuple[IpNetwork, ...]:
    """`TRUSTED_PROXY_IPS` (uvicorn's `--forwarded-allow-ips` format): comma-separated IPs/CIDRs.
    Entries that aren't an IP/CIDR are skipped, `*` included: trusting every peer would let any
    client set `CF-Connecting-IP` (docs/infra.md §7)."""
    if raw is None:
        return ()
    nets: list[IpNetwork] = []
    for entry in (e.strip() for e in raw.split(",")):
        try:
            nets.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            continue
    return tuple(nets)


def _in_networks(ip: str, nets: tuple[IpNetwork, ...]) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in nets)


def client_ip(peer: str | None, headers: Mapping[str, str], trusted: tuple[IpNetwork, ...]) -> str:
    """The address a connection counts against. `peer` is the ASGI client host, already
    rewritten from `X-Forwarded-For` by uvicorn's `--proxy-headers` when the real peer is
    trusted. `CF-Connecting-IP` (Cloudflare Tunnel) wins only when `peer` itself is a trusted
    proxy, so a direct client can't spoof it."""
    if peer is None:
        return "unknown"
    if _in_networks(peer, trusted):
        cf = headers.get("cf-connecting-ip", "").strip()
        try:
            return str(ipaddress.ip_address(cf))
        except ValueError:
            pass
    return peer


class TokenBucket:
    """`burst` frames at once, refilled at `rate` per second."""

    def __init__(
        self, rate: float, burst: int, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._rate = rate
        self._burst = float(burst)
        self._tokens = float(burst)
        self._clock = clock
        self._last = clock()

    def take(self) -> bool:
        now = self._clock()
        self._tokens = min(self._burst, self._tokens + (now - self._last) * self._rate)
        self._last = now
        if self._tokens < 1.0:
            return False
        self._tokens -= 1.0
        return True


class IpConnectionCounter:
    """Open `/ws` connections per client IP, capped at `cap`."""

    def __init__(self, cap: int) -> None:
        self._cap = cap
        self._open: dict[str, int] = {}

    def acquire(self, ip: str) -> bool:
        n = self._open.get(ip, 0)
        if n >= self._cap:
            return False
        self._open[ip] = n + 1
        return True

    def release(self, ip: str) -> None:
        n = self._open.get(ip, 0) - 1
        if n > 0:
            self._open[ip] = n
        else:
            self._open.pop(ip, None)
