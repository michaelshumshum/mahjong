"""`/auth/*` and `/me*` (docs/protocol.md §10 "Accounts"). Every route 404s unless
`ACCOUNTS_ENABLED` is on and a database is configured, so the feature is invisible in prod until
ADR 0028 phase 7."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import secrets
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.accounts.config import AccountsConfig
from app.accounts.google import PROVIDER, GoogleProvider
from app.accounts.learn import (
    MAX_LEARN_COUNT,
    EndlessValues,
    LessonValues,
    check_lesson,
    import_learn,
    learn_imported_at,
    learn_of,
    record_endless,
    record_lesson,
    update_prefs,
)
from app.accounts.sessions import (
    COOKIE_NAME,
    delete_expired_sessions,
    issue_session,
    resolve_session,
    revoke_session,
)
from app.accounts.users import (
    delete_user,
    drop_sessions,
    identities_of,
    seats_in,
    seats_of,
    upsert_identity,
)
from app.api_models import (
    EndlessScoreIn,
    EndlessScoreOut,
    ExportGame,
    ExportIdentity,
    ExportResponse,
    ExportUser,
    LearnImport,
    LearnImportResponse,
    LearnResponse,
    LessonProgressIn,
    LessonProgressOut,
    MePatch,
    MeResponse,
    MyGame,
    MyGameSeat,
    MyGamesResponse,
    PrefsPatch,
)
from app.db.models import GameMode, LearnEndlessScore, LearnProgress, User
from app.lessons.model import PuzzleKind
from app.names import clean_name
from app.rate_limit import RateLimiter

__all__ = ["auth_router", "configure", "router", "run_session_cleanup", "set_google"]

_CLEANUP_INTERVAL_SECONDS = 3600.0
_OAUTH_COOKIE = "mj_oauth"
_OAUTH_COOKIE_PATH = "/auth/google"
# the round trip through google's consent screen
_OAUTH_COOKIE_MAX_AGE_SECONDS = 600
_MAX_NEXT_LENGTH = 512
# the training-consent wording a user agrees to (ADR 0016); bump with the web's wording.
# phase 3 ships a placeholder, phase 7 the final text
TRAINING_CONSENT_VERSION = "2026-11-draft"
DEFAULT_GAMES_PAGE = 20
MAX_GAMES_PAGE = 50

logger = logging.getLogger(__name__)

# /me*; main.py includes `auth_router` (/auth/*) behind the per-IP auth rate limit
router = APIRouter()
auth_router = APIRouter(prefix="/auth")
_config = AccountsConfig.from_env({})
_session_factory: async_sessionmaker[AsyncSession] | None = None
_google: GoogleProvider | None = None
# None = unlimited
_export_limiter: RateLimiter | None = None
_import_limiter: RateLimiter | None = None
_COUNT_FIELDS = frozenset({"attempts", "step", "streak", "best", "solved"})
_PUZZLE_KINDS = frozenset(PuzzleKind)


def configure(
    config: AccountsConfig,
    session_factory: async_sessionmaker[AsyncSession] | None,
    *,
    export_limiter: RateLimiter | None = None,
    import_limiter: RateLimiter | None = None,
) -> bool:
    """Called from `lifespan`; returns whether accounts are live."""
    global _config, _session_factory, _google, _export_limiter, _import_limiter
    if config.enabled and session_factory is None:
        logger.warning("ACCOUNTS_ENABLED without DATABASE_URL: accounts stay off")
    _config = config
    _session_factory = session_factory if config.enabled else None
    _google = (
        GoogleProvider(config.google_client_id, config.google_client_secret)
        if config.google_client_id and config.google_client_secret
        else None
    )
    _export_limiter = export_limiter
    _import_limiter = import_limiter
    return _session_factory is not None


def set_google(provider: GoogleProvider) -> None:
    """Swap the provider (tests stub Google's endpoints through its transport)."""
    global _google
    _google = provider


def config() -> AccountsConfig:
    return _config


def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


async def run_session_cleanup() -> None:
    """Delete expired sessions hourly, for the lifespan's background task."""
    while True:
        if _session_factory is not None:
            try:
                async with _session_factory() as db:
                    await delete_expired_sessions(db, now=now(), idle=_config.session_idle)
            except Exception:
                logger.exception("accounts: expired-session cleanup failed")
        await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)


