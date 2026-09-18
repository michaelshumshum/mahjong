"""Chat (M5, docs/02-protocol.md §2/§3 `chat`) -- rebroadcast, the rate limit, the length cap,
and the seat-binding guard, driven over real WS connections the same
`fastapi.testclient` style `tests/test_ws_gameplay.py` established.

`Room.send_chat`'s rate limit is time-based (a 10s sliding window, `app/room.py`'s
`_CHAT_RATE_WINDOW_MS`) -- too long to actually sleep through in a test, so the
window-elapsed assertion below drives the clock directly via `send_chat`'s own `now_ms`
param, this project's established no-real-`sleep()` convention (see e.g.
`tests/test_disconnect_bot_handover.py`'s module docstring for the zero-window variant of the
same idea; chat's window can't be zeroed the same way without defeating the thing being
tested, so the clock itself is the injected value here instead).
"""

from __future__ import annotations

import itertools
import time
import uuid
from typing import Any

from fastapi.testclient import TestClient

from app.main import app
from app.room import _CHAT_RATE_LIMIT, _CHAT_RATE_WINDOW_MS
from app.ws import get_room

_id_gen = itertools.count(1)


def _ts() -> int:
    return time.time_ns() // 1_000_000


def _msg(t: str, d: dict[str, object], *, id_: str | None = None) -> dict[str, object]:
    frame: dict[str, object] = {"v": 1, "t": t, "ts": _ts(), "d": d}
    if id_ is not None:
        frame["id"] = id_
    return frame


def _next_id() -> str:
    return f"c-{next(_id_gen)}"


def _join_four(wss: list[Any]) -> None:
    for seat, ws in enumerate(wss):
        ws.send_json(_msg("join", {"seat": seat, "name": f"Player{seat}"}, id_=_next_id()))
        for s in range(seat + 1):
            frame = wss[s].receive_json()
            assert frame["t"] == "seat_state"
        assert ws.receive_json()["t"] == "state_sync"
        ack = ws.receive_json()
        assert ack["t"] == "ack" and ack["d"]["ok"] is True


def test_chat_rebroadcast_reaches_every_seat_including_sender() -> None:
    room_id = f"chat-{uuid.uuid4()}"
    with (
        TestClient(app) as client,
        client.websocket_connect(f"/ws?room={room_id}") as ws0,
        client.websocket_connect(f"/ws?room={room_id}") as ws1,
        client.websocket_connect(f"/ws?room={room_id}") as ws2,
        client.websocket_connect(f"/ws?room={room_id}") as ws3,
    ):
        wss = [ws0, ws1, ws2, ws3]
        _join_four(wss)

        wss[1].send_json(_msg("chat", {"text": "gg"}, id_=_next_id()))
        for ws in wss:
            frame = ws.receive_json()
            assert frame["t"] == "chat"
            assert frame["d"] == {"seat": 1, "text": "gg", "name": "Player1"}
        ack = wss[1].receive_json()
        assert ack["t"] == "ack" and ack["d"]["ok"] is True


def test_chat_over_length_is_truncated_not_rejected() -> None:
    room_id = f"chat-len-{uuid.uuid4()}"
    with (
        TestClient(app) as client,
        client.websocket_connect(f"/ws?room={room_id}") as ws0,
        client.websocket_connect(f"/ws?room={room_id}") as ws1,
        client.websocket_connect(f"/ws?room={room_id}") as ws2,
        client.websocket_connect(f"/ws?room={room_id}") as ws3,
    ):
        wss = [ws0, ws1, ws2, ws3]
        _join_four(wss)

        long_text = "x" * 500
        wss[0].send_json(_msg("chat", {"text": long_text}, id_=_next_id()))
        for ws in wss:
            frame = ws.receive_json()
            assert frame["t"] == "chat"
            assert frame["d"]["text"] == "x" * 200
        ack = wss[0].receive_json()
        assert ack["t"] == "ack" and ack["d"]["ok"] is True


