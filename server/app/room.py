"""`Room` -- the room actor's core dispatch loop (docs/00-architecture.md §3, §5;
docs/05-roadmap.md §1's M3).

**Sub-task scope: dispatch only.** No timer heap / claim-window arming (`_arm_timers`), no bot
dispatch (`_poke_bots`), no WS/Session integration -- those are later M3 sub-tasks (3/4/6).
`_next()` is plain `await self.inbox.get()`, not the dual-await-against-a-deadline-heap pattern
§3 D17 describes: there is no deadline source yet for it to race against, and half-building that
race (without a real `TimerHeap` to feed it) would just be dead code with the same footgun D17
warns about, for no benefit until sub-task 3 lands the heap.

One room = one `asyncio.Task` = one writer (server/AGENTS.md): every mutation of `self.state`
happens inside `_handle`, called only from this module's own loop.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass

from app.views import redact_event
from mahjong_core.actions import Action, legal_actions
from mahjong_core.config import RuleSet
from mahjong_core.engine import Event, new_game, reduce, start_next_hand
from mahjong_core.state import GameState, Phase

__all__ = ["Command", "Envelope", "Room"]


@dataclass(frozen=True)
class Command:
    """One already-validated `(seat, Action)` pair flowing through `Room.inbox`. `seat` is the
    seat claiming to issue this. Most claim-window `Action`s (`ClaimChow`/`ClaimPung`/
    `ClaimKong`/`ClaimWin`/`Pass`) already carry their own `seat` field; `Discard`/`DeclareWin`/
    `DeclareConcealedKong`/`DeclareAddedKong` don't (`engine._acting_seat` reads `state.turn` for
    those instead), so `Command.seat` is the only place the claimed acting seat is recorded for
    them before `_authorize` checks it against `state.turn`.

    Parsing a raw client envelope into this shape is app/ws.py's job (sub-task 4) -- this type
    starts one step past that, already holding a real `mahjong_core.actions.Action`.
    """

    seat: int
    action: Action


@dataclass(frozen=True)
class Envelope:
    """One already-redacted wire frame in a seat's ring buffer, stamped with that stream's own
    `seq` (00-architecture.md §3 D1: per-seat, dense, gapless -- never per-room, never derived
    from `event_id`)."""

    seq: int
    event: dict[str, object]


class Room:
    """Owns exactly one `GameState`, mutated only via `reduce()`/`start_next_hand()`. See module
    docstring for what this sub-task deliberately leaves out (`_arm_timers`, `_poke_bots`, the
    D17 timer race, `SeatBinding`/session wiring).
    """

    def __init__(self, room_id: str, ruleset: RuleSet, game_seed: int) -> None:
        self.room_id = room_id
        self.inbox: asyncio.Queue[Command] = asyncio.Queue()
        self.state: GameState = new_game(ruleset, game_seed)
        self.event_id = 0  # internal monotonic id: logging/replay only, never on the wire
        self.seat_seq: list[int] = [0, 0, 0, 0]  # per-seat outbound seq: dense, gapless (D1)
        self.ring: dict[int | str, deque[Envelope]] = {
            seat: deque[Envelope](maxlen=512) for seat in range(4)
        }

    def submit(self, seat: int, action: Action) -> None:
        """Push one command onto the inbox. Stands in for app/ws.py's future envelope parsing
        (sub-task 4) -- also the test-facing entry point (`tests/test_room.py`)."""
        self.inbox.put_nowait(Command(seat=seat, action=action))

    async def run(self) -> None:
        """The room's long-lived loop -- one `asyncio.Task` per room (server/AGENTS.md)."""
        while True:
            await self.process_one()

    async def process_one(self) -> None:
        """Pull and fully handle exactly one command. Split out from `run()` so a test can drive
        the room one command at a time without a real background task racing it."""
        cmd = await self._next()
        self._handle(cmd)

    async def _next(self) -> Command:
        return await self.inbox.get()

    def _authorize(self, cmd: Command) -> Action | None:
        """Reject anything `actions.legal_actions(state, seat)` doesn't currently offer that
        seat (server/AGENTS.md: "the server computes the legal-action set. Never trust a
        client-supplied one") -- enforced here even though every caller today is this module's
        own test, since sub-task 4 will feed real client input through this exact path
        unchanged. Returns `None` for an illegal command; `_handle` drops it with no mutation."""
        if cmd.action in legal_actions(self.state, cmd.seat):
            return cmd.action
        return None

    def _handle(self, cmd: Command) -> None:
        action = self._authorize(cmd)
        if action is None:
            return  # illegal command: dropped silently, state and ring buffers untouched
        self.state, events = reduce(self.state, action)
        self.event_id += 1
        self._publish(events)
        if self.state.phase == Phase.HAND_OVER:
            # server-computed transition, no seat decision (actions.py, engine.py module
            # docstrings) -- advance immediately, same tick, before anything else touches
            # this command's result.
            self.state, more_events = start_next_hand(self.state)
            self.event_id += 1
            self._publish(more_events)

    def _publish(self, events: list[Event]) -> None:
        """`redact_event()` per recipient seat, appended to that seat's ring buffer with a fresh
        per-seat `seq`. Nothing reads `self.ring` yet -- that's sub-task 5's reconnect/resync job
        -- but it's populated correctly now anyway since that's cheap and must already be right
        by the time something does."""
        for event in events:
            for seat in range(4):
                wire = redact_event(self.state, seat, event)
                seq = self.seat_seq[seat]
                self.seat_seq[seat] = seq + 1
                self.ring[seat].append(Envelope(seq=seq, event=wire))
