"""`Room` -- the room actor's core dispatch loop (docs/00-architecture.md §3, §5;
docs/05-roadmap.md §1's M3).

**Sub-task scope: timer heap + D17 + claim-window early exit/timeout.** `_next()` now
implements the real dual-await-against-a-deadline-heap pattern §3 D17 describes: one
long-lived `_inbox_getter()` task, never cancelled, raced against a sleep to the timer heap's
soonest deadline. Bot dispatch (`_poke_bots`) and WS/Session integration are still later M3
sub-tasks (4/6); the heap here is scoped to claim-window deadlines only (`TimerHeap`'s own
docstring) -- there is no client/WS layer yet to drive a per-seat turn clock or a bot budget
against, so no machinery is built for those deadline kinds until something needs it.

Claim-window duration comes from `state.ruleset.claim_seconds` (`mahjong_core/config.py`,
already a real field, not a gap this sub-task had to invent).

**Early exit is already inside `reduce()`.** `mahjong_core.engine._apply_claim_response`
(landed in M2's engine-integration sub-task) calls `claims.can_close_early`/`resolve_claims`
itself, inline, the moment a claim response makes the window ready -- before this sub-task, a
real claim response submitted through `Room` already resolved early with no wait. This
sub-task's own job is what `reduce()` *can't* do without a clock: arming the deadline when a
window opens, and turning an *unanswered* deadline into synthesized `Pass` responses fed back
through the exact same `reduce()` path (`_apply_claim_response`/`resolve_claims`) a real
response uses -- see `_handle_claim_timeout`.

One room = one `asyncio.Task` = one writer (server/AGENTS.md): every mutation of `self.state`
happens inside `_apply`, called only from this module's own loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import heapq
from collections import deque
from dataclasses import dataclass
from typing import Any

from app.views import redact_event
from mahjong_core.actions import Action, Pass, legal_actions
from mahjong_core.config import RuleSet
from mahjong_core.engine import Event, new_game, reduce, start_next_hand
from mahjong_core.state import GameState, Phase

__all__ = ["Command", "Envelope", "Room", "TimerHeap"]


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


class TimerHeap:
    """Deadline heap keyed by `(deadline_ts, id)` (00-architecture.md §3 D17). Scoped to
    claim-window deadlines only for this sub-task -- per-seat turn clocks and bot budgets have
    no driver yet (no client/WS layer exists to run a turn clock against; that's M3 sub-task
    4+ territory) and half-building that machinery now would just be dead code. `id` is the
    claim window's own `window_id` (`mahjong_core.state.ClaimWindow`, already a room-global
    monotonic counter via `GameState.next_window_id`), so no separate id generator is needed
    here.

    Lazy deletion: resolving a window early doesn't remove its heap entry -- the entry is left
    in place and the caller (`Room._handle_claim_timeout`) checks the popped `window_id`
    against whatever window is actually current when it fires. A claim window resolving before
    its deadline is the *normal* case (early exit, 00-architecture.md §4), not an edge case, so
    every popped id has to be staleness-checked regardless of whether removal-on-resolve
    existed -- eager removal would only save a few stale heap entries, not remove the check.
    """

    def __init__(self) -> None:
        self._heap: list[tuple[float, int]] = []

    def add(self, deadline_ts: float, id_: int) -> None:
        heapq.heappush(self._heap, (deadline_ts, id_))

    def peek(self) -> float | None:
        """The soonest live deadline, or `None` if the heap is empty."""
        return self._heap[0][0] if self._heap else None

    def pop_expired(self, now: float) -> list[int]:
        """Every id whose deadline is `<= now`, earliest first, removed from the heap."""
        expired: list[int] = []
        while self._heap and self._heap[0][0] <= now:
            _, id_ = heapq.heappop(self._heap)
            expired.append(id_)
        return expired


class Room:
    """Owns exactly one `GameState`, mutated only via `reduce()`/`start_next_hand()`. See module
    docstring for what this sub-task deliberately leaves out (`_poke_bots`, `SeatBinding`/
    session wiring).
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
        self.deadlines = TimerHeap()  # claim window deadlines only (D17) -- see module docstring
        self._getter: asyncio.Task[Command] | None = None  # long-lived, never cancelled (D17)
        self._armed_window_id: int | None = None  # last claim_window.window_id given a deadline

    def submit(self, seat: int, action: Action) -> None:
        """Push one command onto the inbox. Stands in for app/ws.py's future envelope parsing
        (sub-task 4) -- also the test-facing entry point (`tests/test_room.py`)."""
        self.inbox.put_nowait(Command(seat=seat, action=action))

    async def run(self) -> None:
        """The room's long-lived loop -- one `asyncio.Task` per room (server/AGENTS.md)."""
        while True:
            await self.process_one()

    async def process_one(self) -> None:
        """Handle exactly one event: the next inbox `Command`, or a claim-window deadline
        expiry, whichever the event loop resolves first (`_next()`). Split out from `run()` so
        a test can drive the room one event at a time without a real background task racing
        it."""
        event = await self._next()
        if isinstance(event, Command):
            self._handle(event)
        else:
            self._handle_claim_timeout(event)  # event is the expired window_id
        self._arm_claim_timer()

    async def _inbox_getter(self) -> Command:
        return await self.inbox.get()

    def _ensure_getter(self) -> asyncio.Task[Command]:
        if self._getter is None:
            self._getter = asyncio.create_task(self._inbox_getter())
        return self._getter

    async def _next(self) -> Command | int:
        """00-architecture.md §3 D17: one long-lived `_inbox_getter()` task for the room's
        entire lifetime, raced against a sleep to `self.deadlines`' soonest entry via
        `asyncio.wait(..., return_when=FIRST_COMPLETED)` -- the getter is *never* cancelled,
        on either branch. When both are ready in the same `asyncio.wait` call (a command
        arrives the same scheduler tick a deadline expires), the getter always wins: a real
        command is applied that tick and the still-due timer entry is left in the heap to pop
        on the very next call, rather than risking the naive `wait_for`/cancel-on-timeout
        pattern's silent drop of an already-arrived item.
        """
        loop = asyncio.get_running_loop()
        while True:
            getter = self._ensure_getter()
            deadline = self.deadlines.peek()
            waitables: set[asyncio.Future[Any]] = {getter}
            sleeper: asyncio.Task[None] | None = None
            if deadline is not None:
                delay = max(0.0, deadline - loop.time())
                sleeper = asyncio.ensure_future(asyncio.sleep(delay))
                waitables.add(sleeper)

            done, _pending = await asyncio.wait(waitables, return_when=asyncio.FIRST_COMPLETED)

            if sleeper is not None and sleeper not in done:
                sleeper.cancel()  # lost the race -- holds no queue item, safe to cancel
                with contextlib.suppress(asyncio.CancelledError):
                    await sleeper

            if getter in done:
                self._getter = None  # consumed; next call spins up a fresh one (never cancelled)
                return getter.result()

            expired = self.deadlines.pop_expired(loop.time())
            if expired:
                return expired[0]
            # spurious wakeup (shouldn't happen -- loop back and recompute the next deadline)

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
        self._apply(action)

    def _handle_claim_timeout(self, window_id: int) -> None:
        """A claim-window deadline popped off `self.deadlines`. No-op if stale -- the window it
        was armed for already resolved (early exit or a prior timeout) and `self.state` has
        moved on, same staleness discipline `window_id` gets everywhere else (00-architecture.md
        §4: "claims tagged with a stale window are dropped silently"). Otherwise, every offered
        seat that hasn't responded yet is treated as `Pass` (claims.py's own documented
        convention) and fed through the same `reduce()` -> `_apply_claim_response` ->
        `resolve_claims` path a real response uses -- `_apply_claim_response` resolves inline
        the moment the window is ready, exactly like early exit, so this loop and a human's own
        early exit share one resolution path start to finish."""
        window = self.state.claim_window
        if window is None or window.window_id != window_id:
            return
        for offer in window.offers:
            current = self.state.claim_window
            if current is None or current.window_id != window_id:
                return  # resolved partway through (e.g. the second-to-last Pass closed it early)
            if offer.seat in current.responses:
                continue
            self._apply(Pass(window_id=window_id, seat=offer.seat))

    def _apply(self, action: Action) -> None:
        """Run one already-authorized `Action` through `reduce()`, publish, and chain into
        `start_next_hand()` on `HAND_OVER` -- the common tail shared by a real `Command`
        (`_handle`) and a synthesized claim-timeout `Pass` (`_handle_claim_timeout`)."""
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

    def _arm_claim_timer(self) -> None:
        """Arm a deadline the moment `self.state.claim_window` shows a new `window_id` --
        called after every event `process_one()` handles, mirroring `_arm_timers()` in
        00-architecture.md §3's Room sketch. Idempotent per window: `_armed_window_id` stops a
        window that's still accumulating responses across several `process_one()` calls from
        getting a fresh (and later) deadline each time. Duration is `ruleset.claim_seconds`
        (`mahjong_core/config.py`) -- already real config, not a placeholder."""
        window = self.state.claim_window
        if window is None or window.window_id == self._armed_window_id:
            return
        deadline = asyncio.get_running_loop().time() + self.state.ruleset.claim_seconds
        self.deadlines.add(deadline, window.window_id)
        self._armed_window_id = window.window_id

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
