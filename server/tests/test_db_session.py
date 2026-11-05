"""`make_engine` (docs/decisions/0028-user-account-schema.md "Types and tests")."""

from __future__ import annotations

import pytest
from sqlalchemy import Column, ForeignKey, Integer, MetaData, Table, insert, select, text
from sqlalchemy.exc import IntegrityError

from app.db.session import make_engine

_metadata = MetaData()
_parent = Table("parent", _metadata, Column("id", Integer, primary_key=True))
_child = Table(
    "child",
    _metadata,
    Column("id", Integer, primary_key=True),
    Column("parent_id", Integer, ForeignKey("parent.id", ondelete="CASCADE"), nullable=False),
)


async def test_sqlite_engine_enables_foreign_keys() -> None:
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.connect() as conn:
            assert await conn.scalar(text("PRAGMA foreign_keys")) == 1
    finally:
        await engine.dispose()


async def test_sqlite_engine_rejects_a_dangling_foreign_key() -> None:
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(_metadata.create_all)
        async with engine.connect() as conn:
            with pytest.raises(IntegrityError):
                await conn.execute(insert(_child).values(id=1, parent_id=99))
    finally:
        await engine.dispose()


async def test_sqlite_engine_cascades_deletes() -> None:
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(_metadata.create_all)
            await conn.execute(insert(_parent).values(id=1))
            await conn.execute(insert(_child).values(id=1, parent_id=1))
            await conn.execute(_parent.delete().where(_parent.c.id == 1))
            assert (await conn.execute(select(_child))).all() == []
    finally:
        await engine.dispose()
