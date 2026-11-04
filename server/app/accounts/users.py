"""Account rows: sign-in upsert by provider identity, deletion, export reads
(docs/decisions/0028-user-account-schema.md)."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuthSession, GameRecord, GameSeat, Identity, User
from app.names import clean_name

# a provider profile with no usable name
DEFAULT_DISPLAY_NAME = "Player"


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


async def seats_of(db: AsyncSession, user: User) -> list[tuple[GameSeat, GameRecord]]:
    """The user's seats with their games, newest game first."""
    rows = await db.execute(
        select(GameSeat, GameRecord)
        .join(GameRecord, GameRecord.id == GameSeat.game_id)
        .where(GameSeat.user_id == user.id)
        .order_by(GameSeat.game_id.desc())
    )
    return [(seat, game) for seat, game in rows.all()]
