"""`users`, `identities`, `sessions` and the `game_players.user_id` foreign key
(docs/decisions/0028-user-account-schema.md "Foreign keys", "Indexes")."""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from typing import Any

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuthSession, GameRecord, GameSeat, Identity, User

_NOW = dt.datetime(2026, 11, 5, tzinfo=dt.UTC)


async def _user(session: AsyncSession, **overrides: Any) -> User:
    user = User(**({"display_name": "Ann"} | overrides))
    session.add(user)
    await session.commit()
    return user


def _auth_session(user_id: uuid.UUID, token: bytes = b"t") -> AuthSession:
    return AuthSession(
        id_hash=hashlib.sha256(token).digest(),
        user_id=user_id,
        created_at=_NOW,
        last_used_at=_NOW,
        expires_at=_NOW + dt.timedelta(days=90),
    )


async def _game_with_seat(session: AsyncSession, user_id: uuid.UUID | None) -> GameRecord:
    game = GameRecord(
        engine_version="test",
        ruleset={},
        seed=1,
        action_log=[],
        players=["Ann", None, None, None],
        result={},
    )
    session.add(game)
    await session.commit()
    session.add(
        GameSeat(game_id=game.id, seat=0, kind="user", user_id=user_id, final_score=0, placement=1)
    )
    await session.commit()
    return game


async def test_a_user_gets_a_uuid_and_created_at(session: AsyncSession) -> None:
    user = await _user(session)
    assert isinstance(user.id, uuid.UUID)
    fetched = await session.get(User, user.id)
    assert fetched is not None
    assert fetched.created_at is not None
    assert fetched.training_consent_at is None
    assert fetched.consent_version is None
    assert fetched.disabled_at is None


async def test_an_identity_is_keyed_by_provider_and_subject(session: AsyncSession) -> None:
    ann = await _user(session)
    bob = await _user(session, display_name="Bob")
    session.add(Identity(provider="google", subject="123", user_id=ann.id, email="a@x.test"))
    await session.commit()
    session.expunge_all()

    session.add(Identity(provider="google", subject="123", user_id=bob.id, email=None))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_deleting_a_user_cascades_identities_and_sessions(session: AsyncSession) -> None:
    user = await _user(session)
    session.add_all(
        [Identity(provider="google", subject="1", user_id=user.id), _auth_session(user.id)]
    )
    await session.commit()

    await session.execute(delete(User).where(User.id == user.id))
    await session.commit()

    assert (await session.scalars(select(Identity))).all() == []
    assert (await session.scalars(select(AuthSession))).all() == []


async def test_deleting_a_user_keeps_their_seat_as_kind_user(session: AsyncSession) -> None:
    user = await _user(session)
    game = await _game_with_seat(session, user.id)

    await session.execute(delete(User).where(User.id == user.id))
    await session.commit()
    session.expunge_all()

    seat = await session.get(GameSeat, (game.id, 0))
    assert seat is not None
    assert (seat.kind, seat.user_id) == ("user", None)


async def test_a_seat_must_name_an_existing_user(session: AsyncSession) -> None:
    with pytest.raises(IntegrityError):
        await _game_with_seat(session, uuid.uuid4())


async def test_a_session_stores_only_the_32_byte_hash(session: AsyncSession) -> None:
    user = await _user(session)
    session.add(_auth_session(user.id, b"secret"))
    await session.commit()
    [row] = (await session.scalars(select(AuthSession))).all()
    assert row.id_hash == hashlib.sha256(b"secret").digest()
    assert len(row.id_hash) == 32


async def test_cascade_and_cleanup_indexes_exist(session: AsyncSession) -> None:
    rows = (
        await session.execute(
            text(
                "SELECT tbl_name, sql FROM sqlite_master"
                " WHERE type = 'index' AND tbl_name IN ('identities', 'sessions')"
                " AND sql IS NOT NULL"
            )
        )
    ).all()
    columns = sorted((tbl, sql.split("(", 1)[1].rstrip(")")) for tbl, sql in rows)
    assert columns == [
        ("identities", "user_id"),
        ("sessions", "expires_at"),
        ("sessions", "user_id"),
    ]
