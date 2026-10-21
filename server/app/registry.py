"""`TableRegistry` -- module-level table lookup/creation/cleanup (docs/architecture.md §6):
an in-process dict plus the bookkeeping to run each `Table`'s `asyncio.Task` and stop leaking
finished ones.

`Table.run()` returns once `state.phase == Phase.GAME_OVER`, and `get_or_create` wraps each
table's task so `_tasks` drops its entry the moment that happens, freeing the `asyncio.Task`
promptly. The finished `Table` stays in `_tables` for `finished_ttl_seconds`, so reconnecting
after the game ends still works, then `reap` evicts it.

Abandoned tables (docs/architecture.md §8.2): `abandon_grace_seconds` is threaded into every
non-showcase `Table`, and one that ends early (`Table.closed`) is evicted from `_tables` and its
id kept in `_closed`, so `POST /tables` never mints it again.

Limits (docs/architecture.md §8.3): `reap` (every `REAP_INTERVAL_SECONDS` once `start_reaper`
runs) also ends a never-started table idle past `unstarted_ttl_seconds`; `max_tables` caps how
many live at once (`TableLimitError`); `_closed` keeps at most `closed_ids_cap` ids, oldest
dropped first. `clock` is injectable so tests drive the TTLs.

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
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Executor
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clock import now_ms
from app.errors import TABLE_GONE_ERROR
from app.fairness import new_game_seed
from app.table import Table
from app.table_types import TableSettings, WireSeatStatus
from bots.tiers import DEFAULT_BOT_TIER
from mahjong_core.config import RuleSet

__all__ = ["TableLimitError", "TableRegistry", "TableSummary"]

logger = logging.getLogger(__name__)


SHOWCASE_RESTART_SECONDS = 30.0
REAP_INTERVAL_SECONDS = 30.0
DEFAULT_CLOSED_IDS_CAP = 10_000


class TableLimitError(Exception):
    """`get_or_create` would exceed `max_tables` (`POST /tables` answers 503)."""


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
        abandon_grace_seconds: float | None = None,
        max_tables: int | None = None,
        unstarted_ttl_seconds: float | None = None,
        finished_ttl_seconds: float | None = None,
        closed_ids_cap: int = DEFAULT_CLOSED_IDS_CAP,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._bot_pool = bot_pool
        self._abandon_grace_seconds = abandon_grace_seconds
        self._session_factory = session_factory
        # None disables that limit (bare test registries)
        self._max_tables = max_tables
        self._unstarted_ttl = unstarted_ttl_seconds
        self._finished_ttl = finished_ttl_seconds
        self._closed_ids_cap = closed_ids_cap
        self._clock = clock
        self._tables: dict[str, Table] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._created_at: dict[str, float] = {}
        self._finished_at: dict[str, float] = {}
        # ids of evicted tables, insertion-ordered so the oldest go first past the cap
        self._closed: OrderedDict[str, None] = OrderedDict()
        self._reaper_task: asyncio.Task[None] | None = None
        # unlisted by `list_tables`; reachable by id only
        self._private: set[str] = set()
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
        private: bool = False,
    ) -> Table:
        """Return the existing table for `table_id`, or construct and start one -- a table id
        names one particular game, never recycled, even after it finishes. `practice`/`bot_tier`/
        `seat_bot_tiers`/`private` only apply the first time a given `table_id` is created.
        Raises `TableLimitError` instead of creating a table past `max_tables`."""
        table = self._tables.get(table_id)
        if table is not None:
            return table
        if self._max_tables is not None and self.live_count() >= self._max_tables:
            raise TableLimitError(f"{self._max_tables} tables already live")
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
            abandon_grace_seconds=self._abandon_grace_seconds,
        )
        self._tables[table_id] = table
        self._created_at[table_id] = self._clock()
        if private:
            self._private.add(table_id)
        self._tasks[table_id] = asyncio.create_task(self._run(table_id, table))
        return table

    def live_count(self) -> int:
        """Tables counted against `max_tables` -- every one in `_tables` but the showcase."""
        return len(self._tables) - (self._showcase_id in self._tables)

    async def _run(self, table_id: str, table: Table) -> None:
        try:
            await table.run()
        finally:
            self._tasks.pop(table_id, None)
            if self._tables.get(table_id) is table:
                if table.closed:
                    self._evict(table_id)
                else:
                    self._finished_at[table_id] = self._clock()

    def _evict(self, table_id: str) -> None:
        del self._tables[table_id]
        self._private.discard(table_id)
        self._created_at.pop(table_id, None)
        self._finished_at.pop(table_id, None)
        self._closed[table_id] = None
        while len(self._closed) > self._closed_ids_cap:
            self._closed.popitem(last=False)

    def reap(self) -> list[str]:
        """Evict every table past its TTL and return their ids: finished `finished_ttl_seconds`
        ago, or never started, `unstarted_ttl_seconds` old and with no human seat `connected`
        (spectators don't count, same as `_is_abandoned`). Both get `end(TABLE_GONE_ERROR)`, so
        a socket still open on one is told and stops reconnecting; an unstarted one's task is
        cancelled. The showcase is never reaped."""
        now = self._clock()
        reaped: list[str] = []
        for table_id, table in list(self._tables.items()):
            if table_id == self._showcase_id:
                continue
            finished_at = self._finished_at.get(table_id)
            if finished_at is not None:
                expired = self._finished_ttl is not None and now - finished_at >= self._finished_ttl
            else:
                expired = (
                    self._unstarted_ttl is not None
                    and not table.started
                    and now - self._created_at[table_id] >= self._unstarted_ttl
                    and not any(
                        b is not None and b.status == "connected" for b in table.seat_bindings
                    )
                )
            if not expired:
                continue
            table.end(TABLE_GONE_ERROR)
            task = self._tasks.pop(table_id, None)
            if task is not None:
                task.cancel()
            self._evict(table_id)
            reaped.append(table_id)
        if reaped:
            logger.info("reaped %d idle table(s): %s", len(reaped), ", ".join(reaped))
        return reaped

    def start_reaper(self, interval: float = REAP_INTERVAL_SECONDS) -> None:
        """Run `reap` every `interval` seconds until `begin_shutdown`."""

        async def _loop() -> None:
            while True:
                await asyncio.sleep(interval)
                self.reap()

        self._reaper_task = asyncio.create_task(_loop())

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
            # open hands: spectators already see every claim, nothing for a hold to hide
            claim_hold_seconds=0,
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

    def is_closed(self, table_id: str) -> bool:
        """Whether `table_id` named a table since evicted (abandoned or reaped), among the last
        `closed_ids_cap`."""
        return table_id in self._closed

    def is_running(self, table_id: str) -> bool:
        """Whether `table_id`'s background task is still alive -- `False` for an unknown id or a
        finished game."""
        task = self._tasks.get(table_id)
        return task is not None and not task.done()

    def list_tables(self) -> list[TableSummary]:
        """Every still-running table with at least one human seat, plus the showcase table.
        Skips finished games (kept until reaped), tables nobody has joined yet
        (a practice table is bot-only until its owner joins) and private tables."""
        summaries: list[TableSummary] = []
        for table_id, table in self._tables.items():
            bindings = table.seat_bindings
            if table_id != self._showcase_id and (
                table_id in self._private
                or not self.is_running(table_id)
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
        if self._reaper_task is not None:
            self._reaper_task.cancel()
        if self._showcase_task is not None:
            self._showcase_task.cancel()  # also cancels the game task it's awaiting
        ts = deadline_ts if deadline_ts is not None else now_ms() + round(grace_seconds * 1000)
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
