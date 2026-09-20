"""`TableRegistry` -- module-level table lookup/creation/cleanup (M3 sub-task 6; replaces
`app/ws.py`'s bare `_ROOMS`/`_ROOM_TASKS` dicts, which that module's own docstring already
flagged as a stand-in: "sub-task 6 replaces this wholesale").

docs/00-architecture.md §6: matchmaking, presence, and session state are v1 "module-level dicts
in the API process -- no `KV`/`Queue`/`Bus` abstraction layer" until a second real backend exists
to justify one. This is exactly that: an in-process dict plus the bookkeeping needed to run each
`Table`'s `asyncio.Task` and stop leaking finished ones -- no persistence, no capacity limit, no
cross-process routing (all explicitly deferred by that section).

**Table lifecycle -- a real gap neither `00-architecture.md` nor `02-protocol.md` addresses.**
Before this sub-task, `Table.run()` looped `while True` forever, so every finished game left an
idle `asyncio.Task` (and its `Table`) parked in the registry for the rest of the process's life --
a slow, unbounded leak matching the same shape `docs/00-architecture.md`'s "Outbound
backpressure" section already worries about elsewhere. Minimal real fix, not a full expiry
policy: `Table.run()` (see its own docstring) now returns once `state.phase == Phase.GAME_OVER`,
and `get_or_create` here wraps each table's task so `_tasks` drops its entry the moment that
happens -- freeing the `asyncio.Task` promptly. The `Table` object itself is *not* evicted from
`_tables`: reconnecting after the game ended is still a real, supported path (`Table.reconnect`/
`resume` are plain synchronous calls on the `Table` object, unaffected by whether its background
task is still running), and there's no session-expiry/TTL policy documented anywhere to drive a
real eviction decision from. Full table eviction (freeing the memory of a long-dead finished game)
is left as a real, tracked gap -- the same "no eviction, no capacity limit" scope line
`app/ws.py` already carried before this sub-task, just narrowed to "no *table* eviction" now that
task eviction is real.

**DB session factory + graceful shutdown (a later sub-task).** `session_factory`, if given, is
threaded into every `Table` this registry creates so it can persist a `GameRecord` on
`Phase.GAME_OVER` (docs/06-ml.md §2) -- `app/main.py`'s `lifespan` is the one real caller;
`app/ws.py`'s module-level registry gets a fresh one per ASGI startup (`reset_registry`) rather
than a single eternal instance, specifically so this and `draining` below never leak across
separate server lifetimes (a real process restart, or one `TestClient(app)` context in tests).
`begin_shutdown` implements this registry's half of docs/00-architecture.md §8.1's drain
sequence -- see its own docstring.
"""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import Executor

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.table import Table
from bots.worker import DEFAULT_BOT_TIER
from mahjong_core.config import RuleSet

__all__ = ["TableRegistry"]

logger = logging.getLogger(__name__)


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


class TableRegistry:
    """In-process table directory. `bot_pool`, if given, is shared by every `Table` this registry
    creates (D12: one process pool per server process, not one per table) -- omit it to let each
    `Table` fall back to `app/table.py`'s own lazily-created shared pool. `session_factory`,
    similarly, is threaded through to every `Table` this registry creates so it can persist its
    own `GameRecord` on `Phase.GAME_OVER` (docs/06-ml.md §2) -- `None` (the default) means no
    persistence, matching every pre-existing bare `Table()` construction.
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
        # docs/00-architecture.md §8.1 step 1: read by app/ws.py's connection accept and
        # app/main.py's /healthz once a drain has started (`begin_shutdown`).
        self.draining = False

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
    ) -> Table:
        """Return the existing table for `table_id`, or construct and start one -- a table id
        names one particular game, not a recyclable lobby slot, so this never creates a second
        `Table` for an id that already has one, even a finished one (see module docstring).
        `practice`/`bot_tier` are threaded straight through to `Table.__init__` (docs/05-roadmap.md
        M4.5) -- only meaningful the first time a given `table_id` is created; an existing table's
        practice/tier setup was already decided at its own construction and can't be changed
        retroactively by a later `get_or_create` call for the same id."""
        table = self._tables.get(table_id)
        if table is not None:
            return table
        table = Table(
            table_id,
            ruleset,
            game_seed=seed if seed is not None else time.time_ns(),
            require_ready=require_ready,
            bot_pool=self._bot_pool,
            session_factory=self._session_factory,
            practice=practice,
            bot_tier=bot_tier,
        )
        self._tables[table_id] = table
        self._tasks[table_id] = asyncio.create_task(self._run(table_id, table))
        return table

    async def _run(self, table_id: str, table: Table) -> None:
        try:
            await table.run()
        finally:
            self._tasks.pop(table_id, None)

    def is_running(self, table_id: str) -> bool:
        """Whether `table_id`'s background task is still alive -- `False` for an unknown table id
        or one whose game already reached `GAME_OVER` (`Table.run`'s own docstring)."""
        task = self._tasks.get(table_id)
        return task is not None and not task.done()

    async def begin_shutdown(
        self, *, grace_seconds: float = 90.0, deadline_ts: int | None = None
    ) -> None:
        """docs/00-architecture.md §8.1's drain sequence, this registry's half of it --
        `app/main.py`'s `lifespan` calls this on shutdown, `app/ws.py`'s connection accept and
        `/healthz` read `self.draining` (step 1; both are checked separately, not through here).

        Step 2: every currently-running table with at least one seat ever bound gets a broadcast
        `server_shutdown{deadline_ts}` (`Table.broadcast_server_shutdown`) -- a table with no seats
        bound has nobody to warn and nothing worth waiting on.

        Steps 3-5: each such table gets its own bounded wait for a hand boundary
        (`Table.wait_for_shutdown_boundary`), run concurrently (`asyncio.gather`, not a sequence
        of awaits) so the total wall-clock cost is `grace_seconds` once, not once per table. A
        table that times out is logged, not raised on or force-torn-down here -- once every wait
        in the gather resolves (reached or not), this coroutine returns and the caller (the
        process itself, exiting) is what actually ends any table whose task is still running --
        same "abandoned, same as a crash, but warned" §8.1 describes, not a second teardown path.
        """
        self.draining = True
        ts = deadline_ts if deadline_ts is not None else _now_ms() + round(grace_seconds * 1000)
        targets = [
            (table_id, table)
            for table_id, table in self._tables.items()
            if self.is_running(table_id) and any(b is not None for b in table.seat_bindings)
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
