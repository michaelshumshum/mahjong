"""Account rows: sign-in upsert by provider identity, deletion, export reads
and "my games" (docs/decisions/0028-user-account-schema.md)."""

from __future__ import annotations

import datetime as dt
from typing import NamedTuple

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuthSession, GameMode, GameRecord, GameSeat, Identity, User
from app.names import clean_name

# a provider profile with no usable name
DEFAULT_DISPLAY_NAME = "Player"


class GameSummary(NamedTuple):
    """The `games` columns a listing reads: never `action_log`, `ruleset` or all of `result`."""

    id: int
    created_at: dt.datetime
    mode: GameMode | None
    players: list[str | None]
    hand_count: int | None


async def upsert_identity(
    db: AsyncSession, *, provider: str, subject: str, email: str | None, name: str | None
) -> tuple[User, bool]:
    """The user behind `(provider, subject)`, created on first sign-in (name from the provider);
    `email` is refreshed every time. Returns `(user, created)`. Commits."""
    identity = await db.get(Identity, (provider, subject))
    if identity is not None:
        identity.email = email
        user = await db.get(User, identity.user_id)
        assert user is not None  # identities.user_id is a cascading foreign key
        await db.commit()
        return user, False
    user = User(display_name=clean_name(name) or DEFAULT_DISPLAY_NAME)
    db.add(user)
    await db.flush()
    db.add(Identity(provider=provider, subject=subject, user_id=user.id, email=email))
    await db.commit()
    return user, True


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
