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

`SHOWCASE_TABLE_ID` (default `BOTS`, empty disables) names the always-on all-bot table
(`TableRegistry.start_showcase`). Four characters, so it can never collide with a generated
six-character invite code.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import ws
from app.db.session import make_engine, make_session_factory
from app.table import WireSeatStatus
from mahjong_core.config import DEFAULT_RULESET
from mahjong_core.presets import DEFAULT_PRESET_ID, preset_id_for, resolve_ruleset

_DEFAULT_SHUTDOWN_GRACE_SECONDS = 90.0  # docs/00-architecture.md §8.1 step 3, tunable via env
_DEFAULT_SHOWCASE_TABLE_ID = "BOTS"
# matches web/src/lib/table/table-code.ts's TABLE_CODE_ALPHABET -- no 0/O/1/I look-alikes.
# Four-character SHOWCASE_TABLE_ID (above) can never collide with a generated six-character one.
_TABLE_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_TABLE_CODE_LENGTH = 6
_TABLE_ID_GENERATION_ATTEMPTS = 10  # astronomically unlikely to ever retry once, let alone exhaust


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    database_url = os.environ.get("DATABASE_URL")
    engine = make_engine(database_url) if database_url else None
    session_factory = make_session_factory(engine) if engine is not None else None
    registry = ws.reset_registry(session_factory=session_factory)
    showcase_id = os.environ.get("SHOWCASE_TABLE_ID", _DEFAULT_SHOWCASE_TABLE_ID).strip()
    if showcase_id:
        registry.start_showcase(showcase_id, DEFAULT_RULESET)
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
    allow_methods=["GET", "POST"],
    # POST /tables sends a JSON body -- `application/json` isn't a CORS-safelisted content type,
    # so the browser preflights it and refuses without this even though GET never needed it.
    allow_headers=["Content-Type"],
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


class CreateTableRequest(BaseModel):
    # `mahjong_core.presets.RULESET_PRESETS` key, or "custom" to take `rules` below instead.
    ruleset: str = DEFAULT_PRESET_ID
    # `RuleSet.from_dict`-shaped; only read when `ruleset == "custom"`. A structured JSON body
    # field here, not the URL-encoded text `?rules=` on `/ws` has to be (docs/02-protocol.md
    # "Ruleset selection") -- this is the one-request path that shim exists as a fallback for.
    rules: dict[str, Any] | None = None
    practice: bool = False


class CreateTableResponse(BaseModel):
    table_id: str
    # the resolved ruleset, same shape `state_sync.ruleset`/`ruleset_preset` carry
    # (docs/02-protocol.md §3) -- a client gets this back without needing its own WS connection
    # first, e.g. to render "Rules: HK Classic" on the pretable screen immediately.
    ruleset_preset: str | None
    ruleset: dict[str, Any]


def _generate_table_id() -> str:
    """A fresh, never-yet-used table id -- six characters from the same look-alike-free alphabet
    `web/src/lib/table/table-code.ts` used to generate client-side before table creation moved
    server-side (`POST /tables` below). `secrets.choice`, not `random.choice`: this id doubles as
    an invite code gating who can join a specific game without spectating every table
    (`docs/02-protocol.md`'s "Auth" note -- guest-only, so this is the only real access control a
    table has), so it should resist guessing, not just collisions. Collision-checked against the
    registry anyway (astronomically unlikely at 33^6 combinations, but a `Table` actor lives for
    the rest of the process's life once created, so silently colliding into someone else's game
    would be a real, if vanishingly rare, bug -- `TableRegistry.get_or_create`'s own "never
    creates a second `Table` for an id that already has one" would otherwise hand the second
    caller a table it didn't ask for)."""
    registry = ws.registry()
    for _ in range(_TABLE_ID_GENERATION_ATTEMPTS):
        candidate = "".join(secrets.choice(_TABLE_CODE_ALPHABET) for _ in range(_TABLE_CODE_LENGTH))
        if registry.get(candidate) is None:
            return candidate
    raise RuntimeError("could not generate a unique table id")


@app.post("/tables")
async def create_table(body: CreateTableRequest) -> CreateTableResponse:
    """One-request table creation: resolve the ruleset and mint the id together, so a client
    configuring custom rules (docs/05-roadmap.md "Ruleset presets") sends one POST and gets back
    everything it needs to navigate straight to `/table/<id>` -- no more threading a full
    `RuleSet.to_dict()` payload through two nested URL query strings (the lobby page's own URL,
    then the WS connect URL it builds from that). `?ruleset=`/`?rules=` on `/ws`
    (`app/ws.py`'s `_resolve_ruleset_query`) still exist as a fallback for a direct WS connect to
    an unclaimed table id -- this endpoint just resolves the same way
    (`mahjong_core.presets.resolve_ruleset`) and is the primary path a real client should use."""
    resolved = resolve_ruleset(body.ruleset, body.rules)
    table_id = _generate_table_id()
    ws.registry().get_or_create(table_id, resolved, practice=body.practice)
    return CreateTableResponse(
        table_id=table_id,
        ruleset_preset=preset_id_for(resolved),
        ruleset=resolved.to_dict(),
    )


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
