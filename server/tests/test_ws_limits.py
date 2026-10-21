"""`/ws` abuse caps (docs/protocol.md §11): per-IP connections, spectators per table,
per-connection inbound rate, and the bounded table inbox."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from starlette.websockets import WebSocketDisconnect

from app.limits import TokenBucket, WsLimits, client_ip, parse_trusted_proxies
from app.table import INBOX_COMMAND_LIMIT, Table
from app.ws import get_table
from mahjong_core.actions import Discard
from mahjong_core.config import DEFAULT_RULESET
from mahjong_core.tiles import TileId
from tests.tables import table_client
from tests.ws_frames import msg


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_token_bucket_allows_burst_then_refills_at_rate() -> None:
    clock = _FakeClock()
    bucket = TokenBucket(rate=2.0, burst=3, clock=clock)
    assert [bucket.take() for _ in range(4)] == [True, True, True, False]
    clock.now = 0.5  # one token back at 2/s
    assert bucket.take() is True
    assert bucket.take() is False
    clock.now = 100.0  # refill caps at burst
    assert [bucket.take() for _ in range(4)] == [True, True, True, False]


def test_client_ip_trusts_cf_header_only_from_trusted_proxy() -> None:
    trusted = parse_trusted_proxies("10.0.0.0/8, 127.0.0.1")
    headers = {"cf-connecting-ip": "203.0.113.7"}
    assert client_ip("127.0.0.1", headers, trusted) == "203.0.113.7"
    assert client_ip("10.1.2.3", headers, trusted) == "203.0.113.7"
    # spoofed header straight from an untrusted peer
    assert client_ip("198.51.100.1", headers, trusted) == "198.51.100.1"
    # no TRUSTED_PROXY_IPS at all: never trusted
    assert client_ip("127.0.0.1", headers, parse_trusted_proxies(None)) == "127.0.0.1"
    # garbage header from a trusted proxy: fall back to the peer
    assert client_ip("127.0.0.1", {"cf-connecting-ip": "nope"}, trusted) == "127.0.0.1"
    assert client_ip("127.0.0.1", {}, trusted) == "127.0.0.1"
    assert client_ip(None, headers, trusted) == "unknown"


def test_parse_trusted_proxies_wildcard_and_junk() -> None:
    assert parse_trusted_proxies("*") == ()
    assert parse_trusted_proxies("") == ()
    assert parse_trusted_proxies("not-an-ip, 127.0.0.1") == parse_trusted_proxies("127.0.0.1")


def test_ws_limits_from_env_defaults_and_overrides() -> None:
    limits = WsLimits.from_env({})
    assert limits.max_connections_per_ip == 16
    assert limits.max_spectators_per_table == 50
    assert limits.msg_rate == 20.0
    assert limits.msg_burst == 40
    limits = WsLimits.from_env({"WS_MAX_CONNECTIONS_PER_IP": "3", "WS_MSG_RATE": "5"})
    assert limits.max_connections_per_ip == 3
    assert limits.msg_rate == 5.0
    assert WsLimits.from_env({"WS_MSG_BURST": ""}).msg_burst == 40


@pytest.fixture
def tight_limits(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # read on ASGI startup (ws.reset_registry), so set before TestClient(app) enters
    monkeypatch.setenv("WS_MAX_CONNECTIONS_PER_IP", "2")
    monkeypatch.setenv("WS_MAX_SPECTATORS_PER_TABLE", "1")
    monkeypatch.setenv("WS_MSG_RATE", "0.001")
    monkeypatch.setenv("WS_MSG_BURST", "3")
    yield


@pytest.mark.usefixtures("tight_limits")
def test_per_ip_connection_cap_refuses_then_frees_slot() -> None:
    table_id = f"limits-{uuid.uuid4()}"
    with table_client(table_id) as client:
        with (
            client.websocket_connect(f"/ws?table={table_id}"),
            client.websocket_connect(f"/ws?table={table_id}"),
        ):
            with (
                pytest.raises(WebSocketDisconnect) as exc,
                client.websocket_connect(f"/ws?table={table_id}"),
            ):
                pass
            assert exc.value.code == 1008
        # both closed: slots released
        with client.websocket_connect(f"/ws?table={table_id}") as ws:
            ws.send_json(msg("ping", {"t0": 1}))
            assert ws.receive_json()["t"] == "pong"


@pytest.mark.usefixtures("tight_limits")
def test_spectator_cap_refuses_with_spectators_full() -> None:
    table_id = f"limits-{uuid.uuid4()}"
    with (
        table_client(table_id) as client,
        client.websocket_connect(f"/ws?table={table_id}&spectate=true") as first,
    ):
        assert first.receive_json()["t"] == "state_sync"
        with client.websocket_connect(f"/ws?table={table_id}&spectate=true") as second:
            frame = second.receive_json()
            assert frame["t"] == "error"
            assert frame["d"]["code"] == "spectators_full"
            with pytest.raises(WebSocketDisconnect) as exc:
                second.receive_json()
            assert exc.value.code == 1013
        table = get_table(table_id)
        assert table is not None
        assert len(table.spectators) == 1


@pytest.mark.usefixtures("tight_limits")
def test_inbound_rate_limit_closes_socket() -> None:
    table_id = f"limits-{uuid.uuid4()}"
    with table_client(table_id) as client, client.websocket_connect(f"/ws?table={table_id}") as ws:
        for t0 in range(5):
            ws.send_json(msg("ping", {"t0": t0}))
        # burst of 3 answered, the 4th frame closes the socket
        assert [ws.receive_json()["d"]["t0"] for _ in range(3)] == [0, 1, 2]
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1008


def test_table_inbox_drops_commands_past_limit() -> None:
    table = Table("inbox", DEFAULT_RULESET, game_seed=1)
    for _ in range(INBOX_COMMAND_LIMIT + 10):
        table.submit(0, Discard(tile_id=TileId(0)))
    assert table.inbox.qsize() == INBOX_COMMAND_LIMIT
