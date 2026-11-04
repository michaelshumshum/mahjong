"""`/auth/*` and `/me*` (docs/protocol.md §10 "Accounts"). Every route 404s unless
`ACCOUNTS_ENABLED` is on and a database is configured, so the feature is invisible in prod until
ADR 0028 phase 7."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.accounts.config import AccountsConfig
from app.accounts.sessions import (
    COOKIE_NAME,
    delete_expired_sessions,
    resolve_session,
    revoke_session,
)
from app.api_models import MeResponse
from app.db.models import User

__all__ = ["configure", "router", "run_session_cleanup"]

_CLEANUP_INTERVAL_SECONDS = 3600.0

logger = logging.getLogger(__name__)

router = APIRouter()
_config = AccountsConfig.from_env({})
_session_factory: async_sessionmaker[AsyncSession] | None = None


def configure(
    config: AccountsConfig, session_factory: async_sessionmaker[AsyncSession] | None
) -> bool:
    """Called from `lifespan`; returns whether accounts are live."""
    global _config, _session_factory
    if config.enabled and session_factory is None:
        logger.warning("ACCOUNTS_ENABLED without DATABASE_URL: accounts stay off")
    _config = config
    _session_factory = session_factory if config.enabled else None
    return _session_factory is not None


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


@router.post("/auth/logout", status_code=204)
async def logout(db: Db, response: Response, token: SessionCookie = None) -> None:
    if token is not None:
        await revoke_session(db, token)
    clear_session_cookie(response)
