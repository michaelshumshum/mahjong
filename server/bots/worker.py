"""Process-pool worker for bot-driven decisions -- disconnect/bot-handover
(docs/00-architecture.md §3 D12, docs/05-roadmap.md M3 sub-task 6) and bot-seats-from-creation
(M4.5 practice mode, docs/05-roadmap.md M4.5).

**Resolved: the real `Bot.act` tiers now drive both live paths.** This module's own docstring
used to say "revisit this only when a non-uniform tier (T1+) needs to run disconnect-handover
for real, not before" -- that point has now arrived (docs/04-bots.md's changelog note on the
same subject is updated alongside this). The blocker was never behavioural, only architectural:
a worker process never receives `GameState` (D2: `game_seed` must never leave the room's own
process), so it can't call `decode_action(aid, state, seat)` itself to turn a `Bot.act`-returned
id into a concrete `Action`. The fix is exactly what this module's own predecessor docstring
already worked out as the alternative: this worker returns a **bare action id**, not a decoded
`Action`, and `app/room.py`'s `_handle_bot_result` -- which already holds the real `GameState`
-- does the `decode_action` step after the result lands back through `self.inbox`. That is the
one real, deliberate change to `app/room.py`'s result-handling shape this sub-task makes.

`compute_action` is the actual unit submitted to the pool: build the requested tier's `Bot`
(`bots.random.RandomBot`/`bots.efficiency.EfficiencyBot`/`bots.faanbot.FaanBot`, `T0`/`T1`/`T2`
per docs/04-bots.md §2) and call its `act(view, mask, deadline)`. `tier` is a plain per-`Room`
config value (`app/room.py`'s `Room.__init__(bot_tier=...)`), not hardcoded -- the default
(`DEFAULT_BOT_TIER`, `T2`/`FaanBot`) matches M4.5's explicit requirement that a bot-filled table
runs `FaanBot`, not a weaker tier, but every tier stays selectable (tests, and any future
difficulty setting, construct a `Room`/call `compute_action` with a different one).

**Driving an `async def act` from a synchronous `ProcessPoolExecutor` entry point.** There is no
running event loop in a plain `ProcessPoolExecutor` worker, so this calls `asyncio.run(...)` --
the same pattern `bots/arena.py`'s own `_run_duplicate_set` (a `ProcessPoolExecutor` entry point
itself) already uses for the identical reason. Confirmed, not assumed: every tier's `act` here
(`RandomBot`/`EfficiencyBot`/`FaanBot`) is synchronous, pure-CPU heuristic work under the hood
with nothing to genuinely `await` -- `async def` exists on `bots.base.Bot`'s protocol only so a
future tier (a learned policy making a real model call) can drop in without changing the
interface (`bots/base.py`'s own docstring). `asyncio.run` is therefore just the plumbing needed
to call that interface at all from this entry point, not a sign of real concurrency inside a
single decision.
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
"""M4.5's explicit requirement (docs/05-roadmap.md): a bot-filled table runs `FaanBot`, not a
weaker tier -- an all-`EfficiencyBot` (T1) table produces endless exhaustive draws under
`min_faan=3` (docs/04-bots.md §4)."""


def _make_bot(tier: str, seed: int) -> Bot:
    if tier == "T0":
        return RandomBot(rng=random.Random(seed))
    if tier == "T1":
        return EfficiencyBot()
    if tier == "T2":
        return FaanBot()
    raise ValueError(f"unknown bot tier {tier!r}; choices: {BOT_TIERS}")


def compute_action(view: SeatView, mask: list[bool], seed: int, tier: str, deadline: float) -> int:
    """Run one bot decision inside a `ProcessPoolExecutor` worker; returns a bare action id, not
    a concrete `Action` -- see module docstring for why the decode step now lives in
    `app/room.py`. `seed` is derived from the tag the room submitted this job against
    (`app/room.py`'s `BotJobTag`) rather than an unseeded `random.Random()` -- server/AGENTS.md:
    "a failing game is reproducible from (ruleset, seed, actions)" -- and is only actually read
    by `T0`; `T1`/`T2` are stateless (same convention `bots/arena.py`'s own bot factories use).
    Never called with an all-false mask (same contract `Bot.act` documents).
    """
    bot = _make_bot(tier, seed)
    return asyncio.run(bot.act(view, mask, deadline))
