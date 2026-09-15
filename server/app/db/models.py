"""SQLAlchemy models for durable game records (docs/00-architecture.md §6, docs/07-infra.md §6).

Only `games` exists so far -- `users`/`leaderboard` (07-infra.md §6) aren't needed for this
sub-task, which is scoped to `GameRecord` persistence only (docs/05-roadmap.md §2's M1 gate).

JSON columns use `JSONB` on Postgres and generic `JSON` everywhere else (SQLite in tests) via
SQLAlchemy's `.with_variant` -- see server/AGENTS.md's testing-strategy note in the commit that
added this file: SQLite has no JSONB, and CI runs natively with no Postgres available.
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
    """One finished game (`Phase.GAME_OVER`), per `docs/06-ml.md §2`'s definition:
    `engine_version`, the full `ruleset` body (not a hash -- a hash can't be replayed),
    `seed`, the ordered action log, and the outcome. `players` and `result` are the extra
    columns `docs/07-infra.md §6`'s table lists alongside `ruleset`/`seed`/`action_log`.

    Replay-invalidation policy (docs/06-ml.md §2): an `engine_version` mismatch against the
    running engine invalidates replay, with no migration path. This table doesn't enforce
    that itself -- `engine_version` is stored, not gated, so an old record is never deleted or
    rewritten -- `app/db/records.is_replayable` is where the check happens, at read time.
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
