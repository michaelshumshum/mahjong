"""FastAPI app, `lifespan`, uvicorn entry.

Shutdown drain hooks `lifespan`'s post-`yield` phase, not `signal.signal` -- uvicorn already
owns SIGTERM/SIGINT and sends `lifespan.shutdown` before this runs, so a second handler here
would fight uvicorn's own rather than extend it. A `TestClient(app)` context exit runs the same
drain, hence `SHUTDOWN_GRACE_SECONDS=0` for the test session (`server/tests/conftest.py`).

`SHOWCASE_TABLE_ID` (default `BOTS`) is four characters so it can never collide with a
generated six-character table id.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import os
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import ws
from app.api_models import (
    BotLatencyOut,
    CreateTableRequest,
    CreateTableResponse,
    LoadPointOut,
    RandomLessonResponse,
    ScoreHandRequest,
    ScoreHandResponse,
    SeatSummary,
    ServerStatus,
    StatusResponse,
    TableList,
    TableSummaryOut,
)
from app.body_limit import BodySizeLimitMiddleware
from app.db.records import count_games_since
from app.db.session import make_engine, make_session_factory
from app.lessons.model import Band, PuzzleKind
from app.lessons.pool import lesson_payload, load_pool, pick
from app.limits import IpNetwork, client_ip, parse_trusted_proxies
from app.rate_limit import RateLimiter
from app.registry import REAP_INTERVAL_SECONDS, TableLimitError
from app.status import reset_stats, stats
from bots.learned import weights_problem
from bots.tiers import LEARNED_TIERS, BotTier
from mahjong_core.config import DEFAULT_RULESET
from mahjong_core.hand_check import check_hand
from mahjong_core.presets import preset_id_for, resolve_ruleset
from mahjong_core.state import Wind
from mahjong_core.tiles import Flower, TileType, parse_tile

_DEFAULT_SHUTDOWN_GRACE_SECONDS = 90.0  # tunable via env
# must stay well above RuleSet.disconnect_grace_seconds (20s) so a refresh never ends a game
_DEFAULT_ABANDONED_TABLE_GRACE_SECONDS = 120.0
_DEFAULT_SHOWCASE_TABLE_ID = "BOTS"
# docs/architecture.md §8.3: ~20 KB idle, a few hundred KB mid-game, on a 1.9 GiB box
_DEFAULT_MAX_TABLES = 500
_DEFAULT_UNSTARTED_TABLE_TTL_SECONDS = 600.0
_DEFAULT_FINISHED_TABLE_TTL_SECONDS = 600.0
_DEFAULT_TABLE_CREATE_RATE_LIMIT = 10
_DEFAULT_TABLE_CREATE_RATE_WINDOW_SECONDS = 60.0
# a puzzle takes seconds to answer; one a second sustained is a script
_DEFAULT_LESSON_RATE_LIMIT = 60
_DEFAULT_LESSON_RATE_WINDOW_SECONDS = 60.0
# ids a client may ask GET /lessons/random to skip: its recent puzzles
_MAX_LESSON_EXCLUDE = 50
_MAX_LESSON_ID_LENGTH = 64
# matches web/src/lib/table/table-code.ts's TABLE_CODE_ALPHABET -- no 0/O/1/I look-alikes.
_TABLE_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_TABLE_CODE_LENGTH = 6
_TABLE_ID_GENERATION_ATTEMPTS = 10  # astronomically unlikely to ever retry once, let alone exhaust
# GET /status is public and polled; one count query per this many seconds at most
_GAMES_COUNT_CACHE_SECONDS = 60.0


logger = logging.getLogger(__name__)

_learned_weights_problem: str | None = None
# rebuilt per lifespan like the registry; None = unlimited
_create_limiter: RateLimiter | None = None
_lesson_limiter: RateLimiter | None = None
_trusted_proxies: tuple[IpNetwork, ...] = ()
_session_factory: async_sessionmaker[AsyncSession] | None = None
# (monotonic time fetched, count)
_games_24h_cache: tuple[float, int] | None = None


def _optional_limit(raw: str) -> int | None:
    """`0` (or below) turns a count limit off."""
    value = int(raw)
    return value if value > 0 else None


def _rate_limiter(
    limit_var: str, default_limit: int, window_var: str, default_window: float
) -> RateLimiter | None:
    limit = _optional_limit(os.environ.get(limit_var, str(default_limit)))
    if limit is None:
        return None
    window = float(os.environ.get(window_var, default_window))
    return RateLimiter(limit=limit, window_seconds=window)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # degrade rather than refuse to start: a crash-looping api takes every table down, a missing
    # policy only Expert/Impossible (docs/bots.md §2 "Missing weights")
    global _learned_weights_problem, _create_limiter, _trusted_proxies, _session_factory
    global _games_24h_cache, _lesson_limiter
    _learned_weights_problem = weights_problem()
    if _learned_weights_problem is not None:
        logger.error(
            "learned weights unusable, %s disabled: %s",
            "/".join(sorted(LEARNED_TIERS)),
            _learned_weights_problem,
        )
    database_url = os.environ.get("DATABASE_URL")
    engine = make_engine(database_url) if database_url else None
    session_factory = make_session_factory(engine) if engine is not None else None
    _session_factory = session_factory
    _games_24h_cache = None
    abandon_grace = float(
        os.environ.get("ABANDONED_TABLE_GRACE_SECONDS", _DEFAULT_ABANDONED_TABLE_GRACE_SECONDS)
    )
    registry = ws.reset_registry(
        session_factory=session_factory,
        abandon_grace_seconds=abandon_grace,
        max_tables=_optional_limit(os.environ.get("MAX_TABLES", str(_DEFAULT_MAX_TABLES))),
        unstarted_ttl_seconds=float(
            os.environ.get("UNSTARTED_TABLE_TTL_SECONDS", _DEFAULT_UNSTARTED_TABLE_TTL_SECONDS)
        ),
        finished_ttl_seconds=float(
            os.environ.get("FINISHED_TABLE_TTL_SECONDS", _DEFAULT_FINISHED_TABLE_TTL_SECONDS)
        ),
    )
    registry.start_reaper()
    _create_limiter = _rate_limiter(
        "TABLE_CREATE_RATE_LIMIT",
        _DEFAULT_TABLE_CREATE_RATE_LIMIT,
        "TABLE_CREATE_RATE_WINDOW_SECONDS",
        _DEFAULT_TABLE_CREATE_RATE_WINDOW_SECONDS,
    )
    _lesson_limiter = _rate_limiter(
        "LESSON_RATE_LIMIT",
        _DEFAULT_LESSON_RATE_LIMIT,
        "LESSON_RATE_WINDOW_SECONDS",
        _DEFAULT_LESSON_RATE_WINDOW_SECONDS,
    )
    _trusted_proxies = parse_trusted_proxies(os.environ.get("TRUSTED_PROXY_IPS"))
    showcase_id = os.environ.get("SHOWCASE_TABLE_ID", _DEFAULT_SHOWCASE_TABLE_ID).strip()
    if showcase_id:
        registry.start_showcase(showcase_id, DEFAULT_RULESET, bot_tiers=_available_bot_tiers())
    sampler = asyncio.create_task(reset_stats().run_sampler(_history_load))
    try:
        yield
    finally:
        sampler.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sampler
        grace_seconds = float(
            os.environ.get("SHUTDOWN_GRACE_SECONDS", _DEFAULT_SHUTDOWN_GRACE_SECONDS)
        )
        # begin_shutdown awaits every table's drain to completion, so GAME_OVER persists are
        # guaranteed finished (never in flight) before the engine is disposed.
        await registry.begin_shutdown(grace_seconds=grace_seconds)
        if engine is not None:
            await engine.dispose()


def _openapi_url(api_docs: str | None) -> str | None:
    # None also unmounts /docs and /redoc, which both read the schema from it
    return None if api_docs == "0" else "/openapi.json"


# API_DOCS=0 (prod overlay) hides the schema and docs UIs
app = FastAPI(lifespan=lifespan, openapi_url=_openapi_url(os.environ.get("API_DOCS")))
app.include_router(ws.router)
# added before CORS so CORS wraps it and a 413 still carries the allow-origin header
app.add_middleware(BodySizeLimitMiddleware)
# comma-separated CORS_ORIGINS; unset -> no cross-origin reads.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()],
    allow_methods=["GET", "POST"],
    # POST sends a JSON body -- not a CORS-safelisted content type, so browsers preflight and
    # need this header even though GET never did.
    allow_headers=["Content-Type"],
)


def _generate_table_id() -> str:
    """Six characters from a look-alike-free alphabet. `secrets.choice`, not `random.choice`:
    this id doubles as the only real access control a table has (guest-only, no auth), so it
    must resist guessing, not just collisions. Collision-checked against the registry
    regardless."""
    registry = ws.registry()
    for _ in range(_TABLE_ID_GENERATION_ATTEMPTS):
        candidate = "".join(secrets.choice(_TABLE_CODE_ALPHABET) for _ in range(_TABLE_CODE_LENGTH))
        if registry.get(candidate) is None and not registry.is_closed(candidate):
            return candidate
    raise RuntimeError("could not generate a unique table id")


# practice-mode difficulty picker (docs/bots.md §6): Easy/Normal/Expert/Impossible =
# T1/T2/T4/ORACLE. T0/RandomBot is deliberately excluded -- never shipped as a difficulty (§2).
_PRACTICE_BOT_TIERS = (BotTier.T1, BotTier.T2, BotTier.T4, BotTier.ORACLE)


def _available_bot_tiers() -> tuple[str, ...]:
    """`_PRACTICE_BOT_TIERS` minus `LEARNED_TIERS` while the startup weight check failed."""
    unavailable = LEARNED_TIERS if _learned_weights_problem is not None else frozenset()
    return tuple(t for t in _PRACTICE_BOT_TIERS if t not in unavailable)


def _resolve_seat_bot_tiers(
    practice: bool, bot_tiers: dict[int, str] | None
) -> dict[int, str] | None:
    """`CreateTableRequest.bot_tiers` -> `Table(seat_bot_tiers=...)`. Same lenient-fallback
    posture as `resolve_ruleset` (never hard-reject bad input): a seat
    outside 1..3 (seat 0 is the human seat in practice mode) or a tier outside
    `_PRACTICE_BOT_TIERS` is silently dropped rather than raising -- a malformed entry just falls
    back to that seat's `DEFAULT_BOT_TIER` instead of failing the whole request. So is a
    `LEARNED_TIERS` tier while the startup weight check failed (`/healthz` reports it).
    `practice=False` has no bot seats to apply this to, so it resolves to `None` unconditionally.
    """
    if not practice or not bot_tiers:
        return None
    available = _available_bot_tiers()
    resolved = {
        seat: tier for seat, tier in bot_tiers.items() if 1 <= seat <= 3 and tier in available
    }
    return resolved or None


def _check_rate(limiter: RateLimiter | None, request: Request, detail: str) -> None:
    """429 with `Retry-After` once the request's client IP is past `limiter`."""
    if limiter is None:
        return
    ip = client_ip(
        request.client.host if request.client is not None else None,
        request.headers,
        _trusted_proxies,
    )
    if not limiter.allow(ip):
        raise HTTPException(
            status_code=429,
            detail=detail,
            headers={"Retry-After": str(limiter.retry_after(ip))},
        )


