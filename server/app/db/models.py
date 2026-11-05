"""SQLAlchemy models for durable records: finished games (`games`), who held each seat
(`game_players`), standalone hands (`hand_records`) and optional accounts (`users`,
`identities`, `sessions`, `learn_progress`, `learn_endless_scores`).

JSON columns use `JSONB` on Postgres, generic `JSON` elsewhere (`.with_variant`) -- SQLite
(tests) has no JSONB.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Final, Literal, get_args

from sqlalchemy import JSON as GenericJSON
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    TypeDecorator,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.names import MAX_NAME_LENGTH

JSONType = GenericJSON().with_variant(JSONB(), "postgresql")

SeatKind = Literal["user", "guest", "bot"]
GameMode = Literal["practice", "multiplayer"]
SEAT_KINDS: Final[tuple[SeatKind, ...]] = get_args(SeatKind)
GAME_MODES: Final[tuple[GameMode, ...]] = get_args(GameMode)


class UTCDateTime(TypeDecorator[dt.datetime]):
    """`DateTime(timezone=True)` that reads back tz-aware: SQLite (tests) drops the offset, and
    every value stored is UTC."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(self, value: dt.datetime | None, dialect: Any) -> dt.datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=dt.UTC)
        return value


def _sql_in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class Base(DeclarativeBase):
    pass


class GameRecord(Base):
    """One finished game. `ruleset` stores the full body, not a hash -- a hash can't be replayed.
    `engine_version` is stored but not gated here; `app/db/records.is_replayable` checks it at
    read time.
    """

    __tablename__ = "games"
    __table_args__ = (CheckConstraint(f"mode IN ({_sql_in(GAME_MODES)})", name="ck_games_mode"),)

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
    # null on rows saved before ADR 0028: `players` can't tell a bot seat from an empty one
    mode: Mapped[GameMode | None] = mapped_column(String(16), nullable=True)


class GameSeat(Base):
    """Who held one seat of a finished game: an account, a guest or a bot
    (docs/decisions/0028-user-account-schema.md). Names stay in `games.players`.
    """

    __tablename__ = "game_players"
    __table_args__ = (
        CheckConstraint("seat BETWEEN 0 AND 3", name="ck_game_players_seat"),
        CheckConstraint(f"kind IN ({_sql_in(SEAT_KINDS)})", name="ck_game_players_kind"),
        # user with a null user_id is a deleted account, still distinct from a guest
        CheckConstraint(
            "(kind = 'guest' AND user_id IS NULL AND bot_tier IS NULL)"
            " OR (kind = 'bot' AND user_id IS NULL AND bot_tier IS NOT NULL)"
            " OR (kind = 'user' AND bot_tier IS NULL)",
            name="ck_game_players_kind_pairing",
        ),
        CheckConstraint("placement BETWEEN 1 AND 4", name="ck_game_players_placement"),
        Index(
            "ix_game_players_user_id_game_id",
            "user_id",
            text("game_id DESC"),
            postgresql_where=text("user_id IS NOT NULL"),
            sqlite_where=text("user_id IS NOT NULL"),
        ),
    )

    game_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("games.id", ondelete="CASCADE"), primary_key=True
    )
    seat: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    kind: Mapped[SeatKind] = mapped_column(String(8), nullable=False)
    # SET NULL keeps kind = 'user': a deleted account, still distinct from a guest
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL", name="fk_game_players_user_id_users"),
        nullable=True,
    )
    bot_tier: Mapped[str | None] = mapped_column(String(16), nullable=True)
    final_score: Mapped[int] = mapped_column(Integer, nullable=False)
    placement: Mapped[int] = mapped_column(SmallInteger, nullable=False)


class User(Base):
    """An optional account (docs/decisions/0028-user-account-schema.md). uuid, not serial: ids
    appear in URLs and shouldn't be enumerable.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    display_name: Mapped[str] = mapped_column(String(MAX_NAME_LENGTH), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        UTCDateTime, server_default=func.now(), nullable=False
    )
    # null = no consent to training on this user's games (ADR 0016)
    training_consent_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime, nullable=True)
    consent_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    disabled_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime, nullable=True)
    # `prefs` and `learn_imported_at`: in the table, not on the class (see `USER_PREFS`)


# synced settings (`api_models.PrefsPatch`'s keys), read and written with core
USER_PREFS = Column("prefs", JSONType, nullable=False, server_default=text("'{}'"))
# the last learn-progress upload, audit only
USER_LEARN_IMPORTED_AT = Column("learn_imported_at", UTCDateTime, nullable=True)
# unmapped: a user's select, insert and RETURNING never name them, so sign-in and /me work on
# code deployed before `make prod-migrate` (adr 0028 "pull requests", docs/infra.md §6)
User.__table__.append_column(USER_PREFS)
User.__table__.append_column(USER_LEARN_IMPORTED_AT)


class LearnProgress(Base):
    """One lesson's progress for an account (web `LessonProgress`). `imported` marks values
    that came from a local upload rather than a server-recorded answer (ADR 0028 "Trusting the
    upload")."""

    __tablename__ = "learn_progress"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    lesson_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    solved: Mapped[bool] = mapped_column(Boolean, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    solved_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime, nullable=True)
    # a tutorial's resume point; null for puzzles
    step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    imported: Mapped[bool] = mapped_column(Boolean, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, nullable=False)


class LearnEndlessScore(Base):
    """One puzzle kind's endless score for an account (web `EndlessScore`)."""

    __tablename__ = "learn_endless_scores"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # PuzzleKind, checked by the routes
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    streak: Mapped[int] = mapped_column(Integer, nullable=False)
    best: Mapped[int] = mapped_column(Integer, nullable=False)
    solved: Mapped[int] = mapped_column(Integer, nullable=False)
    imported: Mapped[bool] = mapped_column(Boolean, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, nullable=False)


class Identity(Base):
    """One provider sign-in for a user. `subject` is the provider's stable id; `email` is a
    contact field only, never a key.
    """

    __tablename__ = "identities"
    __table_args__ = (Index("ix_identities_user_id", "user_id"),)

    provider: Mapped[str] = mapped_column(String(16), primary_key=True)
    subject: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        UTCDateTime, server_default=func.now(), nullable=False
    )


class AuthSession(Base):
    """A signed-in browser. The cookie carries a random token; only its SHA-256 is stored, so a
    leaked row can't be replayed.
    """

    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_user_id", "user_id"),
        Index("ix_sessions_expires_at", "expires_at"),
    )

    id_hash: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, nullable=False)
    last_used_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, nullable=False)


class HandRecord(Base):
    """One standalone hand, e.g. an RL evaluation episode (`ml/env.py`): played from
    `engine.new_hand(ruleset, seed, dealer=, prevailing=)` to `HAND_OVER`, so it needs `dealer`/
    `prevailing` to replay and can't live in `games`, which only holds finished games.
    """

    __tablename__ = "hand_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engine_version: Mapped[str] = mapped_column(String(32), nullable=False)
    ruleset: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    dealer: Mapped[int] = mapped_column(Integer, nullable=False)
    prevailing: Mapped[int] = mapped_column(Integer, nullable=False)
    action_log: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, nullable=False)
    players: Mapped[list[str | None]] = mapped_column(JSONType, nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
