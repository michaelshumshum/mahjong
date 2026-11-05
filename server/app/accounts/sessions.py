"""Session cookies backed by the `sessions` table (docs/decisions/0028-user-account-schema.md).

The cookie carries a random token; the row is keyed by its SHA-256, so a database leak can't be
replayed. A session ends at `expires_at` (absolute) or once `last_used_at` is older than the
idle window. Sign-out and revocation are a row delete.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets
import uuid
from typing import Final

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuthSession, User

COOKIE_NAME: Final = "mj_session"
TOKEN_BYTES: Final = 32
# last_used_at is written at most this often, so a busy session isn't a write per request
TOUCH_INTERVAL: Final = dt.timedelta(hours=1)


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def _utc(value: dt.datetime) -> dt.datetime:
    # sqlite hands DateTime(timezone=True) back naive; every stored value is utc
    return value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)


async def issue_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    now: dt.datetime,
    max_age: dt.timedelta,
    replacing: str | None = None,
) -> str:
    """A new session for `user_id`; returns the cookie token. `replacing` is the token the
    browser already held, deleted in the same commit (a fresh token at every sign-in)."""
    if replacing is not None:
        await db.execute(delete(AuthSession).where(AuthSession.id_hash == hash_token(replacing)))
    token = secrets.token_urlsafe(TOKEN_BYTES)
    db.add(
        AuthSession(
            id_hash=hash_token(token),
            user_id=user_id,
            created_at=now,
            last_used_at=now,
            expires_at=now + max_age,
        )
    )
    await db.commit()
    return token


async def resolve_session(
    db: AsyncSession, token: str, *, now: dt.datetime, idle: dt.timedelta
) -> User | None:
    """The signed-in user for `token`, or None. An expired session is deleted on sight; a
    disabled user loses every session."""
    row = (
        await db.execute(
            select(AuthSession, User)
            .join(User, User.id == AuthSession.user_id)
            .where(AuthSession.id_hash == hash_token(token))
        )
    ).first()
    if row is None:
        return None
    auth, user = row
    if user.disabled_at is not None:
        await db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
        await db.commit()
        return None
    last_used = _utc(auth.last_used_at)
    if now >= _utc(auth.expires_at) or now - last_used >= idle:
        await db.delete(auth)
        await db.commit()
        return None
    if now - last_used >= TOUCH_INTERVAL:
        auth.last_used_at = now
        await db.commit()
    return user


async def revoke_session(db: AsyncSession, token: str) -> None:
    await db.execute(delete(AuthSession).where(AuthSession.id_hash == hash_token(token)))
    await db.commit()


async def delete_expired_sessions(db: AsyncSession, *, now: dt.datetime, idle: dt.timedelta) -> int:
    """Delete every session past its absolute or idle expiry; returns how many."""
    result = await db.execute(
        delete(AuthSession).where(
            or_(AuthSession.expires_at <= now, AuthSession.last_used_at <= now - idle)
        )
    )
    await db.commit()
    return result.rowcount
