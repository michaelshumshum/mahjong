import uuid

from fastapi.testclient import TestClient

from app.main import app


def test_healthz() -> None:
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200


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
