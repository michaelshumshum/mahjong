"""Accounts test helpers over a file-backed SQLite `DATABASE_URL` (the `accounts_db` fixture in
`conftest.py`): seed a user, sign one in without Google."""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from typing import Any

from sqlalchemy import select

from app.accounts.sessions import issue_session
from app.db.models import AuthSession, Base, User
from app.db.session import make_engine, make_session_factory

MAX_AGE = dt.timedelta(days=90)


def _run[T](database_url: str, work: Any) -> T:
    async def _go() -> T:
        engine = make_engine(database_url)
        try:
            async with make_session_factory(engine)() as db:
                return await work(db)
        finally:
            await engine.dispose()

    return asyncio.run(_go())


def create_schema(database_url: str) -> None:
    async def _go() -> None:
        engine = make_engine(database_url)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        finally:
            await engine.dispose()

    asyncio.run(_go())


def create_user(database_url: str, **columns: Any) -> uuid.UUID:
    async def work(db: Any) -> uuid.UUID:
        user = User(**({"display_name": "Ann"} | columns))
        db.add(user)
        await db.commit()
        return user.id

    return _run(database_url, work)


def sign_in(database_url: str, user_id: uuid.UUID, now: dt.datetime | None = None) -> str:
    """A session token for `user_id`, as the OAuth callback would issue."""

    async def work(db: Any) -> str:
        return await issue_session(db, user_id, now=now or dt.datetime.now(dt.UTC), max_age=MAX_AGE)

    return _run(database_url, work)


def session_count(database_url: str) -> int:
    async def work(db: Any) -> int:
        return len((await db.scalars(select(AuthSession))).all())

    return _run(database_url, work)


def fetch[T](database_url: str, model: type[T], *pk: Any) -> T | None:
    async def work(db: Any) -> T | None:
        return await db.get(model, pk[0] if len(pk) == 1 else pk)

    return _run(database_url, work)
