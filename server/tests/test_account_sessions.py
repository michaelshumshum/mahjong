"""Session cookies: issue, resolve, idle and absolute expiry, touch, rotation, disabled users,
cleanup (docs/decisions/0028-user-account-schema.md "Decisions", docs/protocol.md §10)."""

from __future__ import annotations

import datetime as dt
import hashlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.sessions import (
    TOUCH_INTERVAL,
    delete_expired_sessions,
    hash_token,
    issue_session,
    resolve_session,
    revoke_session,
)
from app.db.models import AuthSession, User

_T0 = dt.datetime(2026, 11, 5, 12, tzinfo=dt.UTC)
_MAX_AGE = dt.timedelta(days=90)
_IDLE = dt.timedelta(days=30)


async def _user(session: AsyncSession, **overrides: object) -> User:
    user = User(**({"display_name": "Ann"} | overrides))
    session.add(user)
    await session.commit()
    return user


async def _issue(session: AsyncSession, user: User, now: dt.datetime = _T0) -> str:
    return await issue_session(session, user.id, now=now, max_age=_MAX_AGE)


async def _resolve(session: AsyncSession, token: str, now: dt.datetime) -> User | None:
    return await resolve_session(session, token, now=now, idle=_IDLE)


async def _rows(session: AsyncSession) -> list[AuthSession]:
    return list((await session.scalars(select(AuthSession))).all())


async def test_issue_stores_only_the_hash_of_a_fresh_token(session: AsyncSession) -> None:
    user = await _user(session)
    token = await _issue(session, user)
    again = await _issue(session, user)

    assert token != again
    assert len(token) >= 43  # 32 random bytes, urlsafe base64
    assert hash_token(token) == hashlib.sha256(token.encode()).digest()
    [first, second] = await _rows(session)
    assert {first.id_hash, second.id_hash} == {hash_token(token), hash_token(again)}
    assert token.encode() not in (first.id_hash, second.id_hash)


async def test_resolve_finds_the_user(session: AsyncSession) -> None:
    user = await _user(session)
    token = await _issue(session, user)
    resolved = await _resolve(session, token, _T0 + dt.timedelta(minutes=1))
    assert resolved is not None and resolved.id == user.id


async def test_an_unknown_token_resolves_to_nobody(session: AsyncSession) -> None:
    assert await _resolve(session, "nope", _T0) is None


async def test_absolute_expiry(session: AsyncSession) -> None:
    user = await _user(session)
    token = await _issue(session, user)
    # used every day, so idle never trips, but the 90-day cap still does
    day = _T0
    while day < _T0 + _MAX_AGE - dt.timedelta(days=1):
        day += dt.timedelta(days=1)
        assert await _resolve(session, token, day) is not None
    assert await _resolve(session, token, _T0 + _MAX_AGE) is None
    assert await _rows(session) == []


async def test_idle_expiry(session: AsyncSession) -> None:
    user = await _user(session)
    token = await _issue(session, user)
    assert await _resolve(session, token, _T0 + _IDLE - dt.timedelta(seconds=1)) is not None
    later = _T0 + _IDLE - dt.timedelta(seconds=1) + _IDLE
    assert await _resolve(session, token, later) is None


async def test_last_used_is_written_at_most_hourly(session: AsyncSession) -> None:
    user = await _user(session)
    token = await _issue(session, user)

    await _resolve(session, token, _T0 + TOUCH_INTERVAL - dt.timedelta(seconds=1))
    [row] = await _rows(session)
    assert row.last_used_at == _T0

    await _resolve(session, token, _T0 + TOUCH_INTERVAL)
    [row] = await _rows(session)
    assert row.last_used_at == _T0 + TOUCH_INTERVAL


async def test_rotation_replaces_the_old_session(session: AsyncSession) -> None:
    user = await _user(session)
    old = await _issue(session, user)
    new = await issue_session(session, user.id, now=_T0, max_age=_MAX_AGE, replacing=old)

    assert await _resolve(session, old, _T0) is None
    assert await _resolve(session, new, _T0) is not None
    assert len(await _rows(session)) == 1


async def test_a_disabled_user_resolves_to_nobody_and_loses_sessions(
    session: AsyncSession,
) -> None:
    user = await _user(session)
    token = await _issue(session, user)
    await _issue(session, user)
    user.disabled_at = _T0
    await session.commit()

    assert await _resolve(session, token, _T0) is None
    assert await _rows(session) == []


async def test_revoke_deletes_the_row(session: AsyncSession) -> None:
    user = await _user(session)
    token = await _issue(session, user)
    await revoke_session(session, token)
    assert await _rows(session) == []
    await revoke_session(session, token)  # already gone: no error


async def test_cleanup_deletes_only_expired_rows(session: AsyncSession) -> None:
    user = await _user(session)
    live = await _issue(session, user, now=_T0)
    await _issue(session, user, now=_T0 - _MAX_AGE)  # absolute
    await _issue(session, user, now=_T0 - dt.timedelta(days=40))  # idle

    deleted = await delete_expired_sessions(session, now=_T0, idle=_IDLE)

    assert deleted == 2
    assert [r.id_hash for r in await _rows(session)] == [hash_token(live)]
