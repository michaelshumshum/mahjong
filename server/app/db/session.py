"""Async SQLAlchemy engine/session factory. Doesn't read `DATABASE_URL` itself -- callers pass
the URL explicitly, so a test can point at SQLite without touching the environment.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

__all__ = ["make_engine", "make_session_factory"]


def make_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
