"""FastAPI app, `lifespan`, uvicorn entry.

Shutdown drain hooks `lifespan`'s post-`yield` phase, not `signal.signal` -- uvicorn already
owns SIGTERM/SIGINT and sends `lifespan.shutdown` before this runs, so a second handler here
would fight uvicorn's own rather than extend it. A `TestClient(app)` context exit runs the same
drain, hence `SHUTDOWN_GRACE_SECONDS=0` for the test session (`server/tests/conftest.py`).

`SHOWCASE_TABLE_ID` (default `BOTS`) is four characters so it can never collide with a
generated six-character table id.
"""

from __future__ import annotations

import logging
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
from bots.learned import weights_problem
from mahjong_core.config import DEFAULT_RULESET
from mahjong_core.presets import DEFAULT_PRESET_ID, preset_id_for, resolve_ruleset

_DEFAULT_SHUTDOWN_GRACE_SECONDS = 90.0  # tunable via env
_DEFAULT_SHOWCASE_TABLE_ID = "BOTS"
# matches web/src/lib/table/table-code.ts's TABLE_CODE_ALPHABET -- no 0/O/1/I look-alikes.
_TABLE_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_TABLE_CODE_LENGTH = 6
_TABLE_ID_GENERATION_ATTEMPTS = 10  # astronomically unlikely to ever retry once, let alone exhaust


logger = logging.getLogger(__name__)

# the tiers that load bots/weights/learned.npz (docs/bots.md §2)
_LEARNED_TIERS = frozenset({"T4", "ORACLE"})
_learned_weights_problem: str | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # degrade rather than refuse to start: a crash-looping api takes every table down, a missing
    # policy only Expert/Impossible (docs/bots.md §2 "Missing weights")
    global _learned_weights_problem
    _learned_weights_problem = weights_problem()
    if _learned_weights_problem is not None:
        logger.error(
            "learned weights unusable, %s disabled: %s",
            "/".join(sorted(_LEARNED_TIERS)),
            _learned_weights_problem,
        )
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
        # begin_shutdown awaits every table's drain to completion, so GAME_OVER persists are
        # guaranteed finished (never in flight) before the engine is disposed.
        await registry.begin_shutdown(grace_seconds=grace_seconds)
        if engine is not None:
            await engine.dispose()


app = FastAPI(lifespan=lifespan)
app.include_router(ws.router)
# comma-separated CORS_ORIGINS; unset -> no cross-origin reads.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()],
    allow_methods=["GET", "POST"],
    # POST sends a JSON body -- not a CORS-safelisted content type, so browsers preflight and
    # need this header even though GET never did.
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
    # `RuleSet.from_dict`-shaped; only read when `ruleset == "custom"`.
    rules: dict[str, Any] | None = None
    practice: bool = False
    # practice mode's per-seat difficulty picker: {1: "T1", 2: "T4", 3: "ORACLE"}-shaped, seat 0
    # excluded (the human seat) -- only meaningful when practice=True, see _resolve_seat_bot_tiers.
    bot_tiers: dict[int, str] | None = None


class CreateTableResponse(BaseModel):
    table_id: str
    # same shape as state_sync.ruleset/ruleset_preset
    ruleset_preset: str | None
    ruleset: dict[str, Any]


def _generate_table_id() -> str:
    """Six characters from a look-alike-free alphabet. `secrets.choice`, not `random.choice`:
    this id doubles as the only real access control a table has (guest-only, no auth), so it
    must resist guessing, not just collisions. Collision-checked against the registry
    regardless."""
    registry = ws.registry()
    for _ in range(_TABLE_ID_GENERATION_ATTEMPTS):
        candidate = "".join(secrets.choice(_TABLE_CODE_ALPHABET) for _ in range(_TABLE_CODE_LENGTH))
        if registry.get(candidate) is None:
            return candidate
    raise RuntimeError("could not generate a unique table id")


# practice-mode difficulty picker (docs/bots.md §6): Easy/Normal/Expert/Impossible =
# T1/T2/T4/ORACLE. T0/RandomBot is deliberately excluded -- never shipped as a difficulty (§2).
_PRACTICE_BOT_TIERS = ("T1", "T2", "T4", "ORACLE")


def _resolve_seat_bot_tiers(
    practice: bool, bot_tiers: dict[int, str] | None
) -> dict[int, str] | None:
    """`CreateTableRequest.bot_tiers` -> `Table(seat_bot_tiers=...)`. Same lenient-fallback
    posture as `_resolve_ruleset_query`/`resolve_ruleset` (never hard-reject bad input): a seat
    outside 1..3 (seat 0 is the human seat in practice mode) or a tier outside
    `_PRACTICE_BOT_TIERS` is silently dropped rather than raising -- a malformed entry just falls
    back to that seat's `DEFAULT_BOT_TIER` instead of failing the whole request. So is a
    `_LEARNED_TIERS` tier while the startup weight check failed (`/healthz` reports it).
    `practice=False` has no bot seats to apply this to, so it resolves to `None` unconditionally.
    """
    if not practice or not bot_tiers:
        return None
    unavailable = _LEARNED_TIERS if _learned_weights_problem is not None else frozenset()
    resolved = {
        seat: tier
        for seat, tier in bot_tiers.items()
        if 1 <= seat <= 3 and tier in _PRACTICE_BOT_TIERS and tier not in unavailable
    }
    return resolved or None


@app.post("/tables")
async def create_table(body: CreateTableRequest) -> CreateTableResponse:
    """Resolves the ruleset and mints the table id together in one request. `?ruleset=`/
    `?rules=` on `/ws` remain a fallback for a direct WS connect to an unclaimed table id."""
    resolved = resolve_ruleset(body.ruleset, body.rules)
    table_id = _generate_table_id()
    ws.registry().get_or_create(
        table_id,
        resolved,
        practice=body.practice,
        seat_bot_tiers=_resolve_seat_bot_tiers(body.practice, body.bot_tiers),
    )
    return CreateTableResponse(
        table_id=table_id,
        ruleset_preset=preset_id_for(resolved),
        ruleset=resolved.to_dict(),
    )


@app.get("/healthz")
async def healthz() -> JSONResponse:
    # fails once a drain has begun, so a load balancer stops routing new traffic here.
    if ws.registry().draining:
        return JSONResponse({"status": "draining"}, status_code=503)
    # 200, not 503: the web client's ApiConnectGate blocks every page on a non-2xx. the compose
    # healthcheck reads "status" instead (docs/infra.md §8)
    if _learned_weights_problem is not None:
        return JSONResponse(
            {
                "status": "degraded",
                "disabled_tiers": sorted(_LEARNED_TIERS),
                "reason": _learned_weights_problem,
            }
        )
    return JSONResponse({"status": "ok"})


@app.get("/tables")
async def list_tables() -> TableList:
    """Lobby table browser -- `TableRegistry.list_tables`."""
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
    # workers=1: tables are in-memory, owned by one process
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, workers=1)
