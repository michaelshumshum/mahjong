"""Bot tier ids (docs/bots.md §2). Values are wire strings (`state_sync`'s per-seat bot tier,
`POST /tables`' `bot_tiers`, `/healthz`'s `disabled_tiers`) and must never change."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

__all__ = ["BOT_TIERS", "DEFAULT_BOT_TIER", "LEARNED_TIERS", "BotTier"]


class BotTier(StrEnum):
    T0 = "T0"
    T1 = "T1"
    T2 = "T2"
    T4 = "T4"
    ORACLE = "ORACLE"


# "T4" is the learned policy; "T3" stays retired with SearchBot (docs/decisions/0012). "ORACLE"
# is not a rung on the ladder but a full-information bot a table opts into explicitly.
BOT_TIERS: Final = tuple(BotTier)
DEFAULT_BOT_TIER: Final = BotTier.T2
"""A bot-filled table runs `FaanBot`, not a weaker tier -- an all-T1 table produces endless
exhaustive draws under `min_faan=3` (docs/bots.md §4)."""

LEARNED_TIERS: Final = frozenset({BotTier.T4, BotTier.ORACLE})
"""The tiers that load bots/weights/learned.npz."""
