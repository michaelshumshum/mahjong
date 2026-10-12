import uuid

import pytest
from fastapi.testclient import TestClient

from app import main, ws
from app.main import app


def test_healthz() -> None:
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200


def test_unusable_weights_degrade_instead_of_refusing_to_start(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """docs/bots.md §2: the api serves (`/healthz` stays 2xx for the web client's gate) but reports
    `degraded`, and Expert/Impossible practice seats fall back to the default tier."""
    monkeypatch.setattr(main, "_learned_weights_problem", None)  # restored after the test
    monkeypatch.setattr(main, "weights_problem", lambda: "learned.npz: FileNotFoundError")
    with caplog.at_level("ERROR", logger="app.main"), TestClient(app) as client:
        health = client.get("/healthz")
        created = client.post(
            "/tables", json={"practice": True, "bot_tiers": {"1": "T4", "2": "ORACLE", "3": "T1"}}
        )
        table = ws.registry().get(created.json()["table_id"])
    assert "learned weights unusable, ORACLE/T4 disabled" in caplog.text
    assert health.status_code == 200
    assert health.json() == {
        "status": "degraded",
        "disabled_tiers": ["ORACLE", "T4"],
        "reason": "learned.npz: FileNotFoundError",
    }
    assert created.status_code == 200
    assert table is not None
    assert [table._effective_bot_tier(s) for s in (1, 2, 3)] == ["T2", "T2", "T1"]


def _msg(t: str, d: dict[str, object], *, id_: str | None = None) -> dict[str, object]:
    frame: dict[str, object] = {"v": 1, "t": t, "ts": 0, "d": d}
    if id_ is not None:
        frame["id"] = id_
    return frame


def test_tables_lists_a_joined_table() -> None:
    table_id = f"browse-{uuid.uuid4()}"
    with TestClient(app) as client:
        assert client.get("/tables").json() == {"tables": []}
        with client.websocket_connect(f"/ws?table={table_id}") as ws:
            ws.send_json(_msg("hello", {"client_version": "test"}))
            ws.send_json(_msg("join", {"seat": 1, "name": "Alice"}, id_="c-1"))
            assert ws.receive_json()["t"] == "seat_state"
            assert ws.receive_json()["t"] == "state_sync"
            assert ws.receive_json()["d"]["ok"] is True

            response = client.get("/tables", headers={"Origin": "http://localhost:5173"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.json() == {
        "tables": [
            {
                "id": table_id,
                "status": "open",
                "hand_no": 1,
                "seats": [
                    {"status": "empty", "name": None},
                    {"status": "connected", "name": "Alice"},
                    {"status": "empty", "name": None},
                    {"status": "empty", "name": None},
                ],
            }
        ]
    }
