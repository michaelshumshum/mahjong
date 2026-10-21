import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app
from app.ws import MAX_FRAME_BYTES, get_table


def test_client_cannot_choose_game_seed() -> None:
    # a client-chosen seed reveals every wall and hand via a local new_game(ruleset, seed)
    with (
        TestClient(app) as client,
        client.websocket_connect("/ws?table=seed-probe&seed=42") as ws,
    ):
        ws.send_json({"v": 1, "t": "ping", "ts": 1000, "d": {"t0": 1}})
        assert ws.receive_json()["t"] == "pong"
        table = get_table("seed-probe")
        assert table is not None
        assert table.state.game_seed != 42


def test_hello_then_ping_pong() -> None:
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"v": 1, "t": "hello", "ts": 1000, "d": {"client_version": "1.0.0"}})

        ws.send_json({"v": 1, "t": "ping", "ts": 1001, "id": "c-1", "d": {"t0": 999}})
        first = ws.receive_json()
        assert first["t"] == "pong"
        assert first["d"]["t0"] == 999
        assert first["seq"] == 1

        ws.send_json({"v": 1, "t": "ping", "ts": 1002, "id": "c-2", "d": {"t0": 1234}})
        second = ws.receive_json()
        assert second["t"] == "pong"
        assert second["d"]["t0"] == 1234
        assert second["seq"] == 2


def test_oversized_frame_closes_with_1009() -> None:
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text("x" * (MAX_FRAME_BYTES + 1))
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1009


def test_frame_at_the_size_limit_is_parsed() -> None:
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        frame = json.dumps({"v": 1, "t": "ping", "ts": 1000, "d": {"t0": 1}})
        ws.send_text(frame + " " * (MAX_FRAME_BYTES - len(frame)))
        assert ws.receive_json()["t"] == "pong"


def test_malformed_frame_returns_error_and_does_not_crash_server() -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_text("not json")
            frame = ws.receive_json()
            assert frame["t"] == "error"
            assert frame["d"]["code"] == "bad_frame"

            try:
                ws.receive_json()
            except WebSocketDisconnect:
                pass

        # server survives a malformed frame: a fresh connection still works
        with client.websocket_connect("/ws") as ws2:
            ws2.send_json({"v": 1, "t": "ping", "ts": 1000, "d": {"t0": 1}})
            pong = ws2.receive_json()
            assert pong["t"] == "pong"
            assert pong["d"]["t0"] == 1
            assert pong["seq"] == 1
