"""`Room` -- the room actor's core dispatch loop (docs/00-architecture.md §3, §5;
docs/05-roadmap.md §1's M3).

**Timer heap + D17 + claim-window early exit/timeout (M3 sub-task 3).** `_next()` implements
the real dual-await-against-a-deadline-heap pattern §3 D17 describes: one long-lived
`_inbox_getter()` task, never cancelled, raced against a sleep to the timer heap's soonest
deadline. The heap holds claim-window, disconnect-grace, *and* per-seat turn deadlines, all
sharing one id space and one `TimerHeap` instance (`TimerHeap`'s own docstring) -- see the
"Turn timeout" note below for the third kind.

**Turn timeout (00-architecture.md §8 "Turn timeout" / "Bot raises / hangs").**
`_arm_turn_timer`, called from `_publish_turn_if_active` every time a seat's `AWAIT_ACTION`
decision is genuinely new, arms a `ruleset.turn_seconds` deadline in the same heap claim
windows and disconnect-grace use. On expiry (`_handle_turn_timeout`) the room applies the
doc's deterministic default (`_timeout_discard_action`: tsumogiri if this decision started
with a freshly drawn tile, else the lowest-`tile_id` concealed tile) through the normal
`_apply()`/`reduce()` path, exactly like a real `Discard` command, then registers a strike
(`_register_turn_timeout_strike`) -- three strikes flips the seat to `autoplay` for the rest
of the game (`SeatBinding.turn_timeout_strikes`). Fires identically for a connected human, a
disconnected/`autoplay` human, and a `bot` seat (M4.5): the timer races the wall clock, not
any particular bot job, so a hung or crashed worker (`_await_bot_job`'s own 10s hard deadline,
`_BOT_JOB_TIMEOUT_SECONDS`) can never wedge a table past `turn_seconds` regardless of whether
it ever answers.

**Disconnect / bot handover (M3 sub-task 6).** `mark_disconnected`/`reconnect` flip
`SeatBinding.status` between `connected`/`disconnected`/`autoplay`, surfaced to every seat via
broadcast `seat_state` and folded into `seat_view()`'s `seat_status`. A disconnect arms a
per-seat grace timer through the *same* `TimerHeap`/`self.deadlines` claim timers already use
(shared id space, `_timer_seat` vs. `_disconnect_timer_seat` tell them apart on pop) rather than
a second timer mechanism; on expiry the seat flips to `autoplay`. `_poke_bots()`, called at the
tail of every `process_one()` tick, submits a decision to a `ProcessPoolExecutor` (D12) for
every `autoplay` **or `bot`** seat that currently has one (its own turn, or a live claim offer),
tagged with `BotJobTag` (`(kind, key, state_version)`); the result re-enters through `self.inbox`
as a `BotResult` carrying a bare action id, decoded back into a real `Action` here (against this
process's own `GameState` -- see `bots/worker.py`'s module docstring for why the worker can't do
that itself), and is dropped if the tag no longer matches `_pending_bot[seat]` by the time it
lands -- the window closed, the turn moved on, or the seat reconnected. `_bot_tier` (`Room.
__init__`) picks the real tier (`T0`/`T1`/`T2`, default `T2`/`FaanBot`) every such job runs. See
`mark_disconnected`/`_poke_bots`/`_handle_bot_result`.

**Bot-filled seats from room creation (M4.5 practice mode).** `practice=True` (`Room.__init__`)
binds seats 1-3 to `bot_tier` bots immediately, before seat 0's human ever `join`s -- a `bot`
`SeatBinding.status`, distinct from `autoplay` (a seat that *was* human and lost its connection)
but driven through the exact same `_poke_bots`/`BotJobTag`/`ProcessPoolExecutor` machinery, not
a parallel code path. See `SeatBinding`'s docstring and `_bind_bot_seat`.

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

**DB persistence + graceful shutdown (docs/00-architecture.md §6/§8.1, docs/06-ml.md §2's
`GameRecord`).** `self.actions` accumulates every `Action` this room ever applies via `_apply`
(never `start_next_hand()` transitions -- those aren't `Action`s and replay reconstructs them
automatically off `Phase.HAND_OVER`, same convention `bots/selfplay.py`'s `play_game` already
documents) across the *entire game*, all hands, surviving `start_next_hand()` transitions simply
because nothing ever resets it -- `Room` is one long-lived object for one game, not recreated
per hand. On reaching `Phase.GAME_OVER`, `process_one()` calls `save_game_record` (if a
`session_factory` was wired in at construction -- `None` is a real, supported "no persistence"
mode, matching every bare `Room()` test that constructs one directly) with `self.actions` and
`players` taken from each seat's `SeatBinding.session_id` -- the closest thing to a stable
identity that exists before `hello`'s guest `name` field ships (M5, 00-architecture.md §2.1); a
`None` entry means that seat was never joined by a human.
`_boundary_this_tick`/`_shutdown_boundary` back `wait_for_shutdown_boundary`,
`app/registry.py`'s `RoomRegistry.begin_shutdown`'s per-room half of the graceful-drain sequence
(§8.1) -- the boundary-reached event is only ever set *after* an in-flight `GAME_OVER` persist
finishes, never before, so a drain can't tear down a room (or the process dispose its DB engine)
while that room's own final write is still in flight. **This was violated until a real bug fix**:
`wait_for_shutdown_boundary`'s own fast path used to return `True` the instant
`self.state.phase == Phase.GAME_OVER`, which `_apply` flips *before* `process_one()`'s tail even
starts the persist -- a drain landing in that window (trivial with `SHUTDOWN_GRACE_SECONDS=0`,
but reachable in production at any grace window if `SIGTERM` lands in the same instant a hand
ends) saw "already done" and let `app/main.py`'s `lifespan` dispose the DB engine while
`_persist_game_record` was still awaiting its own write, silently losing the `GameRecord`. The
fast path now waits on `_game_over_persisted`, set only once that write has actually returned.
"""

from __future__ import annotations

import asyncio
import contextlib
import heapq
import itertools
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import Executor, ProcessPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.records import save_game_record
from app.idempotency import IdempotencyCache
from app.views import SeatView, redact_event, seat_view, seat_view_wire
from bots.worker import BOT_TIERS, DEFAULT_BOT_TIER, compute_action
from mahjong_core.actions import Action, Discard, Pass, action_to_dict, legal_actions
from mahjong_core.config import RuleSet
from mahjong_core.engine import (
    Discarded,
    Drawn,
    Event,
    HandEnded,
    KongReplacementDrawn,
    new_game,
    reduce,
    start_next_hand,
)
from mahjong_core.melds import MeldKind
from mahjong_core.ml import decode_action, legal_mask
from mahjong_core.state import ClaimOffer, ClaimWindow, GameState, Phase
from mahjong_core.tiles import TileId, tile_code, tile_id_type

__all__ = [
    "BotJobTag",
    "BotResult",
    "Command",
    "Envelope",
    "Room",
    "RoomFullError",
    "SeatBinding",
    "SeatNotBoundError",
    "SeatStatus",
    "SeatTakenError",
    "TimerHeap",
    "WireSeatStatus",
]

SeatStatus = Literal["connected", "disconnected", "autoplay", "bot"]

# Wire-level vocabulary for `_seat_status_tuple()`/`seat_view()`'s `seat_status`. `empty` has no
# `SeatBinding` counterpart: a binding only exists once a seat *is* bound, so "nobody has ever
# joined this seat" isn't a `SeatBinding.status` value, only something `_seat_status_tuple()`
# reports for a `None` slot in `Room.seat_bindings`. `bot` *is* a real `SeatBinding.status` now
# (M4.5 practice mode, `_bind_bot_seat`) -- see `SeatBinding`'s docstring.
WireSeatStatus = Literal["connected", "disconnected", "autoplay", "bot", "empty"]

_BOT_JOB_TIMEOUT_SECONDS = 10.0  # hard deadline (00-architecture.md §8 "Bot raises / hangs")

_default_bot_pool: ProcessPoolExecutor | None = None


def _shared_bot_pool() -> ProcessPoolExecutor:
    """One `ProcessPoolExecutor` per server process, created lazily on first use (constructing
    it doesn't spawn a worker -- workers start on first `submit()`), not one per `Room` (D12:
    "a process pool", not a swarm of them). `Room.__init__`'s `bot_pool` param exists so tests
    (and a future `RoomRegistry`) can inject a different `Executor` instead."""
    global _default_bot_pool
    if _default_bot_pool is None:
        _default_bot_pool = ProcessPoolExecutor()
    return _default_bot_pool


