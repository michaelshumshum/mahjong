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


def merge_lesson(row: LessonValues | None, upload: LessonValues) -> LessonValues:
    """ADR 0028's merge: solved OR, attempts max, solved_at earliest non-null, step max."""
    if row is None:
        return upload
    steps = [s for s in (row.step, upload.step) if s is not None]
    return LessonValues(
        solved=row.solved or upload.solved,
        attempts=max(row.attempts, upload.attempts),
        solved_at=_earliest(row.solved_at, upload.solved_at),
        step=max(steps) if steps else None,
    )


def merge_endless(row: EndlessValues | None, upload: EndlessValues) -> EndlessValues:
    """best and solved max; the streak stays the server's, the upload's only for a new row."""
    if row is None:
        return upload
    return EndlessValues(
        streak=row.streak, best=max(row.best, upload.best), solved=max(row.solved, upload.solved)
    )


def merge_prefs(prefs: dict[str, Any], upload: dict[str, Any]) -> dict[str, Any]:
    """An uploaded pref fills a key the account hasn't set; `coach_marks_done` is an OR."""
    merged = upload | prefs
    if upload.get("coach_marks_done") is True:
        merged["coach_marks_done"] = True
    return merged


async def import_learn(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    progress: dict[str, LessonValues],
    endless: dict[str, EndlessValues],
    prefs: dict[str, Any],
    now: dt.datetime,
) -> None:
    """Merge a device's validated upload. A row is `imported` once any field took an uploaded
    value; a replayed upload changes no value, so it leaves every row as it was."""
    rows, scores, stored = await learn_of(db, user_id)
    by_lesson = {row.lesson_id: row for row in rows}
    for lesson_id, values in progress.items():
        row = by_lesson.get(lesson_id)
        old = (
            None if row is None else LessonValues(row.solved, row.attempts, row.solved_at, row.step)
        )
        merged = merge_lesson(old, values)
        if merged == old:
            continue
        if row is None:
            row = LearnProgress(user_id=user_id, lesson_id=lesson_id)
            db.add(row)
        row.solved, row.attempts, row.solved_at, row.step = merged
        row.imported = True
        row.updated_at = now
    by_kind = {score.kind: score for score in scores}
    for kind, values in endless.items():
        score = by_kind.get(kind)
        old_score = None if score is None else EndlessValues(score.streak, score.best, score.solved)
        merged_score = merge_endless(old_score, values)
        if merged_score == old_score:
            continue
        if score is None:
            score = LearnEndlessScore(user_id=user_id, kind=kind)
            db.add(score)
        score.streak, score.best, score.solved = merged_score
        score.imported = True
        score.updated_at = now
    users = User.__table__
    await db.execute(
        update(users)
        .where(users.c.id == user_id)
        .values({USER_PREFS: merge_prefs(stored, prefs), USER_LEARN_IMPORTED_AT: now})
    )
    await db.commit()


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
