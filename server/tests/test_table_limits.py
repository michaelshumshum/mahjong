"""Table creation and retention limits (docs/architecture.md §8.3): tables come only from
`POST /tables`, unstarted and finished tables are reaped, live tables are capped, and
`POST /tables` is rate limited per client IP."""

from __future__ import annotations

import asyncio
import dataclasses

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import ws
from app.main import app
from app.rate_limit import RateLimiter, client_ip, parse_trusted_proxies
from app.registry import TableLimitError, TableRegistry
from mahjong_core.actions import Pass
from mahjong_core.config import DEFAULT_RULESET
from mahjong_core.state import Phase


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_ws_connect_to_unknown_table_is_refused_and_creates_nothing() -> None:
    with TestClient(app) as client:
        before = len(ws.registry())
        with client.websocket_connect("/ws?table=ZZZZZZ") as conn:
            frame = conn.receive_json()
            assert frame["t"] == "error"
            assert frame["d"]["code"] == "table_closed"
            with pytest.raises(WebSocketDisconnect):
                conn.receive_json()
        assert ws.registry().get("ZZZZZZ") is None
        assert len(ws.registry()) == before


async def test_unstarted_table_is_reaped_after_ttl() -> None:
    clock = FakeClock()
    registry = TableRegistry(clock=clock, unstarted_ttl_seconds=600)
    table = registry.get_or_create("idle", DEFAULT_RULESET, seed=1)
    task = registry._tasks["idle"]

    clock.now += 599
    assert registry.reap() == []
    assert registry.get("idle") is table

    clock.now += 2
    assert registry.reap() == ["idle"]
    assert registry.get("idle") is None
    assert table.closed
    await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=2.0)
    assert task.done()
    assert not registry.is_running("idle")
    assert len(registry) == 0


async def test_unstarted_table_with_a_connected_human_is_not_reaped() -> None:
    clock = FakeClock()
    registry = TableRegistry(clock=clock, unstarted_ttl_seconds=600)
    table = registry.get_or_create("waiting", DEFAULT_RULESET, seed=1)
    table.join("s-0", lambda seq, wire: None, seat=0)

    clock.now += 601
    assert registry.reap() == []

    binding = table.seat_bindings[0]
    assert binding is not None
    binding.status = "disconnected"
    assert registry.reap() == ["waiting"]


async def test_finished_table_is_reaped_after_grace() -> None:
    clock = FakeClock()
    registry = TableRegistry(clock=clock, finished_ttl_seconds=300)
    table = registry.get_or_create("done", DEFAULT_RULESET, seed=1, require_ready=False)
    table.state = dataclasses.replace(table.state, phase=Phase.GAME_OVER, claim_window=None)
    table.submit(0, Pass(window_id=0, seat=0))
    async with asyncio.timeout(2.0):
        while registry.is_running("done"):
            await asyncio.sleep(0.01)

    clock.now += 299
    assert registry.reap() == []
    assert registry.get("done") is table  # still reconnectable within the grace

    clock.now += 2
    assert registry.reap() == ["done"]
    assert registry.get("done") is None


async def test_closed_id_set_is_bounded() -> None:
    clock = FakeClock()
    registry = TableRegistry(clock=clock, unstarted_ttl_seconds=0, closed_ids_cap=3)
    for i in range(5):
        registry.get_or_create(f"t{i}", DEFAULT_RULESET, seed=1)
    clock.now += 1
    assert sorted(registry.reap()) == [f"t{i}" for i in range(5)]
    assert sum(registry.is_closed(f"t{i}") for i in range(5)) == 3


async def test_registry_refuses_past_max_tables() -> None:
    registry = TableRegistry(max_tables=2)
    registry.get_or_create("a", DEFAULT_RULESET, seed=1)
    registry.get_or_create("b", DEFAULT_RULESET, seed=1)
    assert registry.get_or_create("a", DEFAULT_RULESET) is registry.get("a")  # existing id is fine
    with pytest.raises(TableLimitError):
        registry.get_or_create("c", DEFAULT_RULESET, seed=1)
    assert registry.get("c") is None


def test_post_tables_returns_503_past_max_tables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_TABLES", "2")
    with TestClient(app) as client:
        assert client.post("/tables", json={}).status_code == 200
        assert client.post("/tables", json={}).status_code == 200
        response = client.post("/tables", json={})
        assert response.status_code == 503
        assert len(ws.registry()) == 2


def test_post_tables_is_rate_limited_per_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TABLE_CREATE_RATE_LIMIT", "3")
    with TestClient(app, client=("203.0.113.5", 5000)) as client:
        for _ in range(3):
            assert client.post("/tables", json={}).status_code == 200
        response = client.post("/tables", json={})
        assert response.status_code == 429
        assert "retry-after" in response.headers
        # an untrusted peer can't dodge the limit by spoofing the tunnel header
        spoofed = client.post("/tables", json={}, headers={"CF-Connecting-IP": "198.51.100.9"})
        assert spoofed.status_code == 429
    assert len(ws.registry()) == 3


def test_post_tables_trusts_cf_connecting_ip_only_from_a_trusted_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TABLE_CREATE_RATE_LIMIT", "1")
    monkeypatch.setenv("TRUSTED_PROXY_IPS", "172.17.0.0/16")
    with TestClient(app, client=("172.17.0.1", 5000)) as client:
        first = {"CF-Connecting-IP": "198.51.100.1"}
        second = {"CF-Connecting-IP": "198.51.100.2"}
        assert client.post("/tables", json={}, headers=first).status_code == 200
        assert client.post("/tables", json={}, headers=first).status_code == 429
        assert client.post("/tables", json={}, headers=second).status_code == 200


def test_rate_limiter_window_slides() -> None:
    clock = FakeClock()
    limiter = RateLimiter(limit=2, window_seconds=60, clock=clock)
    assert limiter.allow("a")
    clock.now += 30
    assert limiter.allow("a")
    assert not limiter.allow("a")
    assert limiter.allow("b")
    clock.now += 31  # first hit has left the window
    assert limiter.allow("a")
    assert not limiter.allow("a")


def test_rate_limiter_forgets_idle_clients() -> None:
    clock = FakeClock()
    limiter = RateLimiter(limit=1, window_seconds=60, clock=clock, max_tracked=2)
    for ip in ("a", "b", "c"):
        assert limiter.allow(ip)
    clock.now += 61
    assert limiter.allow("d")
    assert len(limiter) <= 2


def test_client_ip_ignores_header_from_untrusted_peer() -> None:
    trusted = parse_trusted_proxies("10.0.0.1, 172.17.0.0/16, not-an-ip")
    assert client_ip("10.0.0.1", "198.51.100.7", trusted) == "198.51.100.7"
    assert client_ip("172.17.3.4", "198.51.100.7", trusted) == "198.51.100.7"
    assert client_ip("203.0.113.5", "198.51.100.7", trusted) == "203.0.113.5"
    assert client_ip("10.0.0.1", None, trusted) == "10.0.0.1"
    assert client_ip("10.0.0.1", "garbage", trusted) == "10.0.0.1"
    assert client_ip(None, "198.51.100.7", trusted) == "unknown"
