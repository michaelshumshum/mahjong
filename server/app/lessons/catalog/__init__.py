"""Lesson content, one module per track (ADR 0025). `CATALOG` is `/learn`'s display order."""

from app.lessons.catalog.basics import BASICS
from app.lessons.catalog.mined import MINED
from app.lessons.model import Puzzle

CATALOG: tuple[Puzzle, ...] = (*BASICS, *MINED)