@app.post("/tables")
async def create_table(body: CreateTableRequest, request: Request) -> CreateTableResponse:
    """Resolves the ruleset and mints the table id together in one request -- the only way a
    table is created (`/ws` attaches to existing ones only). 429 past the per-IP rate limit,
    503 past `MAX_TABLES` (docs/architecture.md §8.3)."""
    _check_rate(_create_limiter, request, "too many tables created, try again shortly")
    resolved = resolve_ruleset(body.ruleset, body.rules)
    table_id = _generate_table_id()
    try:
        ws.registry().get_or_create(
            table_id,
            resolved,
            practice=body.practice,
            seat_bot_tiers=_resolve_seat_bot_tiers(body.practice, body.bot_tiers),
            private=body.private,
        )
    except TableLimitError as exc:
        raise HTTPException(
            status_code=503,
            detail="server is at its table limit, try again later",
            headers={"Retry-After": str(round(REAP_INTERVAL_SECONDS))},
        ) from exc
    return CreateTableResponse(
        table_id=table_id,
        ruleset_preset=preset_id_for(resolved),
        ruleset=resolved.to_dict(),
    )


def _server_status() -> ServerStatus:
    if ws.registry().draining:
        return "draining"
    return "degraded" if _learned_weights_problem is not None else "ok"


