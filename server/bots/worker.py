"""Process-pool worker for bot-driven decisions (docs/architecture.md §3, docs/bots.md §1).

Returns a bare action id, not a decoded `Action`: a worker process never receives `GameState`
(`game_seed` must never leave the table's own process), so `app/table.py`'s `_handle_bot_result`
-- which holds the real `GameState` -- does the `decode_action` step once the result lands back.

`compute_action` builds the requested tier's `Bot` and calls `act(view, mask, deadline)` via
`asyncio.run` -- there's no running event loop in a plain `ProcessPoolExecutor` worker, and every
tier's `act` here is synchronous work under the hood, the numpy forward pass of `T4` and `ORACLE`
included (no inference server: docs/ml.md §6).
"""

from __future__ import annotations

import asyncio
import random

from app.views import SeatView
from bots.base import Bot
from bots.efficiency import EfficiencyBot
from bots.faanbot import FaanBot
from bots.random import RandomBot
from bots.tiers import BOT_TIERS, BotTier

__all__ = ["compute_action"]


def _make_bot(tier: str, seed: int) -> Bot:
    if tier == BotTier.T0:
        return RandomBot(rng=random.Random(seed))
    if tier == BotTier.T1:
        return EfficiencyBot()
    if tier == BotTier.T2:
        return FaanBot()
    if tier == BotTier.T4:
        # lazy: numpy + the weights load only in a worker that serves a T4 seat, once per process
        from bots.learned import LearnedBot

        return LearnedBot()
    if tier == BotTier.ORACLE:
        # the T4 policy plus exact vetoes (docs/bots.md §9); no FaanBot fallback when the weights
        # don't load -- it raises like T4 does.
        from bots.oracle_learned import OracleLearnedBot

        return OracleLearnedBot()
    raise ValueError(f"unknown bot tier {tier!r}; choices: {tuple(map(str, BOT_TIERS))}")


def compute_action(view: SeatView, mask: list[bool], seed: int, tier: str, deadline: float) -> int:
    """Runs one bot decision inside a `ProcessPoolExecutor` worker; returns a bare action id (see
    module docstring). `seed` comes from the table's job tag, not an unseeded `Random()`, so a
    run stays reproducible -- `T0` reads it, `T1`/`T2` are stateless."""
    bot = _make_bot(tier, seed)
    return asyncio.run(bot.act(view, mask, deadline))
