"""Lesson content, one module per track (ADR 0025). `CATALOG` is `/learn`'s puzzle order;
`TUTORIALS` come before the puzzles in the generated index."""

from app.lessons.catalog.basics import BASICS
from app.lessons.catalog.mined import MINED
from app.lessons.catalog.tutorials import TUTORIALS
from app.lessons.model import Puzzle

CATALOG: tuple[Puzzle, ...] = (*BASICS, *MINED)

__all__ = ["CATALOG", "TUTORIALS"]
