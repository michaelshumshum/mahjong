import datetime as dt
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app import main
from app.db.models import GameRecord
from app.db.records import count_games_since
from app.status import LATENCY_WINDOW_SECONDS, ServerStats
from tests.tables import table_client
from tests.ws_frames import hello, msg


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_bot_latency_percentiles_cover_only_the_window() -> None:
    clock = _Clock()
    server = ServerStats(clock=clock)
    assert server.bot_decision_ms() is None
    server.record_bot_decision(9.0)  # ages out below
    clock.now += LATENCY_WINDOW_SECONDS + 1
    for ms in range(1, 101):
        server.record_bot_decision(ms / 1000)
    p50, p95 = server.bot_decision_ms() or (0, 0)
    assert p50 == pytest.approx(51)
    assert p95 == pytest.approx(96)


def test_loop_lag_is_the_worst_recent_tick_and_feeds_history() -> None:
    clock = _Clock()
    server = ServerStats(clock=clock)
    assert server.loop_lag_ms() == 0.0
    server.record_loop_lag(0.004)
    server.record_loop_lag(0.001)
    server.record_bot_decision(0.002)
    clock.now += 42
    server.add_history_point(players=3, tables=1)
    (point,) = server.history
    assert server.uptime_seconds() == 42
    assert (point.players, point.tables) == (3, 1)
    assert point.bot_p95_ms == pytest.approx(2)
    assert point.loop_lag_ms == pytest.approx(4)


async def test_count_games_since(session: AsyncSession) -> None:
    now = dt.datetime.now(dt.UTC)
    for age_hours in (1, 23, 25):
        session.add(
            GameRecord(
                engine_version="test",
                ruleset={},
                seed=0,
                action_log=[],
                players=[],
                result={},
                created_at=now - dt.timedelta(hours=age_hours),
            )
        )
    await session.commit()
    assert await count_games_since(session, now - dt.timedelta(days=1)) == 2


def test_status_counts_players_without_naming_tables() -> None:
    table_id = f"status-{uuid.uuid4()}"
    with (
        table_client(table_id, private=True) as client,
        client.websocket_connect(f"/ws?table={table_id}") as ws,
    ):
        ws.send_json(hello())
        ws.send_json(msg("join", {"seat": 0, "name": "Alice"}, id_="c-1"))
        assert ws.receive_json()["t"] == "seat_state"
        assert ws.receive_json()["t"] == "state_sync"
        assert ws.receive_json()["d"]["ok"] is True
        response = client.get("/status")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["players_online"] == 1
    assert body["tables_waiting"] == 1
    assert body["tables_playing"] == 0
    assert body["games_finished_24h"] is None  # no DATABASE_URL under test
    assert body["capacity_pct"] == 0  # 1 of the default 500
    assert table_id not in response.text
    assert "Alice" not in response.text


def test_status_reports_draining(monkeypatch: pytest.MonkeyPatch) -> None:
    with table_client(f"status-{uuid.uuid4()}") as client:
        monkeypatch.setattr(main.ws.registry(), "draining", True)
        assert client.get("/status").json()["status"] == "draining"