_CLAIM_KIND_WIRE = {
    MeldKind.CHOW: "chow",
    MeldKind.PUNG: "pung",
    MeldKind.EXPOSED_KONG: "kong",
}


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _turn_draw_tile_for_current_turn(events: list[Event], state: GameState) -> TileId | None:
    """Whether `state`'s current `AWAIT_ACTION` seat is holding a genuinely freshly-drawn tile
    this decision -- the signal `Room._timeout_discard_action` needs to choose tsumogiri over
    the lowest-`tile_id` fallback (00-architecture.md §8 "Turn timeout"). Reads the real
    `Drawn`/`KongReplacementDrawn` events `reduce()`/`start_next_hand()` actually emitted this
    tick, rather than inferring it from tile counts -- both "just drew" and "just claimed a
    pung/chow" leave the seat's hand at the same size pre-discard, so a count-based heuristic
    can't tell them apart (and risks naming a tile that was never actually drawn).

    `None` covers two different cases identically, both correctly handled by
    `_timeout_discard_action`'s fallback: nothing was drawn (a claimed pung/chow landed the
    seat here with nothing new in hand), and a fresh hand's opening deal (`new_game`/
    `_deal_hand` build the dealt hand directly, with no `Event` of their own -- module
    docstring's "no Event" note -- so there's no single tile to call "the drawn one" even
    though the dealer's stand-in 14th tile plays the same structural role).
    """
    if state.phase != Phase.AWAIT_ACTION:
        return None
    for event in reversed(events):
        if isinstance(event, (Drawn, KongReplacementDrawn)) and event.seat == state.turn:
            return event.tile_id
    return None


class SeatTakenError(Exception):
    """Raised by `Room.join(seat=...)` when the requested seat is already bound
    (docs/02-protocol.md §2 "Seat assignment" -> wire `error{code:'seat_taken'}`)."""

    def __init__(self, seat: int) -> None:
        super().__init__(f"seat {seat} is already taken")
        self.seat = seat


class RoomFullError(Exception):
    """Raised by `Room.join(seat=None)` when every seat is bound (wire
    `error{code:'room_full'}`)."""


class SeatNotBoundError(Exception):
    """Raised by `Room.reconnect(seat, ...)` when nothing has ever `join`ed this seat -- there
    is no `SeatBinding` to reclaim (wire `error{code:'no_such_seat'}`, `app/ws.py`). Distinct
    from `SeatTakenError`: that one fires on `join` finding a seat *already* bound; this one
    fires on `hello{last_seq, seat}` finding a seat *never* bound."""

    def __init__(self, seat: int) -> None:
        super().__init__(f"seat {seat} has never been joined")
        self.seat = seat


@dataclass
class SeatBinding:
    """One seat's session binding (docs/00-architecture.md §3's sketch, built out here --
    sub-task 4's job per that sketch's own note). Lives on `Room`, not `Session`: idempotency
    is scoped "per seat binding, not per socket" (02-protocol.md §1), so it has to survive a
    future reconnect (sub-task 5) swapping out the `Session`/socket underneath it -- this is
    the object that will still exist across that swap.

    `send` is the live connection's push callback (`seq, wire -> None`); `ready`/`no_calls`/
    `auto_pass_chow` are the lobby/pre-arm state 02-protocol.md §2 describes. `status`
    (`connected`/`disconnected`/`autoplay`/`bot` -- `empty` can never apply to a `SeatBinding`:
    a binding only exists once a seat *is* bound, so "nobody has ever joined this seat" is
    reported by `_seat_status_tuple()` for a `None` slot in `Room.seat_bindings`, never as a
    value of this field) transitions via `mark_disconnected`/`reconnect`/the disconnect-grace
    timer (M3 sub-task 6) for a seat that started as a human `join` -- see
    `Room.mark_disconnected`.

    **`bot` (M4.5 practice mode, `_bind_bot_seat`) is the other way a `SeatBinding` comes to
    exist**: a seat bound to a bot from room construction, never a human `join` at all. It
    reuses this exact dataclass -- a real `send` no-op callback, `ready=True` (a bot doesn't
    wait to click ready, so `require_ready` gating still starts the hand correctly once every
    *human* seat has readied) -- rather than a parallel tracking structure, so `_poke_bots()`
    drives it through the identical `BotJobTag`/`ProcessPoolExecutor` path an `autoplay` seat
    already uses (see `_poke_bots`). Unlike `autoplay`, `bot` is never reached by
    `mark_disconnected` (no session ever binds this seat, so `app/ws.py`'s disconnect signal
    never fires for it) and `reconnect` refuses to hijack it (raises `SeatTakenError`, same as
    `join` finding the seat already taken) -- there is no human occupant to hand it back to.

    `turn_timeout_strikes` (00-architecture.md §8 "Turn timeout": "Three strikes -> seat flips
    to AUTOPLAY for the rest of the game") counts consecutive-or-not `AWAIT_ACTION` timeouts
    for this seat, incremented by `Room._register_turn_timeout_strike`. **Never reset anywhere
    -- that omission is the "for the rest of the game" reset policy, not an oversight.** This
    binding is one long-lived object for the room's entire game (never recreated per hand;
    `reconnect` only swaps the live socket underneath it), so simply never zeroing this field
    already gives "accumulates across hand boundaries and reconnects alike" for free, with no
    explicit "which hand is this" bookkeeping needed.
    """

    session_id: str
    send: Callable[[int, dict[str, Any]], None]
    status: SeatStatus = "connected"
    ready: bool = False
    no_calls: bool = False
    auto_pass_chow: bool = False
    idempotency: IdempotencyCache = field(default_factory=IdempotencyCache)
    turn_timeout_strikes: int = 0


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


@dataclass(frozen=True)
class BotJobTag:
    """What a submitted bot job was computed against (00-architecture.md §3 D12's
    `(window_id, state_version)` tag). `state_version` is `Room.event_id` at submission time --
    `event_id` already exists as the room's own monotonic "has anything actually changed"
    counter (module docstring), so it doubles as `state_version` rather than inventing a second
    one; `self.state` is provably unchanged from what a job was computed against as long as
    `event_id` hasn't moved, since `_apply` is the only place either ever changes, together.
    `key` disambiguates *what kind* of decision this was for: the acting seat for a `turn`
    decision (there's no `window_id` outside a claim window), or the `window_id` for a `claim`
    decision."""

    kind: Literal["turn", "claim"]
    key: int
    state_version: int


@dataclass(frozen=True)
class BotResult:
    """A `ProcessPoolExecutor` worker's answer, re-entering through `Room.inbox` exactly like a
    real `Command` (D12) -- `tag` is compared against `Room._pending_bot[seat]` and dropped
    silently if it no longer matches (`_handle_bot_result`).

    `aid` is a bare action id (`mahjong_core.ml`'s fixed 109-id space), not a concrete `Action`
    -- `bots/worker.py`'s `compute_action` can't decode one itself (a worker process never
    receives `GameState`, D2), so `_handle_bot_result` does the `decode_action(aid, state, seat)`
    step here, against the real `GameState` this process already holds. See `bots/worker.py`'s
    module docstring for why this is the one deliberate change to this path's result shape."""

    seat: int
    tag: BotJobTag
    aid: int


@dataclass(frozen=True)
class _WakeUp:
    """No-op inbox marker. `_next()`'s `asyncio.wait()` call fixes its waitable set (the inbox
    `getter` plus a sleeper for whatever `self.deadlines.peek()` was *at that moment*) the
    instant it's entered -- nothing changes that set until one of those waitables completes.
    `_arm_disconnect_timer`/`_arm_seat_claim_timer` can run from *outside* this room's own
    `process_one()` tick (`mark_disconnected`/`resume()`, both called directly from `Session`
    on an incoming WS frame, not from this room's loop) and add a heap entry that's earlier
    than -- or the *only* entry, where none existed -- whatever `_next()` is already blocked
    on. Without this, that new deadline would sit in the heap unnoticed until some unrelated
    inbox item happened to arrive and force a fresh `_next()` call to recompute the sleeper.
    Pushing this onto `self.inbox` forces exactly that recompute, immediately, every time a
    deadline is armed from outside the loop -- see `Room._wake`."""


