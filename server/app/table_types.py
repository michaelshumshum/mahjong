"""Data types shared between `Table` and its callers: seat bindings, inbox commands, ring-buffer
frames, bot-job tags, and per-table settings. Logic lives in `app/table.py`."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from app.idempotency import IdempotencyCache
from mahjong_core.actions import Action

__all__ = [
    "BotJobTag",
    "BotResult",
    "Command",
    "Envelope",
    "SeatBinding",
    "SeatDisconnected",
    "SeatStatus",
    "TableSettings",
    "WireSeatStatus",
]

type SeatStatus = Literal["connected", "disconnected", "autoplay", "bot"]

# `empty` has no `SeatBinding` counterpart -- only `seat_status_tuple()` reports it, for a
# `None` slot in `Table.seat_bindings`.
type WireSeatStatus = Literal["connected", "disconnected", "autoplay", "bot", "empty"]


@dataclass(frozen=True, slots=True)
class TableSettings:
    spectators_see_hands: bool = False


@dataclass
class SeatBinding:
    """One seat's session binding. Lives on `Table`, not `Session`: idempotency is scoped per
    seat binding, not per socket, so it has to survive a reconnect swapping out the socket
    underneath it.

    `send` is the live connection's push callback; `ready`/`no_calls`/`auto_pass_chow` are the
    lobby/pre-arm state. `status` (`connected`/`disconnected`/`autoplay`/`bot` -- `empty` never
    applies here; that's `seat_status_tuple()`'s report for a `None` slot instead) transitions
    via `mark_disconnected`/`reconnect`/the disconnect-grace timer.

    `bot` (practice mode, `_bind_bot_seat`) is the other way a `SeatBinding` comes to exist:
    a seat bound to a bot from table construction, never a human `join`. Reuses this exact
    dataclass (`send` a no-op, `ready=True`) rather than a parallel tracking structure, so
    `_poke_bots()` drives it through the identical path an `autoplay` seat uses. Unlike
    `autoplay`, `bot` is never reached by `mark_disconnected` and `reconnect` refuses to hijack
    it (`SeatTakenError`) -- there is no human occupant to hand it back to.

    `turn_timeout_strikes` (architecture.md §8: three strikes -> `AUTOPLAY` for the rest of
    the game) is never reset anywhere -- that omission *is* the "for the rest of the game"
    policy, since this binding is one long-lived object for the table's entire game.

    `name` is this seat's resolved guest display name -- set once at `join` or `_bind_bot_seat`
    and never touched again (a `hello` reconnect never resends it).

    `reconnect_secret` (architecture.md §2.1) is a random per-seat credential, minted once
    and handed back exactly once, in `join`'s own `ack`. Every later `hello{seat, secret}` must
    present it back; `reconnect()` compares with `secrets.compare_digest` and refuses the
    reclaim on any mismatch (`SeatAuthError`). A bot seat's secret is never handed to anyone.
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
    reconnect_secret: str = field(default_factory=lambda: secrets.token_urlsafe(16))


@dataclass(frozen=True)
class Command:
    """One already-validated `(seat, Action)` pair flowing through `Table.inbox`. Most
    claim-window `Action`s already carry their own `seat` field; `Discard`/`DeclareWin`/
    `DeclareConcealedKong`/`DeclareAddedKong` don't (`engine._acting_seat` reads `state.turn`
    instead), so `Command.seat` is the only place the claimed acting seat is recorded for them
    before `_authorize` checks it against `state.turn`.
    """

    seat: int
    action: Action


@dataclass(frozen=True)
class Envelope:
    """One already-redacted wire frame in a seat's ring buffer, stamped with that stream's own
    `seq` (per-seat, dense, gapless -- never per-table, never derived from `event_id`)."""

    seq: int
    event: dict[str, object]


@dataclass(frozen=True)
class BotJobTag:
    """What a submitted bot job was computed against. `state_version` is `Table.event_id` at
    submission time -- `self.state` is provably unchanged from what the job saw as long as
    `event_id` hasn't moved, since `_apply` is the only place either ever changes, together.
    `key` disambiguates what kind of decision this was for: the acting seat for a `turn`
    decision, or the `window_id` for a `claim` decision."""

    kind: Literal["turn", "claim"]
    key: int
    state_version: int


@dataclass(frozen=True)
class BotResult:
    """A `ProcessPoolExecutor` worker's answer, re-entering through `Table.inbox` exactly like a
    real `Command` -- `tag` is compared against `Table._pending_bot[seat]` and dropped silently
    if it no longer matches.

    `aid` is a bare action id, not a concrete `Action` -- a worker process never receives
    `GameState`, so `_handle_bot_result` does the `decode_action(aid, state, seat)` step here,
    against the real `GameState` this process already holds."""

    seat: int
    tag: BotJobTag
    aid: int


@dataclass(frozen=True)
class SeatDisconnected:
    """A seat's live socket just closed (`mark_disconnected`, called directly from `Session`,
    outside this table's own loop). Routed through `Table.inbox` rather than forfeiting the
    seat's claim inline: forfeiting means calling `_apply()`, which mutates `self.state`, and
    server/AGENTS.md reserves every `GameState` mutation for this table's own task processing
    its inbox in order. Handled by `_handle_seat_disconnected`."""

    seat: int
