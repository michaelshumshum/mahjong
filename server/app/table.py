"""`Table` -- the table actor's core dispatch loop (docs/architecture.md §3, §5).

Timer heap. `_next()` races one long-lived `_inbox_getter()` task, never cancelled, against
a sleep to `self.deadlines`' soonest entry. The heap holds claim-window, disconnect-grace, and
per-seat turn deadlines, sharing one id space and one `TimerHeap` instance.

Turn timeout (architecture.md §8). `_arm_turn_timer` arms a `ruleset.turn_seconds`
deadline whenever a seat's `AWAIT_ACTION` decision is genuinely new. On expiry
(`_handle_turn_timeout`) the table applies the deterministic default (`_timeout_discard_action`)
through the normal `_apply()`/`reduce()` path and registers a strike
(`_register_turn_timeout_strike`) -- three strikes flips the seat to `autoplay` for the rest of
the game. Fires identically for a connected human, a disconnected/`autoplay` human, and a `bot`
seat: the timer races the wall clock, not any particular bot job, so a hung or crashed worker
can never wedge a table past `turn_seconds`.

Disconnect / bot handover. `mark_disconnected`/`reconnect` flip `SeatBinding.status` between
`connected`/`disconnected`/`autoplay`. A disconnect arms a per-seat grace timer through the same
`TimerHeap` claim timers use; on expiry the seat flips to `autoplay`. `_poke_bots()`, called at
the tail of every `process_one()` tick, submits a decision to a `ProcessPoolExecutor` for every
`autoplay`-or-`bot` seat with a decision to make, tagged with `BotJobTag(kind, key,
state_version)`; the result re-enters through `self.inbox` as a `BotResult` carrying a bare
action id, decoded back into a real `Action` here (a worker process never receives `GameState`),
and dropped if the tag no longer matches `_pending_bot[seat]` by the time it lands.

Abandonment (architecture.md §8.2). Once a started table has no human seat `connected`,
`_update_abandon_timer` arms `abandon_grace_seconds` on the same heap; on expiry
`_handle_abandon_timeout` calls `end()` (sets `closed`, drops every bot job, sends
`table_closed`) and `run()` returns without persisting. `TableRegistry` then evicts it; its
reaper (architecture.md §8.3) calls `end()` the same way on an idle unstarted table.

Bot-filled seats from table creation (practice mode). `practice=True` binds seats 1-3 to
their resolved tier immediately, before seat 0's human ever `join`s -- a `bot` status, distinct
from `autoplay`, driven through the identical `_poke_bots` machinery. `seat_bot_tiers` picks a
different tier per seat (falling back to `bot_tier` for any seat it omits) -- see `Table`'s own
docstring and `_effective_bot_tier`. `all_bots=True` binds all four and deals as soon as `run()`
starts -- `app/registry.py`'s always-on showcase table.

Table settings. `TableSettings` holds per-table options that aren't game rules (those live
on `RuleSet`): `spectators_see_hands` switches spectators to the open-hands redaction. Swappable
mid-game via `update_settings`. Only an `all_bots` table may set it, and `join` never seats a
human there (`_check_settings`).

Early exit is already inside `reduce()`. `mahjong_core.engine._apply_claim_response` calls
`claims.can_close_early`/`resolve_claims` itself, inline, the moment a claim response makes the
window ready. This module's own job is what `reduce()` can't do without a clock: arming the
deadline when a window opens, and turning an unanswered deadline into synthesized `Pass`
responses fed back through the same path -- see `_handle_claim_timeout`.

Claim hold (architecture.md §4). Every discard, and every self-declared kong that could be
robbed, holds outbound frames for `claim_hold_seconds`
(`_begin_hold`/`_release_hold`), and a no-claim `ClaimResolved` reaches only the seats offered
(`_publish_claim_resolved`), so an observer can't tell whether a window opened.

Session/WS integration. `join`/`mark_ready`/`set_auto`/`publish_to_seat`/`state_sync_wire`
are this Table's half of the wire protocol -- `app/ws.py`'s `Session` is the other half.
`SeatBinding` holds the live per-seat state that has no home in the pure `GameState`. Several
wire events (`hand_start`/`deal`/`turn`/`claim_offer`/`score`) have no backing
`mahjong_core.engine.Event` to redact -- see `_publish_hand_start_and_deal`/
`_publish_turn_if_active`/`_send_claim_offers`.

One table = one `asyncio.Task` = one writer (server/AGENTS.md): every mutation of `self.state`
happens inside `_apply`, called only from this module's own loop. `join`/`mark_ready`/
`set_auto` mutate `self.seat_bindings` (not `self.state`) directly from whatever task calls
them -- safe because they're synchronous with no `await`, so nothing else can interleave on
this table's event loop between one call's start and its return.

DB persistence + graceful shutdown. `self.actions` accumulates every `Action` this table
ever applies via `_apply` (never `start_next_hand()` transitions, which aren't `Action`s and
reconstruct automatically off `Phase.HAND_OVER`), across the entire game -- `Table` is one
long-lived object, not recreated per hand. On reaching `Phase.GAME_OVER`, `process_one()` calls
`save_game_record` (if a `session_factory` was wired in; `None` means no persistence) with
`self.actions` and `players` taken from each seat's `SeatBinding.name` -- `None` for a seat never
joined by a human. `_boundary_this_tick`/`_shutdown_boundary` back
`wait_for_shutdown_boundary`, `app/registry.py`'s `TableRegistry.begin_shutdown`'s per-table half
of the drain sequence -- the boundary-reached event is only ever set after an in-flight
`GAME_OVER` persist finishes, never before, so a drain can't tear down a table (or dispose the
DB engine) while that table's own final write is still in flight.
"""

from __future__ import annotations

import asyncio
import contextlib
import heapq
import itertools
import logging
import os
import random
import secrets
import time
from collections import deque
from collections.abc import Callable, Mapping
from concurrent.futures import Executor, ProcessPoolExecutor
from dataclasses import dataclass
from typing import Any, Final, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clock import now_ms
from app.db.records import save_game_record
from app.errors import (
    TABLE_CLOSED_ERROR,
    NotHostError,
    SeatAuthError,
    SeatNotBoundError,
    SeatTakenError,
    TableAlreadyStartedError,
    TableFullError,
)
from app.fairness import fairness_reveal, new_nonce, seed_commit
from app.status import stats as server_stats
from app.table_types import (
    BotJobTag,
    BotResult,
    Command,
    Envelope,
    SeatBinding,
    SeatDisconnected,
    TableSettings,
    WireSeatStatus,
)
from app.views import (
    CLAIM_KIND_WIRE,
    HandHistoryRecord,
    _omniscient_seat_view,
    hand_history_wire,
    redact_event,
    seat_view,
    seat_view_wire,
)
from bots.tiers import BOT_TIERS, DEFAULT_BOT_TIER, BotTier
from bots.worker import compute_action
from mahjong_core.actions import Action, Discard, Pass, action_to_dict, legal_actions
from mahjong_core.config import RuleSet
from mahjong_core.engine import new_game, reduce, start_next_hand
from mahjong_core.events import (
    ClaimResolved,
    Discarded,
    Drawn,
    Event,
    HandEnded,
    KongReplacementDrawn,
    MeldFormed,
)
from mahjong_core.melds import MeldKind
from mahjong_core.ml import decode_action, legal_mask
from mahjong_core.presets import preset_id_for
from mahjong_core.state import ClaimOffer, ClaimWindow, GameState, Phase
from mahjong_core.tiles import TileId, tile_code, tile_id_type

__all__ = [
    "Table",
    "TimerHeap",
]

logger = logging.getLogger(__name__)

_BOT_JOB_TIMEOUT_SECONDS = 10.0  # hard deadline (architecture.md §8 "Bot raises / hangs")

# disconnect-handover always drives the autoplay bot at T2/FaanBot, never self._bot_tier -- must
# never land on ORACLE, which would leak every seat's concealed tiles. See _effective_bot_tier.
_DISCONNECT_HANDOVER_BOT_TIER: Final = BotTier.T2
# humanising think delay, applied after the worker replies so it never touches the real
# turn/claim deadline math -- a real tier answers in single-digit ms otherwise. Env-overridable.
_BOT_THINK_MIN_SECONDS = float(os.environ.get("BOT_THINK_MIN_SECONDS", "0.4"))
_BOT_THINK_MAX_SECONDS = float(os.environ.get("BOT_THINK_MAX_SECONDS", "1.4"))
# claim hold (architecture.md §4): every discard / robbable kong holds the next draw this long.
# below the bot think max on purpose (pace over hiding slow bot windows); see the residual leak.
_CLAIM_HOLD_SECONDS = float(os.environ.get("CLAIM_HOLD_SECONDS", "1.0"))
# frames a claim hold never delays: an offered seat's own window traffic, connection notices
_HOLD_EXEMPT_FRAMES: Final = frozenset({"ack", "error", "server_shutdown", "claim_offer"})

_MAX_NAME_LENGTH = 24  # guest display name cap (docs/protocol.md §2 `join.name`)

# client commands past this many queued inbox items are dropped (docs/protocol.md §11)
INBOX_COMMAND_LIMIT: Final = 64

# every bot seat gets a random HK mahjong-parlour nickname instead of a generic "Bot"
# placeholder -- cosmetic only, `self._bot_tier` still governs actual strength.
_BOT_NAME_POOL = (
    "東成西就",
    "八萬富翁",
    "大三元帥",
    "詐糊皇",
    "雞糊佬",
    "十三姨",
    "阿清",
    "阿蓮",
    "阿發",
    "碰哥",
    "槓叔",
    "平叔",
    "自摸嬸",
    "白板",
    "三缺一",
    "雀聖",
    "搭腳仔",
)


def _normalize_name(raw: str | None, seat: int) -> str:
    """Trim whitespace, cap at `_MAX_NAME_LENGTH` chars, fall back to `"Guest N"` (1-indexed)
    when empty or omitted -- a low-stakes guest field, so bad input is normalized, never
    rejected."""
    trimmed = (raw or "").strip()
    if not trimmed:
        return f"Guest {seat + 1}"
    return trimmed[:_MAX_NAME_LENGTH]