def _history_load() -> tuple[int, int]:
    load = ws.registry().load()
    return load.players, load.playing


async def _games_finished_24h() -> int | None:
    global _games_24h_cache
    if _session_factory is None:
        return None
    now = time.monotonic()
    if _games_24h_cache is not None and now - _games_24h_cache[0] < _GAMES_COUNT_CACHE_SECONDS:
        return _games_24h_cache[1]
    since = dt.datetime.now(dt.UTC) - dt.timedelta(days=1)
    try:
        async with _session_factory() as session:
            count = await count_games_since(session, since)
    except Exception:
        # the status page outlives a database outage; it just loses this one number
        logger.exception("status: counting recent games failed")
        return None
    _games_24h_cache = (now, count)
    return count


@app.get("/status")
async def server_status() -> StatusResponse:
    """Public status page numbers (docs/infra.md §8). Aggregates only -- no table ids or names."""
    load = ws.registry().load()
    server = stats()
    bot = server.bot_decision_ms()
    return StatusResponse(
        status=_server_status(),
        uptime_seconds=server.uptime_seconds(),
        players_online=load.players,
        spectators=load.spectators,
        tables_playing=load.playing,
        tables_waiting=load.waiting,
        capacity_pct=(
            round(100 * load.live / load.max_tables) if load.max_tables is not None else None
        ),
        games_finished_24h=await _games_finished_24h(),
        bot_decision_ms=BotLatencyOut(p50_ms=bot[0], p95_ms=bot[1]) if bot is not None else None,
        loop_lag_ms=server.loop_lag_ms(),
        history=[
            LoadPointOut(
                ts=p.ts,
                players=p.players,
                tables=p.tables,
                bot_p95_ms=p.bot_p95_ms,
                loop_lag_ms=p.loop_lag_ms,
            )
            for p in server.history
        ],
    )


