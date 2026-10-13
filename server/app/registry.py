"""`TableRegistry` -- module-level table lookup/creation/cleanup (docs/architecture.md §6):
an in-process dict plus the bookkeeping to run each `Table`'s `asyncio.Task` and stop leaking
finished ones.

`Table.run()` returns once `state.phase == Phase.GAME_OVER`, and `get_or_create` wraps each
table's task so `_tasks` drops its entry the moment that happens, freeing the `asyncio.Task`
promptly. The `Table` object itself is not evicted from `_tables` -- reconnecting after the game
ends is still a supported path, and there's no session-expiry/TTL policy to drive a real
eviction decision from; full table eviction is a tracked gap, not an oversight.

`session_factory`, if given, is threaded into every `Table` so it can persist a `GameRecord` on
`Phase.GAME_OVER`. `app/ws.py`'s module-level registry gets a fresh one per ASGI startup
(`reset_registry`) so this and `draining` never leak across server lifetimes.

Showcase table. `start_showcase` keeps one all-bot table (`Table(all_bots=True)`, open hands
for spectators) running under a fixed id forever, each game drawing every seat's tier at random
from `bot_tiers`: when a game ends it holds the finished table
for `restart_delay` seconds, then swaps in a fresh game under the same id and closes the old
table's spectator sockets so their reconnect lands on the new one. Never persisted and not
waited on by the shutdown drain -- bot-only, nothing to protect.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import Executor
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.fairness import new_game_seed
from app.table import Table, TableSettings, WireSeatStatus
from bots.worker import DEFAULT_BOT_TIER
from mahjong_core.config import RuleSet

__all__ = ["TableRegistry", "TableSummary"]

logger = logging.getLogger(__name__)


SHOWCASE_RESTART_SECONDS = 30.0


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


@dataclass(frozen=True, slots=True)
class TableSummary:
    """One row of the lobby's table browser (`GET /tables`). `open` = still has an empty seat
    and hasn't dealt; `in_progress` = everything else still running (join-able only as a
    spectator)."""

    table_id: str
    status: Literal["open", "in_progress"]
    hand_no: int
    seat_status: tuple[WireSeatStatus, WireSeatStatus, WireSeatStatus, WireSeatStatus]
    names: tuple[str | None, str | None, str | None, str | None]


class TableRegistry:
    """In-process table directory. `bot_pool`, if given, is shared across every `Table` this
    registry creates (one process pool per server, not per table) -- omit to use `app/table.py`'s
    lazy shared default. `session_factory=None` means no persistence.
    """

    def __init__(
        self,
        *,
        bot_pool: Executor | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._bot_pool = bot_pool
        self._session_factory = session_factory
        self._tables: dict[str, Table] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        # read by ws.py's connection accept and main.py's /healthz once a drain starts
        self.draining = False
        self._showcase_id: str | None = None
        self._showcase_task: asyncio.Task[None] | None = None

    def get(self, table_id: str) -> Table | None:
        """Lookup only -- `None` if no table with this id has ever been created."""
        return self._tables.get(table_id)

    def get_or_create(
        self,
        table_id: str,
        ruleset: RuleSet,
        *,
        seed: int | None = None,
        require_ready: bool = True,
        practice: bool = False,
        bot_tier: str = DEFAULT_BOT_TIER,
        seat_bot_tiers: Mapping[int, str] | None = None,
    ) -> Table:
        """Return the existing table for `table_id`, or construct and start one -- a table id
        names one particular game, never recycled, even after it finishes. `practice`/`bot_tier`/
        `seat_bot_tiers` only apply the first time a given `table_id` is created."""
        table = self._tables.get(table_id)
        if table is not None:
            return table
        table = Table(
            table_id,
            ruleset,
            game_seed=seed if seed is not None else new_game_seed(),
            require_ready=require_ready,
            bot_pool=self._bot_pool,
            session_factory=self._session_factory,
            practice=practice,
            bot_tier=bot_tier,
            seat_bot_tiers=seat_bot_tiers,
        )
        self._tables[table_id] = table
        self._tasks[table_id] = asyncio.create_task(self._run(table_id, table))
        return table

    async def _run(self, table_id: str, table: Table) -> None:
        try:
            await table.run()
        finally:
            self._tasks.pop(table_id, None)

    def start_showcase(
        self,
        table_id: str,
        ruleset: RuleSet,
        *,
        restart_delay: float = SHOWCASE_RESTART_SECONDS,
        bot_tiers: Sequence[str] = (DEFAULT_BOT_TIER,),
    ) -> None:
        """Start the always-on all-bot table under `table_id`. The first game is created before
        this returns, so no connection can race it into a plain table."""
        if self._showcase_task is not None:
            raise RuntimeError("showcase already started")
        self._showcase_id = table_id
        first = self._start_showcase_game(table_id, ruleset, bot_tiers)
        self._showcase_task = asyncio.create_task(
            self._run_showcase(first, table_id, ruleset, restart_delay, bot_tiers)
        )

    def _start_showcase_game(
        self, table_id: str, ruleset: RuleSet, bot_tiers: Sequence[str]
    ) -> asyncio.Task[None]:
        previous = self._tables.get(table_id)
        game_seed = new_game_seed()
        tier_rng = random.Random(game_seed)
        table = Table(
            table_id,
            ruleset,
            game_seed=game_seed,
            require_ready=True,
            bot_pool=self._bot_pool,
            seat_bot_tiers={seat: tier_rng.choice(bot_tiers) for seat in range(4)},
            all_bots=True,
            settings=TableSettings(spectators_see_hands=True),
        )
        self._tables[table_id] = table
        if previous is not None:
            previous.close_spectators()
        task = asyncio.create_task(self._run(table_id, table))
        self._tasks[table_id] = task
        return task

    async def _run_showcase(
        self,
        task: asyncio.Task[None],
        table_id: str,
        ruleset: RuleSet,
        restart_delay: float,
        bot_tiers: Sequence[str],
    ) -> None:
        while True:
            try:
                await task
            except Exception:
                logger.exception("showcase table %s crashed, restarting", table_id)
            await asyncio.sleep(restart_delay)
            task = self._start_showcase_game(table_id, ruleset, bot_tiers)

    def is_running(self, table_id: str) -> bool:
        """Whether `table_id`'s background task is still alive -- `False` for an unknown id or a
        finished game."""
        task = self._tasks.get(table_id)
        return task is not None and not task.done()

    def list_tables(self) -> list[TableSummary]:
        """Every still-running table with at least one human seat, plus the showcase table.
        Skips finished games (never evicted from `_tables`) and tables nobody has joined yet
        (a practice table is bot-only until its owner joins)."""
        summaries: list[TableSummary] = []
        for table_id, table in self._tables.items():
            bindings = table.seat_bindings
            if table_id != self._showcase_id and (
                not self.is_running(table_id)
                or not any(b is not None and b.status != "bot" for b in bindings)
            ):
                continue
            is_open = not table.started and any(b is None for b in bindings)
            summaries.append(
                TableSummary(
                    table_id=table_id,
                    status="open" if is_open else "in_progress",
                    hand_no=table.state.hand_no,
                    seat_status=table.seat_status_tuple(),
                    names=table.names_tuple(),
                )
            )
        return summaries

    async def begin_shutdown(
        self, *, grace_seconds: float = 90.0, deadline_ts: int | None = None
    ) -> None:
        """docs/architecture.md §8.1 drain, this registry's half. Broadcasts
        `server_shutdown` to every table with a bound seat, then waits on each via
        `asyncio.gather` (one grace window total, not per table). A timed-out table is logged,
        not torn down here -- the process exiting is what ends it.
        """
        self.draining = True
        if self._showcase_task is not None:
            self._showcase_task.cancel()  # also cancels the game task it's awaiting
        ts = deadline_ts if deadline_ts is not None else _now_ms() + round(grace_seconds * 1000)
        targets = [
            (table_id, table)
            for table_id, table in self._tables.items()
            if table_id != self._showcase_id
            and self.is_running(table_id)
            and any(b is not None for b in table.seat_bindings)
        ]
        if not targets:
            return
        for _table_id, table in targets:
            table.broadcast_server_shutdown(ts)
        results = await asyncio.gather(
            *(table.wait_for_shutdown_boundary(grace_seconds) for _table_id, table in targets)
        )
        for (table_id, _table), reached in zip(targets, results, strict=True):
            if not reached:
                logger.warning(
                    "table %s: shutdown grace window (%.1fs) elapsed mid-hand, abandoning",
                    table_id,
                    grace_seconds,
                )

    def __len__(self) -> int:
        return len(self._tables)
