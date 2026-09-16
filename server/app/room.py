"""`Room` -- the room actor's core dispatch loop (docs/00-architecture.md §3, §5;
docs/05-roadmap.md §1's M3).

**Timer heap + D17 + claim-window early exit/timeout (M3 sub-task 3).** `_next()` implements
the real dual-await-against-a-deadline-heap pattern §3 D17 describes: one long-lived
`_inbox_getter()` task, never cancelled, raced against a sleep to the timer heap's soonest
deadline. The heap itself is scoped to claim-window deadlines only (`TimerHeap`'s own
docstring); per-seat turn clocks and bot budgets still have no driver (no timeout *enforcement*
exists for either -- `turn`'s wire `deadline_ts` is advisory-only, see `_publish_turn_if_active`)
so no machinery is built for those deadline kinds until something needs it. Bot dispatch
(`_poke_bots`) is a later sub-task (6).

**Early exit is already inside `reduce()`.** `mahjong_core.engine._apply_claim_response`
(landed in M2's engine-integration sub-task) calls `claims.can_close_early`/`resolve_claims`
itself, inline, the moment a claim response makes the window ready. This module's own job is
what `reduce()` *can't* do without a clock: arming the deadline when a window opens, and
turning an *unanswered* deadline into synthesized `Pass` responses fed back through the exact
same `reduce()` path (`_apply_claim_response`/`resolve_claims`) a real response uses -- see
`_handle_claim_timeout`.

**Session/WS integration (M3 sub-task 4).** `join`/`mark_ready`/`set_auto`/`publish_to_seat`/
`state_sync_wire` are this Room's half of the wire protocol -- `app/ws.py`'s `Session` is the
other half, turning raw envelopes into calls here and this Room's published wire dicts into
real frames on a socket. `SeatBinding` holds the live per-seat state that has no home in the
pure `GameState` (a connection's push callback, `ready`/pre-arm flags, per-seat idempotency).
Several wire events (`hand_start`/`deal`/`turn`/`claim_offer`/`score`) have no backing
`mahjong_core.engine.Event` to redact -- see `_publish_hand_start_and_deal`/
`_publish_turn_if_active`/`_send_claim_offers`'s docstrings for why, and
docs/00-architecture.md §3's "Session/WS integration" note for the short version.

One room = one `asyncio.Task` = one writer (server/AGENTS.md): every mutation of `self.state`
happens inside `_apply`, called only from this module's own loop. `join`/`mark_ready`/
`set_auto` mutate `self.seat_bindings` (not `self.state`) directly from whatever task calls
them -- safe because they're synchronous with no `await`, so nothing else can interleave on
this room's event loop between one call's start and its return.
"""

from __future__ import annotations

import asyncio
import contextlib
import heapq
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.idempotency import IdempotencyCache
from app.views import redact_event, seat_view, seat_view_wire
from mahjong_core.actions import Action, Pass, action_to_dict, legal_actions
from mahjong_core.config import RuleSet
from mahjong_core.engine import Discarded, Event, HandEnded, new_game, reduce, start_next_hand
from mahjong_core.melds import MeldKind
from mahjong_core.state import ClaimOffer, ClaimWindow, GameState, Phase
from mahjong_core.tiles import tile_code, tile_id_type

__all__ = [
    "Command",
    "Envelope",
    "Room",
    "RoomFullError",
    "SeatBinding",
    "SeatTakenError",
    "TimerHeap",
]

_CLAIM_KIND_WIRE = {
    MeldKind.CHOW: "chow",
    MeldKind.PUNG: "pung",
    MeldKind.EXPOSED_KONG: "kong",
}


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


class SeatTakenError(Exception):
    """Raised by `Room.join(seat=...)` when the requested seat is already bound
    (docs/02-protocol.md §2 "Seat assignment" -> wire `error{code:'seat_taken'}`)."""

    def __init__(self, seat: int) -> None:
        super().__init__(f"seat {seat} is already taken")
        self.seat = seat


class RoomFullError(Exception):
    """Raised by `Room.join(seat=None)` when every seat is bound (wire
    `error{code:'room_full'}`)."""


