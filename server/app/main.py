"""FastAPI app, `lifespan`, uvicorn entry (docs/00-architecture.md §6/§8.1,
docs/05-roadmap.md §1).

`lifespan` builds the DB engine/session factory from `DATABASE_URL` (unset -> no persistence,
matching every bare `Table()`/`TableRegistry()` test that never passes one) and installs a fresh
`TableRegistry` for this server lifetime via `app.ws.reset_registry` -- see that function's own
docstring for why "fresh per startup" matters, not just "mutate the existing one": a previous
lifetime's `draining` flag and tables must never leak into this one, and that includes a
`TestClient(app)` context in tests, which runs this exact same ASGI lifespan protocol.

Graceful shutdown (docs/00-architecture.md §8.1) hooks `lifespan`'s shutdown phase (the code
after `yield`) rather than a manual `signal.signal`/`loop.add_signal_handler` call: uvicorn's own
`Server.install_signal_handlers()` already owns SIGTERM/SIGINT on the running loop and stops
accepting new connections before it sends the ASGI `lifespan.shutdown` message that resumes this
function past `yield` -- installing a second, competing handler here would fight uvicorn's own
rather than extend it.

Verified empirically, not assumed: ran a real `uvicorn.run(app.main:app)` process, joined a real
WS seat into a table (so it has a bound seat and never reaches a hand boundary), sent it a real
`SIGTERM` from another process, and confirmed (a) `/healthz` had been serving `200 ok` right up
to the signal, (b) the process's own logs show uvicorn's "Waiting for application shutdown" step
actually running -- proving SIGTERM really does route through this `lifespan` by default, not
just under `TestClient` -- (c) `TableRegistry.begin_shutdown`'s "abandoning" warning fires for
that table once its grace window elapses, and (d) the process still exits cleanly afterward,
bounded by the configured grace window rather than hanging. Also ran the equivalent with no tables
at all, confirming a `SIGTERM` with nothing to drain exits near-instantly.

The one real consequence of hooking a *generic* ASGI-shutdown signal rather than a SIGTERM-
specific one: a `TestClient(app)` context exiting runs this same drain code, not just a real
process terminating. `SHUTDOWN_GRACE_SECONDS` (server/tests/conftest.py sets it to `0` for the
whole test session) is this codebase's usual test-time-control answer to that -- the same
`disconnect_grace_seconds=0` idea `tests/test_disconnect_bot_handover.py` already established,
applied here via env var instead of a `RuleSet` field since this is process-level, not per-game
config.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import ws
from app.db.session import make_engine, make_session_factory
from app.table import WireSeatStatus

_DEFAULT_SHUTDOWN_GRACE_SECONDS = 90.0  # docs/00-architecture.md §8.1 step 3, tunable via env


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    database_url = os.environ.get("DATABASE_URL")
    engine = make_engine(database_url) if database_url else None
    session_factory = make_session_factory(engine) if engine is not None else None
    registry = ws.reset_registry(session_factory=session_factory)
    try:
        yield
    finally:
        grace_seconds = float(
            os.environ.get("SHUTDOWN_GRACE_SECONDS", _DEFAULT_SHUTDOWN_GRACE_SECONDS)
        )
        # begin_shutdown awaits every affected table's own drain wait to completion before
        # returning (docs/00-architecture.md §8.1 steps 3-5) -- only then is it safe to dispose
        # the engine (app/table.py's process_one() docstring: a table's GAME_OVER persist is
        # guaranteed finished by the time its own wait resolves, never in flight).
        await registry.begin_shutdown(grace_seconds=grace_seconds)
        if engine is not None:
            await engine.dispose()


app = FastAPI(lifespan=lifespan)
app.include_router(ws.router)
# the lobby fetches `/tables` cross-origin (web and api are separate origins in every compose
# setup); comma-separated, unset -> no cross-origin reads.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()],
    allow_methods=["GET"],
)


class SeatSummary(BaseModel):
    status: WireSeatStatus
    name: str | None


class TableSummaryOut(BaseModel):
    id: str
    status: Literal["open", "in_progress"]
    hand_no: int
    seats: list[SeatSummary]


class TableList(BaseModel):
    tables: list[TableSummaryOut]


@app.get("/healthz")
async def healthz() -> JSONResponse:
    # docs/00-architecture.md §8.1 step 1: the health check starts failing once a drain has
    # begun, so a load balancer stops routing new traffic here.
    if ws.registry().draining:
        return JSONResponse({"status": "draining"}, status_code=503)
    return JSONResponse({"status": "ok"})


@app.get("/tables")
async def list_tables() -> TableList:
    """Lobby table browser (docs/02-protocol.md §10) -- `TableRegistry.list_tables`."""
    return TableList(
        tables=[
            TableSummaryOut(
                id=t.table_id,
                status=t.status,
                hand_no=t.hand_no,
                seats=[
                    SeatSummary(status=status, name=name)
                    for status, name in zip(t.seat_status, t.names, strict=True)
                ],
            )
            for t in ws.registry().list_tables()
        ]
    )


if __name__ == "__main__":
    # workers=1: tables are in-memory, owned by one process. docs/07-infra.md §2
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, workers=1)