async def user_for_cookie(token: str | None, origin: str | None) -> User | None:
    """The account behind a WS handshake's session cookie: None when accounts are off, there's
    no cookie, it doesn't resolve, or the upgrade's `Origin` isn't a `CORS_ORIGINS` entry. A
    database error plays on as a guest."""
    if token is None or _session_factory is None:
        return None
    # websockets skip cors, and samesite=lax still sends the cookie from a sibling subdomain:
    # a foreign page could otherwise seat its visitor as their account
    if origin not in _config.origins:
        return None
    try:
        async with _session_factory() as db:
            return await resolve_session(db, token, now=now(), idle=_config.session_idle)
    except Exception:
        logger.exception("accounts: resolving a ws session failed")
        return None


async def _db() -> AsyncIterator[AsyncSession]:
    if _session_factory is None:
        raise HTTPException(status_code=404)
    async with _session_factory() as db:
        yield db


Db = Annotated[AsyncSession, Depends(_db)]
SessionCookie = Annotated[str | None, Cookie(alias=COOKIE_NAME)]


async def _current_user(db: Db, token: SessionCookie = None) -> User:
    user = (
        await resolve_session(db, token, now=now(), idle=_config.session_idle)
        if token is not None
        else None
    )
    if user is None:
        raise HTTPException(status_code=401, detail="not signed in")
    return user


CurrentUser = Annotated[User, Depends(_current_user)]


def set_session_cookie(response: Response, token: str) -> None:
    # host-only (no Domain), so it rides credentialed fetches and the WS handshake to the API
    # host alone; Lax because web and API are one site
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=int(_config.session_max_age.total_seconds()),
        path="/",
        secure=_config.cookie_secure,
        httponly=True,
        samesite="lax",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        COOKIE_NAME, path="/", secure=_config.cookie_secure, httponly=True, samesite="lax"
    )


def me_response(user: User) -> MeResponse:
    return MeResponse(
        id=user.id,
        display_name=user.display_name,
        created_at=user.created_at,
        training_consent_at=user.training_consent_at,
        consent_version=user.consent_version,
    )


@router.get("/me")
async def get_me(user: CurrentUser) -> MeResponse:
    return me_response(user)


@router.patch("/me")
async def patch_me(body: MePatch, user: CurrentUser, db: Db) -> MeResponse:
    if body.prefs is not None:
        await update_prefs(db, user.id, body.prefs.model_dump(exclude_unset=True))
    if body.display_name is not None:
        name = clean_name(body.display_name)
        if name is None:
            raise HTTPException(status_code=422, detail="display_name is empty")
        user.display_name = name
    if body.training_consent is True and user.consent_version != TRAINING_CONSENT_VERSION:
        user.training_consent_at = now()
        user.consent_version = TRAINING_CONSENT_VERSION
    elif body.training_consent is False:
        user.training_consent_at = None
        user.consent_version = None
    await db.commit()
    return me_response(user)


@router.delete("/me", status_code=204)
async def delete_me(user: CurrentUser, db: Db, response: Response) -> None:
    """Immediate and final; the web asks for a typed confirmation first."""
    await delete_user(db, user)
    clear_session_cookie(response)


@router.get("/me/export")
async def export_me(user: CurrentUser, db: Db, response: Response) -> ExportResponse:
    # per account, not per ip: players behind one nat share an ip
    key = str(user.id)
    if _export_limiter is not None and not _export_limiter.allow(key):
        raise HTTPException(
            status_code=429,
            detail="too many exports, try again later",
            headers={"Retry-After": str(_export_limiter.retry_after(key))},
        )
    response.headers["Content-Disposition"] = 'attachment; filename="mahjong-account.json"'
    learn = await learn_response(db, user.id)
    imported_at = await learn_imported_at(db, user.id)
    return ExportResponse(
        user=ExportUser(
            id=user.id,
            display_name=user.display_name,
            created_at=user.created_at,
            training_consent_at=user.training_consent_at,
            consent_version=user.consent_version,
            disabled_at=user.disabled_at,
            learn_imported_at=imported_at,
        ),
        identities=[
            ExportIdentity(
                provider=i.provider, subject=i.subject, email=i.email, created_at=i.created_at
            )
            for i in await identities_of(db, user)
        ],
        games=[
            ExportGame(
                game_id=game.id,
                created_at=game.created_at,
                mode=game.mode,
                seat=seat.seat,
                hand_count=game.hand_count,
                final_score=seat.final_score,
                placement=seat.placement,
                players=game.players,
            )
            for seat, game in await seats_of(db, user)
        ],
        learn=learn,
    )


def _lesson_out(row: LearnProgress) -> LessonProgressOut:
    return LessonProgressOut(
        solved=row.solved,
        attempts=row.attempts,
        solved_at=row.solved_at,
        step=row.step,
        imported=row.imported,
    )


