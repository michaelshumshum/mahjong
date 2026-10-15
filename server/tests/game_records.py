"""Reads persisted `GameRecord`s back for e2e tests."""

import asyncio

from sqlalchemy import select

from app.db.models import GameRecord
from app.db.session import make_engine, make_session_factory


def fetch_latest_record(database_url: str) -> GameRecord | None:
    async def _run() -> GameRecord | None:
        engine = make_engine(database_url)
        try:
            factory = make_session_factory(engine)
            async with factory() as session:
                result = await session.execute(select(GameRecord).order_by(GameRecord.id.desc()))
                return result.scalars().first()
        finally:
            await engine.dispose()

    return asyncio.run(_run())
