"""WS endpoint speaking the envelope protocol (docs/02-protocol.md §1)."""

import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter, ValidationError

from app.protocol import AnyMessage, Error, ErrorPayload, Hello, Ping, Pong, PongPayload

router = APIRouter()

_adapter: TypeAdapter[object] = TypeAdapter(AnyMessage)


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    # M0 stub: no ticket/auth yet (docs/00-architecture.md §2.1, M5 scope) —
    # accept every connection unconditionally.
    await websocket.accept()
    # per-connection counter, not per-seat: real per-seat seq discipline
    # (docs/02-protocol.md §1, D1) arrives with the Room actor in M3.
    seq = 0

    while True:
        try:
            raw = await websocket.receive_text()
        except WebSocketDisconnect:
            return

        try:
            message = _adapter.validate_json(raw)
        except ValidationError as exc:
            seq += 1
            error = Error(
                ts=_now_ms(),
                seq=seq,
                d=ErrorPayload(code="bad_frame", message=str(exc)),
            )
            await websocket.send_text(error.model_dump_json())
            await websocket.close()
            return

        if isinstance(message, Hello):
            continue
        elif isinstance(message, Ping):
            seq += 1
            pong = Pong(
                ts=_now_ms(),
                seq=seq,
                d=PongPayload(t0=message.d.t0, t1=_now_ms()),
            )
            await websocket.send_text(pong.model_dump_json())
        # Pong/Error are server->client only; a client sending one is ignored,
        # not treated as malformed.
