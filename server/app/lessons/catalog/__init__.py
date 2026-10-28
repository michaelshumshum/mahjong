"""Lesson content, one module per track (ADR 0025). `CATALOG` is `/learn`'s display order."""

from app.lessons.model import Puzzle

CATALOG: tuple[Puzzle, ...] = ()
