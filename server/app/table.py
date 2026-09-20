"""`Table` -- the table actor's core dispatch loop (docs/00-architecture.md §3, §5;
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
windows and disconnect-grace use. On expiry (`_handle_turn_timeout`) the table applies the
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
lands -- the window closed, the turn moved on, or the seat reconnected. `_bot_tier` (`Table.
__init__`) picks the real tier (`T0`/`T1`/`T2`, default `T2`/`FaanBot`) every such job runs. See
`mark_disconnected`/`_poke_bots`/`_handle_bot_result`.

**Bot-filled seats from table creation (M4.5 practice mode).** `practice=True` (`Table.__init__`)
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
`state_sync_wire` are this Table's half of the wire protocol -- `app/ws.py`'s `Session` is the
other half, turning raw envelopes into calls here and this Table's published wire dicts into
real frames on a socket. `SeatBinding` holds the live per-seat state that has no home in the
pure `GameState` (a connection's push callback, `ready`/pre-arm flags, per-seat idempotency).
Several wire events (`hand_start`/`deal`/`turn`/`claim_offer`/`score`) have no backing
`mahjong_core.engine.Event` to redact -- see `_publish_hand_start_and_deal`/
`_publish_turn_if_active`/`_send_claim_offers`'s docstrings for why, and
docs/00-architecture.md §3's "Session/WS integration" note for the short version.

One table = one `asyncio.Task` = one writer (server/AGENTS.md): every mutation of `self.state`
happens inside `_apply`, called only from this module's own loop. `join`/`mark_ready`/
`set_auto` mutate `self.seat_bindings` (not `self.state`) directly from whatever task calls
them -- safe because they're synchronous with no `await`, so nothing else can interleave on
this table's event loop between one call's start and its return.

**DB persistence + graceful shutdown (docs/00-architecture.md §6/§8.1, docs/06-ml.md §2's
`GameRecord`).** `self.actions` accumulates every `Action` this table ever applies via `_apply`
(never `start_next_hand()` transitions -- those aren't `Action`s and replay reconstructs them
automatically off `Phase.HAND_OVER`, same convention `bots/selfplay.py`'s `play_game` already
documents) across the *entire game*, all hands, surviving `start_next_hand()` transitions simply
because nothing ever resets it -- `Table` is one long-lived object for one game, not recreated
per hand. On reaching `Phase.GAME_OVER`, `process_one()` calls `save_game_record` (if a
`session_factory` was wired in at construction -- `None` is a real, supported "no persistence"
mode, matching every bare `Table()` test that constructs one directly) with `self.actions` and
`players` taken from each seat's real, chosen `SeatBinding.name` (M5, 00-architecture.md §2.1,
`join.name` -- see `_persist_game_record`'s own docstring); a `None` entry means that seat was
never joined by a human.
`_boundary_this_tick`/`_shutdown_boundary` back `wait_for_shutdown_boundary`,
`app/registry.py`'s `TableRegistry.begin_shutdown`'s per-table half of the graceful-drain sequence
(§8.1) -- the boundary-reached event is only ever set *after* an in-flight `GAME_OVER` persist
finishes, never before, so a drain can't tear down a table (or the process dispose its DB engine)
while that table's own final write is still in flight. **This was violated until a real bug fix**:
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
import logging
import os
import random
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
    "SeatBinding",
    "SeatNotBoundError",
    "SeatStatus",
    "SeatTakenError",
    "Table",
    "TableFullError",
    "TimerHeap",
    "WireSeatStatus",
]

SeatStatus = Literal["connected", "disconnected", "autoplay", "bot"]

# Wire-level vocabulary for `_seat_status_tuple()`/`seat_view()`'s `seat_status`. `empty` has no
# `SeatBinding` counterpart: a binding only exists once a seat *is* bound, so "nobody has ever
# joined this seat" isn't a `SeatBinding.status` value, only something `_seat_status_tuple()`
# reports for a `None` slot in `Table.seat_bindings`. `bot` *is* a real `SeatBinding.status` now
# (M4.5 practice mode, `_bind_bot_seat`) -- see `SeatBinding`'s docstring.
WireSeatStatus = Literal["connected", "disconnected", "autoplay", "bot", "empty"]

logger = logging.getLogger(__name__)

_BOT_JOB_TIMEOUT_SECONDS = 10.0  # hard deadline (00-architecture.md §8 "Bot raises / hangs")

# humanising think delay (docs/04-bots.md §1): a real tier answers in single-digit
# milliseconds, which reads as the table jumping ahead of anyone actually watching it. Applied
# here, after the worker replies, rather than inside the worker (docs/04-bots.md §1) so it never
# touches `_BOT_JOB_TIMEOUT_SECONDS`/`turn_seconds`/`claim_seconds` deadline math. Env-overridable
# (`server/tests/conftest.py` zeroes both for the whole suite) -- same test-time-control
# convention `app/main.py`'s `SHUTDOWN_GRACE_SECONDS` already established, so tests exercising
# many bot turns over a real WS connection don't pay real wall-clock seconds for it.
_BOT_THINK_MIN_SECONDS = float(os.environ.get("BOT_THINK_MIN_SECONDS", "0.4"))
_BOT_THINK_MAX_SECONDS = float(os.environ.get("BOT_THINK_MAX_SECONDS", "1.4"))

_MAX_NAME_LENGTH = 24  # guest display name cap (M5, docs/02-protocol.md §2 `join.name`)

# M4.5 practice-mode bot seats (`_bind_bot_seat`) get a display name from their real tier
# (`bots/worker.py`'s `BOT_TIERS`), not a generic "Bot" placeholder -- matches the class a
# curious player could actually go look up.
_BOT_DISPLAY_NAMES = {"T0": "RandomBot", "T1": "EfficiencyBot", "T2": "FaanBot"}


def _normalize_name(raw: str | None, seat: int) -> str:
    """Guest display name normalization (docs/02-protocol.md §2 `join.name`, M5): trim
    whitespace, cap at `_MAX_NAME_LENGTH` chars, and fall back to a per-seat default
    (`"Guest N"`, 1-indexed) when empty or omitted -- this is a low-stakes guest field, so bad
    input is normalized, never rejected with a hard error (no `error{code:...}` path for it)."""
    trimmed = (raw or "").strip()
    if not trimmed:
        return f"Guest {seat + 1}"
    return trimmed[:_MAX_NAME_LENGTH]


_default_bot_pool: ProcessPoolExecutor | None = None


def _shared_bot_pool() -> ProcessPoolExecutor:
    """One `ProcessPoolExecutor` per server process, created lazily on first use (constructing
    it doesn't spawn a worker -- workers start on first `submit()`), not one per `Table` (D12:
    "a process pool", not a swarm of them). `Table.__init__`'s `bot_pool` param exists so tests
    (and a future `TableRegistry`) can inject a different `Executor` instead."""
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
    this decision -- the signal `Table._timeout_discard_action` needs to choose tsumogiri over
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
    """Raised by `Table.join(seat=...)` when the requested seat is already bound
    (docs/02-protocol.md §2 "Seat assignment" -> wire `error{code:'seat_taken'}`)."""

    def __init__(self, seat: int) -> None:
        super().__init__(f"seat {seat} is already taken")
        self.seat = seat


class TableFullError(Exception):
    """Raised by `Table.join(seat=None)` when every seat is bound (wire
    `error{code:'table_full'}`)."""


class SeatNotBoundError(Exception):
    """Raised by `Table.reconnect(seat, ...)` when nothing has ever `join`ed this seat -- there
    is no `SeatBinding` to reclaim (wire `error{code:'no_such_seat'}`, `app/ws.py`). Distinct
    from `SeatTakenError`: that one fires on `join` finding a seat *already* bound; this one
    fires on `hello{last_seq, seat}` finding a seat *never* bound."""

    def __init__(self, seat: int) -> None:
        super().__init__(f"seat {seat} has never been joined")
        self.seat = seat


@dataclass
class SeatBinding:
    """One seat's session binding (docs/00-architecture.md §3's sketch, built out here --
    sub-task 4's job per that sketch's own note). Lives on `Table`, not `Session`: idempotency
    is scoped "per seat binding, not per socket" (02-protocol.md §1), so it has to survive a
    future reconnect (sub-task 5) swapping out the `Session`/socket underneath it -- this is
    the object that will still exist across that swap.

    `send` is the live connection's push callback (`seq, wire -> None`); `ready`/`no_calls`/
    `auto_pass_chow` are the lobby/pre-arm state 02-protocol.md §2 describes. `status`
    (`connected`/`disconnected`/`autoplay`/`bot` -- `empty` can never apply to a `SeatBinding`:
    a binding only exists once a seat *is* bound, so "nobody has ever joined this seat" is
    reported by `_seat_status_tuple()` for a `None` slot in `Table.seat_bindings`, never as a
    value of this field) transitions via `mark_disconnected`/`reconnect`/the disconnect-grace
    timer (M3 sub-task 6) for a seat that started as a human `join` -- see
    `Table.mark_disconnected`.

    **`bot` (M4.5 practice mode, `_bind_bot_seat`) is the other way a `SeatBinding` comes to
    exist**: a seat bound to a bot from table construction, never a human `join` at all. It
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
    for this seat, incremented by `Table._register_turn_timeout_strike`. **Never reset anywhere
    -- that omission is the "for the rest of the game" reset policy, not an oversight.** This
    binding is one long-lived object for the table's entire game (never recreated per hand;
    `reconnect` only swaps the live socket underneath it), so simply never zeroing this field
    already gives "accumulates across hand boundaries and reconnects alike" for free, with no
    explicit "which hand is this" bookkeeping needed.

    `name` (M5, docs/00-architecture.md §2.1) is this seat's resolved guest display name --
    always a real, non-empty string (`_normalize_name`), set once at `join` (`name` on
    `JoinPayload`) or `_bind_bot_seat` and never touched again: a `hello` reconnect doesn't
    resend it (02-protocol.md §2/§5 -- the server already has it), so there is nothing for
    `reconnect()` to update on this field.
    """

    session_id: str
    send: Callable[[int, dict[str, Any]], None]
    name: str
    status: SeatStatus = "connected"
    ready: bool = False
    no_calls: bool = False
    auto_pass_chow: bool = False
    idempotency: IdempotencyCache = field(default_factory=IdempotencyCache)
    turn_timeout_strikes: int = 0


@dataclass(frozen=True)
class Command:
    """One already-validated `(seat, Action)` pair flowing through `Table.inbox`. `seat` is the
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
    `seq` (00-architecture.md §3 D1: per-seat, dense, gapless -- never per-table, never derived
    from `event_id`)."""

    seq: int
    event: dict[str, object]


@dataclass(frozen=True)
class BotJobTag:
    """What a submitted bot job was computed against (00-architecture.md §3 D12's
    `(window_id, state_version)` tag). `state_version` is `Table.event_id` at submission time --
    `event_id` already exists as the table's own monotonic "has anything actually changed"
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
    """A `ProcessPoolExecutor` worker's answer, re-entering through `Table.inbox` exactly like a
    real `Command` (D12) -- `tag` is compared against `Table._pending_bot[seat]` and dropped
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
class SeatDisconnected:
    """A seat's live socket just closed (`mark_disconnected`, called directly from `Session`,
    outside this table's own loop -- see `_WakeUp`'s docstring for why that matters). Routed
    through `Table.inbox` rather than forfeiting the seat's claim inline from `mark_disconnected`
    itself: forfeiting means calling `_apply()`, which mutates `self.state`, and server/AGENTS.md
    reserves every `GameState` mutation for this table's own task processing its inbox in order --
    `mark_disconnected` already keeps to that boundary for its own bookkeeping (`SeatBinding`/
    `TimerHeap` are Table-level, not `GameState`), and a disconnect is no exception just because
    it wants to feed a synthesized action in. Handled by `_handle_seat_disconnected` (below)."""

    seat: int


@dataclass(frozen=True)
class _WakeUp:
    """No-op inbox marker. `_next()`'s `asyncio.wait()` call fixes its waitable set (the inbox
    `getter` plus a sleeper for whatever `self.deadlines.peek()` was *at that moment*) the
    instant it's entered -- nothing changes that set until one of those waitables completes.
    `_arm_disconnect_timer`/`_arm_seat_claim_timer` can run from *outside* this table's own
    `process_one()` tick (`mark_disconnected`/`resume()`, both called directly from `Session`
    on an incoming WS frame, not from this table's loop) and add a heap entry that's earlier
    than -- or the *only* entry, where none existed -- whatever `_next()` is already blocked
    on. Without this, that new deadline would sit in the heap unnoticed until some unrelated
    inbox item happened to arrive and force a fresh `_next()` call to recompute the sleeper.
    Pushing this onto `self.inbox` forces exactly that recompute, immediately, every time a
    deadline is armed from outside the loop -- see `Table._wake`."""


class TimerHeap:
    """Deadline heap keyed by `(deadline_ts, id)` (00-architecture.md §3 D17). Holds claim-window
    deadlines (M3 sub-task 3/5), disconnect-grace deadlines (M3 sub-task 6), and per-seat
    `AWAIT_ACTION` turn deadlines (00-architecture.md §8 "Turn timeout"), sharing one id space
    (`Table._timer_seq`) and one heap (`Table.deadlines`) -- `_dispatch_expired_timer` tells them
    apart by which side-table (`_timer_seat` / `_turn_timer_seat` / `_disconnect_timer_seat`)
    recognizes a popped id, rather than this class knowing about any of them.

    **`id` is a private per-seat timer id (M3 sub-task 5), not the window's own `window_id`.**
    Sub-task 3 armed exactly one heap entry per claim window, shared by every offered seat, and
    used `window_id` as the heap id directly -- correct as long as every offered seat's deadline
    was always identical. Reconnect (docs/00-architecture.md §8's "mid-claim-window" row) breaks
    that assumption: one seat's deadline can move (re-armed to a fresh window on reconnect)
    without touching another's, so each offered seat needs its *own* heap entry. `Table` now
    hands out a fresh id per seat-arm (`_timer_seq`) and keeps `_timer_seat`/
    `_active_seat_timer` to map an id back to `(window_id, seat)` and to tell a superseded
    (re-armed-away) entry from the one that's actually still live for that seat -- see
    `_arm_seat_claim_timer`/`_handle_claim_timeout`.

    Lazy deletion: resolving a window (or re-arming one seat's entry) early doesn't remove the
    superseded heap entry -- it's left in place and the caller (`Table._handle_claim_timeout`)
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


class Table:
    """Owns exactly one `GameState`, mutated only via `reduce()`/`start_next_hand()`. See module
    docstring for disconnect/bot-handover (`mark_disconnected`/`_poke_bots`, M3 sub-task 6).

    `bot_tier` (`bots.worker.BOT_TIERS`, default `bots.worker.DEFAULT_BOT_TIER` = `T2`/`FaanBot`,
    per docs/05-roadmap.md M4.5) picks which real tier answers for *every* bot-driven seat this
    table ever has -- disconnect-handover autoplay and M4.5 practice-mode bot seats alike, both
    routed through the same `_poke_bots` path (see `SeatBinding`'s docstring). One tier per table,
    not per seat: nothing in this sub-task's scope (a fixed-difficulty practice table) needs a
    mixed-tier table, and `T0`/`T1` stay fully selectable by passing a different value, so the
    arena/tests that assume T0's uniform-random disconnect-handover behavior aren't forced onto
    T2. `practice=True` binds seats 1-3 to `bot_tier` bots immediately at construction (before
    seat 0's human ever joins) -- see `_bind_bot_seat`.
    """

    def __init__(
        self,
        table_id: str,
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
        self.table_id = table_id
        self.inbox: asyncio.Queue[Command | BotResult | SeatDisconnected | _WakeUp] = (
            asyncio.Queue()
        )
        self.state: GameState = new_game(ruleset, game_seed)
        self.event_id = 0  # internal monotonic id: logging/replay only, never on the wire
        # full-game action log (module docstring's "DB persistence" note) -- every Action _apply
        # actually runs through reduce(), never start_next_hand() transitions.
        self.actions: list[Action] = []
        self._session_factory = session_factory
        self._persisted = False  # save_game_record fires at most once, even if driven manually
        self._game_over_persisted = False  # see wait_for_shutdown_boundary -- True only once
        # the GAME_OVER persist attempt returns: a real write, the no-session_factory no-op, or
        # a write that raised (process_one's tail logs it and marks the attempt finished anyway)
        self._boundary_this_tick = False  # reset each process_one() tick, set inside _apply
        self._shutdown_boundary: asyncio.Event | None = None  # see wait_for_shutdown_boundary
        self.seat_seq: list[int] = [0, 0, 0, 0]  # per-seat outbound seq: dense, gapless (D1)
        self.ring: dict[int | str, deque[Envelope]] = {
            seat: deque[Envelope](maxlen=512) for seat in range(4)
        }
        # Spectators (docs/00-architecture.md §3/§5, "Spectating" sub-task): a connection
        # registered via `register_spectator` gets its own entry in `self.ring` (a string
        # `session_id` key -- this dict's `int | str` annotation always allowed for one, it just
        # never had one land in it before this) and its own dense, gapless `seq` counter here,
        # independent of every seat's and every other spectator's own stream (D1). `spectators`
        # maps a registered session id to its live push callback -- the spectator analogue of
        # `SeatBinding.send`, but there is no `SeatBinding`-shaped object for a spectator (no
        # seat to bind, no ready/pre-arm/idempotency state a read-only connection could ever
        # use) so a bare callable is enough.
        self.spectator_seq: dict[str, int] = {}
        self.spectators: dict[str, Callable[[int, dict[str, Any]], None]] = {}
        self.deadlines = TimerHeap()  # claim + disconnect + turn deadlines -- see module docstring
        self._getter: asyncio.Task[Command | BotResult | SeatDisconnected | _WakeUp] | None = (
            None  # long-lived (D17)
        )
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
        # hand-end hold (HAND_OVER, "hand-end hold" note): whole-table wait, not per-seat like
        # claims -- a single active timer id, and a single deadline shared by every seat.
        self._hand_end_acked: set[int] = set()
        self._hand_end_hand_no: int | None = None  # guards a stray/late ack for a prior hand
        self._active_hand_end_timer_id: int | None = None
        self._hand_end_deadline_ms: int | None = None
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
        # tables) gates every command on all four seats joining and `ready`-ing before the table
        # will process anything (`_authorize` below). `require_ready=False` (the default)
        # preserves this Table's pre-sub-task-4 behavior -- immediately actionable straight off
        # `new_game()` -- so `tests/test_table.py`/`tests/test_table_claims.py`, which drive a
        # bare `Table()` with no join/ready flow at all, are unaffected.
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
        (sub-task 4) -- also the test-facing entry point (`tests/test_table.py`)."""
        self.inbox.put_nowait(Command(seat=seat, action=action))

    # --- seats: join / ready / pre-arm (docs/02-protocol.md §2) --------------------------

    def join(
        self,
        session_id: str,
        send: Callable[[int, dict[str, Any]], None],
        *,
        seat: int | None = None,
        name: str | None = None,
    ) -> int:
        """Bind a session to a seat -- `seat=None` means "first open seat"
        (02-protocol.md §2). Raises `SeatTakenError`/`TableFullError` for app/ws.py to turn into
        `error{code:'seat_taken'|'table_full'}`. On success, broadcasts `seat_state` to every
        already-bound seat (including this one) and unicasts a fresh `state_sync` to the
        joining seat -- both per 02-protocol.md §2/§3.

        `name` (M5) is this seat's chosen guest display name -- normalized (`_normalize_name`)
        and stored on the new `SeatBinding` once, here; there is no later path that changes it
        (a `hello` reconnect never resends it -- see `SeatBinding.name`'s own docstring)."""
        if seat is not None:
            if not 0 <= seat < 4:
                raise ValueError(f"seat must be 0..3, got {seat}")
            if self.seat_bindings[seat] is not None:
                raise SeatTakenError(seat)
            chosen = seat
        else:
            open_seats = [s for s in range(4) if self.seat_bindings[s] is None]
            if not open_seats:
                raise TableFullError()
            chosen = open_seats[0]

        resolved_name = _normalize_name(name, chosen)
        self.seat_bindings[chosen] = SeatBinding(
            session_id=session_id, send=send, name=resolved_name
        )
        # This session_id may have been registered as a spectator (`app/ws.py`'s
        # `?spectate=true`, `register_spectator`) before this `join` -- promote it to a real
        # seat stream now, before broadcasting below, so it stops receiving the duplicate
        # spectator-shaped stream and doesn't see `seat_state` twice (once as a spectator, once
        # as the newly-bound seat).
        self.unregister_spectator(session_id)
        self._broadcast_wire(
            {"t": "seat_state", "seat": chosen, "status": "connected", "name": resolved_name}
        )
        self.publish_to_seat(chosen, self.state_sync_wire(chosen))
        return chosen

    def _bind_bot_seat(self, seat: int) -> None:
        """Bind `seat` to a bot from table construction (M4.5 practice mode), not a human `join`
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
            name=_BOT_DISPLAY_NAMES.get(self._bot_tier, "Bot"),
            status="bot",
            ready=True,
        )

    def mark_ready(self, seat: int) -> None:
        """`ready` (02-protocol.md §2): once every seat is joined *and* ready, the table deals
        -- for `require_ready=False` tables (the default; see `__init__`) `self.started` is
        already `True` and this only flips the binding's own flag, matching "not a required
        step" for those direct-construction test tables."""
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

    def mark_hand_end_ack(self, seat: int) -> None:
        """`hand_end_ack` (hand-end hold): this seat dismissed the hand-end overlay early.
        Direct, synchronous, not routed through `submit()`/`reduce()` -- there's no `Action`/
        legality check involved, same reasoning `mark_ready` gives for its own shape. No-op if
        the hold isn't open for the hand this ack claims (`self.state.phase != Phase.HAND_OVER`,
        or a late ack for a hand that's already moved on -- `self._hand_end_hand_no` no longer
        matches `self.state.hand_no`). Once every seat has acked, advances immediately --
        called directly by `Session`, outside `process_one()`'s own loop, so (like `mark_ready`)
        this publishes the follow-on `hand_start`/`deal`/`turn` itself rather than relying on
        `process_one()`'s tail to notice `self.state` changed."""
        if self.state.phase != Phase.HAND_OVER or self._hand_end_hand_no != self.state.hand_no:
            return
        self._hand_end_acked.add(seat)
        if len(self._hand_end_acked) >= 4:
            self._advance_to_next_hand()
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
        `SeatTakenError` if this seat is bound to a bot from table construction (M4.5 practice
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
        # Same promotion as `join` above: a `?spectate=true` connection that turns out to be
        # reclaiming a seat (`hello{seat}`) stops receiving the spectator-shaped stream here,
        # before `resume()` sends anything on the real seat stream.
        self.unregister_spectator(session_id)
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
        `DISCONNECTED`, table continues, grace period before bot takeover.

        Also enqueues `SeatDisconnected` so this table's own loop can forfeit a live claim offer
        this seat is mid-decision on, if it has one (`_handle_seat_disconnected`'s docstring for
        why a disconnect forfeits rather than waiting for reconnect to re-arm). Routed through
        `self.inbox` rather than applied inline here for the same reason every other `GameState`
        mutation is: this method runs on `Session`'s task, not this table's own (`_WakeUp`'s
        docstring) -- `_apply()` must only ever run from inside this table's loop.
        """
        binding = self.seat_bindings[seat]
        if binding is None or binding.session_id != session_id:
            return
        if binding.status != "connected":
            return
        binding.status = "disconnected"
        self._broadcast_wire(
            {"t": "seat_state", "seat": seat, "status": "disconnected", "name": binding.name}
        )
        self._arm_disconnect_timer(seat)
        self.inbox.put_nowait(SeatDisconnected(seat=seat))

    def resume(self, seat: int, last_seq: int | None, *, announce_reconnect: bool = False) -> None:
        """The three-way `hello{last_seq}` branch (02-protocol.md §5) for a seat that just
        called `reconnect()`, compared against *this seat's own* `ring`/`seat_seq` (never the
        table-global `event_id`, D1):

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
        binding = self.seat_bindings[seat]
        assert binding is not None  # reconnect() above already required a bound seat
        rearmed = self._rearm_seat_claim_timer(seat)
        head = self.seat_seq[seat] - 1  # last seq actually sent, or -1 if this seat never got one
        ring = self.ring[seat]
        if last_seq is not None and last_seq == head:
            pass  # nothing missed
        elif last_seq is not None and ring and ring[0].seq <= last_seq < head:
            for env in ring:
                if env.seq > last_seq:
                    binding.send(env.seq, dict(env.event))
        else:
            self.publish_to_seat(seat, self.state_sync_wire(seat))
            if announce_reconnect:
                self._broadcast_wire(
                    {"t": "seat_state", "seat": seat, "status": "connected", "name": binding.name}
                )
            return  # state_sync already carries any fresh deadline_ts -- nothing further to send
        if announce_reconnect:
            self._broadcast_wire(
                {"t": "seat_state", "seat": seat, "status": "connected", "name": binding.name}
            )
        if rearmed:
            self._send_seat_claim_offer(seat)

    # --- wire fan-out ------------------------------------------------------------------

    def publish_to_seat(self, seat: int, wire: dict[str, Any]) -> None:
        """Stamp `wire` with this seat's next `seq`, append it to the seat's ring buffer, and
        push it out over that seat's live connection if one is bound (`SeatBinding.send`) --
        the *only* path any seat-facing frame leaves this Table through, whether it came from
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
        self._broadcast_to_spectators(wire)

    # --- spectators (docs/00-architecture.md §3/§5, "Spectating" sub-task) -----------------

    def register_spectator(
        self, session_id: str, send: Callable[[int, dict[str, Any]], None]
    ) -> None:
        """Start treating `session_id` as an active spectator: seed its own `spectator_seq`/
        `ring` entry (D1 -- dense, gapless, independent of every seat's and every *other*
        spectator's own stream) and immediately send a spectator-redacted `state_sync`
        (`seat=None`, docs/00-architecture.md §5), matching the real `state_sync` a fresh `join`
        already gets (docs/02-protocol.md §3).

        **Trigger, and why it isn't purely passive (docs/02-protocol.md §2's "a socket that
        never sends `join` is a spectator").** The literal passive reading -- register every
        connection as a spectator the instant it's accepted, `join` promotes it away -- races
        the handshake every real *and every test* client already uses: `hello{client_version}`
        (no `seat`) is sent immediately after connecting, *before* `join`, in the normal flow
        (docs/02-protocol.md §2's own table), and would otherwise unavoidably deliver an
        unsolicited spectator `state_sync` to every about-to-join connection before its own
        `join` response -- there is no way to register "eagerly, but only for connections that
        turn out not to join" without either an actual signal or a race. `app/ws.py`'s
        `ws_endpoint` resolves this with an explicit, connection-level `?spectate=true` query
        parameter (mirroring `?practice=true`'s existing shape on the same endpoint) rather than
        a new wire message -- a real spectator client opts in at connect time, so registration
        never has to guess whether a `join` is coming. `join`/`reconnect` still promote a
        spectating connection away the moment it actually claims a seat (`unregister_spectator`,
        called from both), so "a socket that never sends `join` [while marked `spectate=true`]
        is a spectator" holds exactly as intended -- just resolved by an explicit connect-time
        flag instead of a race-prone passive default.
        """
        self.spectator_seq[session_id] = 0
        self.ring[session_id] = deque[Envelope](maxlen=512)
        self.spectators[session_id] = send
        self.publish_to_spectator(session_id, self.state_sync_wire(None))

    def unregister_spectator(self, session_id: str) -> None:
        """Drop `session_id`'s spectator bookkeeping outright -- called when its connection
        actually closes (`app/ws.py`'s `ws_endpoint` `finally` block, the spectator analogue of
        `mark_disconnected`'s seat-side cleanup call site) or when it's promoted to a seat
        (`join`/`reconnect`), so a promoted connection stops receiving the duplicate
        spectator-shaped stream and gets the real seated stream instead. A `session_id` that was
        never registered (every non-`spectate` connection) is a silent no-op.

        **Deliberately not reconnectable, unlike a seat.** A spectator has no `SeatBinding` to
        reclaim and no seat number a later connection could present to ask for this exact
        session back -- there is nothing in this protocol shaped like `hello{seat}` for "the
        same spectator, again" (a spectator session id isn't a value a client could even present
        back on a fresh connection). So a spectator's ring/seq bookkeeping isn't preserved for a
        future reconnect the way a seat's is (docs/00-architecture.md §6's `TableRegistry` note:
        a `SeatBinding` persists forever for reconnect) -- it's removed outright here, and a
        spectator that reconnects later is, correctly, a brand-new spectator session with a
        fresh `state_sync` (a fresh `register_spectator` call from `app/ws.py`, same as its
        first connection). This also bounds memory for a long-running table with many transient
        spectators, which `SeatBinding`'s own "persists forever" story would not.
        """
        self.spectators.pop(session_id, None)
        self.spectator_seq.pop(session_id, None)
        self.ring.pop(session_id, None)

    def publish_to_spectator(self, session_id: str, wire: dict[str, Any]) -> None:
        """Spectator analogue of `publish_to_seat`: stamp `wire` with this spectator session's
        own next `seq`, append it to its own ring buffer, and push it out over the live
        connection. A `session_id` not currently registered (never registered, or already
        unregistered -- promoted to a seat, or its connection closed) is silently ignored."""
        seq = self.spectator_seq.get(session_id)
        if seq is None:
            return
        self.spectator_seq[session_id] = seq + 1
        self.ring[session_id].append(Envelope(seq=seq, event=wire))
        send = self.spectators.get(session_id)
        if send is not None:
            send(seq, wire)

    def _broadcast_to_spectators(self, wire: dict[str, Any]) -> None:
        for session_id in list(self.spectators):
            self.publish_to_spectator(session_id, dict(wire))

    def broadcast_server_shutdown(self, deadline_ts: int) -> None:
        """docs/00-architecture.md §8.1 step 2: tell every seat a drain has started -- clients
        show a "reconnect shortly" banner instead of reading the eventual dropped socket as an
        error. Called by `app/registry.py`'s `TableRegistry.begin_shutdown`, once per table that
        currently has any seat bound, regardless of that seat's live connection status (same
        "broadcast reaches the ring buffer either way" convention every other broadcast here --
        `seat_state`, etc. -- already follows)."""
        self._broadcast_wire({"t": "server_shutdown", "deadline_ts": deadline_ts})

    def state_sync_wire(self, seat: int | None) -> dict[str, Any]:
        """Full redacted snapshot for `seat` (02-protocol.md §3 `state_sync`) -- sent on join,
        (sub-task 5) on reconnect-with-gap, and (the "Spectating" sub-task) on spectator
        registration (`seat=None`); also what `app/outbox.py`'s backpressure collapse resyncs to
        when a connection falls behind (§9). `turn_deadline_ts` is this seat's real armed
        `AWAIT_ACTION` deadline (`_turn_deadline_ms`, 00-architecture.md §8 "Turn timeout") --
        `seat_view()` only actually uses it when `seat == state.turn` and `state.phase ==
        Phase.AWAIT_ACTION`, so passing it unconditionally here is harmless. Both deadline
        lookups are skipped outright for `seat=None` (a spectator never holds a claim/turn
        deadline of its own) rather than probing `dict[tuple[int, int], int]`/`dict[int, int]`
        with a `None`-shaped key, which is also what keeps this typed cleanly under `seat: int |
        None` instead of relying on a lookup that would just always miss."""
        window = self.state.claim_window
        claim_deadline_ts = (
            self._claim_deadline_ms.get((window.window_id, seat))
            if window is not None and seat is not None
            else None
        )
        turn_deadline_ts = self._turn_deadline_ms.get(seat) if seat is not None else None
        view = seat_view(
            self.state,
            seat,
            seat_status=self._seat_status_tuple(),
            names=self._names_tuple(),
            claim_deadline_ts=claim_deadline_ts,
            turn_deadline_ts=turn_deadline_ts,
            hand_end_deadline_ts=self._hand_end_deadline_ms,
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
        that default is for callers with no `Table` behind them at all (bots/arena.py,
        bots/selfplay.py, direct `seat_view()` tests), where every seat is a live simulated
        player, not a lobby seat that may genuinely be empty."""
        return cast(
            "tuple[WireSeatStatus, WireSeatStatus, WireSeatStatus, WireSeatStatus]",
            tuple(b.status if b is not None else "empty" for b in self.seat_bindings),
        )

    def _names_tuple(self) -> tuple[str | None, str | None, str | None, str | None]:
        """Every bound seat's resolved `SeatBinding.name` (M5); `None` for an unbound seat --
        same "empty" convention `_seat_status_tuple()` uses, one level down (a `null` name
        rather than a wire-vocabulary string, since there's no name to report at all)."""
        return cast(
            "tuple[str | None, str | None, str | None, str | None]",
            tuple(b.name if b is not None else None for b in self.seat_bindings),
        )

    async def run(self) -> None:
        """The table's long-lived loop -- one `asyncio.Task` per table (server/AGENTS.md). Stops
        once the game actually ends (`Phase.GAME_OVER`) -- see `app/registry.py`'s
        `TableRegistry` module docstring for why a table's task shouldn't loop forever after that.
        `Table` itself (and reconnect/`state_sync` against it) keeps working after this returns;
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
        (`_next()`). Split out from `run()` so a test can drive the table one event at a time
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
        `process_one()` call, but this table's *very first* call starts as soon as the
        `asyncio.Task` is created (`TableRegistry.get_or_create`) -- before a white-box test's
        `table.state = ...` rigging (`tests/test_ws_gameplay.py`/`tests/test_reconnect.py`'s own
        established pattern) gets a chance to run, if that first call is still sitting inside
        `_next()`'s `await` when the test does it. `_WakeUp` was, until this sub-task, never
        able to resolve that first pending call at all (join/ready/reconnect never touch
        `self.inbox`) -- so it never surfaced. It can now: an early disconnect can be the first
        thing that ever wakes a freshly-created table, and treating that stale `pre_state` vs.
        the just-rigged `self.state` as "changed" would republish a spurious `turn` nobody
        asked for. `_WakeUp` never itself mutates `self.state` by construction, so it is simply
        never a valid trigger for this check.

        **GAME_OVER persistence + shutdown-boundary signal (module docstring).** Both live at
        this tail, after everything else this tick did: `_boundary_this_tick` is reset here (not
        at the top of the *next* call) so it only ever reflects *this* tick's own work, and the
        GAME_OVER persist -- if a `session_factory` was wired in, and only once ever
        (`_persisted`) -- is awaited to completion *before* `self._shutdown_boundary` (if a
        `wait_for_shutdown_boundary` caller is actually waiting on one) is signalled. That
        ordering is load-bearing, not incidental: `app/registry.py`'s `TableRegistry.begin_shutdown`
        disposes the DB engine only after every table's drain wait resolves, so a drain that woke
        up *before* this table's own final write finished could tear down/dispose the engine out
        from under an in-flight `session.commit()`.
        """
        pre_state = self.state
        self._boundary_this_tick = False
        event = await self._next()
        if isinstance(event, Command):
            self._handle(event)
        elif isinstance(event, BotResult):
            self._handle_bot_result(event)
        elif isinstance(event, SeatDisconnected):
            self._handle_seat_disconnected(event)
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
            try:
                await self._persist_game_record()
            except Exception:
                # a lost record must not also wedge the drain: `wait_for_shutdown_boundary`
                # blocks *unbounded* on exactly this window, so letting this propagate would
                # kill the table task with `_game_over_persisted` still False and the boundary
                # below never signalled -- every drain on this table then hangs forever, and
                # with it the process (or a TestClient context) trying to exit.
                logger.exception("table %s: GAME_OVER persist failed, record lost", self.table_id)
            self._game_over_persisted = True
        if self._boundary_this_tick and self._shutdown_boundary is not None:
            self._shutdown_boundary.set()

    async def _inbox_getter(self) -> Command | BotResult | SeatDisconnected | _WakeUp:
        return await self.inbox.get()

    def _ensure_getter(self) -> asyncio.Task[Command | BotResult | SeatDisconnected | _WakeUp]:
        if self._getter is None:
            self._getter = asyncio.create_task(self._inbox_getter())
        return self._getter

    async def _next(self) -> Command | BotResult | SeatDisconnected | _WakeUp | list[int]:
        """00-architecture.md §3 D17: one long-lived `_inbox_getter()` task for the table's
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

        `require_ready` tables additionally refuse everything until `self.started` -- belt and
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
        window, turn, hand-end, and disconnect-grace timers share one id space, so this just
        asks which side-table (or, for hand-end, single active id) recognizes it."""
        if timer_id in self._timer_seat:
            self._handle_claim_timeout(timer_id)
        elif timer_id in self._turn_timer_seat:
            self._handle_turn_timeout(timer_id)
        elif timer_id == self._active_hand_end_timer_id:
            self._handle_hand_end_timeout(timer_id)
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
        table-created bot seat were ever malfunctioning) but skips the status flip/broadcast --
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
        self._broadcast_wire(
            {"t": "seat_state", "seat": seat, "status": "autoplay", "name": binding.name}
        )

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
        self._broadcast_wire(
            {"t": "seat_state", "seat": seat, "status": "autoplay", "name": binding.name}
        )

    def _wake(self) -> None:
        """Force a blocked `_next()` to re-loop and recompute its wait set against the current
        `self.deadlines` -- see `_WakeUp`'s docstring for why this is needed at all."""
        self.inbox.put_nowait(_WakeUp())

    def _arm_disconnect_timer(self, seat: int) -> None:
        """Give `seat` a fresh `TimerHeap` entry, `ruleset.disconnect_grace_seconds` from right
        now (default 20s, `mahjong_core/config.py`) -- the disconnect-side analogue of
        `_arm_seat_claim_timer`, sharing the same heap and id sequence (`TimerHeap`'s
        docstring). Always called from `mark_disconnected`, itself called from `Session` outside
        this table's own loop -- `_wake()` at the end guarantees `_next()` actually notices."""
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
        `mark_ready()` -- both on this table's own event loop -- so, like the initial claim-
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
        the table loop is never blocked on a bot's answer.
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
                names=self._names_tuple(),
                claim_deadline_ts=claim_deadline_ts,
                turn_deadline_ts=turn_deadline_ts,
            )
            mask = legal_mask(self.state, seat)
            self._submit_bot_job(seat, tag, view, mask)

    def _submit_bot_job(self, seat: int, tag: BotJobTag, view: SeatView, mask: list[bool]) -> None:
        """Schedule `bots.worker.compute_action` on `self._bot_pool` (a `ProcessPoolExecutor` by
        default, D12: "the GIL makes a thread pool useless for CPU-bound pure-Python search") and
        return immediately -- the actual wait lives in `_await_bot_job`, a separate task, so this
        method never blocks the table loop. `seed` is derived from the tag rather than an unseeded
        `random.Random()` so a given decision point's bot output is reproducible (server/
        AGENTS.md). `self._bot_tier` (`Table.__init__`'s `bot_tier` param, `T0`/`T1`/`T2`) picks
        which real tier answers -- configurable per table, not hardcoded (docs/05-roadmap.md
        M4.5); `deadline` is advisory only (`bots/base.py`'s `Bot.act` contract), derived from
        the same hard `_BOT_JOB_TIMEOUT_SECONDS` this table actually enforces in `_await_bot_job`
        below, on the shared `time.monotonic()` clock every process on this machine agrees on.
        """
        loop = asyncio.get_running_loop()
        seed = hash((self.table_id, tag.kind, tag.key, tag.state_version, seat)) & 0xFFFFFFFF
        deadline = time.monotonic() + _BOT_JOB_TIMEOUT_SECONDS
        future = loop.run_in_executor(
            self._bot_pool, compute_action, view, mask, seed, self._bot_tier, deadline
        )
        task = asyncio.ensure_future(self._await_bot_job(seat, tag, future, seed))
        self._bot_tasks.add(task)
        task.add_done_callback(self._bot_tasks.discard)

    async def _await_bot_job(
        self, seat: int, tag: BotJobTag, future: asyncio.Future[int], seed: int
    ) -> None:
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

        Once the worker answers, sleeps a humanising `_BOT_THINK_MIN_SECONDS`-
        `_BOT_THINK_MAX_SECONDS` delay (docs/04-bots.md §1) before re-entering the result through
        `self.inbox` -- a real tier answers in single-digit milliseconds, which otherwise reads as
        the table racing ahead of anyone watching it. `seed`-derived, not an unseeded
        `random.Random()`, for the same reproducibility reason `_submit_bot_job` seeds the bot's
        own RNG with it (server/AGENTS.md); XORed with a constant so this delay doesn't just echo
        the bot's own action-choice draw. Sleeping here, in this job's own task, delays only this
        seat's result -- it never blocks the table loop or any other seat's job. If the pending tag
        goes stale while asleep (window closed, turn moved on, seat reconnected), the result lands
        anyway but `_handle_bot_result` drops it exactly like any other stale answer.
        """
        with contextlib.suppress(Exception):
            aid = await asyncio.wait_for(future, timeout=_BOT_JOB_TIMEOUT_SECONDS)
            think_seconds = random.Random(seed ^ 0x5A5A5A5A).uniform(
                _BOT_THINK_MIN_SECONDS, _BOT_THINK_MAX_SECONDS
            )
            await asyncio.sleep(think_seconds)
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

    def _handle_seat_disconnected(self, event: SeatDisconnected) -> None:
        """`mark_disconnected` enqueued this the moment `event.seat`'s socket closed. If that
        seat held a live, unresolved claim offer at that instant, forfeit it right now --
        immediately, not on the claim-window timeout -- same `Pass` path a real timeout uses
        (`_handle_claim_timeout` above).

        Why immediately, not "wait for `resume()` to re-arm on reconnect" (the previous
        design, 00-architecture.md §8's "mid-claim-window" reconnect row): `Table.resume()`'s
        full-`state_sync` branch (the common case now that seats survive a page reload) never
        follows up with a real `claim_offer` -- `StateSyncPayload.claim_options` carries only
        `{kind, tiles?}` per option, no `window_id`, no discarder, no discarded tile
        (`app/protocol.py`), so the client has nothing to render a dialog from or submit a
        `claim` against even though the server was still nominally waiting on this seat. The
        seat would reconnect into a table that looked paused with no way to act on the thing
        pausing it, until the re-armed timer eventually passed it anyway. Forfeiting on
        disconnect removes the offer before any reconnect can observe it, so there is nothing
        left to hand back -- simpler than teaching every reconnect path to resend a full,
        un-redacted-shape `claim_offer`, and product-acceptable: a player who drops mid-decision
        forfeits that decision, the same way a claim-window timeout already treats silence.

        No-op if there's no live window, this seat has no offer in it, or it already responded
        (its real `Claim`/`Pass` was already in `self.inbox` ahead of this disconnect notice --
        `_apply`'s single-writer ordering means whichever actually got here first wins, and a
        response already recorded always beats a forfeit that arrives after it)."""
        window = self.state.claim_window
        if window is None or event.seat in window.responses:
            return
        if not any(o.seat == event.seat for o in window.offers):
            return
        self._apply(Pass(window_id=window.window_id, seat=event.seat))

    def _apply(self, action: Action) -> None:
        """Run one already-authorized `Action` through `reduce()`, publish, and open the
        hand-end hold on `HAND_OVER` -- the common tail shared by a real `Command` (`_handle`),
        a synthesized claim-timeout `Pass` (`_handle_claim_timeout`), a synthesized turn-timeout
        `Discard` (`_handle_turn_timeout`), and a pre-armed auto-pass (`_send_claim_offers`).

        Landing on `HAND_OVER` no longer chains straight into `start_next_hand()` the same
        tick (that used to happen here, unconditionally) -- see `_open_hand_end_window`'s
        docstring for why the round is now held open first. `_open_hand_end_window` has to run
        *before* `self._publish(events)` below (it computes this hold's `deadline_ts`, which
        the just-produced `hand_end` wire frame needs to carry), but the actual advance -- if
        every seat is already acked, e.g. an all-bot practice table -- must not run until
        *after* `events` (which includes `hand_end`/`score`) is on the wire, or `hand_start`/
        `deal` would leapfrog them out of order."""
        self.actions.append(action)  # full-game log (module docstring) -- reduce()-bound only
        self.state, events = reduce(self.state, action)
        self.event_id += 1
        advance_immediately = False
        if self.state.phase == Phase.HAND_OVER:
            advance_immediately = self._open_hand_end_window()
        self._publish(events)
        if advance_immediately:
            self._advance_to_next_hand()
        else:
            # refreshed every call, in lockstep with self.state -- see `_turn_draw_tile`'s own
            # __init__ comment and `_turn_draw_tile_for_current_turn`'s docstring. When
            # `advance_immediately`, `_advance_to_next_hand` refreshes this itself instead,
            # against `more_events`/the post-advance state.
            self._turn_draw_tile = _turn_draw_tile_for_current_turn(events, self.state)

    def _open_hand_end_window(self) -> bool:
        """Open the `HAND_OVER` hold (docs/00-architecture.md §3's "Hand-end hold"): every
        hand end -- win or exhaustive draw alike, no outcome branching -- holds the table at
        `HAND_OVER` for up to `ruleset.hand_end_seconds`, or until every seat acks
        (`mark_hand_end_ack`), whichever first. This is a clock/session concern (`ClaimWindow`'s
        own docstring: "a clock, socket, or random value belongs in app/"), so it lives entirely
        here -- `mahjong_core.engine`/`state` are untouched.

        Seeds the ack set with every seat whose `SeatBinding.status` is `bot`/`autoplay` --
        mirrors `_send_claim_offers`'s `no_calls`/`auto_pass_chow` pre-resolution check: no
        human is present to click dismiss for those seats. A genuinely `disconnected` seat is
        deliberately *not* pre-seeded -- it's still someone's seat, it just rides out the same
        hold as everyone else. An unbound seat (`None` binding -- direct-construction test
        `Table`s with no join/ready flow at all) isn't pre-seeded either, for the same reason.

        Also computes this hold's `deadline_ts` (`self._hand_end_deadline_ms`) unconditionally,
        even when about to advance immediately -- the just-published `hand_end` frame carries
        it regardless of whether the hold turns out to be instantaneous.

        Returns whether every seat is already acked, in which case the caller (`_apply`)
        advances immediately, same tick, once this tick's own events are on the wire --
        preserves today's exact behavior for an all-bot practice table. Otherwise arms
        `_arm_hand_end_timer`."""
        self._hand_end_hand_no = self.state.hand_no
        self._hand_end_acked = {
            seat
            for seat, binding in enumerate(self.seat_bindings)
            if binding is not None and binding.status in ("bot", "autoplay")
        }
        duration = self.state.ruleset.hand_end_seconds
        self._hand_end_deadline_ms = _now_ms() + round(duration * 1000)
        if len(self._hand_end_acked) >= 4:
            return True
        self._arm_hand_end_timer()
        return False

    def _advance_to_next_hand(self) -> None:
        """The actual `start_next_hand()` transition -- deferred out of `_apply` so it can run
        once the hand-end hold actually closes (all-acked, `mark_hand_end_ack`, or timeout,
        `_handle_hand_end_timeout`), not unconditionally the same tick `HAND_OVER` is reached.
        Body is exactly what `_apply` used to do inline: advance, publish, flag the boundary,
        and (a fresh hand dealt straight into `AWAIT_ACTION`) synthesize `hand_start`/`deal`."""
        self.state, more_events = start_next_hand(self.state)
        self.event_id += 1
        self._publish(more_events)
        # a hand boundary -- the next hand dealt, or the game ended -- either way
        # `process_one()`'s tail is what actually wakes a pending `wait_for_shutdown_boundary`
        # (only after any GAME_OVER persist below has actually finished, never before).
        self._boundary_this_tick = True
        self._turn_draw_tile = _turn_draw_tile_for_current_turn(more_events, self.state)
        if self.state.phase == Phase.AWAIT_ACTION:
            # start_next_hand() deals the next hand with no Event of its own (state.py/
            # engine.py: `new_game`/`_deal_hand` build state directly, not through
            # reduce()) -- hand_start/deal have no engine event to redact either way
            # (02-protocol.md §3's sketch, no EventKind backs them), so this Table
            # synthesizes both here, the same way it does for the ready-triggered hand 1
            # start (`Table.mark_ready`).
            self._publish_hand_start_and_deal()

    def _arm_hand_end_timer(self) -> None:
        """Give the table a single fresh `TimerHeap` entry, `ruleset.hand_end_seconds` from right
        now -- modeled directly on `_arm_turn_timer`, but whole-table (one active id), not
        per-seat like claims: there's no priority/tiebreak logic here, just "wait for N of 4"
        (the closer template is `mark_ready`'s all-seats wait, not `ClaimWindow`). `deadline_ts`
        itself is computed by the caller (`_open_hand_end_window`), which needs it before this
        method runs (to stamp the `hand_end` frame) -- this method only arms the heap entry."""
        loop = asyncio.get_running_loop()
        duration = self.state.ruleset.hand_end_seconds
        deadline = loop.time() + duration
        timer_id = next(self._timer_seq)
        self.deadlines.add(deadline, timer_id)
        self._active_hand_end_timer_id = timer_id

    def _handle_hand_end_timeout(self, timer_id: int) -> None:
        """The hand-end hold's deadline popped with the table still waiting on at least one
        seat's ack. No-op if stale: unknown/superseded id (`_active_hand_end_timer_id` no
        longer matches -- same lazy-deletion staleness check every other timer here uses), or
        the hold already closed some other way (all-acked) before this fired -- `self.state.
        phase` has moved on to `AWAIT_ACTION`/`GAME_OVER` by then."""
        if self._active_hand_end_timer_id != timer_id:
            return
        if self.state.phase != Phase.HAND_OVER:
            return
        self._advance_to_next_hand()

    def _arm_claim_timer(self) -> None:
        """Arm a deadline the moment `self.state.claim_window` shows a new `window_id` --
        called after every event `process_one()` handles, mirroring `_arm_timers()` in
        00-architecture.md §3's Table sketch. Idempotent per window: `_armed_window_id` stops a
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
        re-arm (`_rearm_seat_claim_timer`) runs from `resume()`, outside this table's loop, where
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
                "options": self._claim_options_wire(offer, window.tile),
                "deadline_ts": self._claim_deadline_ms[(window.window_id, seat)],
            },
        )

    @staticmethod
    def _claim_options_wire(offer: ClaimOffer, claimed: TileId) -> list[dict[str, Any]]:
        """`tiles` names only the claimer's *own* tiles, excluding the claimed discard, because
        that is what a `claim`'s `tiles` disambiguator means on the way back in (02-protocol.md
        §2 and its §7 example) -- echoing the full meld here made every disambiguated claim
        fail `_pick_claim_meld` as `illegal`."""
        options: list[dict[str, Any]] = []
        if offer.can_win:
            options.append({"kind": "win"})
        for meld in offer.melds:
            own = [t for t in meld.tiles if t != claimed]
            options.append({"kind": _CLAIM_KIND_WIRE[meld.kind], "tiles": own})
        options.append({"kind": "pass"})
        return options

    def _publish_hand_start_and_deal(self) -> None:
        """Synthesize `hand_start` (broadcast) and `deal` (per-seat) -- see `_arm_claim_timer`'s
        docstring for why these have no backing `Event`. Called once the table actually starts
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
        the acting seat only, matching `turn.legal`'s own "unicast to the acting seat" contract
        -- spectators get the same public `{seat, phase, deadline_ts}` shape every non-acting
        seat does, never `legal` (it would name the acting seat's own concealed tile ids).
        """
        if self.state.phase != Phase.AWAIT_ACTION:
            return
        seat = self.state.turn
        deadline_ts = self._arm_turn_timer(seat)
        legal = [action_to_dict(a) for a in legal_actions(self.state, seat)]
        public_wire: dict[str, Any] = {
            "t": "turn",
            "seat": seat,
            "phase": self.state.phase.value,
            "deadline_ts": deadline_ts,
        }
        for s in range(4):
            wire: dict[str, Any] = dict(public_wire)
            if s == seat:
                wire["legal"] = legal
            self.publish_to_seat(s, wire)
        self._broadcast_to_spectators(public_wire)

    def _augment_event_wire(self, wire: dict[str, Any], event: Event) -> None:
        """The two fields `redact_event` alone can't derive from `state` in general (see that
        function's own module docstring): `discard.tile`/`pool_index` (this Table still holds
        `state` from immediately after the `reduce()` call that produced the event, before any
        *later* command could claim that discard away) and `hand_end.deadline_ts` (this
        `HAND_OVER` landing's own hold, already computed by `_open_hand_end_window` before
        `_apply` calls `_publish`). Identical for every recipient -- seats and spectators alike
        -- so `_publish` computes it once per event, not once per recipient."""
        if isinstance(event, Discarded):
            pool = self.state.seats[event.seat].discards
            wire["tile"] = tile_code(tile_id_type(event.tile_id))
            wire["pool_index"] = len(pool) - 1
        if isinstance(event, HandEnded):
            wire["deadline_ts"] = self._hand_end_deadline_ms

    def _publish(self, events: list[Event]) -> None:
        """`redact_event()` per recipient seat, appended to that seat's ring buffer with a fresh
        per-seat `seq`, and pushed out over each seat's live connection (`publish_to_seat`) --
        plus one more `redact_event(state, None, event)` pass, spectator-redacted exactly like
        `seat_view(state, None)`'s "union of what all four players show publicly" (docs/00-
        architecture.md §5), fanned out to every currently-registered spectator session
        (`_broadcast_to_spectators`) the same way `_augment_event_wire` augments it -- skipped
        entirely when there are no spectators to avoid redacting an event nobody will receive.
        A `HandEnded` also gets a broadcast `score` alongside it -- `state.seats[*].score`
        already reflects `_apply_payments()`'s result by the time `self.state` was reassigned
        above `_publish`'s own caller; `_broadcast_wire` itself reaches spectators too."""
        for event in events:
            for seat in range(4):
                wire = redact_event(self.state, seat, event)
                self._augment_event_wire(wire, event)
                self.publish_to_seat(seat, wire)
            if self.spectators:
                spectator_wire = redact_event(self.state, None, event)
                self._augment_event_wire(spectator_wire, event)
                self._broadcast_to_spectators(spectator_wire)
            if isinstance(event, HandEnded):
                self._broadcast_wire(
                    {"t": "score", "totals": {s: self.state.seats[s].score for s in range(4)}}
                )

    async def _persist_game_record(self) -> None:
        """`Phase.GAME_OVER` persistence (docs/06-ml.md §2, docs/00-architecture.md §6) -- a
        no-op if this `Table` was never given a `session_factory` (every bare `Table()` test, and
        any deployment with no `DATABASE_URL`, app/main.py's `lifespan`). `players` is each
        seat's real chosen `SeatBinding.name` (M5, 00-architecture.md §2.1) -- swapped in from
        the old `SeatBinding.session_id` stand-in this sub-task replaces, now that a real guest
        name exists. `None` for a seat nobody ever joined *by a human* -- a `bot` seat (M4.5
        practice mode) was never joined by a human either, so it gets `None` here too, not its
        synthetic display name (`"FaanBot"` etc.), which would otherwise misleadingly read as a
        real player. Only ever called once, from `process_one()`'s own tail (`self._persisted`
        guards a second call)."""
        if self._session_factory is None:
            return
        players = [
            b.name if b is not None and b.status != "bot" else None for b in self.seat_bindings
        ]
        async with self._session_factory() as session:
            await save_game_record(session, self.state, self.actions, players=players)

    async def wait_for_shutdown_boundary(self, timeout: float) -> bool:
        """docs/00-architecture.md §8.1 steps 3-5: block until this table reaches a hand boundary
        -- a fresh hand dealt, or the game ends (`_boundary_this_tick`, set inside `_apply`) --
        or `timeout` seconds elapse, whichever is first. Returns whether a boundary was actually
        reached; `False` means the grace window elapsed first and the caller
        (`app/registry.py`'s `TableRegistry.begin_shutdown`) abandons this table, same as a crash,
        but warned.

        A table whose GAME_OVER persist has actually *finished* (`_game_over_persisted`) returns
        `True` immediately with no event/wait at all -- nothing left to abandon.

        **The in-between state is the one two real bugs lived in.** `begin_shutdown` only ever
        calls this on a table whose background task is still running (`TableRegistry.is_running`),
        and a still-running table already at `Phase.GAME_OVER` is, by construction, one whose
        final `process_one()` tick is suspended inside `await self._persist_game_record()` --
        `state.phase` and `self._persisted` both flip synchronously, with no `await` between
        them and the persist call, so no other coroutine on this event loop can ever observe
        `state.phase == Phase.GAME_OVER` with `_game_over_persisted` still `False` except by
        genuinely racing that in-flight write. That is exactly why `process_one()`'s tail catches
        a failing `_persist_game_record()` rather than letting it propagate: a write that raises
        would otherwise end the table task inside this window, leaving the flag `False` and the
        boundary event unset with nothing alive left to set either, and the unbounded wait below
        would then never return -- a dead table wedging the whole drain (and the process, or the
        `TestClient` context, waiting on it) forever. The wait is unbounded on purpose; what
        makes that safe is that the window it waits on can only ever be exited, never abandoned.

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
        data loss, plus a spurious warning for a table that was, in fact, finishing normally. The
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
