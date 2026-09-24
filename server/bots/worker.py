"""Process-pool worker for bot-driven decisions (docs/00-architecture.md §3, docs/04-bots.md §1).

Returns a bare action id, not a decoded `Action`: a worker process never receives `GameState`
(`game_seed` must never leave the table's own process), so `app/table.py`'s `_handle_bot_result`
-- which holds the real `GameState` -- does the `decode_action` step once the result lands back.

`compute_action` builds the requested tier's `Bot` and calls `act(view, mask, deadline)` via
`asyncio.run` -- there's no running event loop in a plain `ProcessPoolExecutor` worker, and every
tier's `act` here is synchronous heuristic work under the hood; `async` exists on the `Bot`
protocol only so a future learned-policy tier can await a real model call.
"""

from __future__ import annotations

import asyncio
import random
from typing import Final

from app.views import SeatView
from bots.base import Bot
from bots.efficiency import EfficiencyBot
from bots.faanbot import FaanBot
from bots.random import RandomBot

__all__ = ["BOT_TIERS", "DEFAULT_BOT_TIER", "compute_action"]

BOT_TIERS: Final = ("T0", "T1", "T2")
DEFAULT_BOT_TIER: Final = "T2"
"""A bot-filled table runs `FaanBot`, not a weaker tier -- an all-T1 table produces endless
exhaustive draws under `min_faan=3` (docs/04-bots.md §4)."""


def _make_bot(tier: str, seed: int) -> Bot:
    if tier == "T0":
        return RandomBot(rng=random.Random(seed))
    if tier == "T1":
        return EfficiencyBot()
    if tier == "T2":
        return FaanBot()
    raise ValueError(f"unknown bot tier {tier!r}; choices: {BOT_TIERS}")


def compute_action(view: SeatView, mask: list[bool], seed: int, tier: str, deadline: float) -> int:
    """Runs one bot decision inside a `ProcessPoolExecutor` worker; returns a bare action id (see
    module docstring). `seed` comes from the table's job tag, not an unseeded `Random()`, so a
    run stays reproducible -- only `T0` actually reads it, `T1`/`T2` are stateless."""
    bot = _make_bot(tier, seed)
    return asyncio.run(bot.act(view, mask, deadline))
