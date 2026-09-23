"""WS endpoint speaking the envelope protocol (docs/02-protocol.md §1) -- a real `Session` per
connection that joins a `Table` and exchanges gameplay messages (docs/05-roadmap.md M3 sub-task
4). Extends M0's hello/ping stub in place rather than replacing it: `Session` still owns the
connection loop, still validates against `AnyMessage`, still keeps hello/ping/pong exactly as
M0 left them (see `Session.handle`'s docstring for why those two intentionally do *not* move
onto the per-seat `seq` stream this sub-task adds for everything else).

**Table lookup is `app/registry.py`'s `TableRegistry`** (M3 sub-task 6 -- replaces this module's
former bare `dict[str, Table]`, which its own docstring already flagged as a stand-in: "a real
`TableRegistry` with matchmaking is a later sub-task"). Still one process-wide, module-level
singleton (`_registry` below) -- `TableRegistry` itself stays an in-process dict per
docs/00-architecture.md §6, not a new abstraction layer. `?ruleset=` picks a
`mahjong_core.presets.RULESET_PRESETS` key (default `DEFAULT_PRESET_ID`) for the table's
`RuleSet`, or `custom` to take a full `RuleSet.from_dict`-shaped JSON body from `?rules=`
instead -- see `_resolve_ruleset_query`. This is a fallback path for a direct WS connect to an
unclaimed table id, not the primary one: a real client creates the table via `POST /tables`
(`app/main.py`'s `create_table`), which resolves the ruleset and mints the id in one request and
is what these query params' resolution logic (`mahjong_core.presets.resolve_ruleset`) is shared
with. Only meaningful the first time a given `table` id is created, same as `?practice=` below
(`TableRegistry.get_or_create`'s own note): an existing table's ruleset was already decided at
its own construction. `?seed=` exists only so tests can pin a table's deal. `?practice=true` (M4.5,
docs/05-roadmap.md) binds seats 1-3 to bots at table creation, before any human ever joins --
see `app/table.py`'s `Table.__init__(practice=...)`/`_bind_bot_seat`; only meaningful the first
time a given `table` id is created (`TableRegistry.get_or_create`'s own note). `?spectate=true`
("Spectating" sub-task, docs/05-roadmap.md M5) registers this connection as an active spectator
at accept time -- see `app/table.py`'s `Table.register_spectator` for why this is an explicit,
per-connection opt-in rather than the literal passive default docs/02-protocol.md §2 describes.

**DB wiring + graceful shutdown (a later sub-task).** `_registry` is no longer a fixed
module-import-time singleton: `reset_registry()` swaps in a fresh `TableRegistry` (optionally
carrying a DB session factory) and `app/main.py`'s `lifespan` calls it on every ASGI startup --
see `reset_registry`'s own docstring for why a fresh instance per startup matters, not just a
mutated one. `ws_endpoint` itself refuses every new connection once `_registry.draining` is set
(docs/00-architecture.md §8.1 step 1); `registry()` is the read accessor `/healthz` uses for the
same flag.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from concurrent.futures import Executor
from typing import Any, Protocol

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import protocol as proto
from app.outbox import BoundedOutbox
from app.registry import TableRegistry
from app.table import (
    NotHostError,
    SeatAuthError,
    SeatNotBoundError,
    SeatTakenError,
    Table,
    TableAlreadyStartedError,
    TableFullError,
)
from mahjong_core.actions import (
    Action,
    ClaimChow,
    ClaimKong,
    ClaimPung,
    ClaimWin,
    DeclareAddedKong,
    DeclareConcealedKong,
    DeclareWin,
    Pass,
)
from mahjong_core.actions import Discard as DiscardAction
from mahjong_core.config import RuleSet
from mahjong_core.melds import Meld, MeldKind, legal_self_melds
from mahjong_core.presets import DEFAULT_PRESET_ID, resolve_ruleset
from mahjong_core.tiles import TileId

router = APIRouter()

_adapter: TypeAdapter[object] = TypeAdapter(proto.AnyMessage)

_OUTBOX_MAXSIZE = 64  # docs/00-architecture.md "Outbound backpressure" / 02-protocol.md §9

_registry = TableRegistry()

_CLAIM_WIRE_TO_MELD_KIND = {
    "chow": MeldKind.CHOW,
    "pung": MeldKind.PUNG,
    "kong": MeldKind.EXPOSED_KONG,
}
_DECLARE_WIRE_TO_MELD_KIND = {
    "concealed_kong": MeldKind.CONCEALED_KONG,
    "added_kong": MeldKind.ADDED_KONG,
}


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def get_table(table_id: str) -> Table | None:
    """Test/introspection hook onto the registry -- not part of the wire protocol."""
    return _registry.get(table_id)


def registry() -> TableRegistry:
    """Accessor for `app/main.py`'s `lifespan` (wiring a DB session factory at startup, running
    the graceful-shutdown drain at shutdown), `/healthz` (reading `.draining`), and `/tables`."""
    return _registry


def reset_registry(
    *,
    bot_pool: Executor | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> TableRegistry:
    """Install a fresh `TableRegistry` as this module's singleton. `app/main.py`'s `lifespan`
    calls this on every ASGI startup -- a real process, or one `TestClient(app)` context in
    tests -- so each server lifetime gets its own registry: `draining` always starts `False`,
    and a previous lifetime's tables/background tasks never leak into this one's shutdown drain
    (docs/00-architecture.md §8.1; see `app/registry.py`'s module docstring)."""
    global _registry
    _registry = TableRegistry(bot_pool=bot_pool, session_factory=session_factory)
    return _registry


def _resolve_ruleset_query(ruleset: str, rules: str | None) -> RuleSet:
    """`?ruleset=`/`?rules=` on `/ws` -> the `RuleSet` a new table should construct with. This is
    the WS-connect fallback path -- the primary, one-request path is `POST /tables`
    (`app/main.py`'s `create_table`), which already gets `rules` as a structured JSON body rather
    than URL-encoded text and calls `mahjong_core.presets.resolve_ruleset` directly. A direct WS
    connect to an unclaimed table id skips that REST call entirely (matching this endpoint's
    existing "no table API needed, auto-create on first connect" posture,
    docs/03-frontend.md's "/table/[id] wiring") and needs its own text -> dict step first: `rules`
    arrives as raw query-string JSON, so a malformed/non-JSON value is folded into
    `resolve_ruleset`'s already-lenient fallback (unknown preset id, failed `RuleSet` validation)
    rather than treated separately."""
    parsed: dict[str, Any] | None = None
    if rules is not None:
        try:
            parsed = json.loads(rules)
        except json.JSONDecodeError:
            parsed = None
    return resolve_ruleset(ruleset, parsed)


def _get_or_create_table(
    table_id: str, seed: int | None, practice: bool, ruleset: str, rules: str | None
) -> Table:
    return _registry.get_or_create(
        table_id,
        _resolve_ruleset_query(ruleset, rules),
        seed=seed,
        require_ready=True,
        practice=practice,
    )


class _IdempotentMessage(Protocol):
    """Structural type for `_dispatch`'s `msg` param -- every post-join `ClientMessage` variant
    (`Ready`/`Discard`/`Claim`/`Declare`/`Auto`/`HandEndAck`) has an `id` and a `d`
    payload model, but they share no common base beyond `proto.Envelope`, which doesn't type
    `d` at all (each subclass narrows it separately)."""

    id: str | None

    @property
    def d(self) -> BaseModel: ...


def _pick_meld(candidates: list[Meld], tiles: list[int] | None) -> Meld | None:
    """Exact match against a client-supplied tile set, or the sole candidate if there's only
    one and the client didn't bother disambiguating."""
    if tiles is not None:
        wanted = set(tiles)
        for meld in candidates:
            if set(meld.tiles) == wanted:
                return meld
        return None
    return candidates[0] if len(candidates) == 1 else None


def _pick_claim_meld(
    candidates: list[Meld], claimed_tile: int, tiles: list[int] | None
) -> Meld | None:
    """Same idea as `_pick_meld`, but a claim's `tiles` disambiguator excludes the claimed
    discard itself (02-protocol.md §2: "tiles disambiguates a chow (e.g. 4-5 vs 5-6 for a 6)"
    -- the client names its own two tiles, not the discard)."""
    if tiles is not None:
        wanted = set(tiles)
        for meld in candidates:
            own = {t for t in meld.tiles if t != claimed_tile}
            if own == wanted:
                return meld
        return None
    return candidates[0] if len(candidates) == 1 else None


class Session:
    """One connection. Pre-`join`, frames go out on a local per-connection counter (exactly
    M0's behavior -- `hello`/`ping` never move off it, see `handle`). Once `join` binds a seat,
    every gameplay response (`ack`, and anything `Table` publishes) is routed through that
    seat's own `Table.publish_to_seat`, which owns the real per-seat `seq` (docs/02-protocol.md
    §1 D1)."""

    def __init__(self, websocket: WebSocket, table: Table) -> None:
        self.ws = websocket
        self.table = table
        self.session_id = str(uuid.uuid4())
        self.seat: int | None = None
        self._local_seq = 0
        self.outbox = BoundedOutbox(maxsize=_OUTBOX_MAXSIZE, resync=self._resync)

    # --- outbound plumbing ---------------------------------------------------------------

    def _resync(self) -> None:
        """`BoundedOutbox`'s overflow callback (docs/02-protocol.md §9) -- re-publishes a fresh
        `state_sync` through `Table`, which allocates a real, correctly-ordered `seq` for it
        (see `app/outbox.py`'s module docstring for why this can't fabricate one locally). A
        registered spectator (`self.seat is None`) gets the spectator-shaped equivalent
        (`Table.publish_to_spectator`/`state_sync_wire(None)`) -- a no-op if this session was
        never registered as one (`?spectate=true`), same tolerance `publish_to_spectator`
        already documents."""
        if self.seat is not None:
            self.table.publish_to_seat(self.seat, self.table.state_sync_wire(self.seat))
        else:
            self.table.publish_to_spectator(self.session_id, self.table.state_sync_wire(None))

    def _push(self, seq: int, wire: dict[str, Any]) -> None:
        """Registered with `Table` as this seat's `SeatBinding.send` once joined."""
        t = wire["t"]
        d = {k: v for k, v in wire.items() if k != "t"}
        self.outbox.push({"v": 1, "t": t, "seq": seq, "ts": _now_ms(), "d": d})

    def _send_local(self, t: str, payload: dict[str, Any]) -> None:
        """Pre-join (or join-failure) frames only: M0's original per-connection counter, never
        the per-seat stream (there is no seat yet)."""
        self._local_seq += 1
        self.outbox.push({"v": 1, "t": t, "seq": self._local_seq, "ts": _now_ms(), "d": payload})

    def _ack(
        self,
        msg: _IdempotentMessage,
        *,
        ok: bool,
        error: str | None = None,
        reconnect_secret: str | None = None,
    ) -> None:
        if msg.id is None:
            return  # ack is keyed on id (02-protocol.md §1) -- no id, nothing to acknowledge
        payload: dict[str, Any] = {"id": msg.id, "ok": ok}
        if error is not None:
            payload["error"] = error
        if reconnect_secret is not None:
            payload["reconnect_secret"] = reconnect_secret
        if self.seat is not None:
            self.table.publish_to_seat(self.seat, {"t": "ack", **payload})
        else:
            self._send_local("ack", payload)

    async def send_bad_frame(self, message: str) -> None:
        self._send_local("error", {"code": "bad_frame", "message": message})

    # --- dispatch --------------------------------------------------------------------------

    async def handle(self, message: object) -> None:
        """`ping` is handled exactly as M0 did -- a connection-local `pong`, no `ack`, no
        per-seat `seq` -- since it isn't one of the gameplay intents this sub-task's
        `ack`/idempotency contract covers (02-protocol.md §1's `ack` line: "client->server
        intents carrying an id"; the M0 test suite's `ping` already carries an `id` and expects
        a bare `pong`, not an `ack`, so unifying it onto the per-seat stream is left to whoever
        needs it). `hello` with no `seat` is the same M0 no-op preceding `join`; `hello` with a
        `seat` is M3 sub-task 5's reconnect handshake -- see `_handle_hello`."""
        if isinstance(message, proto.Hello):
            await self._handle_hello(message)
            return
        if isinstance(message, proto.Ping):
            self._send_local("pong", {"t0": message.d.t0, "t1": _now_ms()})
            return
        if isinstance(message, proto.Join):
            await self._handle_join(message)
            return
        if isinstance(message, proto.Ready):
            await self._dispatch(message, self._apply_ready)
            return
        if isinstance(message, proto.StartWithBots):
            await self._dispatch(message, self._apply_start_with_bots)
            return
        if isinstance(message, proto.HandEndAck):
            await self._dispatch(message, self._apply_hand_end_ack)
            return
        if isinstance(message, proto.Discard):
            await self._dispatch(message, self._apply_discard)
            return
        if isinstance(message, proto.Claim):
            await self._dispatch(message, self._apply_claim)
            return
        if isinstance(message, proto.Declare):
            await self._dispatch(message, self._apply_declare)
            return
        if isinstance(message, proto.Auto):
            await self._dispatch(message, self._apply_auto)
            return
        # every remaining `AnyMessage` member is server->client (Pong/Error/StateSync/...) --
        # a client sending one parses successfully and is ignored, not rejected (same lenient
        # wrong-direction handling M0's own comment described).

    async def _handle_hello(self, msg: proto.Hello) -> None:
        """`hello{last_seq, seat, secret}` on an already-bound seat is 02-protocol.md §2's
        reconnect path ("a reconnecting player doesn't re-join... hello{last_seq} on an
        already-bound seat reclaims it directly"). `seat` is still client-asserted (which seat),
        but `secret` -- the one-time credential that seat's own `join` ack returned
        (`HelloPayload`/`AckPayload` docstrings) -- is checked against `SeatBinding.
        reconnect_secret` before the reclaim happens (00-architecture.md §2.1); there is still no
        account system behind it, only proof of having been handed this seat's `join` ack.
        `d.seat is None` is the unchanged M0 no-op (a bare `hello` ahead of a fresh `join`)."""
        if msg.d.seat is None:
            return
        if self.seat is not None:
            self._send_local(
                "error", {"code": "already_joined", "message": "connection already bound"}
            )
            return
        try:
            was_disconnected = self.table.reconnect(
                msg.d.seat, self.session_id, self._push, msg.d.secret
            )
        except SeatNotBoundError:
            self._send_local(
                "error", {"code": "no_such_seat", "message": f"seat {msg.d.seat} is not bound"}
            )
            return
        except SeatTakenError:
            # M4.5 practice mode: seat is bound to a bot from table creation, never a human --
            # there's no prior human occupant for this hello{seat} to reclaim (Table.reconnect's
            # own docstring). Same wire error `join` gives a seat someone else already holds.
            self._send_local(
                "error", {"code": "seat_taken", "message": f"seat {msg.d.seat} is a bot seat"}
            )
            return
        except SeatAuthError:
            self._send_local(
                "error", {"code": "bad_secret", "message": f"wrong secret for seat {msg.d.seat}"}
            )
            return
        self.seat = msg.d.seat
        self.table.resume(msg.d.seat, msg.d.last_seq, announce_reconnect=was_disconnected)

    async def _handle_join(self, msg: proto.Join) -> None:
        if self.seat is not None:
            self._ack(msg, ok=False, error="already_joined")
            return
        try:
            seat = self.table.join(self.session_id, self._push, seat=msg.d.seat, name=msg.d.name)
        except SeatTakenError:
            self._ack(msg, ok=False, error="seat_taken")
            return
        except TableFullError:
            self._ack(msg, ok=False, error="table_full")
            return
        self.seat = seat
        binding = self.table.seat_bindings[seat]
        assert binding is not None
        self._ack(msg, ok=True, reconnect_secret=binding.reconnect_secret)

    # --- idempotent gameplay intents (02-protocol.md §1/§2) ---------------------------------

    async def _dispatch(self, msg: _IdempotentMessage, apply: Any) -> None:
        """Shared idempotency + ack wrapper for every post-join intent. `apply(seat, d)` returns
        `(ok, error)`; idempotency is scoped to the seat *binding* (`SeatBinding.idempotency`,
        not this `Session`) per 02-protocol.md §1, so it survives this connection.

        `ok=True` here means "accepted for processing", not "guaranteed legal" -- `Table`'s own
        `_authorize` silently drops a well-formed but currently-illegal `Command` (unchanged
        M2/M3 behavior); this layer's job is the `id`/ack contract, not re-deriving game
        legality `Table` already owns. `Discard`/`Ready`/`Auto` are always structurally
        applyable; `Claim`/`Declare` can fail to even construct an `Action` (an unknown
        `window_id`, an unmatched disambiguator) and get `ok=False, error="illegal"` without
        ever reaching `Table.submit`.
        """
        if self.seat is None:
            self._send_local("error", {"code": "not_joined", "message": "join a seat first"})
            return
        binding = self.table.seat_bindings[self.seat]
        assert binding is not None  # self.seat is only ever set once Table.join bound it
        payload = msg.d.model_dump()
        if msg.id is not None:
            is_retry, ok, error = binding.idempotency.check(msg.id, payload)
            if is_retry:
                self._ack(msg, ok=ok, error=error)
                return
        ok, error = apply(self.seat, msg.d)
        if msg.id is not None:
            binding.idempotency.record(msg.id, payload, ok=ok, error=error)
        self._ack(msg, ok=ok, error=error)

    def _apply_ready(self, seat: int, _d: proto.ReadyPayload) -> tuple[bool, str | None]:
        self.table.mark_ready(seat)
        return True, None

    def _apply_start_with_bots(
        self, seat: int, _d: proto.StartWithBotsPayload
    ) -> tuple[bool, str | None]:
        try:
            self.table.start_with_bots(seat)
        except NotHostError:
            return False, "not_host"
        except TableAlreadyStartedError:
            return False, "already_started"
        return True, None

    def _apply_hand_end_ack(
        self, seat: int, _d: proto.HandEndAckPayload
    ) -> tuple[bool, str | None]:
        self.table.mark_hand_end_ack(seat)
        return True, None

    def _apply_discard(self, seat: int, d: proto.DiscardPayload) -> tuple[bool, str | None]:
        self.table.submit(seat, DiscardAction(tile_id=TileId(d.tile_id)))
        return True, None

    def _apply_auto(self, seat: int, d: proto.AutoPayload) -> tuple[bool, str | None]:
        self.table.set_auto(seat, no_calls=d.no_calls, auto_pass_chow=d.auto_pass_chow)
        return True, None

    def _apply_claim(self, seat: int, d: proto.ClaimPayload) -> tuple[bool, str | None]:
        action = self._build_claim_action(seat, d)
        if action is None:
            return False, "illegal"
        self.table.submit(seat, action)
        return True, None

    def _build_claim_action(self, seat: int, d: proto.ClaimPayload) -> Action | None:
        window = self.table.state.claim_window
        if window is None or window.window_id != d.window_id:
            return None
        if d.choice == "pass":
            return Pass(window_id=d.window_id, seat=seat)
        offer = next((o for o in window.offers if o.seat == seat), None)
        if offer is None:
            return None
        if d.choice == "win":
            return ClaimWin(window_id=d.window_id, seat=seat) if offer.can_win else None
        want_kind = _CLAIM_WIRE_TO_MELD_KIND.get(d.choice)
        if want_kind is None:
            return None
        candidates = [m for m in offer.melds if m.kind == want_kind]
        meld = _pick_claim_meld(candidates, window.tile, d.tiles)
        if meld is None:
            return None
        if want_kind == MeldKind.CHOW:
            return ClaimChow(window_id=d.window_id, seat=seat, meld=meld)
        if want_kind == MeldKind.PUNG:
            return ClaimPung(window_id=d.window_id, seat=seat, meld=meld)
        return ClaimKong(window_id=d.window_id, seat=seat, meld=meld)

    def _apply_declare(self, seat: int, d: proto.DeclarePayload) -> tuple[bool, str | None]:
        action = self._build_declare_action(seat, d)
        if action is None:
            return False, "illegal"
        self.table.submit(seat, action)
        return True, None

    def _build_declare_action(self, seat: int, d: proto.DeclarePayload) -> Action | None:
        if d.kind == "win":
            return DeclareWin()
        want_kind = _DECLARE_WIRE_TO_MELD_KIND[d.kind]
        seat_state = self.table.state.seats[seat]
        candidates = [
            m
            for m in legal_self_melds(seat_state.concealed, seat_state.melds)
            if m.kind == want_kind
        ]
        meld = _pick_meld(candidates, d.tiles)
        if meld is None:
            return None
        if want_kind == MeldKind.CONCEALED_KONG:
            return DeclareConcealedKong(meld=meld)
        return DeclareAddedKong(meld=meld)

    # --- writer loop -------------------------------------------------------------------------

    async def writer(self) -> None:
        # a send on an already-closed/disconnected socket can raise any of several
        # transport-specific errors depending on ASGI server -- none of them are actionable
        # here beyond "stop pumping and close", so this suppresses broadly rather than
        # enumerating transport internals.
        with contextlib.suppress(Exception):
            while True:
                frame = await self.outbox.get()
                if frame is None:
                    break
                await self.ws.send_text(json.dumps(frame))
                if self.outbox.dead:
                    break
        with contextlib.suppress(Exception):
            await self.ws.close()


@router.websocket("/ws")
async def ws_endpoint(
    websocket: WebSocket,
    table: str = "default",
    seed: int | None = None,
    practice: bool = False,
    spectate: bool = False,
    ruleset: str = DEFAULT_PRESET_ID,
    rules: str | None = None,
) -> None:
    if _registry.draining:
        # docs/00-architecture.md §8.1 step 1: stop accepting new connections (reconnects
        # included -- a reconnecting client's own backoff, 02-protocol.md §8, just retries after
        # the process cycles) once a drain has started. 1013 = "Try Again Later" (RFC 6455).
        await websocket.close(code=1013)
        return
    # No ticket/auth, permanently (docs/00-architecture.md §2.1 cuts real accounts/tickets
    # entirely) -- accept every other connection unconditionally.
    await websocket.accept()
    table_obj = _get_or_create_table(table, seed, practice, ruleset, rules)
    session = Session(websocket, table_obj)
    if spectate:
        # Explicit, connection-level opt-in ("Spectating" sub-task; `Table.register_spectator`'s
        # own docstring explains why this can't be the literal passive default docs/02-
        # protocol.md §2 describes -- it would race every real client's own hello-before-join
        # handshake). Mirrors `?practice=true`'s existing shape on this same endpoint rather
        # than adding a new wire message.
        table_obj.register_spectator(session.session_id, session._push, session.outbox.close)
    writer_task = asyncio.create_task(session.writer())
    try:
        while True:
            try:
                raw = await websocket.receive_text()
            except WebSocketDisconnect:
                break
            try:
                message = _adapter.validate_json(raw)
            except ValidationError as exc:
                await session.send_bad_frame(str(exc))
                break
            await session.handle(message)
    finally:
        # disconnect detection (docs/00-architecture.md §8 "Player disconnects"): the only
        # signal this sub-task wires up is the connection actually closing (`WebSocketDisconnect`
        # above, a bad-frame break, or any other exit from the loop) -- a heartbeat-driven dead
        # socket (docs/02-protocol.md §8's `heartbeat_timeout`) has no driver anywhere in this
        # codebase yet (sub-task 4 never built one; checked, not just assumed), so it's a real,
        # separate, still-open gap, not silently folded into this. `session.session_id` (not
        # just `session.seat`) guards the race where a newer reconnect already reclaimed this
        # seat before this connection's own `finally` runs -- see `Table.mark_disconnected`.
        if session.seat is not None:
            table_obj.mark_disconnected(session.seat, session.session_id)
        else:
            # A no-op for a connection never registered as a spectator (no `?spectate=true`) --
            # see `Table.unregister_spectator`'s own docstring for why a spectator's bookkeeping
            # is dropped outright on close rather than kept around for reconnect the way a
            # seat's is.
            table_obj.unregister_spectator(session.session_id)
        session.outbox.close()
        with contextlib.suppress(Exception):
            await writer_task
