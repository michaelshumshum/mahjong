"""`app/registry.py`'s `RoomRegistry` -- room lookup/creation/cleanup (M3 sub-task 6).

`get_or_create`/`get` are exercised directly against a bare `RoomRegistry()` (no WS layer) --
`app/ws.py`'s own module-level `_registry` is exactly this class, already covered indirectly by
every WS-integration test (`tests/test_ws_gameplay.py`, `tests/test_reconnect.py`,
`tests/test_disconnect_bot_handover.py`). This file's own job is the registry's *own* behavior:
dedup on repeated `get_or_create`, `get` on an unknown id, and the task-cleanup-on-`GAME_OVER`
lifecycle `app/registry.py`'s module docstring documents.
"""

from __future__ import annotations

import asyncio
import dataclasses

from app.registry import RoomRegistry
from mahjong_core.actions import Pass
from mahjong_core.config import DEFAULT_RULESET
from mahjong_core.state import Phase


async def _wait_until_stopped(
    registry: RoomRegistry, room_id: str, *, timeout: float = 2.0
) -> None:
    async def _poll() -> None:
        while registry.is_running(room_id):
            await asyncio.sleep(0.01)

    await asyncio.wait_for(_poll(), timeout=timeout)


def test_get_unknown_room_returns_none() -> None:
    registry = RoomRegistry()
    assert registry.get("no-such-room") is None
    assert len(registry) == 0


async def test_get_or_create_is_idempotent_per_room_id() -> None:
    registry = RoomRegistry()
    room1 = registry.get_or_create("room-a", DEFAULT_RULESET, seed=1)
    room2 = registry.get_or_create("room-a", DEFAULT_RULESET, seed=999)  # seed ignored on reuse
    assert room1 is room2
    assert registry.get("room-a") is room1
    assert len(registry) == 1

    room_b = registry.get_or_create("room-b", DEFAULT_RULESET, seed=1)
    assert room_b is not room1
    assert len(registry) == 2


async def test_get_or_create_passes_through_require_ready_and_seed() -> None:
    registry = RoomRegistry()
    room = registry.get_or_create("room-c", DEFAULT_RULESET, seed=42, require_ready=False)
    assert room.require_ready is False
    assert room.started is True  # require_ready=False rooms start immediately (Room.__init__)


async def test_room_task_stops_and_is_cleaned_up_on_game_over() -> None:
    """`Room.run()` (see its own docstring) returns once `state.phase == Phase.GAME_OVER`;
    `RoomRegistry._run` wraps that so `_tasks` drops the entry the moment it does -- the `Room`
    object itself stays in `_rooms` (see `app/registry.py`'s module docstring on why)."""
    registry = RoomRegistry()
    room = registry.get_or_create("room-gameover", DEFAULT_RULESET, seed=1, require_ready=False)
    assert registry.is_running("room-gameover")

    # force GAME_OVER directly (white-box, same style tests/test_reconnect.py's `room.state = ...`
    # rigging already established) and nudge the room's own background task awake with a command
    # it will drop as illegal (GAME_OVER has no legal_actions for any seat) -- process_one() only
    # re-checks phase after handling *something*, per Room.run()'s own loop.
    room.state = dataclasses.replace(room.state, phase=Phase.GAME_OVER, claim_window=None)
    room.submit(0, Pass(window_id=0, seat=0))

    await _wait_until_stopped(registry, "room-gameover")
    assert not registry.is_running("room-gameover")
    assert registry.get("room-gameover") is room  # the Room itself is retained, not evicted

    # get_or_create on the same (finished) room id returns the same, now-task-less Room --
    # a room id names one particular game, not a recyclable lobby slot.
    same_room = registry.get_or_create("room-gameover", DEFAULT_RULESET, seed=2)
    assert same_room is room
    assert not registry.is_running("room-gameover")
