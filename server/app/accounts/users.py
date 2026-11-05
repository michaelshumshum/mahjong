"""Account rows: sign-in upsert by provider identity (docs/decisions/0028-user-account-schema.md)."""

from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuthSession, Identity, User
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