class TimerHeap:
    """Deadline heap keyed by `(deadline_ts, id)` (00-architecture.md §3 D17). Holds claim-window
    deadlines (M3 sub-task 3/5), disconnect-grace deadlines (M3 sub-task 6), and per-seat
    `AWAIT_ACTION` turn deadlines (00-architecture.md §8 "Turn timeout"), sharing one id space
    (`Room._timer_seq`) and one heap (`Room.deadlines`) -- `_dispatch_expired_timer` tells them
    apart by which side-table (`_timer_seat` / `_turn_timer_seat` / `_disconnect_timer_seat`)
    recognizes a popped id, rather than this class knowing about any of them.

    **`id` is a private per-seat timer id (M3 sub-task 5), not the window's own `window_id`.**
    Sub-task 3 armed exactly one heap entry per claim window, shared by every offered seat, and
    used `window_id` as the heap id directly -- correct as long as every offered seat's deadline
    was always identical. Reconnect (docs/00-architecture.md §8's "mid-claim-window" row) breaks
    that assumption: one seat's deadline can move (re-armed to a fresh window on reconnect)
    without touching another's, so each offered seat needs its *own* heap entry. `Room` now
    hands out a fresh id per seat-arm (`_timer_seq`) and keeps `_timer_seat`/
    `_active_seat_timer` to map an id back to `(window_id, seat)` and to tell a superseded
    (re-armed-away) entry from the one that's actually still live for that seat -- see
    `_arm_seat_claim_timer`/`_handle_claim_timeout`.

    Lazy deletion: resolving a window (or re-arming one seat's entry) early doesn't remove the
    superseded heap entry -- it's left in place and the caller (`Room._handle_claim_timeout`)
    checks the popped id against whatever is actually current when it fires. A claim window
    resolving before its deadline is the *normal* case (early exit, 00-architecture.md §4), not
    an edge case, so every popped id has to be staleness-checked regardless of whether
    removal-on-resolve existed -- eager removal would only save a few stale heap entries, not
    remove the check.
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
    docstring for disconnect/bot-handover (`mark_disconnected`/`_poke_bots`, M3 sub-task 6).

    `bot_tier` (`bots.worker.BOT_TIERS`, default `bots.worker.DEFAULT_BOT_TIER` = `T2`/`FaanBot`,
    per docs/05-roadmap.md M4.5) picks which real tier answers for *every* bot-driven seat this
    room ever has -- disconnect-handover autoplay and M4.5 practice-mode bot seats alike, both
    routed through the same `_poke_bots` path (see `SeatBinding`'s docstring). One tier per room,
    not per seat: nothing in this sub-task's scope (a fixed-difficulty practice table) needs a
    mixed-tier room, and `T0`/`T1` stay fully selectable by passing a different value, so the
    arena/tests that assume T0's uniform-random disconnect-handover behavior aren't forced onto
    T2. `practice=True` binds seats 1-3 to `bot_tier` bots immediately at construction (before
    seat 0's human ever joins) -- see `_bind_bot_seat`.
    """

    def __init__(
        self,
        room_id: str,
        ruleset: RuleSet,
        game_seed: int,
        *,
        require_ready: bool = False,
        bot_pool: Executor | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        bot_tier: str = DEFAULT_BOT_TIER,
        practice: bool = False,
    ) -> None:
        if bot_tier not in BOT_TIERS:
            raise ValueError(f"unknown bot tier {bot_tier!r}; choices: {BOT_TIERS}")
        self._bot_tier = bot_tier
        self.room_id = room_id
        self.inbox: asyncio.Queue[Command | BotResult | _WakeUp] = asyncio.Queue()
        self.state: GameState = new_game(ruleset, game_seed)
        self.event_id = 0  # internal monotonic id: logging/replay only, never on the wire
        # full-game action log (module docstring's "DB persistence" note) -- every Action _apply
        # actually runs through reduce(), never start_next_hand() transitions.
        self.actions: list[Action] = []
        self._session_factory = session_factory
        self._persisted = False  # save_game_record fires at most once, even if driven manually
        self._game_over_persisted = False  # see wait_for_shutdown_boundary -- True only once
        # the GAME_OVER persist attempt (a real write, or the no-session_factory no-op) returns
        self._boundary_this_tick = False  # reset each process_one() tick, set inside _apply
        self._shutdown_boundary: asyncio.Event | None = None  # see wait_for_shutdown_boundary
        self.seat_seq: list[int] = [0, 0, 0, 0]  # per-seat outbound seq: dense, gapless (D1)
        self.ring: dict[int | str, deque[Envelope]] = {
            seat: deque[Envelope](maxlen=512) for seat in range(4)
        }
        self.deadlines = TimerHeap()  # claim + disconnect + turn deadlines -- see module docstring
        self._getter: asyncio.Task[Command | BotResult | _WakeUp] | None = None  # long-lived (D17)
        self._armed_window_id: int | None = None  # last claim_window.window_id given a deadline
        # shared TimerHeap id space, claim/turn/disconnect-grace timers alike (see
        # TimerHeap's docstring)
        self._timer_seq = itertools.count(1)
        self._timer_seat: dict[int, tuple[int, int]] = {}  # timer id -> (window_id, seat)
        # (window_id, seat) -> the timer id that's actually live for it right now
        self._active_seat_timer: dict[tuple[int, int], int] = {}
        self._claim_deadline_ms: dict[tuple[int, int], int] = {}  # (window_id, seat) -> deadline_ts
        self._disconnect_timer_seat: dict[int, int] = {}  # timer id -> seat
        self._active_disconnect_timer: dict[int, int] = {}  # seat -> the timer id live for it
        # per-seat AWAIT_ACTION turn deadlines (00-architecture.md §8 "Turn timeout") -- same
        # lazy-deletion staleness discipline as the claim-window tables above, one live entry
        # per seat since only one seat is ever `state.turn` at a time.
        self._turn_timer_seat: dict[int, int] = {}  # timer id -> seat
        self._active_turn_timer: dict[int, int] = {}  # seat -> the timer id live for it
        self._turn_deadline_ms: dict[int, int] = {}  # seat -> that seat's current turn deadline_ts
        # the tile_id `Drawn`/`KongReplacementDrawn` landed for whichever seat `self.state` is
        # currently offering an AWAIT_ACTION decision to, if any -- refreshed every `_apply()`
        # call in lockstep with `self.state` itself, so it's always describing *that* decision by
        # the time `_timeout_discard_action` reads it (see `_apply`'s own note).
        self._turn_draw_tile: TileId | None = None

        # bot handover (M3 sub-task 6, D12): seat -> the BotJobTag currently in flight for it
        # (absent = no job outstanding). `_bot_tasks` holds strong refs to the asyncio.Tasks
        # awaiting each ProcessPoolExecutor future so they aren't GC'd mid-flight.
        self._pending_bot: dict[int, BotJobTag] = {}
        self._bot_tasks: set[asyncio.Task[None]] = set()
        self._bot_pool: Executor = bot_pool if bot_pool is not None else _shared_bot_pool()

        # docs/02-protocol.md §2 "Seat assignment": `require_ready=True` (app/ws.py's real
        # rooms) gates every command on all four seats joining and `ready`-ing before the room
        # will process anything (`_authorize` below). `require_ready=False` (the default)
        # preserves this Room's pre-sub-task-4 behavior -- immediately actionable straight off
        # `new_game()` -- so `tests/test_room.py`/`tests/test_room_claims.py`, which drive a
        # bare `Room()` with no join/ready flow at all, are unaffected.
        self.require_ready = require_ready
        self.started = not require_ready
        self.seat_bindings: list[SeatBinding | None] = [None, None, None, None]

        # M4.5 practice mode (docs/05-roadmap.md): seat 0 is left open for the human `join`;
        # seats 1-3 are bound to `self._bot_tier` bots immediately, before anyone ever connects
        # -- see `_bind_bot_seat`'s docstring for why this is cleanest done here rather than on
        # a later "still empty after N seconds" trigger.
        if practice:
            for seat in range(1, 4):
                self._bind_bot_seat(seat)

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

    def _bind_bot_seat(self, seat: int) -> None:
        """Bind `seat` to a bot from room construction (M4.5 practice mode), not a human `join`
        -- called only from `__init__`, before any real connection exists, so there is nothing
        to broadcast yet (the first seat that actually joins gets a correct `seat_status` for
        this seat -- `bot` -- in its own `state_sync`, same as any other already-bound seat).

        A real `SeatBinding` (see its own docstring's "`bot`" note) rather than a parallel
        tracking structure: `send` is a no-op (no live socket to push to -- `publish_to_seat`'s
        ring-buffer bookkeeping is harmless busywork against a seat nobody will ever replay
        from), `ready=True` (a bot doesn't wait to click ready), `session_id` is a synthetic,
        never-matched value (`mark_disconnected`'s session-id guard means a stray disconnect
        signal could never affect this binding even if one somehow arrived for this seat
        number, which `app/ws.py` never lets happen -- see `reconnect`'s bot-seat guard)."""
        self.seat_bindings[seat] = SeatBinding(
            session_id=f"bot-seat-{seat}",
            send=lambda seq, wire: None,
            status="bot",
            ready=True,
        )

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

    # --- reconnect / resync (docs/02-protocol.md §5, docs/00-architecture.md §8) -----------

    def reconnect(
        self, seat: int, session_id: str, send: Callable[[int, dict[str, Any]], None]
    ) -> bool:
        """Rebind an already-bound seat's live connection to a fresh socket
        (02-protocol.md §2: "hello{last_seq} on an already-bound seat reclaims it directly").
        Unlike `join`, this never constructs a new `SeatBinding` -- `ready`/pre-arm toggles and
        the per-seat `IdempotencyCache` (02-protocol.md §1: "survives reconnect... the seat's id
        history") all live on the binding that already exists, so only the live-socket half
        (`session_id`/`send`) is swapped. Raises `SeatNotBoundError` if nothing has ever joined
        this seat -- there's no binding to reclaim; the caller should `join` instead. Raises
        `SeatTakenError` if this seat is bound to a bot from room construction (M4.5 practice
        mode, `_bind_bot_seat`) rather than a human -- there is no prior human occupant to hand
        the seat back to, so a `hello{seat}` naming it is refused the same way `join` refuses a
        seat someone else already holds (`app/ws.py`'s `_handle_hello` turns this into the same
        `error{code:'seat_taken'}` `join` would).

        Also flips `status` back to `connected` (00-architecture.md §8 "Player reconnects": "Bot
        relinquishes the seat") if this seat was `disconnected`/`autoplay` -- and drops any
        in-flight bot job for this seat by clearing `_pending_bot[seat]`: a `BotResult` that
        lands later carries the old tag, which no longer matches, so `_handle_bot_result` drops
        it (D12's staleness rule doing double duty as "the bot stops acting for it" -- no
        separate cancellation path needed). Also invalidates this seat's disconnect-grace timer,
        if one is still ticking, the same lazy-deletion way `_rearm_seat_claim_timer`
        invalidates a superseded claim timer.

        Returns whether `status` actually changed away from `disconnected`/`autoplay`.
        **Deliberately does not itself broadcast `seat_state` for that** -- the caller
        (`Session._handle_hello`, via `resume()`'s `announce_reconnect`) defers that broadcast
        until after `resume()`'s own replay/state_sync decision. Broadcasting here instead would
        append the "connected" frame to this very seat's ring *before* `resume()` takes its
        `head`/ring snapshot, making `resume()`'s own replay branch re-deliver it a second time
        to the seat that just reconnected -- the exact frame announcing its own reconnection,
        double-sent. Every other seat only ever sees it once either way; only the reconnecting
        seat's replay path can re-observe its own just-appended history.
        """
        binding = self.seat_bindings[seat]
        if binding is None:
            raise SeatNotBoundError(seat)
        if binding.status == "bot":
            raise SeatTakenError(seat)
        binding.session_id = session_id
        binding.send = send
        was_status = binding.status
        binding.status = "connected"
        self._pending_bot.pop(seat, None)
        self._active_disconnect_timer.pop(seat, None)
        return was_status != "connected"

    def mark_disconnected(self, seat: int, session_id: str) -> None:
        """The WS connection for `seat` closed (`app/ws.py`'s `ws_endpoint` `finally` block --
        the only disconnect signal this sub-task wires up; a heartbeat-driven dead-socket
        timeout per docs/02-protocol.md §8 has no driver anywhere in this codebase yet, sub-task
        4 never built one, so it's out of scope here too, not silently dropped).

        `session_id` guards a real race: an old, already-superseded connection's `finally` can
        run *after* a fresh reconnect already rebound this seat to a new session (event-loop
        scheduling gives no ordering guarantee between "old socket's read loop notices EOF" and
        "new socket's `hello` gets processed"). If `binding.session_id` no longer matches the
        session that's reporting the disconnect, a newer connection already has this seat --
        do nothing, rather than marking a live reconnect disconnected out from under it.

        No-op if the seat isn't bound, or is already `disconnected`/`autoplay` (a duplicate
        close notification, or a socket that closed after the grace period already flipped the
        seat to `autoplay`) -- 00-architecture.md §8 "Player disconnects": seat marked
        `DISCONNECTED`, room continues, grace period before bot takeover.
        """
        binding = self.seat_bindings[seat]
        if binding is None or binding.session_id != session_id:
            return
        if binding.status != "connected":
            return
        binding.status = "disconnected"
        self._broadcast_wire({"t": "seat_state", "seat": seat, "status": "disconnected"})
        self._arm_disconnect_timer(seat)

    def resume(self, seat: int, last_seq: int | None, *, announce_reconnect: bool = False) -> None:
        """The three-way `hello{last_seq}` branch (02-protocol.md §5) for a seat that just
        called `reconnect()`, compared against *this seat's own* `ring`/`seat_seq` (never the
        room-global `event_id`, D1):

        - `last_seq == head` -- nothing missed, resume live: no replay.
        - `last_seq` still in the 512-entry ring -- replay exactly the envelopes after it,
          already-redacted, exactly as originally sent (never re-redacted against `self.state`,
          which has moved on -- 02-protocol.md §5's own rationale for why the ring stores
          post-redaction frames).
        - otherwise (evicted from the ring, or no real `last_seq` at all) -- a full
          `state_sync`, same as `join`.

        Also re-arms this seat's own claim-window deadline first if it holds a live, unresolved
        offer (00-architecture.md §8's "mid-claim-window" reconnect row) -- done before the
        branch above so a `state_sync` picks up the fresh deadline in the same round trip; the
        live/replay branches instead follow up with one fresh `claim_offer` carrying the new
        deadline, since a replayed frame is history and must not be mutated in place.

        `announce_reconnect` (M3 sub-task 6, set from `reconnect()`'s own return value by
        `Session._handle_hello`) broadcasts `seat_state{status:"connected"}` -- deliberately
        *after* the branch above, not before: see `reconnect()`'s docstring for why broadcasting
        it earlier would let this seat's own replay branch re-deliver it a second time.

        Runs to completion synchronously, with no `await` anywhere in this method: a caller
        that has actually *received* any one frame this call produced (the replay, the
        `state_sync`, or the `announce_reconnect` broadcast) is guaranteed this call has
        already finished, rearm included -- see `tests/test_reconnect.py`'s module docstring
        for why that guarantee is the whole fix for a real, CI-only test race that lived here.
        """
        rearmed = self._rearm_seat_claim_timer(seat)
        head = self.seat_seq[seat] - 1  # last seq actually sent, or -1 if this seat never got one
        ring = self.ring[seat]
        if last_seq is not None and last_seq == head:
            pass  # nothing missed
        elif last_seq is not None and ring and ring[0].seq <= last_seq < head:
            binding = self.seat_bindings[seat]
            assert binding is not None  # reconnect() above already required a bound seat
            for env in ring:
                if env.seq > last_seq:
                    binding.send(env.seq, dict(env.event))
        else:
            self.publish_to_seat(seat, self.state_sync_wire(seat))
            if announce_reconnect:
                self._broadcast_wire({"t": "seat_state", "seat": seat, "status": "connected"})
            return  # state_sync already carries any fresh deadline_ts -- nothing further to send
        if announce_reconnect:
            self._broadcast_wire({"t": "seat_state", "seat": seat, "status": "connected"})
        if rearmed:
            self._send_seat_claim_offer(seat)

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

    def broadcast_server_shutdown(self, deadline_ts: int) -> None:
        """docs/00-architecture.md §8.1 step 2: tell every seat a drain has started -- clients
        show a "reconnect shortly" banner instead of reading the eventual dropped socket as an
        error. Called by `app/registry.py`'s `RoomRegistry.begin_shutdown`, once per room that
        currently has any seat bound, regardless of that seat's live connection status (same
        "broadcast reaches the ring buffer either way" convention every other broadcast here --
        `seat_state`, etc. -- already follows)."""
        self._broadcast_wire({"t": "server_shutdown", "deadline_ts": deadline_ts})

    def state_sync_wire(self, seat: int) -> dict[str, Any]:
        """Full redacted snapshot for `seat` (02-protocol.md §3 `state_sync`) -- sent on join,
        and (sub-task 5) on reconnect-with-gap; also what `app/outbox.py`'s backpressure
        collapse resyncs to when a connection falls behind (§9). `turn_deadline_ts` is this
        seat's real armed `AWAIT_ACTION` deadline (`_turn_deadline_ms`, 00-architecture.md §8
        "Turn timeout") -- `seat_view()` only actually uses it when `seat == state.turn` and
        `state.phase == Phase.AWAIT_ACTION`, so passing it unconditionally here is harmless."""
        window = self.state.claim_window
        claim_deadline_ts = (
            self._claim_deadline_ms.get((window.window_id, seat)) if window else None
        )
        view = seat_view(
            self.state,
            seat,
            seat_status=self._seat_status_tuple(),
            claim_deadline_ts=claim_deadline_ts,
            turn_deadline_ts=self._turn_deadline_ms.get(seat),
        )
        wire = seat_view_wire(view)
        wire["t"] = "state_sync"
        return wire

    def _seat_status_tuple(
        self,
    ) -> tuple[WireSeatStatus, WireSeatStatus, WireSeatStatus, WireSeatStatus]:
        """Every bound seat's real `status`; an unbound seat reads `empty` -- distinct from
        `connected`, so a client mid-lobby (`state_sync` reaches it as soon as it joins, well
        before all four seats are bound -- 02-protocol.md §3) can tell "nobody has joined this
        seat yet" from "someone's here and their socket is live", e.g. to render a "waiting for
        N more players" screen. `app/views.py`'s `_DEFAULT_SEAT_STATUS` stays `connected` --
        that default is for callers with no `Room` behind them at all (bots/arena.py,
        bots/selfplay.py, direct `seat_view()` tests), where every seat is a live simulated
        player, not a lobby seat that may genuinely be empty."""
        return cast(
            "tuple[WireSeatStatus, WireSeatStatus, WireSeatStatus, WireSeatStatus]",
            tuple(b.status if b is not None else "empty" for b in self.seat_bindings),
        )

    async def run(self) -> None:
        """The room's long-lived loop -- one `asyncio.Task` per room (server/AGENTS.md). Stops
        once the game actually ends (`Phase.GAME_OVER`) -- see `app/registry.py`'s
        `RoomRegistry` module docstring for why a room's task shouldn't loop forever after that.
        `Room` itself (and reconnect/`state_sync` against it) keeps working after this returns;
        only the background task -- which would otherwise sit awaiting an inbox that can never
        legally produce anything again (`_authorize` rejects everything once `legal_actions` is
        empty for every seat) -- stops.
        """
        while True:
            await self.process_one()
            if self.state.phase == Phase.GAME_OVER:
                return

    async def process_one(self) -> None:
        """Handle exactly one event: the next inbox `Command`/`BotResult`, or every claim-window
        or disconnect-grace timer that's expired, whichever the event loop resolves first
        (`_next()`). Split out from `run()` so a test can drive the room one event at a time
        without a real background task racing it. `turn` is only (re-)published when this cycle
        actually mutated `self.state` -- an illegal/dropped command (or a stale, already-
        resolved/superseded timeout) leaves `state` as the exact same object (`_authorize`/
        `_handle_claim_timeout`/`_handle_bot_result`'s own no-op paths never call `_apply`), and
        must not re-stamp a fresh `seq` onto every seat's stream for a turn prompt nothing about
        actually changed. `_poke_bots()` runs every tick regardless (00-architecture.md §3's
        sketch runs it unconditionally after `_arm_timers()`) -- cheap and idempotent
        (`_pending_bot` skips a seat whose current decision already has a job in flight), and
        needed even on a no-op tick: some *other* seat's action can hand an already-`autoplay`
        seat a fresh turn or claim offer without that seat's own state changing at all.

        A single `_next()` call can return *several* expired timer ids at once (every offered
        claim seat has its own heap entry, M3 sub-task 5 -- see `TimerHeap`'s docstring), so all
        of them get processed in this one tick.

        **A `_WakeUp` never counts as "state changed", even if `self.state is not pre_state`
        happens to be true (M3 sub-task 6).** `pre_state` is captured fresh at the top of every
        `process_one()` call, but this room's *very first* call starts as soon as the
        `asyncio.Task` is created (`RoomRegistry.get_or_create`) -- before a white-box test's
        `room.state = ...` rigging (`tests/test_ws_gameplay.py`/`tests/test_reconnect.py`'s own
        established pattern) gets a chance to run, if that first call is still sitting inside
        `_next()`'s `await` when the test does it. `_WakeUp` was, until this sub-task, never
        able to resolve that first pending call at all (join/ready/reconnect never touch
        `self.inbox`) -- so it never surfaced. It can now: an early disconnect can be the first
        thing that ever wakes a freshly-created room, and treating that stale `pre_state` vs.
        the just-rigged `self.state` as "changed" would republish a spurious `turn` nobody
        asked for. `_WakeUp` never itself mutates `self.state` by construction, so it is simply
        never a valid trigger for this check.

        **GAME_OVER persistence + shutdown-boundary signal (module docstring).** Both live at
        this tail, after everything else this tick did: `_boundary_this_tick` is reset here (not
        at the top of the *next* call) so it only ever reflects *this* tick's own work, and the
        GAME_OVER persist -- if a `session_factory` was wired in, and only once ever
        (`_persisted`) -- is awaited to completion *before* `self._shutdown_boundary` (if a
        `wait_for_shutdown_boundary` caller is actually waiting on one) is signalled. That
        ordering is load-bearing, not incidental: `app/registry.py`'s `RoomRegistry.begin_shutdown`
        disposes the DB engine only after every room's drain wait resolves, so a drain that woke
        up *before* this room's own final write finished could tear down/dispose the engine out
        from under an in-flight `session.commit()`.
        """
        pre_state = self.state
        self._boundary_this_tick = False
        event = await self._next()
        if isinstance(event, Command):
            self._handle(event)
        elif isinstance(event, BotResult):
            self._handle_bot_result(event)
        elif isinstance(event, _WakeUp):
            pass  # nothing to handle -- see _WakeUp's own docstring
        else:
            for timer_id in event:
                self._dispatch_expired_timer(timer_id)
        self._arm_claim_timer()
        if not isinstance(event, _WakeUp) and self.state is not pre_state:
            self._publish_turn_if_active()
        self._poke_bots()
        if self.state.phase == Phase.GAME_OVER and not self._persisted:
            self._persisted = True
            await self._persist_game_record()
            self._game_over_persisted = True
        if self._boundary_this_tick and self._shutdown_boundary is not None:
            self._shutdown_boundary.set()

    async def _inbox_getter(self) -> Command | BotResult | _WakeUp:
        return await self.inbox.get()

    def _ensure_getter(self) -> asyncio.Task[Command | BotResult | _WakeUp]:
        if self._getter is None:
            self._getter = asyncio.create_task(self._inbox_getter())
        return self._getter

    async def _next(self) -> Command | BotResult | _WakeUp | list[int]:
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
                return expired  # every id due this tick -- process_one() handles all of them
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

    def _handle_bot_result(self, result: BotResult) -> None:
        """A worker's answer, re-entering through `self.inbox` (D12). Dropped silently if
        `_pending_bot[result.seat]` no longer equals `result.tag` -- the window/turn moved on,
        or the seat reconnected (`reconnect()` clears the entry outright), since either means
        this job was computed against a `self.state` that isn't "now" anymore. When the tag
        *does* match, `self.event_id` is provably unchanged since submission (only `_apply`
        ever advances it, and nothing else could have without also changing the tag -- see
        `BotJobTag`'s docstring), so `self.state` is byte-identical to what the worker saw --
        which is exactly what makes `decode_action(result.aid, self.state, result.seat)` safe to
        call here: the worker never had `self.state` itself (D2), only the id it computed
        against a `SeatView`/mask built from this same state, so decoding against `self.state`
        now reconstructs precisely the `Action` the worker meant (see `bots/worker.py`'s module
        docstring for why the decode step lives here and not there). `_authorize` still runs
        anyway as a defense-in-depth belt-and-suspenders (server/AGENTS.md: "the server computes
        the legal-action set" -- true even for the server's own bot output), not because it's
        expected to ever actually reject something here.
        """
        if self._pending_bot.get(result.seat) != result.tag:
            return
        del self._pending_bot[result.seat]
        binding = self.seat_bindings[result.seat]
        if binding is None or binding.status not in ("autoplay", "bot"):
            return  # reconnected since submission but the tag pop above raced it -- drop
        try:
            decoded = decode_action(result.aid, self.state, result.seat)
        except ValueError:
            return  # defense-in-depth: provably shouldn't happen, see docstring above
        action = self._authorize(Command(seat=result.seat, action=decoded))
        if action is None:
            return
        self._apply(action)

    def _dispatch_expired_timer(self, timer_id: int) -> None:
        """One id popped off the shared `self.deadlines` heap (`TimerHeap`'s docstring): claim-
        window, turn, and disconnect-grace timers share one id space, so this just asks which
        side-table recognizes it."""
        if timer_id in self._timer_seat:
            self._handle_claim_timeout(timer_id)
        elif timer_id in self._turn_timer_seat:
            self._handle_turn_timeout(timer_id)
        else:
            self._handle_disconnect_timeout(timer_id)

    def _handle_turn_timeout(self, timer_id: int) -> None:
        """One per-seat `AWAIT_ACTION` deadline popped (00-architecture.md §8 "Turn timeout").
        No-op if stale: unknown id, superseded by a later arm for the same seat
        (`_active_turn_timer[seat]` no longer points at it -- same lazy-deletion staleness
        check `_handle_claim_timeout` uses), or `seat` genuinely isn't the one still deciding
        (a real command for it raced this timer and won -- D17's own guarantee).

        `state.claim_window` is always `None` while `state.phase == Phase.AWAIT_ACTION`
        (`GameState.__post_init__`'s own invariant: a claim window and `AWAIT_ACTION` are
        mutually exclusive phases) -- a seat can never simultaneously be `state.turn` *and*
        hold a live claim offer, so 00-architecture.md §8's "auto-pass any pending claims"
        never has anything to actually do here. The assert documents that this was checked
        against the real invariant, not assumed.

        Applies the deterministic default (`_timeout_discard_action`) through the normal
        `_apply()`/`reduce()` path, exactly like a real `Discard` command, then registers a
        strike (`_register_turn_timeout_strike`). Fires identically whether `seat` is a
        connected human, a disconnected/`autoplay` human, or a `bot` seat (M4.5) -- the timer
        races the wall clock, not any particular bot job, so a hung or crashed worker can't
        outlast `turn_seconds` regardless of whether `_await_bot_job`'s own 10s hard deadline
        ever fires first. Clears a stale `_pending_bot[seat]` (if any) up front, same tidy-up
        `reconnect()` already does when it takes a decision away from an in-flight bot job --
        this tick's own `_poke_bots()` tail then submits fresh work if `seat` still has a
        decision to make afterward."""
        seat = self._turn_timer_seat.get(timer_id)
        if seat is None:
            return
        if self._active_turn_timer.get(seat) != timer_id:
            return
        if self.state.phase != Phase.AWAIT_ACTION or self.state.turn != seat:
            return
        assert self.state.claim_window is None  # AWAIT_ACTION never carries one -- see docstring
        self._pending_bot.pop(seat, None)
        self._apply(self._timeout_discard_action(seat))
        self._register_turn_timeout_strike(seat)

    def _timeout_discard_action(self, seat: int) -> Discard:
        """00-architecture.md §8 "Turn timeout": deliberately dumb, not defensive. Tsumogiri --
        discard the tile that just landed in `seat`'s hand -- if this decision point started
        with a freshly drawn tile (`self._turn_draw_tile`, set in `_apply` from that tick's own
        `Drawn`/`KongReplacementDrawn` events; a kong's replacement draw is unaffected, since it
        always produces one of those events too). Otherwise (a claimed pung/chow landed `seat`
        here with nothing new in hand, or a fresh hand's opening deal with no single "the drawn
        tile" to name) the lowest-`tile_id` concealed tile.

        Sourced from `legal_actions(state, seat)`'s own `Discard` set, not `state.seats[seat].
        concealed` directly, so this can never name a tile that isn't actually a legal discard
        right now -- `AWAIT_ACTION` always offers at least one `Discard` (one per concealed
        tile, `actions._turn_actions`), so `discard_ids` is never empty here.
        """
        discard_ids = sorted(
            a.tile_id for a in legal_actions(self.state, seat) if isinstance(a, Discard)
        )
        assert discard_ids, "AWAIT_ACTION always offers at least one Discard"
        drawn = self._turn_draw_tile
        if drawn is not None and drawn in discard_ids:
            return Discard(tile_id=drawn)
        return Discard(tile_id=discard_ids[0])

    def _register_turn_timeout_strike(self, seat: int) -> None:
        """docs/00-architecture.md §8 "Turn timeout": "Three strikes -> seat flips to AUTOPLAY
        for the rest of the game." Counted on `SeatBinding.turn_timeout_strikes` -- see that
        field's own docstring for why simply never resetting it already means "for the rest of
        the game", with no explicit hand-boundary bookkeeping needed.

        A `bot`/already-`autoplay` seat still accumulates strikes here (useful signal if a
        room-created bot seat were ever malfunctioning) but skips the status flip/broadcast --
        there's no human occupant to take control away from, and the seat is already being
        played by the server either way."""
        binding = self.seat_bindings[seat]
        if binding is None:
            return
        binding.turn_timeout_strikes += 1
        if binding.turn_timeout_strikes < self.state.ruleset.turn_timeout_strikes:
            return
        if binding.status in ("autoplay", "bot"):
            return
        binding.status = "autoplay"
        self._broadcast_wire({"t": "seat_state", "seat": seat, "status": "autoplay"})

    def _handle_disconnect_timeout(self, timer_id: int) -> None:
        """A disconnect-grace deadline popped (00-architecture.md §8 "Player disconnects":
        grace period before AUTOPLAY). No-op if stale -- unknown id, or
        `_active_disconnect_timer[seat]` no longer points at it (the seat reconnected since this
        was armed, `reconnect()` pops that mapping -- same lazy-deletion staleness check
        `_handle_claim_timeout` already uses for claim timers) -- or the seat somehow isn't
        `disconnected` anymore for any other reason. Otherwise flips the seat to `autoplay` and
        broadcasts `seat_state`; `_poke_bots()` (this tick's own tail, `process_one()`) picks up
        the transition and submits a job if this seat currently has a decision to make."""
        seat = self._disconnect_timer_seat.get(timer_id)
        if seat is None:
            return
        if self._active_disconnect_timer.get(seat) != timer_id:
            return
        binding = self.seat_bindings[seat]
        if binding is None or binding.status != "disconnected":
            return
        binding.status = "autoplay"
        self._broadcast_wire({"t": "seat_state", "seat": seat, "status": "autoplay"})

    def _wake(self) -> None:
        """Force a blocked `_next()` to re-loop and recompute its wait set against the current
        `self.deadlines` -- see `_WakeUp`'s docstring for why this is needed at all."""
        self.inbox.put_nowait(_WakeUp())

    def _arm_disconnect_timer(self, seat: int) -> None:
        """Give `seat` a fresh `TimerHeap` entry, `ruleset.disconnect_grace_seconds` from right
        now (default 20s, `mahjong_core/config.py`) -- the disconnect-side analogue of
        `_arm_seat_claim_timer`, sharing the same heap and id sequence (`TimerHeap`'s
        docstring). Always called from `mark_disconnected`, itself called from `Session` outside
        this room's own loop -- `_wake()` at the end guarantees `_next()` actually notices."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.state.ruleset.disconnect_grace_seconds
        timer_id = next(self._timer_seq)
        self.deadlines.add(deadline, timer_id)
        self._disconnect_timer_seat[timer_id] = seat
        self._active_disconnect_timer[seat] = timer_id
        self._wake()

    def _arm_turn_timer(self, seat: int) -> int:
        """Give `seat` a fresh `TimerHeap` entry, `ruleset.turn_seconds` from right now
        (00-architecture.md §8 "Turn timeout") -- the turn-side analogue of
        `_arm_seat_claim_timer`/`_arm_disconnect_timer`, sharing the same heap and id sequence
        (`TimerHeap`'s docstring). Only ever called from `_publish_turn_if_active`, itself
        always running synchronously inside an already-executing `process_one()` tick or
        `mark_ready()` -- both on this room's own event loop -- so, like the initial claim-
        window arm (`_arm_claim_timer`), this needs no `_wake()` call of its own: the next
        `_next()` call picks up the fresh heap entry naturally when it recomputes its wait set.
        Returns the wire `deadline_ts` (epoch ms) for `_publish_turn_if_active` to publish."""
        loop = asyncio.get_running_loop()
        duration = self.state.ruleset.turn_seconds
        deadline = loop.time() + duration
        timer_id = next(self._timer_seq)
        self.deadlines.add(deadline, timer_id)
        self._turn_timer_seat[timer_id] = seat
        self._active_turn_timer[seat] = timer_id
        deadline_ts = _now_ms() + round(duration * 1000)
        self._turn_deadline_ms[seat] = deadline_ts
        return deadline_ts

    def _poke_bots(self) -> None:
        """00-architecture.md §3's `_poke_bots()`: submit a decision to the bot worker pool for
        every seat bound `autoplay` *or* `bot` (M4.5 practice mode -- both kinds of `SeatBinding`
        get driven through the identical path here, not a parallel one; see `SeatBinding`'s
        docstring) that currently has one to make -- its own `AWAIT_ACTION` turn, or a live claim
        offer it hasn't answered -- tagged with what it's computed against (`BotJobTag`) so a
        stale result is dropped when it lands (D12; see `_handle_bot_result`). Idempotent: a seat
        whose current decision already has a job in flight (`_pending_bot[seat]` already equals
        the freshly-computed tag) isn't resubmitted. Never runs bot logic inline (D12) --
        `_submit_bot_job` only ever schedules work on `self._bot_pool` and returns immediately;
        the room loop is never blocked on a bot's answer.
        """
        window = self.state.claim_window
        for seat in range(4):
            binding = self.seat_bindings[seat]
            if binding is None or binding.status not in ("autoplay", "bot"):
                continue
            tag: BotJobTag | None = None
            if (
                window is not None
                and seat not in window.responses
                and any(o.seat == seat for o in window.offers)
            ):
                tag = BotJobTag(kind="claim", key=window.window_id, state_version=self.event_id)
            elif self.state.phase == Phase.AWAIT_ACTION and self.state.turn == seat:
                tag = BotJobTag(kind="turn", key=seat, state_version=self.event_id)
            if tag is None or self._pending_bot.get(seat) == tag:
                continue
            self._pending_bot[seat] = tag
            claim_deadline_ts = (
                self._claim_deadline_ms.get((tag.key, seat)) if tag.kind == "claim" else None
            )
            turn_deadline_ts = self._turn_deadline_ms.get(seat) if tag.kind == "turn" else None
            view = seat_view(
                self.state,
                seat,
                seat_status=self._seat_status_tuple(),
                claim_deadline_ts=claim_deadline_ts,
                turn_deadline_ts=turn_deadline_ts,
            )
            mask = legal_mask(self.state, seat)
            self._submit_bot_job(seat, tag, view, mask)

    def _submit_bot_job(self, seat: int, tag: BotJobTag, view: SeatView, mask: list[bool]) -> None:
        """Schedule `bots.worker.compute_action` on `self._bot_pool` (a `ProcessPoolExecutor` by
        default, D12: "the GIL makes a thread pool useless for CPU-bound pure-Python search") and
        return immediately -- the actual wait lives in `_await_bot_job`, a separate task, so this
        method never blocks the room loop. `seed` is derived from the tag rather than an unseeded
        `random.Random()` so a given decision point's bot output is reproducible (server/
        AGENTS.md). `self._bot_tier` (`Room.__init__`'s `bot_tier` param, `T0`/`T1`/`T2`) picks
        which real tier answers -- configurable per room, not hardcoded (docs/05-roadmap.md
        M4.5); `deadline` is advisory only (`bots/base.py`'s `Bot.act` contract), derived from
        the same hard `_BOT_JOB_TIMEOUT_SECONDS` this room actually enforces in `_await_bot_job`
        below, on the shared `time.monotonic()` clock every process on this machine agrees on.
        """
        loop = asyncio.get_running_loop()
        seed = hash((self.room_id, tag.kind, tag.key, tag.state_version, seat)) & 0xFFFFFFFF
        deadline = time.monotonic() + _BOT_JOB_TIMEOUT_SECONDS
        future = loop.run_in_executor(
            self._bot_pool, compute_action, view, mask, seed, self._bot_tier, deadline
        )
        task = asyncio.ensure_future(self._await_bot_job(seat, tag, future))
        self._bot_tasks.add(task)
        task.add_done_callback(self._bot_tasks.discard)

    async def _await_bot_job(self, seat: int, tag: BotJobTag, future: asyncio.Future[int]) -> None:
        """Await one submitted job under a hard deadline (00-architecture.md §8 "Bot raises /
        hangs": "A bot must never be able to wedge a table"), then re-enter it through
        `self.inbox` as a `BotResult` exactly like the architecture sketch describes (D12) --
        never applied directly from here, so it still goes through the same staleness check
        (`_handle_bot_result`) and single-writer discipline every other inbox item does.

        On timeout or a worker crash: this method itself still applies no synthesized default
        action -- it just clears the pending tag (if it's still this job's) so the next
        `_poke_bots()` tick retries from scratch. What actually stops a stalled *turn* decision
        from wedging the table is the independent, seat-level `ruleset.turn_seconds` deadline
        (`_arm_turn_timer`/`_handle_turn_timeout`, 00-architecture.md §8 "Turn timeout"), which
        races the wall clock regardless of whether any particular bot job is in flight -- not
        this method's own 10s job deadline. An *unanswered claim* still resolves correctly
        regardless, through its own real `TimerHeap` entry, unaffected by either. In practice
        this path only fires for an actual crash, not a legitimate miss: every tier's `act()`
        here is O(a heuristic scan), not a search with a real budget to exceed.
        """
        with contextlib.suppress(Exception):
            aid = await asyncio.wait_for(future, timeout=_BOT_JOB_TIMEOUT_SECONDS)
            self.inbox.put_nowait(BotResult(seat=seat, tag=tag, aid=aid))
            return
        if self._pending_bot.get(seat) == tag:
            del self._pending_bot[seat]

    def _handle_claim_timeout(self, timer_id: int) -> None:
        """One per-seat claim-window timer id popped off `self.deadlines` (`_timer_seat` maps
        it back to `(window_id, seat)` -- M3 sub-task 5 moved from one shared heap entry per
        window to one per offered seat; see `TimerHeap`'s docstring for why). No-op if stale:

        - unknown id (already handled and dropped from `_timer_seat` -- doesn't happen today
          since entries are never actively evicted, kept for defensiveness),
        - the window it was armed for already resolved (early exit or a prior timeout) and
          `self.state` has moved on (00-architecture.md §4: "claims tagged with a stale window
          are dropped silently"),
        - **or this id has been superseded** -- `_active_seat_timer[(window_id, seat)]` no
          longer points at it, meaning a reconnect re-armed this seat's deadline to a later one
          (`_rearm_seat_claim_timer`) and this is the original, now-stale entry left behind by
          lazy deletion. Without this check a reconnecting seat's *old* deadline would still
          fire and auto-Pass them right out from under the fresh window they were just given.

        Otherwise this seat is treated as `Pass` (claims.py's own documented convention) and fed
        through the same `reduce()` -> `_apply_claim_response` -> `resolve_claims` path a real
        response uses -- resolved inline the moment the window is ready, exactly like early
        exit and a real response."""
        target = self._timer_seat.get(timer_id)
        if target is None:
            return
        window_id, seat = target
        window = self.state.claim_window
        if window is None or window.window_id != window_id:
            return
        if self._active_seat_timer.get((window_id, seat)) != timer_id:
            return
        if seat in window.responses:
            return
        self._apply(Pass(window_id=window_id, seat=seat))

    def _apply(self, action: Action) -> None:
        """Run one already-authorized `Action` through `reduce()`, publish, and chain into
        `start_next_hand()` on `HAND_OVER` -- the common tail shared by a real `Command`
        (`_handle`), a synthesized claim-timeout `Pass` (`_handle_claim_timeout`), a
        synthesized turn-timeout `Discard` (`_handle_turn_timeout`), and a pre-armed auto-pass
        (`_send_claim_offers`)."""
        self.actions.append(action)  # full-game log (module docstring) -- reduce()-bound only
        self.state, events = reduce(self.state, action)
        self.event_id += 1
        self._publish(events)
        all_events = events
        if self.state.phase == Phase.HAND_OVER:
            # server-computed transition, no seat decision (actions.py, engine.py module
            # docstrings) -- advance immediately, same tick, before anything else touches
            # this command's result.
            self.state, more_events = start_next_hand(self.state)
            self.event_id += 1
            self._publish(more_events)
            all_events = [*events, *more_events]
            # a hand boundary -- the next hand dealt, or the game ended -- either way
            # `process_one()`'s tail is what actually wakes a pending `wait_for_shutdown_boundary`
            # (only after any GAME_OVER persist below has actually finished, never before).
            self._boundary_this_tick = True
            if self.state.phase == Phase.AWAIT_ACTION:
                # start_next_hand() deals the next hand with no Event of its own (state.py/
                # engine.py: `new_game`/`_deal_hand` build state directly, not through
                # reduce()) -- hand_start/deal have no engine event to redact either way
                # (02-protocol.md §3's sketch, no EventKind backs them), so this Room
                # synthesizes both here, the same way it does for the ready-triggered hand 1
                # start (`Room.mark_ready`).
                self._publish_hand_start_and_deal()
        # refreshed every call, in lockstep with self.state -- see `_turn_draw_tile`'s own
        # __init__ comment and `_turn_draw_tile_for_current_turn`'s docstring.
        self._turn_draw_tile = _turn_draw_tile_for_current_turn(all_events, self.state)

    def _arm_claim_timer(self) -> None:
        """Arm a deadline the moment `self.state.claim_window` shows a new `window_id` --
        called after every event `process_one()` handles, mirroring `_arm_timers()` in
        00-architecture.md §3's Room sketch. Idempotent per window: `_armed_window_id` stops a
        window that's still accumulating responses across several `process_one()` calls from
        getting a fresh (and later) deadline each time. Duration is `ruleset.claim_seconds`
        (`mahjong_core/config.py`) -- already real config, not a placeholder.

        Arms one heap entry per offered seat (`_arm_seat_claim_timer`), not one shared entry
        for the whole window -- see `TimerHeap`'s docstring for why M3 sub-task 5 needed that
        split (a reconnecting seat's deadline has to be movable without touching anyone else's).

        Also the one place `claim_offer` gets sent (`_send_claim_offers`): the wire message has
        no backing `Event` either (same "no EventKind" gap as hand_start/deal above), and needs
        the real deadlines this method just armed anyway, so folding both into one idempotent,
        once-per-window call avoids a second `_armed_window_id`-shaped tracker.
        """
        window = self.state.claim_window
        if window is None or window.window_id == self._armed_window_id:
            return
        self._armed_window_id = window.window_id
        for offer in window.offers:
            self._arm_seat_claim_timer(window.window_id, offer.seat)
        self._send_claim_offers(window)

    def _arm_seat_claim_timer(self, window_id: int, seat: int) -> None:
        """Give `seat` its own fresh `TimerHeap` entry for `window_id`, a full
        `ruleset.claim_seconds` from right now -- the one primitive both the initial window-open
        arm (`_arm_claim_timer`, every offered seat at once) and a mid-window reconnect re-arm
        (`_rearm_seat_claim_timer`, one seat only) go through. Recorded in `_timer_seat` (id ->
        `(window_id, seat)`) and `_active_seat_timer` (`(window_id, seat)` -> the id that's
        actually current) so `_handle_claim_timeout` can tell a superseded entry from a live
        one -- see that method's docstring.

        **Not itself a `_wake()` call site** (see `_WakeUp`'s docstring): the initial window-open
        arm (`_arm_claim_timer`) always runs synchronously inside an already-executing
        `process_one()` tick, so the *next* `_next()` call picks up the fresh heap entry
        naturally when it recomputes its wait set -- no external nudge needed. A mid-window
        re-arm (`_rearm_seat_claim_timer`) runs from `resume()`, outside this room's loop, where
        that guarantee doesn't hold -- it calls `_wake()` itself, after this returns.
        """
        loop = asyncio.get_running_loop()
        duration = self.state.ruleset.claim_seconds
        deadline = loop.time() + duration
        timer_id = next(self._timer_seq)
        self.deadlines.add(deadline, timer_id)
        self._timer_seat[timer_id] = (window_id, seat)
        self._active_seat_timer[(window_id, seat)] = timer_id
        # `TimerHeap`/`deadline` are monotonic loop time (D17); the wire needs server epoch ms
        # (02-protocol.md §4/§1's `ts`) -- `duration` converts directly since it's already the
        # real elapsed span from "now" in both clocks.
        self._claim_deadline_ms[(window_id, seat)] = _now_ms() + round(duration * 1000)

    def _rearm_seat_claim_timer(self, seat: int) -> bool:
        """docs/00-architecture.md §8, "mid-claim-window" reconnect row: if `seat` holds a
        live, unresolved claim offer, give it a fresh full-length window measured from right
        now (`_arm_seat_claim_timer`, same duration as everyone else) -- every other offered
        seat's deadline is untouched, since each has its own heap entry. Returns whether a
        re-arm actually happened, so `resume()` knows whether to also push a fresh
        `claim_offer` reflecting it. No-op (`False`) if there's no live window, this seat has
        no offer in it, or it already responded.

        **"sized for a bot answering in milliseconds" (00-architecture.md §8):** bot handover
        exists now (M3 sub-task 6, `_poke_bots`), but every offered seat -- human, or `AUTOPLAY`
        and bot-answered -- is still armed with the same `ruleset.claim_seconds` human-length
        window (`_arm_claim_timer`); nothing gave bots a separate, shorter claim-window deadline
        (`compute_action`'s policy is instant, so it answers well inside that window regardless,
        the same way a fast human click would). So the doc's "sized for a bot" scenario still
        doesn't literally exist -- read as before: without this re-arm, a seat that disconnects
        partway through its window and reconnects late would get only whatever sliver of the
        *original* deadline is left, not a fair chance to respond. Re-arming to a fresh full
        window from the reconnect moment fixes that, and this re-arm always wins over whatever
        the seat was offered before, bot-answered or not.
        """
        window = self.state.claim_window
        if window is None or seat in window.responses:
            return False
        if not any(o.seat == seat for o in window.offers):
            return False
        self._arm_seat_claim_timer(window.window_id, seat)
        self._wake()  # out-of-loop call (resume(), via Session) -- see _WakeUp's docstring
        return True

    def _send_claim_offers(self, window: ClaimWindow) -> None:
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
            self._send_seat_claim_offer(offer.seat)

    def _send_seat_claim_offer(self, seat: int) -> None:
        """The actual `claim_offer` unicast for one seat, reading its deadline back out of
        `_claim_deadline_ms` -- shared by `_send_claim_offers` (every offered seat, window-open
        time) and `resume()` (one seat, after a mid-window reconnect re-arm). Requires a live
        offer for `seat` and a deadline already armed for it (both callers guarantee this)."""
        window = self.state.claim_window
        assert window is not None
        offer = next(o for o in window.offers if o.seat == seat)
        self.publish_to_seat(
            seat,
            {
                "t": "claim_offer",
                "window_id": window.window_id,
                "options": self._claim_options_wire(offer),
                "deadline_ts": self._claim_deadline_ms[(window.window_id, seat)],
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
        it). `seats` is each seat's real `status` (`app/views.py`'s `SeatView` shape, M3
        sub-task 6 -- see `SeatBinding`/`mark_disconnected`)."""
        state = self.state
        self._broadcast_wire(
            {
                "t": "hand_start",
                "hand_no": state.hand_no,
                "prevailing": state.prevailing.name,
                "dealer": state.dealer,
                "seats": list(self._seat_status_tuple()),
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
        this doesn't need `_arm_claim_timer`'s once-per-window idempotency guard -- and, by the
        same reasoning, is the one and only call site for `_arm_turn_timer` (00-architecture.md
        §8 "Turn timeout"): every call here is a genuinely new decision needing its own fresh
        deadline, so there's nothing for this method's own idempotency to guard against either.

        `deadline_ts` is now a real, enforced `TimerHeap` deadline (`_arm_turn_timer`), not
        merely advisory -- see that method and `_handle_turn_timeout`. `legal` is unicast to
        the acting seat only, matching `turn.legal`'s own "unicast to the acting seat" contract.
        """
        if self.state.phase != Phase.AWAIT_ACTION:
            return
        seat = self.state.turn
        deadline_ts = self._arm_turn_timer(seat)
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

    async def _persist_game_record(self) -> None:
        """`Phase.GAME_OVER` persistence (docs/06-ml.md §2, docs/00-architecture.md §6) -- a
        no-op if this `Room` was never given a `session_factory` (every bare `Room()` test, and
        any deployment with no `DATABASE_URL`, app/main.py's `lifespan`). `players` is each
        seat's `SeatBinding.session_id` -- the closest thing to a stable per-seat identity that
        exists before `hello`'s guest `name` field ships (M5, 00-architecture.md §2.1); `None`
        for a seat nobody ever joined *by a human* -- a `bot` seat (M4.5 practice mode) was
        never joined by a human either, so it gets `None` here too, not its synthetic
        `session_id`, which would otherwise misleadingly read as a real player. Only ever called
        once, from `process_one()`'s own tail (`self._persisted` guards a second call)."""
        if self._session_factory is None:
            return
        players = [
            b.session_id if b is not None and b.status != "bot" else None
            for b in self.seat_bindings
        ]
        async with self._session_factory() as session:
            await save_game_record(session, self.state, self.actions, players=players)

    async def wait_for_shutdown_boundary(self, timeout: float) -> bool:
        """docs/00-architecture.md §8.1 steps 3-5: block until this room reaches a hand boundary
        -- a fresh hand dealt, or the game ends (`_boundary_this_tick`, set inside `_apply`) --
        or `timeout` seconds elapse, whichever is first. Returns whether a boundary was actually
        reached; `False` means the grace window elapsed first and the caller
        (`app/registry.py`'s `RoomRegistry.begin_shutdown`) abandons this room, same as a crash,
        but warned.

        A room whose GAME_OVER persist has actually *finished* (`_game_over_persisted`) returns
        `True` immediately with no event/wait at all -- nothing left to abandon.

        **The in-between state is the one two real bugs lived in.** `begin_shutdown` only ever
        calls this on a room whose background task is still running (`RoomRegistry.is_running`),
        and a still-running room already at `Phase.GAME_OVER` is, by construction, one whose
        final `process_one()` tick is suspended inside `await self._persist_game_record()` --
        `state.phase` and `self._persisted` both flip synchronously, with no `await` between
        them and the persist call, so no other coroutine on this event loop can ever observe
        `state.phase == Phase.GAME_OVER` with `_game_over_persisted` still `False` except by
        genuinely racing that in-flight write.

        Bug 1 (fixed): this method used to fast-path on `self.state.phase == Phase.GAME_OVER`
        directly, before `_game_over_persisted` existed. That returned `True` the instant the
        phase flipped, well before the write it was supposed to be waiting for even started,
        letting `app/main.py`'s `lifespan` dispose the DB engine out from under the still-in-
        flight `save_game_record`.

        Bug 2 (also fixed, and the one that made bug 1's fix alone insufficient): once landed in
        that in-between state, this fell through to the normal `asyncio.wait_for(..., timeout)`
        path -- correct for "let the current hand finish," wrong here, because
        `server/tests/conftest.py` pins `timeout=0` for the entire test session and
        `asyncio.wait_for` with a non-positive timeout (`asyncio/tasks.py`) cancels immediately
        without giving the awaited event a single scheduling turn, regardless of how close it is
        to firing. So a drain landing mid-persist still reached `engine.dispose()` right after --
        now via the "grace window elapsed, abandoning" branch instead of the old fast path, same
        data loss, plus a spurious warning for a room that was, in fact, finishing normally. The
        fix: waiting out an *already-in-flight* GAME_OVER persist is a durability guarantee, not
        the boundable "let the hand finish" allowance `timeout` exists for -- there is no further
        hand for a timeout to bound here, so that wait ignores the caller's `timeout` entirely.

        A *fresh* `asyncio.Event` is installed for the duration of this call either way (not a
        long-lived one reused across calls): reusing one risks a stale `.set()` from a boundary
        that happened *before* this particular drain started being mistaken for "the boundary
        this drain is waiting for."
        """
        if self._game_over_persisted:
            return True
        already_over = self.state.phase == Phase.GAME_OVER
        self._shutdown_boundary = asyncio.Event()
        try:
            await asyncio.wait_for(
                self._shutdown_boundary.wait(), timeout=None if already_over else timeout
            )
            return True
        except TimeoutError:
            return False
        finally:
            self._shutdown_boundary = None