def _parse_codes[T: (TileType, Flower)](codes: list[str], kind: type[T]) -> list[T]:
    parsed = []
    for code in codes:
        try:
            tile = parse_tile(code)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not isinstance(tile, kind):
            raise HTTPException(status_code=422, detail=f"unexpected tile here: {code!r}")
        parsed.append(tile)
    return parsed


@app.post("/score")
async def score_hand(body: ScoreHandRequest) -> ScoreHandResponse:
    """The faan guide's hand checker (docs/protocol.md §10): scores a 14-tile hand.
    Pure computation, no table involved; `422` on a hand no deal could produce."""
    ruleset = resolve_ruleset(body.ruleset, body.rules)
    try:
        checked = check_hand(
            _parse_codes(body.tiles, TileType),
            _parse_codes(body.flowers, Flower),
            self_drawn=body.self_drawn,
            seat_wind=Wind(body.seat_wind),
            prevailing_wind=Wind(body.prevailing_wind),
            ruleset=ruleset,
            fully_concealed=body.fully_concealed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result = checked.result
    return ScoreHandResponse(
        winning=checked.winning,
        total_faan=result.total_faan if result else None,
        breakdown=result.breakdown if result else {},
        clears_min_faan=result.clears_min_faan if result else None,
        points=checked.points,
        min_faan=ruleset.min_faan,
    )


@app.get("/lessons/random", response_model=RandomLessonResponse)
async def random_lesson(
    request: Request,
    kind: PuzzleKind,
    band: Band | None = None,
    exclude: Annotated[
        list[Annotated[str, StringConstraints(max_length=_MAX_LESSON_ID_LENGTH)]],
        Query(max_length=_MAX_LESSON_EXCLUDE),
    ] = [],  # noqa: B006 -- fastapi copies query defaults
) -> JSONResponse:
    """Learn mode's endless puzzles (docs/protocol.md §10): a random pooled puzzle of `kind`
    and `band` (any band if omitted), skipping `exclude`d ids while others remain. Returned as
    the stored lesson payload, so the key is never regraded per request."""
    _check_rate(_lesson_limiter, request, "too many puzzles requested, try again shortly")
    pooled = pick(load_pool(), kind, band, frozenset(exclude))
    return JSONResponse(lesson_payload(pooled))


@app.get("/healthz")
async def healthz() -> JSONResponse:
    # fails once a drain has begun, so a load balancer stops routing new traffic here.
    status = _server_status()
    if status == "draining":
        return JSONResponse({"status": status}, status_code=503)
    # 200, not 503: the web client's ApiConnectGate blocks every page on a non-2xx. the compose
    # healthcheck reads "status" instead (docs/infra.md §8)
    if status == "degraded":
        return JSONResponse(
            {
                "status": "degraded",
                "disabled_tiers": sorted(LEARNED_TIERS),
                "reason": _learned_weights_problem,
            }
        )
    return JSONResponse({"status": status})


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
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        workers=1,
        limit_concurrency=1000,
        ws_max_size=ws.MAX_FRAME_BYTES,
        ws_per_message_deflate=False,
    )
