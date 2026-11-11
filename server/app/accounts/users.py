"""Account rows: sign-in upsert by provider identity, deletion, export reads
and "my games" (docs/decisions/0028-user-account-schema.md)."""

from __future__ import annotations

import datetime as dt
import secrets
import string
from typing import NamedTuple

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuthSession, GameMode, GameRecord, GameSeat, Identity, User
from app.names import clean_name

# a new account's name until the sign-up step renames it. not the provider's profile name: that
# is usually a real name, and games.players keeps it after the account is deleted
_PLACEHOLDER_PREFIX = "Player"
_PLACEHOLDER_DIGITS = 4


def placeholder_name() -> str:
    """`Player 0427`: identifies nobody, and the digits tell two new players apart."""
    digits = "".join(secrets.choice(string.digits) for _ in range(_PLACEHOLDER_DIGITS))
    name = clean_name(f"{_PLACEHOLDER_PREFIX} {digits}")
    assert name is not None
    return name


class GameSummary(NamedTuple):
    """The `games` columns a listing reads: never `action_log`, `ruleset` or all of `result`."""

    id: int
    created_at: dt.datetime
    mode: GameMode | None
    players: list[str | None]
    hand_count: int | None


async def upsert_identity(
    db: AsyncSession,
    *,
    provider: str,
    subject: str,
    email: str | None,
    picture: str | None = None,
) -> tuple[User, bool]:
    """The user behind `(provider, subject)`, created on first sign-in with a placeholder name;
    `email` and the user's `avatar_url` are refreshed every time. Returns `(user, created)`.
    Commits."""
    identity = await db.get(Identity, (provider, subject))
    if identity is not None:
        return await _returning(db, identity, email, picture), False
    user = User(display_name=placeholder_name(), avatar_url=picture)
    db.add(user)
    try:
        await db.flush()
        db.add(Identity(provider=provider, subject=subject, user_id=user.id, email=email))
        await db.commit()
    except IntegrityError:
        # a concurrent first sign-in for the same subject inserted it first
        await db.rollback()
        identity = await db.get(Identity, (provider, subject))
        if identity is None:
            raise
        return await _returning(db, identity, email, picture), False
    return user, True


async def _returning(
    db: AsyncSession, identity: Identity, email: str | None, picture: str | None
) -> User:
    identity.email = email
    user = await db.get(User, identity.user_id)
    assert user is not None  # identities.user_id is a cascading foreign key
    user.avatar_url = picture
    await db.commit()
    return user


async def drop_sessions(db: AsyncSession, user: User) -> None:
    await db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    await db.commit()


async def delete_user(db: AsyncSession, user: User) -> None:
    """Immediate account deletion: identities and sessions cascade; the user's seats in past
    games keep `kind = 'user'` with a null `user_id` (ON DELETE SET NULL)."""
    await db.execute(delete(User).where(User.id == user.id))
    await db.commit()


async def identities_of(db: AsyncSession, user: User) -> list[Identity]:
    rows = await db.scalars(
        select(Identity).where(Identity.user_id == user.id).order_by(Identity.created_at)
    )
    return list(rows.all())


async def seats_of(
    db: AsyncSession,
    user: User,
    *,
    before: int | None = None,
    limit: int | None = None,
    mode: GameMode | None = None,
) -> list[tuple[GameSeat, GameSummary]]:
    """The user's seats with their games, newest game first; `before` is a keyset cursor (a
    game id), served by the partial index `(user_id, game_id DESC)`."""
    query = (
        select(
            GameSeat,
            GameRecord.id,
            GameRecord.created_at,
            GameRecord.mode,
            GameRecord.players,
            GameRecord.result["hand_count"].as_integer(),
        )
        .join(GameRecord, GameRecord.id == GameSeat.game_id)
        .where(GameSeat.user_id == user.id)
        .order_by(GameSeat.game_id.desc())
        .limit(limit)
    )
    if before is not None:
        query = query.where(GameSeat.game_id < before)
    if mode is not None:
        query = query.where(GameRecord.mode == mode)
    rows = await db.execute(query)
    return [(seat, GameSummary(*game)) for seat, *game in rows.all()]


async def seats_in(db: AsyncSession, game_ids: list[int]) -> list[GameSeat]:
    """Every seat row of these games."""
    if not game_ids:
        return []
    return list(await db.scalars(select(GameSeat).where(GameSeat.game_id.in_(game_ids))))
