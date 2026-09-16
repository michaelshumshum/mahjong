"""Faan scoring: pattern detection (patterns.py), decomposition maximisation (faan.py, later
sub-task), and payout (payout.py, later sub-task) -- docs/05-roadmap.md §1, §2.

Re-exports the public surface `patterns.py` currently offers; `faan.py`/`payout.py` will add
theirs here once they exist.
"""

from __future__ import annotations

from mahjong_core.scoring.patterns import (
    PATTERNS,
    Pattern,
    ScoringContext,
    score_hand,
    seat_wind_for,
)

__all__ = ["PATTERNS", "Pattern", "ScoringContext", "score_hand", "seat_wind_for"]