_default_bot_pool: ProcessPoolExecutor | None = None


def _shared_bot_pool() -> ProcessPoolExecutor:
    """One `ProcessPoolExecutor` per server process, created lazily on first use (constructing
    it doesn't spawn a worker), not one per `Table`. `Table.__init__`'s `bot_pool` param exists
    so tests (and `TableRegistry`) can inject a different `Executor` instead.

    Every tier shares this pool. A second, dedicated pool for `T3` (`SearchBot`) existed
    historically -- `SearchBot` budgeted 300-800ms per decision, two to three orders of
    magnitude slower than a `T1`/`T2` decision, which would have head-of-line-blocked unrelated
    tables' jobs sharing this pool. `SearchBot` was removed (docs/decisions/0012-searchbot-removed.md: determinized
    rollout search never beat plain `FaanBot` in arena validation, a structural ceiling from the
    rollout policy's own noise, not a fixable bug), so the isolation problem it existed to solve
    no longer has a tier that needs it."""
    global _default_bot_pool
    if _default_bot_pool is None:
        _default_bot_pool = ProcessPoolExecutor()
    return _default_bot_pool


def _turn_draw_tile_for_current_turn(events: list[Event], state: GameState) -> TileId | None:
    """Whether `state`'s current `AWAIT_ACTION` seat is holding a genuinely freshly-drawn tile
    this decision -- the signal `_timeout_discard_action` needs to choose tsumogiri over the
    lowest-`tile_id` fallback. Reads the real `Drawn`/`KongReplacementDrawn` events this tick
    actually emitted, rather than inferring it from tile counts -- "just drew" and "just claimed
    a pung/chow" leave the hand at the same size pre-discard, so a count-based heuristic can't
    tell them apart. `None` covers both "nothing was drawn" and a fresh hand's opening deal
    (`new_game`/`_deal_hand` build state directly, no `Event` to point at)."""
    if state.phase != Phase.AWAIT_ACTION:
        return None
    for event in reversed(events):
        if isinstance(event, (Drawn, KongReplacementDrawn)) and event.seat == state.turn:
            return event.tile_id
    return None


@dataclass(frozen=True)
class _WakeUp:
    """No-op inbox marker. `_next()`'s `asyncio.wait()` call fixes its waitable set (the inbox
    getter plus a sleeper for whatever `self.deadlines.peek()` was at that moment) the instant
    it's entered. `_arm_disconnect_timer`/`_arm_seat_claim_timer` can run from outside this
    table's own `process_one()` tick (`mark_disconnected`/`resume()`, called directly from
    `Session`) and add a heap entry earlier than whatever `_next()` is already blocked on --
    without this, that new deadline would sit unnoticed until some unrelated inbox item forced a
    recompute. Pushing this onto `self.inbox` forces exactly that recompute -- see
    `Table._wake`."""