@dataclass
class SeatBinding:
    """One seat's session binding (docs/00-architecture.md §3's sketch, built out here --
    sub-task 4's job per that sketch's own note). Lives on `Room`, not `Session`: idempotency
    is scoped "per seat binding, not per socket" (02-protocol.md §1), so it has to survive a
    future reconnect (sub-task 5) swapping out the `Session`/socket underneath it -- this is
    the object that will still exist across that swap.

    `send` is the live connection's push callback (`seq, wire -> None`); `ready`/`no_calls`/
    `auto_pass_chow` are the lobby/pre-arm state 02-protocol.md §2 describes. `seat_status`
    (connected/disconnected/autoplay/bot) has no real transitions yet -- every bound seat here
    is `"connected"` for this sub-task's scope (disconnect/bot-handover is sub-task 6).
    """

    session_id: str
    send: Callable[[int, dict[str, Any]], None]
    ready: bool = False
    no_calls: bool = False
    auto_pass_chow: bool = False
    idempotency: IdempotencyCache = field(default_factory=IdempotencyCache)


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

    def __init__(
        self, room_id: str, ruleset: RuleSet, game_seed: int, *, require_ready: bool = False
    ) -> None:
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
        self._claim_deadline_ms: dict[int, int] = {}  # window_id -> epoch-ms deadline, wire-facing

        # docs/02-protocol.md §2 "Seat assignment": `require_ready=True` (app/ws.py's real
        # rooms) gates every command on all four seats joining and `ready`-ing before the room
        # will process anything (`_authorize` below). `require_ready=False` (the default)
        # preserves this Room's pre-sub-task-4 behavior -- immediately actionable straight off
        # `new_game()` -- so `tests/test_room.py`/`tests/test_room_claims.py`, which drive a
        # bare `Room()` with no join/ready flow at all, are unaffected.
        self.require_ready = require_ready
        self.started = not require_ready
        self.seat_bindings: list[SeatBinding | None] = [None, None, None, None]

    def submit(self, seat: int, action: Action) -> None:
        """Push one command onto the inbox. This is app/ws.py's envelope-parsing landing spot
        (sub-task 4) -- also the test-facing entry point (`tests/test_room.py`)."""
        self.inbox.put_nowait(Command(seat=seat, action=action))

    # --- seats: join / ready / pre-arm (docs/02-protocol.md §2) --------------------------

    def join(
        self,
        session_id: str,
        send: Callable[[int, dict[str, Any]], None],
        *,
        seat: int | None = None,
    ) -> int:
        """Bind a session to a seat -- `seat=None` means "first open seat"
        (02-protocol.md §2). Raises `SeatTakenError`/`RoomFullError` for app/ws.py to turn into
        `error{code:'seat_taken'|'room_full'}`. On success, broadcasts `seat_state` to every
        already-bound seat (including this one) and unicasts a fresh `state_sync` to the
        joining seat -- both per 02-protocol.md §2/§3."""
        if seat is not None:
            if not 0 <= seat < 4:
                raise ValueError(f"seat must be 0..3, got {seat}")
            if self.seat_bindings[seat] is not None:
                raise SeatTakenError(seat)
            chosen = seat
        else:
            open_seats = [s for s in range(4) if self.seat_bindings[s] is None]
            if not open_seats:
                raise RoomFullError()
            chosen = open_seats[0]

        self.seat_bindings[chosen] = SeatBinding(session_id=session_id, send=send)
        self._broadcast_wire({"t": "seat_state", "seat": chosen, "status": "connected"})
        self.publish_to_seat(chosen, self.state_sync_wire(chosen))
        return chosen

    def mark_ready(self, seat: int) -> None:
        """`ready` (02-protocol.md §2): once every seat is joined *and* ready, the room deals
        -- for `require_ready=False` rooms (the default; see `__init__`) `self.started` is
        already `True` and this only flips the binding's own flag, matching "not a required
        step" for those direct-construction test rooms."""
        binding = self.seat_bindings[seat]
        if binding is None:
            raise ValueError(f"seat {seat} has not joined")
        binding.ready = True
        if self.started:
            return
        if all(b is not None and b.ready for b in self.seat_bindings):
            self.started = True
            self._publish_hand_start_and_deal()
            self._publish_turn_if_active()

    def set_auto(self, seat: int, *, no_calls: bool | None, auto_pass_chow: bool | None) -> None:
        """`auto` pre-arm toggles (02-protocol.md §2) -- `None` leaves that toggle unchanged,
        matching the wire payload's own `Optional` fields ("omit to leave as-is")."""
        binding = self.seat_bindings[seat]
        if binding is None:
            return
        if no_calls is not None:
            binding.no_calls = no_calls
        if auto_pass_chow is not None:
            binding.auto_pass_chow = auto_pass_chow

    # --- wire fan-out ------------------------------------------------------------------

    def publish_to_seat(self, seat: int, wire: dict[str, Any]) -> None:
        """Stamp `wire` with this seat's next `seq`, append it to the seat's ring buffer, and
        push it out over that seat's live connection if one is bound (`SeatBinding.send`) --
        the *only* path any seat-facing frame leaves this Room through, whether it came from
        `redact_event()` (`_publish`) or was synthesized here (`state_sync`/`hand_start`/
        `deal`/`turn`/`claim_offer`/`score`/`seat_state`/`ack`)."""
        seq = self.seat_seq[seat]
        self.seat_seq[seat] = seq + 1
        self.ring[seat].append(Envelope(seq=seq, event=wire))
        binding = self.seat_bindings[seat]
        if binding is not None:
            binding.send(seq, wire)

    def _broadcast_wire(self, wire: dict[str, Any]) -> None:
        for seat in range(4):
            self.publish_to_seat(seat, dict(wire))

    def state_sync_wire(self, seat: int) -> dict[str, Any]:
        """Full redacted snapshot for `seat` (02-protocol.md §3 `state_sync`) -- sent on join,
        and (sub-task 5) on reconnect-with-gap; also what `app/outbox.py`'s backpressure
        collapse resyncs to when a connection falls behind (§9)."""
        window = self.state.claim_window
        claim_deadline_ts = self._claim_deadline_ms.get(window.window_id) if window else None
        view = seat_view(self.state, seat, claim_deadline_ts=claim_deadline_ts)
        wire = seat_view_wire(view)
        wire["t"] = "state_sync"
        return wire

    async def run(self) -> None:
        """The room's long-lived loop -- one `asyncio.Task` per room (server/AGENTS.md)."""
        while True:
            await self.process_one()

    async def process_one(self) -> None:
        """Handle exactly one event: the next inbox `Command`, or a claim-window deadline
        expiry, whichever the event loop resolves first (`_next()`). Split out from `run()` so
        a test can drive the room one event at a time without a real background task racing
        it. `turn` is only (re-)published when this cycle actually mutated `self.state` --
        an illegal/dropped command (or a stale, already-resolved claim timeout) leaves `state`
        as the exact same object (`_authorize`/`_handle_claim_timeout`'s own no-op paths never
        call `_apply`), and must not re-stamp a fresh `seq` onto every seat's stream for a turn
        prompt nothing about actually changed."""
        pre_state = self.state
        event = await self._next()
        if isinstance(event, Command):
            self._handle(event)
        else:
            self._handle_claim_timeout(event)  # event is the expired window_id
        self._arm_claim_timer()
        if self.state is not pre_state:
            self._publish_turn_if_active()

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
        unchanged. Returns `None` for an illegal command; `_handle` drops it with no mutation.

        `require_ready` rooms additionally refuse everything until `self.started` -- belt and
        suspenders with app/ws.py's own pre-check (Session never even calls `submit()` before
        `ready`-gating completes), but this is the one place server/AGENTS.md's "never trust a
        client-supplied [legal-action set]" is actually enforced, so the gate belongs here too.
        """
        if not self.started:
            return None
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
        (`_handle`), a synthesized claim-timeout `Pass` (`_handle_claim_timeout`), and a
        pre-armed auto-pass (`_send_claim_offers`)."""
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
            if self.state.phase == Phase.AWAIT_ACTION:
                # start_next_hand() deals the next hand with no Event of its own (state.py/
                # engine.py: `new_game`/`_deal_hand` build state directly, not through
                # reduce()) -- hand_start/deal have no engine event to redact either way
                # (02-protocol.md §3's sketch, no EventKind backs them), so this Room
                # synthesizes both here, the same way it does for the ready-triggered hand 1
                # start (`Room.mark_ready`).
                self._publish_hand_start_and_deal()

    def _arm_claim_timer(self) -> None:
        """Arm a deadline the moment `self.state.claim_window` shows a new `window_id` --
        called after every event `process_one()` handles, mirroring `_arm_timers()` in
        00-architecture.md §3's Room sketch. Idempotent per window: `_armed_window_id` stops a
        window that's still accumulating responses across several `process_one()` calls from
        getting a fresh (and later) deadline each time. Duration is `ruleset.claim_seconds`
        (`mahjong_core/config.py`) -- already real config, not a placeholder.

        Also the one place `claim_offer` gets sent (`_send_claim_offers`): the wire message has
        no backing `Event` either (same "no EventKind" gap as hand_start/deal above), and needs
        the real deadline this method just computed anyway, so folding both into one idempotent,
        once-per-window call avoids a second `_armed_window_id`-shaped tracker.
        """
        window = self.state.claim_window
        if window is None or window.window_id == self._armed_window_id:
            return
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.state.ruleset.claim_seconds
        self.deadlines.add(deadline, window.window_id)
        self._armed_window_id = window.window_id
        # `TimerHeap`/`deadline` are monotonic loop time (D17); the wire needs server epoch ms
        # (02-protocol.md §4/§1's `ts`) -- converted once, here, via the (constant, within one
        # `_arm_claim_timer` call) offset between the two clocks.
        deadline_ms = _now_ms() + round((deadline - loop.time()) * 1000)
        self._claim_deadline_ms[window.window_id] = deadline_ms
        self._send_claim_offers(window, deadline_ms)

    def _send_claim_offers(self, window: ClaimWindow, deadline_ms: int) -> None:
        """Unicast `claim_offer` to every offered seat (02-protocol.md §3) -- except a seat
        whose pre-arm toggle (`auto`, §2) already decided this offer: `no_calls`, or
        `auto_pass_chow` when every option on offer is a chow. A win-eligible offer is *never*
        auto-resolved this way regardless of pre-arm (§2 "Declining a claim on purpose") -- it
        always gets a real `claim_offer`. Re-checks `self.state.claim_window` every iteration:
        a pre-armed `Pass` submitted mid-loop can close the window early (00-architecture.md
        §4), same staleness discipline `_handle_claim_timeout` already uses."""
        for offer in window.offers:
            current = self.state.claim_window
            if current is None or current.window_id != window.window_id:
                return  # resolved already -- a pre-armed pass closed it early
            binding = self.seat_bindings[offer.seat]
            if (
                binding is not None
                and not offer.can_win
                and (
                    binding.no_calls
                    or (
                        binding.auto_pass_chow and all(m.kind == MeldKind.CHOW for m in offer.melds)
                    )
                )
            ):
                self._apply(Pass(window_id=window.window_id, seat=offer.seat))
                continue
            self.publish_to_seat(
                offer.seat,
                {
                    "t": "claim_offer",
                    "window_id": window.window_id,
                    "options": self._claim_options_wire(offer),
                    "deadline_ts": deadline_ms,
                },
            )

    @staticmethod
    def _claim_options_wire(offer: ClaimOffer) -> list[dict[str, Any]]:
        options: list[dict[str, Any]] = []
        if offer.can_win:
            options.append({"kind": "win"})
        for meld in offer.melds:
            options.append({"kind": _CLAIM_KIND_WIRE[meld.kind], "tiles": list(meld.tiles)})
        options.append({"kind": "pass"})
        return options

    def _publish_hand_start_and_deal(self) -> None:
        """Synthesize `hand_start` (broadcast) and `deal` (per-seat) -- see `_arm_claim_timer`'s
        docstring for why these have no backing `Event`. Called once the room actually starts
        (`mark_ready`) and once per later hand (`_apply`, right after `start_next_hand()` deals
        it). `seats` is each seat's `seat_status` (`app/views.py`'s `SeatView` shape) -- every
        bound seat reads `"connected"` today (see `SeatBinding`'s docstring on why nothing
        richer exists yet)."""
        state = self.state
        self._broadcast_wire(
            {
                "t": "hand_start",
                "hand_no": state.hand_no,
                "prevailing": state.prevailing.name,
                "dealer": state.dealer,
                "seats": ["connected", "connected", "connected", "connected"],
            }
        )
        for seat in range(4):
            self.publish_to_seat(
                seat,
                {
                    "t": "deal",
                    "your_hand": list(state.seats[seat].concealed),
                    "counts": {s: len(state.seats[s].concealed) for s in range(4)},
                    "wall_remaining": len(state.wall.tiles),
                },
            )

    def _publish_turn_if_active(self) -> None:
        """Synthesize `turn` (02-protocol.md §3) whenever `self.state` is sitting in
        `AWAIT_ACTION` after something changed it -- called from `process_one()`'s tail and
        from the ready-triggered start (`mark_ready`). No backing `Event` either (same gap);
        every landing in `AWAIT_ACTION` is a genuinely new decision point (a fresh turn, or the
        same seat again after a self-kong's replacement draw changed their legal actions), so
        this doesn't need `_arm_claim_timer`'s once-per-window idempotency guard.

        `deadline_ts` is advisory only -- `ruleset.turn_seconds` from "now", not a real armed
        timer: per-turn timeout enforcement (tsumogiri-on-expiry) has no driver yet, same scope
        line `app/room.py`'s module docstring already draws ("no machinery is built for those
        deadline kinds until something needs it"); this sub-task is only "how a client would
        learn the deadline, not new timer logic" (its own brief). `legal` is unicast to the
        acting seat only, matching `turn.legal`'s own "unicast to the acting seat" contract.
        """
        if self.state.phase != Phase.AWAIT_ACTION:
            return
        seat = self.state.turn
        deadline_ts = _now_ms() + self.state.ruleset.turn_seconds * 1000
        legal = [action_to_dict(a) for a in legal_actions(self.state, seat)]
        for s in range(4):
            wire: dict[str, Any] = {
                "t": "turn",
                "seat": seat,
                "phase": self.state.phase.value,
                "deadline_ts": deadline_ts,
            }
            if s == seat:
                wire["legal"] = legal
            self.publish_to_seat(s, wire)

    def _publish(self, events: list[Event]) -> None:
        """`redact_event()` per recipient seat, appended to that seat's ring buffer with a fresh
        per-seat `seq`, and pushed out over each seat's live connection (`publish_to_seat`).
        `Discarded` gets `tile`/`pool_index` filled in here -- `redact_event` alone can't in
        general (`app/views.py`'s `DiscardWire` docstring), but this Room always redacts a
        `Discarded` event using `self.state` from immediately after the very `reduce()` call
        that produced it, before any *later*, separate command could claim that discard and
        remove it from the pool -- so `self.state.seats[event.seat].discards` still has it at
        its correct tail position every time this runs. A `HandEnded` also gets a broadcast
        `score` alongside it -- `state.seats[*].score` already reflects `_apply_payments()`'s
        result by the time `self.state` was reassigned above `_publish`'s own caller."""
        for event in events:
            for seat in range(4):
                wire = redact_event(self.state, seat, event)
                if isinstance(event, Discarded):
                    pool = self.state.seats[event.seat].discards
                    wire["tile"] = tile_code(tile_id_type(event.tile_id))
                    wire["pool_index"] = len(pool) - 1
                self.publish_to_seat(seat, wire)
            if isinstance(event, HandEnded):
                self._broadcast_wire(
                    {"t": "score", "totals": {s: self.state.seats[s].score for s in range(4)}}
                )
