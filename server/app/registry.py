"""`RoomRegistry` -- module-level room lookup/creation/cleanup (M3 sub-task 6; replaces
`app/ws.py`'s bare `_ROOMS`/`_ROOM_TASKS` dicts, which that module's own docstring already
flagged as a stand-in: "sub-task 6 replaces this wholesale").

docs/00-architecture.md §6: matchmaking, presence, and session state are v1 "module-level dicts
in the API process -- no `KV`/`Queue`/`Bus` abstraction layer" until a second real backend exists
to justify one. This is exactly that: an in-process dict plus the bookkeeping needed to run each
`Room`'s `asyncio.Task` and stop leaking finished ones -- no persistence, no capacity limit, no
cross-process routing (all explicitly deferred by that section).

**Room lifecycle -- a real gap neither `00-architecture.md` nor `02-protocol.md` addresses.**
Before this sub-task, `Room.run()` looped `while True` forever, so every finished game left an
idle `asyncio.Task` (and its `Room`) parked in the registry for the rest of the process's life --
a slow, unbounded leak matching the same shape `docs/00-architecture.md`'s "Outbound
backpressure" section already worries about elsewhere. Minimal real fix, not a full expiry
policy: `Room.run()` (see its own docstring) now returns once `state.phase == Phase.GAME_OVER`,
and `get_or_create` here wraps each room's task so `_tasks` drops its entry the moment that
happens -- freeing the `asyncio.Task` promptly. The `Room` object itself is *not* evicted from
`_rooms`: reconnecting after the game ended is still a real, supported path (`Room.reconnect`/
`resume` are plain synchronous calls on the `Room` object, unaffected by whether its background
task is still running), and there's no session-expiry/TTL policy documented anywhere to drive a
real eviction decision from. Full room eviction (freeing the memory of a long-dead finished game)
is left as a real, tracked gap -- the same "no eviction, no capacity limit" scope line
`app/ws.py` already carried before this sub-task, just narrowed to "no *room* eviction" now that
task eviction is real.
"""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import Executor

from app.room import Room
from mahjong_core.config import RuleSet

__all__ = ["RoomRegistry"]


class RoomRegistry:
    """In-process room directory. `bot_pool`, if given, is shared by every `Room` this registry
    creates (D12: one process pool per server process, not one per room) -- omit it to let each
    `Room` fall back to `app/room.py`'s own lazily-created shared pool."""

    def __init__(self, *, bot_pool: Executor | None = None) -> None:
        self._bot_pool = bot_pool
        self._rooms: dict[str, Room] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def get(self, room_id: str) -> Room | None:
        """Lookup only -- `None` if no room with this id has ever been created."""
        return self._rooms.get(room_id)

    def get_or_create(
        self,
        room_id: str,
        ruleset: RuleSet,
        *,
        seed: int | None = None,
        require_ready: bool = True,
    ) -> Room:
        """Return the existing room for `room_id`, or construct and start one -- a room id
        names one particular game, not a recyclable lobby slot, so this never creates a second
        `Room` for an id that already has one, even a finished one (see module docstring)."""
        room = self._rooms.get(room_id)
        if room is not None:
            return room
        room = Room(
            room_id,
            ruleset,
            game_seed=seed if seed is not None else time.time_ns(),
            require_ready=require_ready,
            bot_pool=self._bot_pool,
        )
        self._rooms[room_id] = room
        self._tasks[room_id] = asyncio.create_task(self._run(room_id, room))
        return room

    async def _run(self, room_id: str, room: Room) -> None:
        try:
            await room.run()
        finally:
            self._tasks.pop(room_id, None)

    def is_running(self, room_id: str) -> bool:
        """Whether `room_id`'s background task is still alive -- `False` for an unknown room id
        or one whose game already reached `GAME_OVER` (`Room.run`'s own docstring)."""
        task = self._tasks.get(room_id)
        return task is not None and not task.done()

    def __len__(self) -> int:
        return len(self._rooms)