class TimerHeap:
    """Deadline heap keyed by `(deadline_ts, id)`. Holds claim-window, disconnect-grace, and
    per-seat `AWAIT_ACTION` turn deadlines, sharing one id space (`Table._timer_seq`) and one
    heap -- `_dispatch_expired_timer` tells them apart by which side-table (`_timer_seat`/
    `_turn_timer_seat`/`_disconnect_timer_seat`) recognizes a popped id.

    `id` is a private per-seat timer id, not the window's own `window_id`: one seat's claim
    deadline can move (re-armed on reconnect) without touching another offered seat's, so each
    needs its own heap entry -- `_timer_seat`/`_active_seat_timer` map an id back to
    `(window_id, seat)` and tell a superseded entry from the one still live.

    Lazy deletion: resolving a window (or re-arming one seat's entry) early doesn't remove the
    superseded heap entry -- it's left in place and the caller (`_handle_claim_timeout`) checks
    the popped id against whatever is actually current when it fires. Early exit resolving a
    window before its deadline is the normal case, not an edge case, so every popped id needs
    this staleness check regardless.
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
    docstring for disconnect/bot-handover (`mark_disconnected`/`_poke_bots`).

    `bot_tier` (`bots.tiers.BOT_TIERS`, default `T2`/`FaanBot`) picks which real tier answers
    for a practice-mode `bot` seat (`_bind_bot_seat`, at construction) or an in-game `autoplay`
    seat this table has, both routed through `_poke_bots` -- with one deliberate exception:
    disconnect-handover (a real human's seat gone `autoplay`) always uses `T2`/`FaanBot`
    regardless of `bot_tier`, never this table's configured tier -- see
    `_DISCONNECT_HANDOVER_BOT_TIER`/`_effective_bot_tier`. `seat_bot_tiers` overrides `bot_tier`
    per seat -- practice mode's per-seat difficulty picker (`app/main.py`'s `create_table`,
    docs/frontend.md §7 "Practice mode"). A seat missing from the mapping falls back
    to `bot_tier`, so arena/tests that pass a bare `bot_tier=` and expect it applied uniformly
    (e.g. T0's uniform-random behavior) are unaffected. `practice=True` binds seats 1-3 to their
    resolved tier (`_effective_bot_tier`) immediately at construction, before seat 0's human ever
    joins -- see `_bind_bot_seat`.
    `"ORACLE"` builds its view via `_omniscient_seat_view` (`app/views.py`) instead of the
    ordinary `seat_view`, but the bot doing the deciding (`bots/worker.py`'s `_make_bot`) costs
    single-digit milliseconds like every other tier, so it shares the same pool every tier uses (`_shared_bot_pool`'s docstring has the historical
    note on why a second, `T3`-only pool briefly existed and was removed).
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
        seat_bot_tiers: Mapping[int, str] | None = None,
        practice: bool = False,
        all_bots: bool = False,
        settings: TableSettings | None = None,
        abandon_grace_seconds: float | None = None,
        claim_hold_seconds: float | None = None,
    ) -> None:
        if bot_tier not in BOT_TIERS:
            raise ValueError(
                f"unknown bot tier {bot_tier!r}; choices: {tuple(map(str, BOT_TIERS))}"
            )
        self._bot_tier = bot_tier
        # per-seat override on top of self._bot_tier (_effective_bot_tier). Validated here too,
        # since Table is also constructed directly by tests/tools, not just via the API boundary.
        if seat_bot_tiers is not None:
            for seat, tier in seat_bot_tiers.items():
                if not 0 <= seat < 4:
                    raise ValueError(f"seat must be 0..3, got {seat}")
                if tier not in BOT_TIERS:
                    raise ValueError(
                        f"unknown bot tier {tier!r}; choices: {tuple(map(str, BOT_TIERS))}"
                    )
        self._seat_bot_tiers: dict[int, str] = dict(seat_bot_tiers) if seat_bot_tiers else {}
        # seeded off game_seed (reproducible from ruleset/seed/actions), XORed with a constant so
        # this stream doesn't just echo the wall shuffle new_game() also derives from game_seed.
        self._bot_name_rng = random.Random(game_seed ^ 0x8888)
        self._bot_names_used: set[str] = set()
        self.table_id = table_id
        self.inbox: asyncio.Queue[Command | BotResult | SeatDisconnected | _WakeUp] = (
            asyncio.Queue()
        )
        self.state: GameState = new_game(ruleset, game_seed)
        self.event_id = 0  # internal id, logging/replay only, never on the wire
        # full-game action log -- every action that ran through reduce(), never start_next_hand().
        self.actions: list[Action] = []
        self._session_factory = session_factory
        self._persisted = False  # save_game_record fires at most once, even if driven manually
        # true once the GAME_OVER persist attempt returns (write, no-op, or failure) -- see wait_for_shutdown_boundary.
        self._game_over_persisted = False
        self._boundary_this_tick = False  # reset each process_one() tick, set inside _apply
        self._shutdown_boundary: asyncio.Event | None = None
        self.seat_seq: list[int] = [0, 0, 0, 0]  # per-seat outbound seq: dense, gapless
        self.ring: dict[int | str, deque[Envelope]] = {
            seat: deque[Envelope](maxlen=512) for seat in range(4)
        }
        # a spectator gets its own self.ring/seq entry (session_id key), independent of every seat's
        # and other spectators' streams; `spectators` maps session id -> push callback (SeatBinding.send's analogue).
        self.spectator_seq: dict[str, int] = {}
        self.spectators: dict[str, Callable[[int, dict[str, Any]], None]] = {}
        self._spectator_close: dict[str, Callable[[], None]] = {}
        self.settings = settings if settings is not None else TableSettings()
        self.deadlines = TimerHeap()  # claim + disconnect + turn deadlines -- see module docstring
        self._getter: asyncio.Task[Command | BotResult | SeatDisconnected | _WakeUp] | None = (
            None  # long-lived, never cancelled
        )
        self._armed_window_id: int | None = None  # last claim_window.window_id given a deadline
        # shared TimerHeap id space, claim/turn/disconnect-grace timers alike
        self._timer_seq = itertools.count(1)
        self._timer_seat: dict[int, tuple[int, int]] = {}  # timer id -> (window_id, seat)
        # (window_id, seat) -> the timer id that's actually live for it right now
        self._active_seat_timer: dict[tuple[int, int], int] = {}
        self._claim_deadline_ms: dict[tuple[int, int], int] = {}
        self._disconnect_timer_seat: dict[int, int] = {}
        self._active_disconnect_timer: dict[int, int] = {}
        # None never ends the table early (showcase, bare test tables)
        self.abandon_grace_seconds = abandon_grace_seconds
        self._abandon_timer_id: int | None = None
        self.closed = False  # ended early by end(); never persisted
        # claim hold: while _hold_timer_id is live, frames queue per recipient -- see _begin_hold
        self.claim_hold_seconds = (
            _CLAIM_HOLD_SECONDS if claim_hold_seconds is None else claim_hold_seconds
        )
        self._hold_timer_id: int | None = None
        self._held: dict[int | str, list[dict[str, Any]]] = {}
        self._held_sync: set[int | str] = set()
        self._turn_publish_due = False
        # per-seat AWAIT_ACTION turn deadlines -- same lazy-deletion staleness discipline as claims.
        self._turn_timer_seat: dict[int, int] = {}
        self._active_turn_timer: dict[int, int] = {}
        self._turn_deadline_ms: dict[int, int] = {}
        # hand-end hold is whole-table, not per-seat: one shared active timer id and deadline.
        self._hand_end_acked: set[int] = set()
        self._hand_end_hand_no: int | None = None  # guards a stray/late ack for a prior hand
        self._active_hand_end_timer_id: int | None = None
        self._hand_end_deadline_ms: int | None = None
        # the tile_id Drawn/KongReplacementDrawn landed for the seat self.state is offering an
        # AWAIT_ACTION decision to, if any; refreshed every _apply() in lockstep with self.state.
        self._turn_draw_tile: TileId | None = None

        # every completed hand, oldest first -- populated by _record_hand_history on each HandEnded.
        # lets a client with only a fresh state_sync still show the full scoresheet.
        self._hand_history: list[HandHistoryRecord] = []
        # (hand_no, nonce) behind the current hand's seed_commit; provable_fairness tables only.
        self._fairness_nonce: tuple[int, bytes] | None = None

        # seat -> BotJobTag in flight for it (absent = none outstanding). _bot_tasks holds strong
        # refs to the asyncio.Tasks awaiting each ProcessPoolExecutor future so they aren't GC'd mid-flight.
        self._pending_bot: dict[int, BotJobTag] = {}
        self._bot_tasks: set[asyncio.Task[None]] = set()
        self._bot_pool: Executor = bot_pool if bot_pool is not None else _shared_bot_pool()
        # "ORACLE" needs no dedicated pool: its bot costs single-digit ms like T2/T4, so every
        # tier shares this one pool.

        # require_ready=True (real tables) gates every command on all four seats joining+ready
        # first (_authorize below); require_ready=False (default) is actionable off new_game().
        self.require_ready = require_ready
        self.started = not require_ready
        self.seat_bindings: list[SeatBinding | None] = [None, None, None, None]
        # whichever seat's join was first; None until someone joins. practice=True binds seats 1-3
        # directly (not via join), so the human's own first join still becomes host.
        self.host_seat: int | None = None

        # practice mode: seat 0 stays open for the human; seats 1-3 bind immediately to their
        # resolved tier (self._seat_bot_tiers, falling back to self._bot_tier).
        self.all_bots = all_bots
        self._check_settings(self.settings)
        if practice or all_bots:
            for seat in range(0 if all_bots else 1, 4):
                self._bind_bot_seat(seat)

    def submit(self, seat: int, action: Action) -> None:
        """Push one command onto the inbox -- app/ws.py's envelope-parsing landing spot, also
        the test-facing entry point."""
        if self.inbox.qsize() >= INBOX_COMMAND_LIMIT:
            logger.warning("table %s: inbox full, dropping seat %d command", self.table_id, seat)
            return
        self.inbox.put_nowait(Command(seat=seat, action=action))

    def join(
        self,
        session_id: str,
        send: Callable[[int, dict[str, Any]], None],
        *,
        seat: int | None = None,
        name: str | None = None,
    ) -> int:
        """Bind a session to a seat -- `seat=None` means "first open seat". Raises
        `SeatTakenError`/`TableFullError` for app/ws.py to turn into
        `error{code:'seat_taken'|'table_full'}`. On success, broadcasts `seat_state` to every
        already-bound seat and unicasts a fresh `state_sync` to the joining seat.

        `name` is this seat's chosen guest display name -- normalized and stored once, here;
        there is no later path that changes it (a `hello` reconnect never resends it).

        An `all_bots` table never seats a human, even on a freed seat: its spectators may see
        every hand (`_check_settings`)."""
        if self.all_bots:
            raise TableFullError()
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

        if self.host_seat is None:
            self.host_seat = chosen
        resolved_name = _normalize_name(name, chosen)
        self.seat_bindings[chosen] = SeatBinding(
            session_id=session_id, send=send, name=resolved_name
        )
        # this session_id may have been registered as a spectator before this join -- promote
        # it to a real seat stream now, before broadcasting, so it doesn't see seat_state twice.
        self.unregister_spectator(session_id)
        self._broadcast_wire(
            {"t": "seat_state", "seat": chosen, "status": "connected", "name": resolved_name}
        )
        self.publish_to_seat(chosen, self.state_sync_wire(chosen))
        return chosen

    def _bind_bot_seat(self, seat: int) -> None:
        """Bind `seat` to a bot from table construction (practice mode), not a human `join` --
        called only from `__init__`, before any real connection exists, so there's nothing to
        broadcast yet. A real `SeatBinding` rather than a parallel tracking structure: `send` is
        a no-op, `ready=True` (a bot doesn't wait to click ready), `session_id` is a synthetic,
        never-matched value."""
        self.seat_bindings[seat] = SeatBinding(
            session_id=f"bot-seat-{seat}",
            send=lambda seq, wire: None,
            name=self._draw_bot_name(),
            status="bot",
            ready=True,
        )

    def _draw_bot_name(self) -> str:
        """A random display name for a newly bound bot seat, unique among every bot this table
        has ever bound. Falls back to allowing a repeat only once the pool itself is exhausted
        -- unreachable with 4 seats against a 17-name pool, kept only so this can never raise."""
        available = [n for n in _BOT_NAME_POOL if n not in self._bot_names_used]
        name = self._bot_name_rng.choice(available or list(_BOT_NAME_POOL))
        self._bot_names_used.add(name)
        return name

    def mark_ready(self, seat: int) -> None:
        """Once every seat is joined and ready, the table deals -- for `require_ready=False`
        tables `self.started` is already `True` and this only flips the binding's own flag."""
        binding = self.seat_bindings[seat]
        if binding is None:
            raise ValueError(f"seat {seat} has not joined")
        binding.ready = True
        self._maybe_start()

    def _maybe_start(self) -> None:
        """Shared tail of `mark_ready`/`start_with_bots`: once every seat is bound *and* ready,
        deal hand 1. A no-op otherwise, and idempotent once `self.started` is already true."""
        if self.started:
            return
        if all(b is not None and b.ready for b in self.seat_bindings):
            self.started = True
            self._publish_hand_start_and_deal()
            self._publish_turn_if_active()

    def start_with_bots(self, seat: int) -> None:
        """Host-only shortcut past waiting for a full human table: bind every still-empty seat
        to a bot and start the hand immediately once that makes every seat bound and ready.
        `NotHostError` for a non-host caller, `TableAlreadyStartedError` once `self.started`."""
        if seat != self.host_seat:
            raise NotHostError(seat)
        if self.started:
            raise TableAlreadyStartedError()
        for s in range(4):
            if self.seat_bindings[s] is not None:
                continue
            self._bind_bot_seat(s)
            binding = self.seat_bindings[s]
            assert binding is not None
            self._broadcast_wire(
                {"t": "seat_state", "seat": s, "status": "bot", "name": binding.name}
            )
        self._maybe_start()

    def mark_hand_end_ack(self, seat: int) -> None:
        """This seat dismissed the hand-end overlay early. Direct, synchronous, not routed
        through `submit()`/`reduce()` -- no `Action`/legality check involved. No-op if the hold
        isn't open for the hand this ack claims. Once every seat has acked, advances
        immediately and publishes the follow-on `hand_start`/`deal`/`turn` itself, since this
        runs outside `process_one()`'s own loop."""
        if self.state.phase != Phase.HAND_OVER or self._hand_end_hand_no != self.state.hand_no:
            return
        self._hand_end_acked.add(seat)
        if len(self._hand_end_acked) >= 4:
            self._advance_to_next_hand()
            self._publish_turn_if_active()

    def set_auto(self, seat: int, *, no_calls: bool | None, auto_pass_chow: bool | None) -> None:
        """`auto` pre-arm toggles -- `None` leaves that toggle unchanged."""
        binding = self.seat_bindings[seat]
        if binding is None:
            return
        if no_calls is not None:
            binding.no_calls = no_calls
        if auto_pass_chow is not None:
            binding.auto_pass_chow = auto_pass_chow

    def reconnect(
        self,
        seat: int,
        session_id: str,
        send: Callable[[int, dict[str, Any]], None],
        secret: str | None,
    ) -> bool:
        """Rebind an already-bound seat's live connection to a fresh socket. Unlike `join`,
        this never constructs a new `SeatBinding` -- `ready`/pre-arm toggles and the per-seat
        `IdempotencyCache` all live on the binding that already exists, so only the live-socket
        half (`session_id`/`send`) is swapped. Raises `SeatNotBoundError` if nothing has ever
        joined this seat. Raises `SeatTakenError` if this seat is bound to a bot (practice mode)
        rather than a human -- no prior human occupant to hand it back to. Raises
        `SeatAuthError` if `secret` doesn't match `binding.reconnect_secret`
        (`secrets.compare_digest`, checked before anything about the binding changes).

        Also flips `status` back to `connected` if this seat was `disconnected`/`autoplay`, and
        drops any in-flight bot job for this seat (a later `BotResult` carries the old tag,
        which no longer matches, so `_handle_bot_result` drops it -- no separate cancellation
        path needed). Also invalidates this seat's disconnect-grace timer if one is still
        ticking.

        Returns whether `status` actually changed away from `disconnected`/`autoplay`.
        Deliberately does not itself broadcast `seat_state` for that -- the caller defers that
        broadcast until after `resume()`'s own replay/state_sync decision, or this seat's own
        replay branch would re-deliver its own reconnection frame a second time.
        """
        binding = self.seat_bindings[seat]
        if binding is None:
            raise SeatNotBoundError(seat)
        if binding.status == "bot":
            raise SeatTakenError(seat)
        if not secrets.compare_digest(binding.reconnect_secret, secret or ""):
            raise SeatAuthError(seat)
        # same promotion as join above: a spectate=true connection reclaiming a seat stops
        # receiving the spectator-shaped stream here, before resume() sends anything.
        self.unregister_spectator(session_id)
        binding.session_id = session_id
        binding.send = send
        was_status = binding.status
        binding.status = "connected"
        self._pending_bot.pop(seat, None)
        self._active_disconnect_timer.pop(seat, None)
        self._abandon_timer_id = None
        return was_status != "connected"

    def mark_disconnected(self, seat: int, session_id: str) -> None:
        """The WS connection for `seat` closed. `session_id` guards a real race: an old,
        already-superseded connection's `finally` can run after a fresh reconnect already
        rebound this seat to a new session -- if `binding.session_id` no longer matches, a
        newer connection already has this seat, so do nothing.

        No-op if the seat isn't bound, or is already `disconnected`/`autoplay`.

        Also enqueues `SeatDisconnected` so this table's own loop can forfeit a live claim offer
        this seat is mid-decision on, if it has one -- routed through `self.inbox` rather than
        applied inline, since this method runs on `Session`'s task, not this table's own, and
        `_apply()` must only ever run from inside this table's loop.
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
        """The three-way `hello{last_seq}` branch for a seat that just called `reconnect()`,
        compared against this seat's own `ring`/`seat_seq` (never the table-global `event_id`):

        - `last_seq == head` -- nothing missed, resume live: no replay.
        - `last_seq` still in the 512-entry ring -- replay exactly the envelopes after it,
          already-redacted, exactly as originally sent (never re-redacted against `self.state`,
          which has moved on).
        - otherwise -- a full `state_sync`, same as `join`.

        Also re-arms this seat's own claim-window deadline first if it holds a live, unresolved
        offer -- done before the branch above so a `state_sync` picks up the fresh deadline in
        the same round trip; the live/replay branches instead follow up with one fresh
        `claim_offer`, since a replayed frame is history and must not be mutated in place.

        `announce_reconnect` broadcasts `seat_state{status:"connected"}` deliberately after the
        branch above, not before -- see `reconnect()`'s docstring for why.

        Runs to completion synchronously, with no `await` anywhere in this method: a caller
        that has received any one frame this call produced is guaranteed this call has already
        finished, rearm included.
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

    def publish_to_seat(
        self, seat: int, wire: dict[str, Any], *, bypass_hold: bool = False
    ) -> None:
        """Stamp `wire` with this seat's next `seq`, append it to the seat's ring buffer, and
        push it out over that seat's live connection if one is bound -- the only path any
        seat-facing frame leaves this Table through. During a claim hold the frame is queued
        unstamped instead (`_hold_frame`), so `seq` stays gapless in send order."""
        if not bypass_hold and self._hold_frame(seat, wire):
            return
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

    def register_spectator(
        self,
        session_id: str,
        send: Callable[[int, dict[str, Any]], None],
        close: Callable[[], None] | None = None,
    ) -> None:
        """Start treating `session_id` as an active spectator: seed its own `spectator_seq`/
        `ring` entry and immediately send a spectator-redacted `state_sync` (`seat=None`),
        matching what a fresh `join` already gets.

        Not a purely passive trigger: registering every connection as a spectator the instant
        it's accepted would race the handshake every real client uses (`hello{client_version}`
        is sent before `join`), unavoidably delivering an unsolicited spectator `state_sync` to
        every about-to-join connection. `app/ws.py`'s `ws_endpoint` resolves this with an
        explicit, connection-level `?spectate=true` query parameter instead. `join`/`reconnect`
        still promote a spectating connection away the moment it actually claims a seat
        (`unregister_spectator`, called from both).
        """
        self.spectator_seq[session_id] = 0
        self.ring[session_id] = deque[Envelope](maxlen=512)
        self.spectators[session_id] = send
        if close is not None:
            self._spectator_close[session_id] = close
        self.publish_to_spectator(session_id, self.state_sync_wire(None))

    def unregister_spectator(self, session_id: str) -> None:
        """Drop `session_id`'s spectator bookkeeping outright -- called when its connection
        closes, or when it's promoted to a seat (`join`/`reconnect`). A `session_id` never
        registered is a silent no-op.

        Deliberately not reconnectable, unlike a seat: a spectator has no `SeatBinding` and no
        seat number a later connection could present to ask for this exact session back. A
        spectator that reconnects later is a brand-new session with a fresh `state_sync`. This
        also bounds memory for a long-running table with many transient spectators.
        """
        self.spectators.pop(session_id, None)
        self.spectator_seq.pop(session_id, None)
        self.ring.pop(session_id, None)
        self._spectator_close.pop(session_id, None)

    def close_spectators(self) -> None:
        """Close every spectator connection registered with a `close` callback -- a showcase
        table being replaced by its next game (`app/registry.py`). The client's own reconnect
        lands it on whatever table now holds this id."""
        for close in list(self._spectator_close.values()):
            close()

    def _check_settings(self, settings: TableSettings) -> None:
        """Raise `ValueError` for settings this table may not run with. `spectators_see_hands`
        needs `all_bots`: on a table a human can sit at, live open hands are a collusion channel.
        Keyed on `all_bots`, not current occupancy, so `join` refusing every human on such a
        table keeps it true for the table's lifetime."""
        if settings.spectators_see_hands and not self.all_bots:
            raise ValueError("spectators_see_hands is only allowed on an all-bot table")

    def update_settings(self, settings: TableSettings) -> None:
        """Swap this table's `TableSettings`; spectators get a fresh `state_sync` when what they
        may see changed. Raises `ValueError` (settings unchanged) per `_check_settings`."""
        self._check_settings(settings)
        reveal_changed = settings.spectators_see_hands != self.settings.spectators_see_hands
        self.settings = settings
        if reveal_changed:
            for session_id in list(self.spectators):
                self.publish_to_spectator(session_id, self.state_sync_wire(None))

    def publish_to_spectator(self, session_id: str, wire: dict[str, Any]) -> None:
        """Spectator analogue of `publish_to_seat`. A `session_id` not currently registered is
        silently ignored."""
        seq = self.spectator_seq.get(session_id)
        if seq is None:
            return
        if self._hold_frame(session_id, wire):
            return
        self.spectator_seq[session_id] = seq + 1
        self.ring[session_id].append(Envelope(seq=seq, event=wire))
        send = self.spectators.get(session_id)
        if send is not None:
            send(seq, wire)

    def _broadcast_to_spectators(self, wire: dict[str, Any]) -> None:
        for session_id in list(self.spectators):
            self.publish_to_spectator(session_id, dict(wire))

    def _hold_frame(self, key: int | str, wire: dict[str, Any]) -> bool:
        """Queue `wire` for `key` (a seat or spectator session) if a claim hold is live; returns
        whether it was queued. A `state_sync` replaces that recipient's queue and is rebuilt at
        release, since one built now would show the held draw; later frames are covered by it."""
        if self._hold_timer_id is None or wire["t"] in _HOLD_EXEMPT_FRAMES:
            return False
        if wire["t"] == "state_sync":
            self._held.pop(key, None)
            self._held_sync.add(key)
        elif key not in self._held_sync:
            self._held.setdefault(key, []).append(wire)
        return True

    def _begin_hold(self) -> None:
        """Start a claim hold (architecture.md §4 "Claim hold"): every frame not in
        `_HOLD_EXEMPT_FRAMES` queues until `claim_hold_seconds` from now, whether or not a
        window opened. `_authorize`/`_poke_bots`/`process_one` also keep the next turn from
        starting until release. Always runs inside this table's own tick, so needs no `_wake()`."""
        if self.claim_hold_seconds <= 0 or self._hold_timer_id is not None:
            return
        loop = asyncio.get_running_loop()
        timer_id = next(self._timer_seq)
        self.deadlines.add(loop.time() + self.claim_hold_seconds, timer_id)
        self._hold_timer_id = timer_id

    def _release_hold(self) -> None:
        """Flush every queued frame in order and send each deferred `state_sync` built against
        the state as of now. The deferred `turn` follows from `process_one()`'s tail."""
        self._hold_timer_id = None
        held, synced = self._held, self._held_sync
        self._held, self._held_sync = {}, set()
        for key, frames in held.items():
            for wire in frames:
                if isinstance(key, int):
                    self.publish_to_seat(key, wire)
                else:
                    self.publish_to_spectator(key, wire)
        for key in synced:
            if isinstance(key, int):
                self.publish_to_seat(key, self.state_sync_wire(key))
            else:
                self.publish_to_spectator(key, self.state_sync_wire(None))

    def broadcast_server_shutdown(self, deadline_ts: int) -> None:
        """Tell every seat a drain has started -- clients show a "reconnect shortly" banner
        instead of reading the eventual dropped socket as an error."""
        self._broadcast_wire({"t": "server_shutdown", "deadline_ts": deadline_ts})

    def state_sync_wire(self, seat: int | None) -> dict[str, Any]:
        """Full redacted snapshot for `seat` -- sent on join, reconnect-with-gap, spectator
        registration (`seat=None`), and backpressure collapse. Both deadline lookups are
        skipped outright for `seat=None` (a spectator never holds a claim/turn deadline) rather
        than probing the dict with a `None`-shaped key."""
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
            seat_status=self.seat_status_tuple(),
            names=self.names_tuple(),
            claim_deadline_ts=claim_deadline_ts,
            turn_deadline_ts=turn_deadline_ts,
            hand_end_deadline_ts=self._hand_end_deadline_ms,
            host_seat=self.host_seat,
            reveal_hands=seat is None and self.settings.spectators_see_hands,
        )
        wire = seat_view_wire(view)
        wire["t"] = "state_sync"
        wire["hand_history"] = hand_history_wire(self._hand_history)
        # fixed at construction, never changes after new_game(). ruleset_preset is the
        # RULESET_PRESETS key it matches, or null for a custom ruleset.
        wire["ruleset_preset"] = preset_id_for(self.state.ruleset)
        wire["ruleset"] = self.state.ruleset.to_dict()
        wire["bot_levels"] = list(self.bot_levels_tuple())
        commit = self._seed_commit()
        if commit is not None:
            wire["seed_commit"] = commit
        return wire

    def seat_status_tuple(
        self,
    ) -> tuple[WireSeatStatus, WireSeatStatus, WireSeatStatus, WireSeatStatus]:
        """Every bound seat's real `status`; an unbound seat reads `empty` -- distinct from
        `connected`, so a client mid-lobby can tell "nobody has joined this seat yet" from
        "someone's here and their socket is live"."""
        return cast(
            "tuple[WireSeatStatus, WireSeatStatus, WireSeatStatus, WireSeatStatus]",
            tuple(b.status if b is not None else "empty" for b in self.seat_bindings),
        )

    def names_tuple(self) -> tuple[str | None, str | None, str | None, str | None]:
        """Every bound seat's resolved `SeatBinding.name`; `None` for an unbound seat."""
        return cast(
            "tuple[str | None, str | None, str | None, str | None]",
            tuple(b.name if b is not None else None for b in self.seat_bindings),
        )

    def bot_levels_tuple(self) -> tuple[str | None, str | None, str | None, str | None]:
        """Each `bot`-status seat's tier; `None` for every other seat, `autoplay` included --
        a human's handover tier isn't the seat's level."""
        return cast(
            "tuple[str | None, str | None, str | None, str | None]",
            tuple(
                self._effective_bot_tier(seat) if b is not None and b.status == "bot" else None
                for seat, b in enumerate(self.seat_bindings)
            ),
        )

    async def run(self) -> None:
        """The table's long-lived loop -- one `asyncio.Task` per table. Stops once the game
        actually ends (`Phase.GAME_OVER`); `Table` itself (reconnect/`state_sync`) keeps working
        after this returns, only the background task stops."""
        # an all-bot table has nobody to ready it -- deal and hand the first turn to its bot
        # here, the first moment a running loop exists for _arm_turn_timer/bot jobs
        self._maybe_start()
        self._poke_bots()
        while True:
            await self.process_one()
            if self.closed or self.state.phase == Phase.GAME_OVER:
                return

    async def process_one(self) -> None:
        """Handle exactly one event: the next inbox `Command`/`BotResult`, or every claim-window
        or disconnect-grace timer that's expired, whichever resolves first (`_next()`). Split
        out from `run()` so a test can drive the table one event at a time. `turn` is only
        re-published when this cycle actually mutated `self.state` -- an illegal/dropped command
        or a stale timeout leaves `state` as the same object, and must not re-stamp a fresh `seq`
        for nothing. `_poke_bots()` runs every tick regardless (cheap and idempotent), since some
        other seat's action can hand an already-`autoplay` seat a fresh decision without that
        seat's own state changing.

        A single `_next()` call can return several expired timer ids at once (every offered
        claim seat has its own heap entry), so all get processed in this one tick.

        A `_WakeUp` never counts as "state changed", even if `self.state is not pre_state`
        happens to be true -- a test's white-box `table.state = ...` rig can land between
        `pre_state`'s capture and a `_WakeUp` resolving the table's very first pending call, and
        `_WakeUp` never itself mutates `self.state` by construction, so it's never a valid
        trigger for this check.

        GAME_OVER persistence + shutdown-boundary signal both live at this tail: the persist (if
        a `session_factory` was wired in, once ever) is awaited to completion before
        `self._shutdown_boundary` is signalled -- load-bearing, since `TableRegistry.
        begin_shutdown` disposes the DB engine only after every table's drain wait resolves.
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
        if self.closed:
            if self._shutdown_boundary is not None:
                self._shutdown_boundary.set()
            return
        self._arm_claim_timer()
        if not isinstance(event, _WakeUp) and self.state is not pre_state:
            self._turn_publish_due = True
        # a claim hold defers the turn (and its timer) to the tick that releases it
        if self._turn_publish_due and self._hold_timer_id is None:
            self._turn_publish_due = False
            self._publish_turn_if_active()
        self._poke_bots()
        self._update_abandon_timer()
        if self.state.phase == Phase.GAME_OVER and not self._persisted:
            self._persisted = True
            try:
                await self._persist_game_record()
            except Exception:
                # must not propagate: wait_for_shutdown_boundary blocks unbounded on this window,
                # so an uncaught exception here would hang the drain (and the process) forever.
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
        """One long-lived `_inbox_getter()` task for the table's entire lifetime, raced against
        a sleep to `self.deadlines`' soonest entry -- the getter is never cancelled, on either
        branch. When both are ready in the same `asyncio.wait` call, the getter always wins: a
        real command is applied that tick and the still-due timer is left in the heap to pop
        next call, rather than risking `wait_for`/cancel-on-timeout's silent drop of an
        already-arrived item.
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
        seat (server/AGENTS.md: never trust a client-supplied legal-action set). Returns `None`
        for an illegal command; `_handle` drops it with no mutation.

        `require_ready` tables additionally refuse everything until `self.started` -- belt and
        suspenders with app/ws.py's own pre-check, but this is the one place the legality gate
        is actually enforced.
        """
        if not self.started:
            return None
        if self._hold_timer_id is not None and self.state.phase == Phase.AWAIT_ACTION:
            return None  # that seat's draw/turn is still held back (_begin_hold)
        if cmd.action in legal_actions(self.state, cmd.seat):
            return cmd.action
        return None

    def _handle(self, cmd: Command) -> None:
        action = self._authorize(cmd)
        if action is None:
            return  # illegal command: dropped silently, state and ring buffers untouched
        self._apply(action)

    def _handle_bot_result(self, result: BotResult) -> None:
        """A worker's answer, re-entering through `self.inbox`. Dropped silently if
        `_pending_bot[result.seat]` no longer equals `result.tag` -- the window/turn moved on,
        or the seat reconnected, meaning this job was computed against a `self.state` that isn't
        "now" anymore. When the tag does match, `self.event_id` is provably unchanged since
        submission, so `self.state` is byte-identical to what the worker saw -- which is what
        makes `decode_action(result.aid, self.state, result.seat)` safe to call here: the worker
        never had `self.state` itself, only the id it computed against a `SeatView`/mask built
        from this same state. `_authorize` still runs anyway as defense-in-depth, not because
        it's expected to ever actually reject something here.
        """
        if self.closed or self._pending_bot.get(result.seat) != result.tag:
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
        """One id popped off the shared `self.deadlines` heap: claim-window, turn, hand-end, and
        disconnect-grace timers share one id space, so this just asks which side-table (or, for
        hand-end, single active id) recognizes it."""
        if timer_id in self._timer_seat:
            self._handle_claim_timeout(timer_id)
        elif timer_id in self._turn_timer_seat:
            self._handle_turn_timeout(timer_id)
        elif timer_id == self._active_hand_end_timer_id:
            self._handle_hand_end_timeout(timer_id)
        elif timer_id == self._abandon_timer_id:
            self._handle_abandon_timeout()
        elif timer_id == self._hold_timer_id:
            self._release_hold()
        else:
            self._handle_disconnect_timeout(timer_id)

    def _handle_turn_timeout(self, timer_id: int) -> None:
        """One per-seat `AWAIT_ACTION` deadline popped. No-op if stale: unknown id, superseded
        by a later arm for the same seat, or `seat` genuinely isn't the one still deciding (a
        real command for it raced this timer and won).

        `state.claim_window` is always `None` while `state.phase == Phase.AWAIT_ACTION`
        (`GameState.__post_init__`'s invariant) -- a seat can never simultaneously be
        `state.turn` and hold a live claim offer. The assert documents that this was checked
        against the real invariant, not assumed.

        Applies the deterministic default (`_timeout_discard_action`) through the normal
        `_apply()`/`reduce()` path, then registers a strike. Fires identically whether `seat` is
        a connected human, a disconnected/`autoplay` human, or a `bot` seat -- the timer races
        the wall clock, not any particular bot job, so a hung or crashed worker can't outlast
        `turn_seconds`."""
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
        """Deliberately dumb, not defensive. Tsumogiri -- discard the tile that just landed in
        `seat`'s hand, if this decision started with a freshly drawn tile (`self._turn_draw_tile`).
        Otherwise (a claimed pung/chow landed here with nothing new, or a fresh hand's opening
        deal) the lowest-`tile_id` concealed tile.

        Sourced from `legal_actions(state, seat)`'s own `Discard` set, not `state.seats[seat].
        concealed` directly, so this can never name a tile that isn't actually a legal discard
        right now.
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
        """Three strikes -> seat flips to `AUTOPLAY` for the rest of the game. A `bot`/already-
        `autoplay` seat still accumulates strikes here but skips the status flip/broadcast --
        there's no human occupant to take control away from."""
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
        """A disconnect-grace deadline popped. No-op if stale -- unknown id, superseded (the
        seat reconnected since this was armed), or the seat somehow isn't `disconnected` anymore.
        Otherwise flips the seat to `autoplay` and broadcasts `seat_state`.

        Pre-start (`not self.started`), there's no hand for a bot to play, so the seat frees
        back to `None` instead of `AUTOPLAY` -- so an abandoned waiting-room table stops showing
        up in `TableRegistry.list_tables()` as taken with nobody there."""
        seat = self._disconnect_timer_seat.get(timer_id)
        if seat is None:
            return
        if self._active_disconnect_timer.get(seat) != timer_id:
            return
        binding = self.seat_bindings[seat]
        if binding is None or binding.status != "disconnected":
            return
        if not self.started:
            self.seat_bindings[seat] = None
            self._pending_bot.pop(seat, None)
            self._active_disconnect_timer.pop(seat, None)
            if self.host_seat == seat:
                self.host_seat = None
            self._broadcast_wire({"t": "seat_state", "seat": seat, "status": "empty", "name": None})
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
        now (default 20s). Always called from `mark_disconnected`, itself called from `Session`
        outside this table's own loop -- `_wake()` at the end guarantees `_next()` notices."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.state.ruleset.disconnect_grace_seconds
        timer_id = next(self._timer_seq)
        self.deadlines.add(deadline, timer_id)
        self._disconnect_timer_seat[timer_id] = seat
        self._active_disconnect_timer[seat] = timer_id
        self._wake()

    def _is_abandoned(self) -> bool:
        """Started, with at least one human-bound seat and none of them `connected`. `bot` seats
        and spectators never count -- a spectator keeping a table alive would be trivially
        exploitable."""
        if not self.started or self.abandon_grace_seconds is None:
            return False
        humans = [b for b in self.seat_bindings if b is not None and b.status != "bot"]
        return bool(humans) and all(b.status != "connected" for b in humans)

    def _update_abandon_timer(self) -> None:
        """Arm `abandon_grace_seconds` from the tick the last human went away; disarm (lazily,
        like every other timer here) once one is back. `reconnect()` also disarms directly, so
        a second departure always gets a fresh full grace."""
        if not self._is_abandoned():
            self._abandon_timer_id = None
            return
        if self._abandon_timer_id is not None:
            return
        assert self.abandon_grace_seconds is not None
        loop = asyncio.get_running_loop()
        timer_id = next(self._timer_seq)
        self.deadlines.add(loop.time() + self.abandon_grace_seconds, timer_id)
        self._abandon_timer_id = timer_id

    def _handle_abandon_timeout(self) -> None:
        """The abandonment deadline popped. Re-checks rather than trusting the arm: a reconnect
        off-loop may have landed since. Ends the table: no further bot jobs, every in-flight one
        dropped, every remaining socket told why (spectators also closed), never persisted."""
        self._abandon_timer_id = None
        if not self._is_abandoned():
            return
        self.end(TABLE_CLOSED_ERROR)
        logger.warning(
            "table %s: ended at hand %d, reason: abandoned (no human connected for %.0fs)",
            self.table_id,
            self.state.hand_no,
            self.abandon_grace_seconds,
        )

    def end(self, error: Mapping[str, str]) -> None:
        """Stop this table for good: no further bot jobs, every in-flight one dropped, every
        seat stream and spectator sent `error` (spectators also closed), never persisted. Called
        from the table's own loop (abandonment) or by `TableRegistry.reap`, which then cancels
        the task; synchronous either way, so it never interleaves with a tick."""
        self.closed = True
        self._pending_bot.clear()
        for task in list(self._bot_tasks):
            task.cancel()
        self._broadcast_wire({"t": "error", **error})
        self.close_spectators()
        if self._getter is not None:
            # the never-cancel rule guards against losing an item; nothing is read after this
            self._getter.cancel()
            self._getter = None

    def _arm_turn_timer(self, seat: int) -> int:
        """Give `seat` a fresh `TimerHeap` entry, `ruleset.turn_seconds` from right now. Only
        ever called synchronously from within `process_one()`/`mark_ready()`, both on this
        table's own event loop, so this needs no `_wake()` call -- the next `_next()` picks up
        the fresh heap entry naturally. Returns the wire `deadline_ts` (epoch ms)."""
        loop = asyncio.get_running_loop()
        duration = self.state.ruleset.turn_seconds
        deadline = loop.time() + duration
        timer_id = next(self._timer_seq)
        self.deadlines.add(deadline, timer_id)
        self._turn_timer_seat[timer_id] = seat
        self._active_turn_timer[seat] = timer_id
        deadline_ts = now_ms() + round(duration * 1000)
        self._turn_deadline_ms[seat] = deadline_ts
        return deadline_ts

    def _poke_bots(self) -> None:
        """Submit a decision to the bot worker pool for every seat bound `autoplay` or `bot`
        that currently has one to make -- its own `AWAIT_ACTION` turn, or a live claim offer it
        hasn't answered -- tagged with what it's computed against (`BotJobTag`) so a stale
        result is dropped when it lands. Idempotent: a seat whose current decision already has a
        job in flight isn't resubmitted. Never runs bot logic inline -- `_submit_bot_job` only
        schedules work and returns immediately; it also builds the `SeatView` this seat's job
        gets, since which tier (and therefore which `SeatView` constructor) applies to a given
        seat needs `_effective_bot_tier`'s "is this a real human's autoplay seat" check.
        """
        if self.closed:
            return
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
            elif (
                self._hold_timer_id is None
                and self.state.phase == Phase.AWAIT_ACTION
                and self.state.turn == seat
            ):
                tag = BotJobTag(kind="turn", key=seat, state_version=self.event_id)
            if tag is None or self._pending_bot.get(seat) == tag:
                continue
            self._pending_bot[seat] = tag
            mask = legal_mask(self.state, seat)
            self._submit_bot_job(seat, tag, mask)

    def _effective_bot_tier(self, seat: int) -> str:
        """The tier that actually drives `seat`'s next bot decision -- `self._seat_bot_tiers[seat]`
        if this seat has a per-seat override, else `self._bot_tier`, with one deliberate
        exception: disconnect-handover (`seat`'s binding is `autoplay`, meaning a real human went
        quiet and a bot took the seat over) is always `_DISCONNECT_HANDOVER_BOT_TIER`
        ("T2"/`FaanBot`), regardless of what tier this table or seat is configured with. A human
        never opted into whatever tier the table happens to run, and specifically must never
        have their seat driven by `ORACLE`, whose view is built by `_omniscient_seat_view` and
        carries every other seat's concealed tiles -- a real human's own seat must never be the
        one a bot job is built omnisciently for.

        A `bot`-status seat (practice mode / `all_bots`, bound at `__init__` time, never a real
        human -- `_bind_bot_seat`) is unaffected and uses its resolved tier as configured.
        """
        binding = self.seat_bindings[seat]
        if binding is not None and binding.status == "autoplay":
            return _DISCONNECT_HANDOVER_BOT_TIER
        return self._seat_bot_tiers.get(seat, self._bot_tier)

    def _submit_bot_job(self, seat: int, tag: BotJobTag, mask: list[bool]) -> None:
        """Build this seat's `SeatView` and schedule `bots.worker.compute_action` on the right
        bot pool (a `ProcessPoolExecutor` -- the GIL makes a thread pool useless for CPU-bound
        search), returning immediately -- the actual wait lives in `_await_bot_job`, a separate
        task. `seed` is derived from the tag, not an unseeded `random.Random()`, so a given
        decision point's bot output is reproducible. `deadline` is advisory only, derived from
        the same hard `_BOT_JOB_TIMEOUT_SECONDS` `_await_bot_job` actually enforces.

        Tier resolution goes through `_effective_bot_tier`, not `self._bot_tier` directly, so
        disconnect-handover is pinned to T2 regardless of this table's configured tier (see that
        method's docstring -- the one explicit product requirement behind this whole method's
        shape).

        `ORACLE` jobs build their view with `_omniscient_seat_view` (`app/views.py`) instead of
        the normal `seat_view(state, seat)` -- **this is the only call site for that function in
        the entire codebase**; see its docstring, and `tests/test_oracle_containment.py`, which
        pins that structurally. The bot itself is built by `bots/worker.py`'s `_make_bot`, and
        `ORACLE` jobs share `self._bot_pool` like every other tier.
        """
        loop = asyncio.get_running_loop()
        tier = self._effective_bot_tier(seat)
        seed = hash((self.table_id, tag.kind, tag.key, tag.state_version, seat)) & 0xFFFFFFFF
        deadline = time.monotonic() + _BOT_JOB_TIMEOUT_SECONDS

        if tier == BotTier.ORACLE:
            # the only live call site for _omniscient_seat_view (see its docstring for the safety
            # argument) -- unreachable for a real human seat since disconnect-handover forces T2.
            view = _omniscient_seat_view(self.state, seat)
        else:
            claim_deadline_ts = (
                self._claim_deadline_ms.get((tag.key, seat)) if tag.kind == "claim" else None
            )
            turn_deadline_ts = self._turn_deadline_ms.get(seat) if tag.kind == "turn" else None
            view = seat_view(
                self.state,
                seat,
                seat_status=self.seat_status_tuple(),
                names=self.names_tuple(),
                claim_deadline_ts=claim_deadline_ts,
                turn_deadline_ts=turn_deadline_ts,
            )

        future = loop.run_in_executor(
            self._bot_pool, compute_action, view, mask, seed, tier, deadline
        )
        task = asyncio.ensure_future(self._await_bot_job(seat, tag, future, seed, tier))
        self._bot_tasks.add(task)
        task.add_done_callback(self._bot_tasks.discard)

    async def _await_bot_job(
        self, seat: int, tag: BotJobTag, future: asyncio.Future[int], seed: int, tier: str
    ) -> None:
        """Await one submitted job under a hard deadline, then re-enter it through `self.inbox`
        as a `BotResult` -- never applied directly from here, so it still goes through the same
        staleness check and single-writer discipline every other inbox item does.

        On timeout or a worker crash: logs it with the tier, table and seat, applies no
        synthesized default action, and clears the pending tag so the next `_poke_bots()` tick
        retries from scratch. What actually stops a
        stalled turn decision from wedging the table is the independent, seat-level
        `ruleset.turn_seconds` deadline, which races the wall clock regardless of whether any
        particular bot job is in flight.

        Once the worker answers, sleeps a humanising `_BOT_THINK_MIN_SECONDS`-
        `_BOT_THINK_MAX_SECONDS` delay before re-entering the result -- a real tier answers in
        single-digit milliseconds, which otherwise reads as the table racing ahead of anyone
        watching. Sleeping here, in this job's own task, delays only this seat's result. If the
        pending tag goes stale while asleep, the result lands anyway but `_handle_bot_result`
        drops it like any other stale answer.
        """
        started = time.monotonic()
        try:
            aid = await asyncio.wait_for(future, timeout=_BOT_JOB_TIMEOUT_SECONDS)
            server_stats().record_bot_decision(time.monotonic() - started)
            think_seconds = random.Random(seed ^ 0x5A5A5A5A).uniform(
                _BOT_THINK_MIN_SECONDS, _BOT_THINK_MAX_SECONDS
            )
            await asyncio.sleep(think_seconds)
            self.inbox.put_nowait(BotResult(seat=seat, tag=tag, aid=aid))
            return
        except TimeoutError:
            logger.warning(
                "table %s seat %d: %s bot job timed out after %.0fs",
                self.table_id,
                seat,
                tier,
                _BOT_JOB_TIMEOUT_SECONDS,
            )
        except Exception:
            logger.exception("table %s seat %d: %s bot job failed", self.table_id, seat, tier)
        if self._pending_bot.get(seat) == tag:
            del self._pending_bot[seat]

    def _handle_claim_timeout(self, timer_id: int) -> None:
        """One per-seat claim-window timer id popped off `self.deadlines` (`_timer_seat` maps
        it back to `(window_id, seat)`). No-op if stale: unknown id, the window already resolved
        and `self.state` moved on, or this id has been superseded by a reconnect re-arming this
        seat's deadline to a later one -- without that check a reconnecting seat's old deadline
        would fire and auto-Pass them right out from under the fresh window they were just given.

        Otherwise this seat is treated as `Pass` and fed through the same `reduce()` ->
        `_apply_claim_response` -> `resolve_claims` path a real response uses."""
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
        seat held a live, unresolved claim offer at that instant, forfeit it right now,
        immediately, not on the claim-window timeout -- same `Pass` path a real timeout uses.

        Why immediately rather than waiting for `resume()` to re-arm on reconnect:
        `StateSyncPayload.claim_options` carries no `window_id`, so a reconnecting client has
        nothing to render a dialog from or submit a `claim` against even if the server were
        still nominally waiting on this seat -- it would reconnect into a table that looked
        paused with no way to act on the thing pausing it. Forfeiting on disconnect removes the
        offer before any reconnect can observe it.

        No-op if there's no live window, this seat has no offer in it, or it already responded
        (whichever arrives first at `_apply`'s single-writer ordering wins)."""
        window = self.state.claim_window
        if window is None or event.seat in window.responses:
            return
        if not any(o.seat == event.seat for o in window.offers):
            return
        self._apply(Pass(window_id=window.window_id, seat=event.seat))

    def _apply(self, action: Action) -> None:
        """Run one already-authorized `Action` through `reduce()`, publish, and open the
        hand-end hold on `HAND_OVER` -- the common tail shared by a real `Command`, a
        synthesized claim-timeout `Pass`, a synthesized turn-timeout `Discard`, and a pre-armed
        auto-pass.

        Landing on `HAND_OVER` no longer chains straight into `start_next_hand()` the same tick
        -- see `_open_hand_end_window`'s docstring for why the round is held open first. That
        must run before `self._publish(events)` below (it computes this hold's `deadline_ts`,
        which the just-produced `hand_end` frame needs to carry), but the actual advance must
        not run until after `events` is on the wire, or `hand_start`/`deal` would leapfrog it."""
        self.actions.append(action)  # full-game log -- reduce()-bound only
        window = self.state.claim_window
        offered = frozenset(o.seat for o in window.offers) if window is not None else frozenset()
        self.state, events = reduce(self.state, action)
        self.event_id += 1
        advance_immediately = False
        if self.state.phase == Phase.HAND_OVER:
            advance_immediately = self._open_hand_end_window()
        self._publish(events, offered=offered)
        if advance_immediately:
            self._advance_to_next_hand()
        else:
            # refreshed every call, in lockstep with self.state. When advance_immediately,
            # _advance_to_next_hand refreshes this itself instead, against the post-advance state.
            self._turn_draw_tile = _turn_draw_tile_for_current_turn(events, self.state)

    def _open_hand_end_window(self) -> bool:
        """Open the `HAND_OVER` hold: every hand end holds the table at `HAND_OVER` for up to
        `ruleset.hand_end_seconds`, or until every seat acks, whichever first. A clock/session
        concern, so it lives entirely here -- `mahjong_core.engine`/`state` are untouched.

        Seeds the ack set with every seat whose `SeatBinding.status` is `bot`/`autoplay` -- no
        human present to click dismiss. A `disconnected` seat is deliberately not pre-seeded --
        it's still someone's seat, it just rides out the same hold as everyone else.

        Also computes this hold's `deadline_ts` unconditionally, even when about to advance
        immediately, so the just-published `hand_end` frame always carries it.

        Returns whether every seat is already acked, in which case the caller advances
        immediately once this tick's own events are on the wire. Otherwise arms
        `_arm_hand_end_timer`."""
        self._hand_end_hand_no = self.state.hand_no
        self._hand_end_acked = {
            seat
            for seat, binding in enumerate(self.seat_bindings)
            if binding is not None and binding.status in ("bot", "autoplay")
        }
        duration = self.state.ruleset.hand_end_seconds
        self._hand_end_deadline_ms = now_ms() + round(duration * 1000)
        # an all-bot table rides out the full hold: nobody seated would dismiss it, and it's
        # the spectators' only chance to read the result
        if len(self._hand_end_acked) >= 4 and not self.all_bots:
            return True
        self._arm_hand_end_timer()
        return False

    def _advance_to_next_hand(self) -> None:
        """The actual `start_next_hand()` transition -- deferred out of `_apply` so it can run
        once the hand-end hold actually closes (all-acked or timeout), not unconditionally the
        same tick `HAND_OVER` is reached."""
        self.state, more_events = start_next_hand(self.state)
        self.event_id += 1
        self._publish(more_events)
        # a hand boundary -- process_one()'s tail wakes a pending wait_for_shutdown_boundary
        # only after any GAME_OVER persist below has actually finished, never before.
        self._boundary_this_tick = True
        self._turn_draw_tile = _turn_draw_tile_for_current_turn(more_events, self.state)
        if self.state.phase == Phase.AWAIT_ACTION:
            # start_next_hand() emits no Event, so there's nothing to redact into hand_start/deal --
            # this Table synthesizes both here, same as the ready-triggered hand 1 start.
            self._publish_hand_start_and_deal()

    def _arm_hand_end_timer(self) -> None:
        """Give the table a single fresh `TimerHeap` entry, `ruleset.hand_end_seconds` from
        right now -- whole-table (one active id), not per-seat like claims: just "wait for N of
        4". `deadline_ts` itself is computed by the caller (`_open_hand_end_window`); this
        method only arms the heap entry."""
        loop = asyncio.get_running_loop()
        duration = self.state.ruleset.hand_end_seconds
        deadline = loop.time() + duration
        timer_id = next(self._timer_seq)
        self.deadlines.add(deadline, timer_id)
        self._active_hand_end_timer_id = timer_id

    def _handle_hand_end_timeout(self, timer_id: int) -> None:
        """The hand-end hold's deadline popped with the table still waiting on at least one
        seat's ack. No-op if stale: unknown/superseded id, or the hold already closed some
        other way (all-acked) before this fired."""
        if self._active_hand_end_timer_id != timer_id:
            return
        if self.state.phase != Phase.HAND_OVER:
            return
        self._advance_to_next_hand()

    def _arm_claim_timer(self) -> None:
        """Arm a deadline the moment `self.state.claim_window` shows a new `window_id`, called
        after every event `process_one()` handles. Idempotent per window: `_armed_window_id`
        stops a window still accumulating responses across several calls from getting a fresh,
        later deadline each time.

        Arms one heap entry per offered seat (`_arm_seat_claim_timer`), not one shared entry --
        a reconnecting seat's deadline has to be movable without touching anyone else's.

        Also the one place `claim_offer` gets sent (`_send_claim_offers`): it needs the real
        deadlines this method just armed anyway, so folding both into one idempotent,
        once-per-window call avoids a second tracker.
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
        arm (every offered seat at once) and a mid-window reconnect re-arm (one seat only) go
        through. Recorded in `_timer_seat`/`_active_seat_timer` so `_handle_claim_timeout` can
        tell a superseded entry from a live one.

        Not itself a `_wake()` call site: the initial window-open arm always runs synchronously
        inside an already-executing `process_one()` tick, so the next `_next()` call picks up
        the fresh heap entry naturally. A mid-window re-arm runs from `resume()`, outside this
        table's loop, where that guarantee doesn't hold -- it calls `_wake()` itself.
        """
        loop = asyncio.get_running_loop()
        duration = self.state.ruleset.claim_seconds
        deadline = loop.time() + duration
        timer_id = next(self._timer_seq)
        self.deadlines.add(deadline, timer_id)
        self._timer_seat[timer_id] = (window_id, seat)
        self._active_seat_timer[(window_id, seat)] = timer_id
        # deadline above is monotonic loop time; the wire needs server epoch ms -- duration
        # converts directly since it's the same elapsed span in both clocks.
        self._claim_deadline_ms[(window_id, seat)] = now_ms() + round(duration * 1000)

    def _rearm_seat_claim_timer(self, seat: int) -> bool:
        """If `seat` holds a live, unresolved claim offer, give it a fresh full-length window
        measured from right now -- every other offered seat's deadline is untouched, since each
        has its own heap entry. Returns whether a re-arm actually happened, so `resume()` knows
        whether to also push a fresh `claim_offer`. No-op (`False`) if there's no live window,
        this seat has no offer in it, or it already responded.

        Without this re-arm, a seat that disconnects partway through its window and reconnects
        late would get only whatever sliver of the original deadline is left, not a fair chance
        to respond.
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
        """Unicast `claim_offer` to every offered seat, except one whose pre-arm toggle already
        decided this offer: `no_calls`, or `auto_pass_chow` when every option is a chow. A
        win-eligible offer is never auto-resolved this way regardless of pre-arm -- it always
        gets a real `claim_offer`. Re-checks `self.state.claim_window` every iteration: a
        pre-armed `Pass` submitted mid-loop can close the window early."""
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
        `_claim_deadline_ms` -- shared by `_send_claim_offers` and `resume()`. Requires a live
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
        """`tiles` names only the claimer's own tiles, excluding the claimed discard -- echoing
        the full meld here made every disambiguated claim fail `_pick_claim_meld` as
        `illegal`."""
        options: list[dict[str, Any]] = []
        if offer.can_win:
            options.append({"kind": "win"})
        for meld in offer.melds:
            own = [t for t in meld.tiles if t != claimed]
            options.append({"kind": CLAIM_KIND_WIRE[meld.kind], "tiles": own})
        options.append({"kind": "pass"})
        return options

    def _publish_hand_start_and_deal(self) -> None:
        """Synthesize `hand_start` (broadcast) and `deal` (per-seat) -- these have no backing
        `Event`. Called once the table actually starts and once per later hand."""
        state = self.state
        hand_start: dict[str, Any] = {
            "t": "hand_start",
            "hand_no": state.hand_no,
            "prevailing": state.prevailing.name,
            "dealer": state.dealer,
            "seats": list(self.seat_status_tuple()),
        }
        commit = self._seed_commit()
        if commit is not None:
            hand_start["seed_commit"] = commit
        self._broadcast_wire(hand_start)
        for seat in range(4):
            self.publish_to_seat(
                seat,
                {
                    "t": "deal",
                    "your_hand": list(state.seats[seat].concealed),
                    "counts": {s: len(state.seats[s].concealed) for s in range(4)},
                    "flowers": [[tile_code(f) for f in s.flowers] for s in state.seats],
                    "wall_remaining": len(state.wall.tiles),
                },
            )
        if self.settings.spectators_see_hands:
            # spectators get no `deal`; a fresh snapshot is how they learn the new hands
            for session_id in list(self.spectators):
                self.publish_to_spectator(session_id, self.state_sync_wire(None))

    def _publish_turn_if_active(self) -> None:
        """Synthesize `turn` whenever `self.state` is sitting in `AWAIT_ACTION` after something
        changed it. No backing `Event`; every landing in `AWAIT_ACTION` is a genuinely new
        decision point, so this is also the one and only call site for `_arm_turn_timer` -- no
        idempotency guard needed.

        `legal` is unicast to the acting seat only; spectators get the same public
        `{seat, phase, deadline_ts}` shape every non-acting seat does, never `legal` (it would
        name the acting seat's own concealed tile ids).
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
        """The two fields `redact_event` alone can't derive from `state` in general:
        `discard.tile`/`pool_index` (this Table still holds `state` from immediately after the
        `reduce()` call, before a later command could claim that discard away) and
        `hand_end.deadline_ts` (already computed by `_open_hand_end_window`). Identical for
        every recipient, so computed once per event, not once per recipient."""
        if isinstance(event, Discarded):
            pool = self.state.seats[event.seat].discards
            wire["tile"] = tile_code(tile_id_type(event.tile_id))
            wire["pool_index"] = len(pool) - 1
        if isinstance(event, HandEnded):
            wire["deadline_ts"] = self._hand_end_deadline_ms
            reveal = self._fairness_reveal()
            if reveal is not None:
                wire["fairness"] = reveal

    def _seed_commit(self) -> str | None:
        """The current hand's `seed_commit`, or `None` off `provable_fairness`. The nonce is
        minted on first use per hand, so `hand_start` and a later `state_sync` agree."""
        if not self.state.ruleset.provable_fairness:
            return None
        if self._fairness_nonce is None or self._fairness_nonce[0] != self.state.hand_no:
            self._fairness_nonce = (self.state.hand_no, new_nonce())
        return seed_commit(self.state.hand_seed, self._fairness_nonce[1])

    def _fairness_reveal(self) -> dict[str, str] | None:
        """`hand_end.fairness` for the hand `self.state` is on; never `game_seed`."""
        if self._seed_commit() is None:
            return None
        assert self._fairness_nonce is not None
        return fairness_reveal(self.state.hand_seed, self._fairness_nonce[1])

    def _publish(self, events: list[Event], *, offered: frozenset[int] = frozenset()) -> None:
        """`redact_event()` per recipient seat, published via `publish_to_seat`, plus one more
        spectator-redacted pass fanned out to every registered spectator session -- skipped
        entirely when there are no spectators. A `HandEnded` also gets a broadcast `score`
        alongside it.

        `offered` is the seats the window this tick resolved had offered a claim to. A
        `ClaimResolved` reaches them unheld (it closes their prompt); a no-claim one reaches
        nobody else, which would otherwise learn a window existed. A `Discarded`, or a kong
        that could be robbed (`_kong_may_be_robbed`), starts a claim hold after its own frames,
        so the draw behind it is held whether or not a window opened (`_begin_hold`)."""
        for event in events:
            if isinstance(event, ClaimResolved):
                self._publish_claim_resolved(event, offered)
                continue
            for seat in range(4):
                wire = redact_event(self.state, seat, event)
                self._augment_event_wire(wire, event)
                self.publish_to_seat(seat, wire)
            if self.spectators:
                spectator_wire = redact_event(
                    self.state, None, event, reveal_hands=self.settings.spectators_see_hands
                )
                self._augment_event_wire(spectator_wire, event)
                self._broadcast_to_spectators(spectator_wire)
            if isinstance(event, HandEnded):
                self._record_hand_history(event)
                self._broadcast_wire(
                    {"t": "score", "totals": {s: self.state.seats[s].score for s in range(4)}}
                )
            if isinstance(event, Discarded) or (
                isinstance(event, MeldFormed) and self._kong_may_be_robbed(event.meld.kind)
            ):
                self._begin_hold()

    def _kong_may_be_robbed(self, kind: MeldKind) -> bool:
        """Whether a self-declared kong of `kind` could open a rob window under this ruleset
        (`mahjong_core.engine._kong_rob_offers`) -- the kongs a claim hold has to cover."""
        ruleset = self.state.ruleset
        if not ruleset.kong_rob_enabled:
            return False
        if kind == MeldKind.ADDED_KONG:
            return True
        return kind == MeldKind.CONCEALED_KONG and ruleset.concealed_kong_robbable

    def _publish_claim_resolved(self, event: ClaimResolved, offered: frozenset[int]) -> None:
        private = event.winning_seat is None
        for seat in range(4):
            if seat in offered or not private:
                self.publish_to_seat(
                    seat, redact_event(self.state, seat, event), bypass_hold=seat in offered
                )
        if not private and self.spectators:
            self._broadcast_to_spectators(redact_event(self.state, None, event))

    def _record_hand_history(self, event: HandEnded) -> None:
        """Snapshot this just-ended hand into `self._hand_history`. Called from `_publish` while
        `self.state` is still this hand's state -- `dealer`/`prevailing`/`seats[winner].melds`
        all get reset by the `hand_start` that follows, so this is the only point they're still
        readable. Reuses `redact_event`'s own `HandEnded` redaction for every field but
        `winner_melds` rather than re-deriving the same logic a second time."""
        hand_end_wire = redact_event(self.state, None, event)
        winner = cast("int | None", hand_end_wire["winner"])
        self._hand_history.append(
            HandHistoryRecord(
                hand_no=cast("int", hand_end_wire["hand_no"]),
                outcome=cast("str", hand_end_wire["outcome"]),
                winner=winner,
                win_type=cast("str | None", hand_end_wire["win_type"]),
                discarder=cast("int | None", hand_end_wire["discarder"]),
                faan=cast("int | None", hand_end_wire["faan"]),
                faan_breakdown=cast("dict[str, int] | None", hand_end_wire["faan_breakdown"]),
                points=cast("int | None", hand_end_wire["points"]),
                payments=cast("dict[int, int] | None", hand_end_wire["payments"]),
                revealed=cast("bool", hand_end_wire["revealed"]),
                winning_hand=cast("list[int] | None", hand_end_wire["winning_hand"]),
                dealer=self.state.dealer,
                prevailing=self.state.prevailing.name,
                winner_melds=self.state.seats[winner].melds if winner is not None else None,
                fairness=self._fairness_reveal(),
            )
        )

    async def _persist_game_record(self) -> None:
        """`Phase.GAME_OVER` persistence -- a no-op if this `Table` was never given a
        `session_factory`. `players` is each seat's real `SeatBinding.name`; `None` for a seat
        nobody ever joined by a human -- a `bot` seat gets `None` here too, not its synthetic
        display name, which would otherwise misleadingly read as a real player. Only ever called
        once, from `process_one()`'s own tail."""
        if self._session_factory is None:
            return
        players = [
            b.name if b is not None and b.status != "bot" else None for b in self.seat_bindings
        ]
        async with self._session_factory() as session:
            await save_game_record(session, self.state, self.actions, players=players)

    async def wait_for_shutdown_boundary(self, timeout: float) -> bool:
        """Block until this table reaches a hand boundary -- a fresh hand dealt, or the game
        ends -- or `timeout` seconds elapse, whichever is first. Returns whether a boundary was
        actually reached; `False` means the grace window elapsed first and the caller abandons
        this table, same as a crash, but warned.

        A table whose GAME_OVER persist has actually finished (`_game_over_persisted`) returns
        `True` immediately -- nothing left to abandon. A table already at `Phase.GAME_OVER` but
        not yet persisted is, by construction, one whose final `process_one()` tick is suspended
        inside the persist call -- that wait ignores the caller's `timeout` entirely (waiting out
        an already-in-flight persist is a durability guarantee, not the boundable "let the hand
        finish" allowance `timeout` exists for), and is unbounded on purpose: `process_one()`'s
        tail catches a failing persist rather than letting it propagate, so the window this waits
        on can only ever be exited, never abandoned with nothing left alive to set it.

        A fresh `asyncio.Event` is installed for the duration of this call, not a long-lived one
        reused across calls: reusing one risks a stale `.set()` from an earlier boundary being
        mistaken for the one this drain is waiting for.
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
