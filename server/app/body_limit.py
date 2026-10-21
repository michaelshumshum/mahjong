"""Pure ASGI middleware capping an HTTP request body at `MAX_REQUEST_BODY_BYTES`
(docs/protocol.md §10). A declared `Content-Length` over the cap gets a 413 before anything is
read; a chunked body without one is counted as it streams and fails with the same 413 the moment
it crosses the cap, so the app never buffers more than the cap plus one chunk."""

from __future__ import annotations

from starlette.exceptions import HTTPException
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

__all__ = ["MAX_REQUEST_BODY_BYTES", "BodySizeLimitMiddleware"]

# a full custom RuleSet body is ~1-2 KB
MAX_REQUEST_BODY_BYTES = 16 * 1024

_TOO_LARGE = 413


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int = MAX_REQUEST_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = _content_length(scope)
        if declared is not None and declared > self.max_bytes:
            await PlainTextResponse("request body too large", _TOO_LARGE)(scope, receive, send)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # surfaces through the app's own exception handling, inside CORS
                    raise HTTPException(_TOO_LARGE, "request body too large")
            return message

        await self.app(scope, limited_receive, send)


def _content_length(scope: Scope) -> int | None:
    for name, value in scope["headers"]:
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None