def _endless_out(row: LearnEndlessScore) -> EndlessScoreOut:
    return EndlessScoreOut(
        streak=row.streak, best=row.best, solved=row.solved, imported=row.imported
    )


async def learn_response(db: AsyncSession, user_id: uuid.UUID) -> LearnResponse:
    progress, endless, prefs = await learn_of(db, user_id)
    return LearnResponse(
        progress={row.lesson_id: _lesson_out(row) for row in progress},
        endless={row.kind: _endless_out(row) for row in endless},
        prefs=prefs,
    )


@router.get("/me/learn")
async def get_learn(user: CurrentUser, db: Db) -> LearnResponse:
    return await learn_response(db, user.id)


def _clamped(entry: object) -> object:
    """An upload entry with every count above `MAX_LEARN_COUNT` lowered to it."""
    if not isinstance(entry, dict):
        return entry
    return {
        key: min(value, MAX_LEARN_COUNT) if type(value) is int and key in _COUNT_FIELDS else value
        for key, value in entry.items()
    }


def _valid[T: BaseModel](model: type[T], entry: object) -> T | None:
    try:
        return model.model_validate(_clamped(entry))
    except ValidationError:
        return None


@router.post("/me/learn/import")
async def import_learn_progress(
    body: LearnImport, user: CurrentUser, db: Db
) -> LearnImportResponse:
    """A device's one-time upload of its guest progress. Each entry is validated on its own; a
    bad one is dropped (and counted), never the whole upload."""
    key = str(user.id)
    if _import_limiter is not None and not _import_limiter.allow(key):
        raise HTTPException(
            status_code=429,
            detail="too many uploads, try again later",
            headers={"Retry-After": str(_import_limiter.retry_after(key))},
        )
    at = now()
    dropped = 0
    progress: dict[str, LessonValues] = {}
    for lesson_id, entry in body.progress.items():
        parsed = _valid(LessonProgressIn, entry)
        values = None
        if parsed is not None:
            values = check_lesson(
                lesson_id,
                LessonValues(parsed.solved, parsed.attempts, parsed.solved_at, parsed.step),
                at,
            )
        if values is None:
            dropped += 1
        else:
            progress[lesson_id] = values
    endless: dict[str, EndlessValues] = {}
    for kind, entry in body.endless.items():
        score = _valid(EndlessScoreIn, entry)
        if score is None or kind not in _PUZZLE_KINDS:
            dropped += 1
        else:
            endless[kind] = EndlessValues(score.streak, score.best, score.solved)
    prefs: dict[str, Any] = {}
    for name, value in body.prefs.items():
        pref = _valid(PrefsPatch, {name: value})
        if pref is None or value is None:
            dropped += 1
        else:
            prefs |= pref.model_dump(exclude_unset=True)
    user_id = user.id
    try:
        await import_learn(db, user_id, progress=progress, endless=endless, prefs=prefs, now=at)
    except IntegrityError as exc:
        # a concurrent write inserted one of the rows; the device keeps its copy and retries
        raise HTTPException(status_code=409, detail="progress changed, try again") from exc
    learn = await learn_response(db, user_id)
    return LearnImportResponse(**learn.model_dump(), dropped=dropped)


@router.put("/me/learn/endless/{kind}")
async def put_endless(
    kind: PuzzleKind, body: EndlessScoreIn, user: CurrentUser, db: Db
) -> EndlessScoreOut:
    values = EndlessValues(body.streak, body.best, body.solved)
    return _endless_out(await record_endless(db, user.id, kind, values, now()))


@router.put("/me/learn/{lesson_id}")
async def put_lesson(
    lesson_id: str, body: LessonProgressIn, user: CurrentUser, db: Db
) -> LessonProgressOut:
    values = check_lesson(
        lesson_id, LessonValues(body.solved, body.attempts, body.solved_at, body.step), now()
    )
    if values is None:
        raise HTTPException(status_code=422, detail="unknown lesson, or a bad step or solved_at")
    return _lesson_out(await record_lesson(db, user.id, lesson_id, values, now()))


