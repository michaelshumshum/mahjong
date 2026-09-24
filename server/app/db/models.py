"""SQLAlchemy models for durable game records. Only `games` exists so far.

JSON columns use `JSONB` on Postgres, generic `JSON` elsewhere (`.with_variant`) -- SQLite
(tests) has no JSONB.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import JSON as GenericJSON
from sqlalchemy import BigInteger, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JSONType = GenericJSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class GameRecord(Base):
    """One finished game. `ruleset` stores the full body, not a hash -- a hash can't be replayed.
    `engine_version` is stored but not gated here; `app/db/records.is_replayable` checks it at
    read time.
    """

    __tablename__ = "games"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engine_version: Mapped[str] = mapped_column(String(32), nullable=False)
    ruleset: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    action_log: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, nullable=False)
    players: Mapped[list[str | None]] = mapped_column(JSONType, nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
