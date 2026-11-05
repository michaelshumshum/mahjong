"""An account's learn progress (docs/decisions/0028-user-account-schema.md "Learn progress: guest
vs signed in"): reads, server-recorded writes, and the merge for a device's one-time upload."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, NamedTuple

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    USER_LEARN_IMPORTED_AT,
    USER_PREFS,
    LearnEndlessScore,
    LearnProgress,
    User,
)
from app.lessons.catalog import LESSON_IDS, TUTORIAL_IDS

# attempts, a tutorial step and endless counts; far past any real player
MAX_LEARN_COUNT = 100_000
# a client clock this far ahead still records a solve "now"; further is rejected
CLOCK_SKEW = dt.timedelta(minutes=5)


class LessonValues(NamedTuple):
    solved: bool
    attempts: int
    solved_at: dt.datetime | None
    step: int | None


class EndlessValues(NamedTuple):
    streak: int
    best: int
    solved: int


def check_lesson(lesson_id: str, values: LessonValues, now: dt.datetime) -> LessonValues | None:
    """`values` for a known lesson with `solved_at` clamped to `now`, or None when the lesson is
    unknown, a puzzle carries a step or `solved_at` is in the future. Field-level rules (counts,
    solved => attempts) are the request model's."""
    if lesson_id not in LESSON_IDS:
        return None
    if values.step is not None and lesson_id not in TUTORIAL_IDS:
        return None
    if values.solved_at is not None:
        if values.solved_at > now + CLOCK_SKEW:
            return None
        values = values._replace(solved_at=min(values.solved_at, now))
    return values


async def learn_of(
    db: AsyncSession, user_id: uuid.UUID
) -> tuple[list[LearnProgress], list[LearnEndlessScore], dict[str, Any]]:
    progress = await db.scalars(select(LearnProgress).where(LearnProgress.user_id == user_id))
    endless = await db.scalars(
        select(LearnEndlessScore).where(LearnEndlessScore.user_id == user_id)
    )
    return list(progress.all()), list(endless.all()), await prefs_of(db, user_id)


async def prefs_of(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    prefs = await db.scalar(select(USER_PREFS).where(User.id == user_id))
    return dict(prefs or {})


async def learn_imported_at(db: AsyncSession, user_id: uuid.UUID) -> dt.datetime | None:
    return await db.scalar(select(USER_LEARN_IMPORTED_AT).where(User.id == user_id))


async def record_lesson(
    db: AsyncSession,
    user_id: uuid.UUID,
    lesson_id: str,
    values: LessonValues,
    now: dt.datetime,
    *,
    retried: bool = False,
) -> LearnProgress:
    """A server-recorded answer. `solved`, `attempts` and `solved_at` never go backwards (a
    second device's stale copy can't undo a solve); `step` is the latest resume point. A new
    solve clears `imported`."""
    row = await db.get(LearnProgress, (user_id, lesson_id))
    if row is None:
        row = LearnProgress(user_id=user_id, lesson_id=lesson_id, imported=False)
        db.add(row)
        row.solved, row.attempts, row.solved_at = False, 0, None
    if values.solved and not row.solved:
        row.imported = False
    row.solved = row.solved or values.solved
    row.attempts = max(row.attempts, values.attempts)
    row.solved_at = _earliest(row.solved_at, values.solved_at)
    row.step = values.step
    row.updated_at = now
    if not await _committed(db, retry=not retried):
        return await record_lesson(db, user_id, lesson_id, values, now, retried=True)
    return row


async def record_endless(
    db: AsyncSession,
    user_id: uuid.UUID,
    kind: str,
    values: EndlessValues,
    now: dt.datetime,
    *,
    retried: bool = False,
) -> LearnEndlessScore:
    """A server-recorded endless score: `streak` as sent, `best` and `solved` never lower. A
    better `best` clears `imported`."""
    row = await db.get(LearnEndlessScore, (user_id, kind))
    if row is None:
        row = LearnEndlessScore(user_id=user_id, kind=kind, imported=False)
        db.add(row)
        row.best, row.solved = 0, 0
    if values.best > row.best:
        row.imported = False
    row.streak = values.streak
    row.best = max(row.best, values.best)
    row.solved = max(row.solved, values.solved)
    row.updated_at = now
    if not await _committed(db, retry=not retried):
        return await record_endless(db, user_id, kind, values, now, retried=True)
    return row


async def update_prefs(db: AsyncSession, user_id: uuid.UUID, changes: dict[str, Any]) -> None:
    """Set each key in `changes`; a None value removes the key. Doesn't commit."""
    prefs = await prefs_of(db, user_id)
    for key, value in changes.items():
        if value is None:
            prefs.pop(key, None)
        else:
            prefs[key] = value
    users = User.__table__
    await db.execute(update(users).where(users.c.id == user_id).values({USER_PREFS: prefs}))


async def _committed(db: AsyncSession, *, retry: bool) -> bool:
    """False when the commit failed and may be retried once: a concurrent first write (another
    tab) inserted the same row, which the retry then updates."""
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        if not retry:
            raise
        return False
    return True


def _earliest(a: dt.datetime | None, b: dt.datetime | None) -> dt.datetime | None:
    if a is None or b is None:
        return a or b
    return min(a, b)
