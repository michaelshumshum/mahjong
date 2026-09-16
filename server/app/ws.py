"""WS endpoint speaking the envelope protocol (docs/02-protocol.md §1) -- a real `Session` per
connection that joins a `Room` and exchanges gameplay messages (docs/05-roadmap.md M3 sub-task
4). Extends M0's hello/ping stub in place rather than replacing it: `Session` still owns the
connection loop, still validates against `AnyMessage`, still keeps hello/ping/pong exactly as
M0 left them (see `Session.handle`'s docstring for why those two intentionally do *not* move
onto the per-seat `seq` stream this sub-task adds for everything else).

**Room lookup is `app/registry.py`'s `RoomRegistry`** (M3 sub-task 6 -- replaces this module's
former bare `dict[str, Room]`, which its own docstring already flagged as a stand-in: "a real
`RoomRegistry` with matchmaking is a later sub-task"). Still one process-wide, module-level
singleton (`_registry` below) -- `RoomRegistry` itself stays an in-process dict per
docs/00-architecture.md §6, not a new abstraction layer. One `RuleSet` (`DEFAULT_RULESET`) for
every room -- `?seed=` exists only so tests can pin a room's deal.

**DB wiring + graceful shutdown (a later sub-task).** `_registry` is no longer a fixed
module-import-time singleton: `reset_registry()` swaps in a fresh `RoomRegistry` (optionally
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
from app.registry import RoomRegistry
from app.room import Room, RoomFullError, SeatNotBoundError, SeatTakenError
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
from mahjong_core.config import DEFAULT_RULESET
from mahjong_core.melds import Meld, MeldKind, legal_self_melds
from mahjong_core.tiles import TileId

router = APIRouter()

_adapter: TypeAdapter[object] = TypeAdapter(proto.AnyMessage)

_OUTBOX_MAXSIZE = 64  # docs/00-architecture.md "Outbound backpressure" / 02-protocol.md §9

_registry = RoomRegistry()

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


def get_room(room_id: str) -> Room | None:
    """Test/introspection hook onto the registry -- not part of the wire protocol."""
    return _registry.get(room_id)


def registry() -> RoomRegistry:
    """Accessor for `app/main.py`'s `lifespan` (wiring a DB session factory at startup, running
    the graceful-shutdown drain at shutdown) and `/healthz` (reading `.draining`)."""
    return _registry


def reset_registry(
    *,
    bot_pool: Executor | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> RoomRegistry:
    """Install a fresh `RoomRegistry` as this module's singleton. `app/main.py`'s `lifespan`
    calls this on every ASGI startup -- a real process, or one `TestClient(app)` context in
    tests -- so each server lifetime gets its own registry: `draining` always starts `False`,
    and a previous lifetime's rooms/background tasks never leak into this one's shutdown drain
    (docs/00-architecture.md §8.1; see `app/registry.py`'s module docstring)."""
    global _registry
    _registry = RoomRegistry(bot_pool=bot_pool, session_factory=session_factory)
    return _registry


def _get_or_create_room(room_id: str, seed: int | None) -> Room:
    return _registry.get_or_create(room_id, DEFAULT_RULESET, seed=seed, require_ready=True)


class _IdempotentMessage(Protocol):
    """Structural type for `_dispatch`'s `msg` param -- every post-join `ClientMessage` variant
    (`Ready`/`Discard`/`Claim`/`Declare`/`Auto`/`Chat`) has an `id` and a `d` payload model,
    but they share no common base beyond `proto.Envelope`, which doesn't type `d` at all
    (each subclass narrows it separately)."""

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
    every gameplay response (`ack`, and anything `Room` publishes) is routed through that
    seat's own `Room.publish_to_seat`, which owns the real per-seat `seq` (docs/02-protocol.md
    §1 D1)."""

    def __init__(self, websocket: WebSocket, room: Room) -> None:
        self.ws = websocket
        self.room = room
        self.session_id = str(uuid.uuid4())
        self.seat: int | None = None
        self._local_seq = 0
        self.outbox = BoundedOutbox(maxsize=_OUTBOX_MAXSIZE, resync=self._resync)

    # --- outbound plumbing ---------------------------------------------------------------

    def _resync(self) -> None:
        """`BoundedOutbox`'s overflow callback (docs/02-protocol.md §9) -- re-publishes a fresh
        `state_sync` through `Room`, which allocates a real, correctly-ordered `seq` for it
        (see `app/outbox.py`'s module docstring for why this can't fabricate one locally)."""
        if self.seat is not None:
            self.room.publish_to_seat(self.seat, self.room.state_sync_wire(self.seat))

    def _push(self, seq: int, wire: dict[str, Any]) -> None:
        """Registered with `Room` as this seat's `SeatBinding.send` once joined."""
        t = wire["t"]
        d = {k: v for k, v in wire.items() if k != "t"}
        self.outbox.push({"v": 1, "t": t, "seq": seq, "ts": _now_ms(), "d": d})

    def _send_local(self, t: str, payload: dict[str, Any]) -> None:
        """Pre-join (or join-failure) frames only: M0's original per-connection counter, never
        the per-seat stream (there is no seat yet)."""
        self._local_seq += 1
        self.outbox.push({"v": 1, "t": t, "seq": self._local_seq, "ts": _now_ms(), "d": payload})

    def _ack(self, msg: _IdempotentMessage, *, ok: bool, error: str | None = None) -> None:
        if msg.id is None:
            return  # ack is keyed on id (02-protocol.md §1) -- no id, nothing to acknowledge
        payload: dict[str, Any] = {"id": msg.id, "ok": ok}
        if error is not None:
            payload["error"] = error
        if self.seat is not None:
            self.room.publish_to_seat(self.seat, {"t": "ack", **payload})
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
        if isinstance(message, proto.Chat):
            await self._dispatch(message, self._apply_chat)
            return
        # every remaining `AnyMessage` member is server->client (Pong/Error/StateSync/...) --
        # a client sending one parses successfully and is ignored, not rejected (same lenient
        # wrong-direction handling M0's own comment described).

    async def _handle_hello(self, msg: proto.Hello) -> None:
        """`hello{last_seq, seat}` on an already-bound seat is 02-protocol.md §2's reconnect
        path ("a reconnecting player doesn't re-join... hello{last_seq} on an already-bound
        seat reclaims it directly"). `seat` (not part of the wire table before this sub-task)
        is the interim stand-in for the identity a real auth ticket would carry -- see
        `HelloPayload`'s own docstring. `d.seat is None` is the unchanged M0 no-op (a bare
        `hello` ahead of a fresh `join`)."""
        if msg.d.seat is None:
            return
        if self.seat is not None:
            self._send_local(
                "error", {"code": "already_joined", "message": "connection already bound"}
            )
            return
        try:
            was_disconnected = self.room.reconnect(msg.d.seat, self.session_id, self._push)
        except SeatNotBoundError:
            self._send_local(
                "error", {"code": "no_such_seat", "message": f"seat {msg.d.seat} is not bound"}
            )
            return
        self.seat = msg.d.seat
        self.room.resume(msg.d.seat, msg.d.last_seq, announce_reconnect=was_disconnected)

    async def _handle_join(self, msg: proto.Join) -> None:
        if self.seat is not None:
            self._ack(msg, ok=False, error="already_joined")
            return
        try:
            seat = self.room.join(self.session_id, self._push, seat=msg.d.seat)
        except SeatTakenError:
            self._ack(msg, ok=False, error="seat_taken")
            return
        except RoomFullError:
            self._ack(msg, ok=False, error="room_full")
            return
        self.seat = seat
        self._ack(msg, ok=True)

    # --- idempotent gameplay intents (02-protocol.md §1/§2) ---------------------------------

    async def _dispatch(self, msg: _IdempotentMessage, apply: Any) -> None:
        """Shared idempotency + ack wrapper for every post-join intent. `apply(seat, d)` returns
        `(ok, error)`; idempotency is scoped to the seat *binding* (`SeatBinding.idempotency`,
        not this `Session`) per 02-protocol.md §1, so it survives this connection.

        `ok=True` here means "accepted for processing", not "guaranteed legal" -- `Room`'s own
        `_authorize` silently drops a well-formed but currently-illegal `Command` (unchanged
        M2/M3 behavior); this layer's job is the `id`/ack contract, not re-deriving game
        legality `Room` already owns. `Discard`/`Ready`/`Auto`/`Chat` are always structurally
        applyable; `Claim`/`Declare` can fail to even construct an `Action` (an unknown
        `window_id`, an unmatched disambiguator) and get `ok=False, error="illegal"` without
        ever reaching `Room.submit`.
        """
        if self.seat is None:
            self._send_local("error", {"code": "not_joined", "message": "join a seat first"})
            return
        binding = self.room.seat_bindings[self.seat]
        assert binding is not None  # self.seat is only ever set once Room.join bound it
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
        self.room.mark_ready(seat)
        return True, None

    def _apply_discard(self, seat: int, d: proto.DiscardPayload) -> tuple[bool, str | None]:
        self.room.submit(seat, DiscardAction(tile_id=TileId(d.tile_id)))
        return True, None

    def _apply_auto(self, seat: int, d: proto.AutoPayload) -> tuple[bool, str | None]:
        self.room.set_auto(seat, no_calls=d.no_calls, auto_pass_chow=d.auto_pass_chow)
        return True, None

    def _apply_chat(self, seat: int, d: proto.ChatPayload) -> tuple[bool, str | None]:
        # rebroadcast/rate-limiting deliberately deferred: 02-protocol.md §3's event table has
        # no server->client chat broadcast type to deliver through in the first place, and it
        # isn't needed for a hand to play out end to end -- accepted (ack'd) and dropped.
        return True, None

    def _apply_claim(self, seat: int, d: proto.ClaimPayload) -> tuple[bool, str | None]:
        action = self._build_claim_action(seat, d)
        if action is None:
            return False, "illegal"
        self.room.submit(seat, action)
        return True, None

    def _build_claim_action(self, seat: int, d: proto.ClaimPayload) -> Action | None:
        window = self.room.state.claim_window
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
        self.room.submit(seat, action)
        return True, None

    def _build_declare_action(self, seat: int, d: proto.DeclarePayload) -> Action | None:
        if d.kind == "win":
            return DeclareWin()
        want_kind = _DECLARE_WIRE_TO_MELD_KIND[d.kind]
        seat_state = self.room.state.seats[seat]
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
async def ws_endpoint(websocket: WebSocket, room: str = "default", seed: int | None = None) -> None:
    if _registry.draining:
        # docs/00-architecture.md §8.1 step 1: stop accepting new connections (reconnects
        # included -- a reconnecting client's own backoff, 02-protocol.md §8, just retries after
        # the process cycles) once a drain has started. 1013 = "Try Again Later" (RFC 6455).
        await websocket.close(code=1013)
        return
    # M0-era stub still applies: no ticket/auth yet (docs/00-architecture.md §2.1, M5 scope) --
    # accept every other connection unconditionally.
    await websocket.accept()
    room_obj = _get_or_create_room(room, seed)
    session = Session(websocket, room_obj)
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
        # seat before this connection's own `finally` runs -- see `Room.mark_disconnected`.
        if session.seat is not None:
            room_obj.mark_disconnected(session.seat, session.session_id)
        session.outbox.close()
        with contextlib.suppress(Exception):
            await writer_task