def test_chat_rate_limit_drops_silently_then_recovers_after_window() -> None:
    room_id = f"chat-rate-{uuid.uuid4()}"
    with (
        TestClient(app) as client,
        client.websocket_connect(f"/ws?room={room_id}") as ws0,
        client.websocket_connect(f"/ws?room={room_id}") as ws1,
        client.websocket_connect(f"/ws?room={room_id}") as ws2,
        client.websocket_connect(f"/ws?room={room_id}") as ws3,
    ):
        wss = [ws0, ws1, ws2, ws3]
        _join_four(wss)
        room = get_room(room_id)
        assert room is not None

        # exhaust the window over real WS traffic -- every one of these is legitimately
        # under the limit, so each gets a real broadcast + ok:true ack.
        for i in range(_CHAT_RATE_LIMIT):
            wss[2].send_json(_msg("chat", {"text": f"m{i}"}, id_=_next_id()))
            for ws in wss:
                frame = ws.receive_json()
                assert frame["t"] == "chat" and frame["d"]["text"] == f"m{i}"
            ack = wss[2].receive_json()
            assert ack["t"] == "ack" and ack["d"]["ok"] is True

        # one more, still inside the window: ack is still ok:true (accepted for processing,
        # per _dispatch's own contract) but nothing is broadcast -- checked white-box via
        # the ring buffer, since there is no frame to block-read for an absence. Seat 2's
        # own ring still grows by exactly one (the ack itself, sender-only); every other
        # seat's ring -- and seat 2's *chat* count -- must not move at all.
        before = {seat: len(room.ring[seat]) for seat in range(4)}
        wss[2].send_json(_msg("chat", {"text": "over the limit"}, id_=_next_id()))
        ack = wss[2].receive_json()
        assert ack["t"] == "ack" and ack["d"]["ok"] is True
        after = {seat: len(room.ring[seat]) for seat in range(4)}
        assert after == {**before, 2: before[2] + 1}

        # jump the clock past the window (this seat's own bookkeeping only) -- back under
        # the limit, a fresh message broadcasts normally again.
        future = _ts() + _CHAT_RATE_WINDOW_MS + 1_000
        room.send_chat(2, "back under the limit", now_ms=future)
        frame = wss[3].receive_json()
        assert frame["t"] == "chat"
        assert frame["d"] == {"seat": 2, "text": "back under the limit", "name": "Player2"}


def test_chat_from_unjoined_spectator_is_rejected_not_spoofed() -> None:
    room_id = f"chat-spectator-{uuid.uuid4()}"
    with (
        TestClient(app) as client,
        client.websocket_connect(f"/ws?room={room_id}") as ws0,
        client.websocket_connect(f"/ws?room={room_id}") as ws1,
        client.websocket_connect(f"/ws?room={room_id}") as ws2,
        client.websocket_connect(f"/ws?room={room_id}") as spectator,
    ):
        wss = [ws0, ws1, ws2]
        for seat, ws in enumerate(wss):
            ws.send_json(_msg("join", {"seat": seat}, id_=_next_id()))
            for s in range(seat + 1):
                assert wss[s].receive_json()["t"] == "seat_state"
            assert ws.receive_json()["t"] == "state_sync"
            ack = ws.receive_json()
            assert ack["t"] == "ack" and ack["d"]["ok"] is True

        room = get_room(room_id)
        assert room is not None
        before = {seat: len(room.ring[seat]) for seat in range(4)}

        # never joined -- same seat-binding guard `_dispatch` already applies to every
        # other post-join intent (docs/02-protocol.md §2's "join is the only way to occupy
        # a seat; a socket that never sends it is a spectator").
        spectator.send_json(_msg("chat", {"text": "spoofed"}, id_=_next_id()))
        frame = spectator.receive_json()
        assert frame["t"] == "error"
        assert frame["d"]["code"] == "not_joined"

        after = {seat: len(room.ring[seat]) for seat in range(4)}
        assert before == after
