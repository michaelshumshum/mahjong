"""Lesson content, one module per track (ADR 0025). `CATALOG` is `/learn`'s puzzle order;
`TUTORIALS` come before the puzzles in the generated index."""

from app.lessons.catalog.basics import BASICS
from app.lessons.catalog.mined import MINED
from app.lessons.catalog.tutorials import TUTORIALS
from app.lessons.model import Puzzle

CATALOG: tuple[Puzzle, ...] = (*BASICS, *MINED)
# every `/learn/[id]` lesson, the keys of an account's learn progress
LESSON_IDS: frozenset[str] = frozenset([*(p.id for p in CATALOG), *(t.id for t in TUTORIALS)])
TUTORIAL_IDS: frozenset[str] = frozenset(t.id for t in TUTORIALS)

__all__ = ["CATALOG", "LESSON_IDS", "TUTORIALS", "TUTORIAL_IDS"]
