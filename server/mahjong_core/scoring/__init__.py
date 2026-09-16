"""Faan scoring: pattern detection (patterns.py), decomposition maximisation (faan.py), and
payout (payout.py, later sub-task) -- docs/05-roadmap.md §1, §2.

Re-exports the public surface `patterns.py`/`faan.py` currently offer; `payout.py` will add
its own once it exists.
"""

from __future__ import annotations

from mahjong_core.scoring.faan import FaanResult, score_winning_hand
from mahjong_core.scoring.patterns import (
    PATTERNS,
    Pattern,
    ScoringContext,
    score_hand,
    seat_wind_for,
)

__all__ = [
    "PATTERNS",
    "FaanResult",
    "Pattern",
    "ScoringContext",
    "score_hand",
    "score_winning_hand",
    "seat_wind_for",
]