@router.get("/me/games")
async def my_games(
    user: CurrentUser,
    db: Db,
    before: Annotated[int | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_GAMES_PAGE)] = DEFAULT_GAMES_PAGE,
    mode: Annotated[GameMode | None, Query()] = None,
) -> MyGamesResponse:
    # one extra row says whether another page exists
    rows = await seats_of(db, user, before=before, limit=limit + 1, mode=mode)
    page = rows[:limit]
    players = {game.id: game.players for _, game in page}
    own_seat = {game.id: own.seat for own, game in page}
    others: dict[int, list[MyGameSeat]] = {}
    for seat in sorted(await seats_in(db, list(players)), key=lambda s: s.seat):
        if seat.seat == own_seat[seat.game_id]:
            continue
        others.setdefault(seat.game_id, []).append(
            MyGameSeat(
                seat=seat.seat,
                kind=seat.kind,
                name=None if seat.kind == "bot" else players[seat.game_id][seat.seat],
                bot_tier=seat.bot_tier,
            )
        )
    return MyGamesResponse(
        games=[
            MyGame(
                game_id=game.id,
                created_at=game.created_at,
                mode=game.mode,
                hand_count=game.hand_count,
                seat=own.seat,
                placement=own.placement,
                final_score=own.final_score,
                others=others.get(game.id, []),
            )
            for own, game in page
        ],
        next=page[-1][1].id if len(rows) > limit else None,
    )


@auth_router.post("/logout", status_code=204)
async def logout(db: Db, response: Response, token: SessionCookie = None) -> None:
    if token is not None:
        await revoke_session(db, token)
    clear_session_cookie(response)


def _safe_next(raw: str | None) -> str:
    """A same-origin path on the web, or `/`: never `//host` or a scheme (open redirect)."""
    if (
        not raw
        or len(raw) > _MAX_NEXT_LENGTH
        or not raw.startswith("/")
        or raw.startswith("//")
        or "\\" in raw
    ):
        return "/"
    return raw


def _web_redirect(path: str, **flags: str) -> RedirectResponse:
    query = urlencode(flags)
    if query:
        path = f"{path}{'&' if '?' in path else '?'}{query}"
    return RedirectResponse(f"{_config.web_url}{path}", status_code=303)


def _google_or_404() -> GoogleProvider:
    if _google is None or _session_factory is None:
        raise HTTPException(status_code=404)
    return _google


def _callback_url() -> str:
    return f"{_config.api_url}/auth/google/callback"


@auth_router.get("/google/login")
async def google_login(next: str | None = None) -> RedirectResponse:
    """Start sign-in: PKCE verifier, `state` and the return path ride a short-lived cookie
    scoped to the callback, then the browser goes to Google's consent screen."""
    google = _google_or_404()
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    response = RedirectResponse(
        google.authorize_url(redirect_uri=_callback_url(), state=state, code_verifier=verifier),
        status_code=302,
    )
    response.set_cookie(
        _OAUTH_COOKIE,
        # token_urlsafe never contains '.', so the path after the second one is `next` verbatim
        f"{state}.{verifier}.{_safe_next(next)}",
        max_age=_OAUTH_COOKIE_MAX_AGE_SECONDS,
        path=_OAUTH_COOKIE_PATH,
        secure=_config.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response


OAuthCookie = Annotated[str | None, Cookie(alias=_OAUTH_COOKIE)]


@auth_router.get("/google/callback")
async def google_callback(
    db: Db,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    pending: OAuthCookie = None,
    token: SessionCookie = None,
) -> RedirectResponse:
    """Finish sign-in: check `state`, exchange the code with the PKCE verifier, upsert the user
    by `(google, sub)`, issue a fresh session and send the browser back to the web. A first
    sign-in adds `signup=1`, so the web can show its sign-up step."""
    google = _google_or_404()
    parts = (pending or "").split(".", 2)
    if len(parts) != 3 or state is None or not secrets.compare_digest(parts[0], state):
        raise HTTPException(status_code=400, detail="sign-in expired or was tampered with")
    _, verifier, next_path = parts
    if error is not None or code is None:
        response = _web_redirect(next_path, signin="failed")
    else:
        try:
            profile = await google.fetch_profile(
                redirect_uri=_callback_url(), code=code, code_verifier=verifier
            )
        except Exception as exc:
            logger.warning("google sign-in failed: %r", exc)
            raise HTTPException(status_code=502, detail="google sign-in failed") from exc
        user, created = await upsert_identity(
            db, provider=PROVIDER, subject=profile.subject, email=profile.email
        )
        if user.disabled_at is not None:
            await drop_sessions(db, user)
            response = _web_redirect(next_path, signin="disabled")
        else:
            new_token = await issue_session(
                db, user.id, now=now(), max_age=_config.session_max_age, replacing=token
            )
            response = _web_redirect(next_path, **({"signup": "1"} if created else {}))
            set_session_cookie(response, new_token)
    response.delete_cookie(
        _OAUTH_COOKIE,
        path=_OAUTH_COOKIE_PATH,
        secure=_config.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response
