"""Faan scoring: pattern detection (patterns.py), decomposition maximisation (faan.py), and
faan -> points -> payments (payout.py).

Re-exports the public surface `patterns.py`/`faan.py` offer. `payout.py`'s `Discard` would
collide with `actions.Discard` at engine.py's only call site, so it (and its sibling
`SelfDraw`/`WinType`) stay un-re-exported here -- engine.py imports
`mahjong_core.scoring.payout` directly, aliased.
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
