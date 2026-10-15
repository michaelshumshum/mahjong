"""WS endpoint speaking the envelope protocol (docs/protocol.md §1) -- one `Session` per
connection, joined to a `Table`. `hello`/`ping` stay on a local per-connection counter, never
the per-seat `seq` stream everything else uses (see `Session.handle`).

Table lookup is `app/registry.py`'s `TableRegistry`, one process-wide singleton (`_registry`).
`?ruleset=`/`?rules=` and `?practice=` are a fallback for a direct WS connect to an unclaimed
table id -- the primary path is `POST /tables` (`app/main.py`'s `create_table`), which resolves
the same way. Both are only meaningful the first time a given `table` id is created. `?seed=`
exists only so tests can pin a table's deal. `?spectate=true` registers this connection as a
spectator at accept time -- an explicit opt-in rather than a passive default, since the latter
would race every real client's own hello-before-join handshake.

`reset_registry()` swaps in a fresh `TableRegistry` per ASGI startup so `draining`/tables never
leak across server lifetimes (including a `TestClient(app)` context in tests).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from concurrent.futures import Executor
from typing import Any, Protocol

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import protocol as proto
from app.clock import now_ms
from app.errors import (
    TABLE_CLOSED_ERROR,
    ErrorCode,
    NotHostError,
    SeatAuthError,
    SeatNotBoundError,
    SeatTakenError,
    TableAlreadyStartedError,
    TableFullError,
)
from app.outbox import BoundedOutbox
from app.registry import TableRegistry
from app.table import Table
from app.views import CLAIM_KIND_WIRE
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

_OUTBOX_MAXSIZE = 64  # docs/architecture.md "Outbound backpressure" / protocol.md §9

_registry = TableRegistry()

_CLAIM_WIRE_TO_MELD_KIND = {wire: kind for kind, wire in CLAIM_KIND_WIRE.items()}
_DECLARE_WIRE_TO_MELD_KIND = {
    "concealed_kong": MeldKind.CONCEALED_KONG,
    "added_kong": MeldKind.ADDED_KONG,
}


def get_table(table_id: str) -> Table | None:
    """Test/introspection hook onto the registry -- not part of the wire protocol."""
    return _registry.get(table_id)


def registry() -> TableRegistry:
    """Accessor used by `app/main.py`'s `lifespan`, `/healthz`, and `/tables`."""
    return _registry


def reset_registry(
    *,
    bot_pool: Executor | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    abandon_grace_seconds: float | None = None,
) -> TableRegistry:
    """Install a fresh `TableRegistry` as this module's singleton -- called on every ASGI
    startup (including a `TestClient(app)` context) so a previous lifetime's tables/draining
    flag never leak into this one."""
    global _registry
    _registry = TableRegistry(
        bot_pool=bot_pool,
        session_factory=session_factory,
        abandon_grace_seconds=abandon_grace_seconds,
    )
    return _registry


def _resolve_ruleset_query(ruleset: str, rules: str | None) -> RuleSet:
    """`?ruleset=`/`?rules=` on `/ws` -> the `RuleSet` to construct with -- the WS-connect
    fallback to `POST /tables`'s primary path. `rules` arrives as raw query-string JSON here, so
    a malformed value just folds into `resolve_ruleset`'s existing lenient fallback rather than
    being handled separately."""
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
    """Structural type for `_dispatch`'s `msg` param -- every post-join message has `id`/`d`,
    but shares no common base that types `d` (each Envelope subclass narrows it separately)."""

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
    """Same as `_pick_meld`, but a claim's `tiles` excludes the claimed discard -- the client
    names only its own two tiles."""
    if tiles is not None:
        wanted = set(tiles)
        for meld in candidates:
            own = {t for t in meld.tiles if t != claimed_tile}
            if own == wanted:
                return meld
        return None
    return candidates[0] if len(candidates) == 1 else None


class Session:
    """One connection. Pre-`join`, frames go out on a local per-connection counter (`hello`/
    `ping` never move off it, see `handle`). Once `join` binds a seat, every response routes
    through that seat's own `Table.publish_to_seat`, which owns the real per-seat `seq`."""

    def __init__(self, websocket: WebSocket, table: Table) -> None:
        self.ws = websocket
        self.table = table
        self.session_id = str(uuid.uuid4())
        self.seat: int | None = None
        self._local_seq = 0
        self.outbox = BoundedOutbox(maxsize=_OUTBOX_MAXSIZE, resync=self._resync)

    def _resync(self) -> None:
        """`BoundedOutbox`'s overflow callback -- re-publishes a fresh `state_sync` through
        `Table`, which allocates a real, correctly-ordered `seq` (can't fabricate one locally).
        A spectator (`self.seat is None`) gets the spectator equivalent; a no-op if this
        session was never registered as one."""
        if self.seat is not None:
            self.table.publish_to_seat(self.seat, self.table.state_sync_wire(self.seat))
        else:
            self.table.publish_to_spectator(self.session_id, self.table.state_sync_wire(None))

    def _push(self, seq: int, wire: dict[str, Any]) -> None:
        """Registered with `Table` as this seat's `SeatBinding.send` once joined."""
        t = wire["t"]
        d = {k: v for k, v in wire.items() if k != "t"}
        self.outbox.push({"v": 1, "t": t, "seq": seq, "ts": now_ms(), "d": d})

    def _send_local(self, t: str, payload: dict[str, Any]) -> None:
        """Pre-join (or join-failure) frames only -- the per-connection counter, never the
        per-seat stream (there is no seat yet)."""
        self._local_seq += 1
        self.outbox.push({"v": 1, "t": t, "seq": self._local_seq, "ts": now_ms(), "d": payload})

    def _ack(
        self,
        msg: _IdempotentMessage,
        *,
        ok: bool,
        error: str | None = None,
        reconnect_secret: str | None = None,
    ) -> None:
        if msg.id is None:
            return  # ack is keyed on id -- no id, nothing to acknowledge
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
        self._send_local("error", {"code": ErrorCode.BAD_FRAME, "message": message})

    async def handle(self, message: object) -> None:
        """`ping` gets a connection-local `pong`, no `ack`, no per-seat `seq` -- it isn't one of
        the gameplay intents the idempotency contract covers. `hello` with no `seat` is a no-op
        preceding `join`; `hello` with a `seat` is the reconnect handshake -- see
        `_handle_hello`."""
        if self.table.closed:
            # connected in the instant before the table ended (docs/architecture.md §8.2)
            self._send_local("error", dict(TABLE_CLOSED_ERROR))
            self.outbox.close()
            return
        if isinstance(message, proto.Hello):
            await self._handle_hello(message)
            return
        if isinstance(message, proto.Ping):
            self._send_local("pong", {"t0": message.d.t0, "t1": now_ms()})
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
        # every remaining AnyMessage member is server->client -- a client sending one parses
        # but is ignored, not rejected.

    async def _handle_hello(self, msg: proto.Hello) -> None:
        """`hello{last_seq, seat, secret}` on an already-bound seat reclaims it. `seat` is
        client-asserted; `secret` is checked against `SeatBinding.reconnect_secret` before the
        reclaim happens. `d.seat is None` is the no-op path ahead of a fresh `join`."""
        if msg.d.seat is None:
            return
        if self.seat is not None:
            self._send_local(
                "error", {"code": ErrorCode.ALREADY_JOINED, "message": "connection already bound"}
            )
            return
        try:
            was_disconnected = self.table.reconnect(
                msg.d.seat, self.session_id, self._push, msg.d.secret
            )
        except SeatNotBoundError:
            self._send_local(
                "error",
                {"code": ErrorCode.NO_SUCH_SEAT, "message": f"seat {msg.d.seat} is not bound"},
            )
            return
        except SeatTakenError:
            # seat is a bot seat, no human occupant to reclaim from -- same wire error join
            # gives an already-taken seat.
            self._send_local(
                "error",
                {"code": ErrorCode.SEAT_TAKEN, "message": f"seat {msg.d.seat} is a bot seat"},
            )
            return
        except SeatAuthError:
            self._send_local(
                "error",
                {"code": ErrorCode.BAD_SECRET, "message": f"wrong secret for seat {msg.d.seat}"},
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

    async def _dispatch(self, msg: _IdempotentMessage, apply: Any) -> None:
        """Shared idempotency + ack wrapper for every post-join intent. `apply(seat, d)` returns
        `(ok, error)`; idempotency is scoped to the seat binding, not this `Session`, so it
        survives reconnect.

        `ok=True` means "accepted for processing", not "guaranteed legal" -- `Table._authorize`
        still silently drops a well-formed but currently-illegal command. `Claim`/`Declare` can
        fail to even construct an `Action` and get `ok=False, error="illegal"` without reaching
        `Table.submit`.
        """
        if self.seat is None:
            self._send_local(
                "error", {"code": ErrorCode.NOT_JOINED, "message": "join a seat first"}
            )
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
        window = self.table.state.claim_window
        if d.choice == "pass" and (window is None or window.window_id != d.window_id):
            # client auto-pass races the server's own timeout at the same deadline; outcome is
            # a pass either way.
            return True, None
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

    async def writer(self) -> None:
        # a send on a closed socket can raise several transport-specific errors -- none
        # actionable beyond "stop and close".
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
        # stop accepting new connections (reconnects included) once a drain has started.
        # 1013 = "Try Again Later" (RFC 6455).
        await websocket.close(code=1013)
        return
    # no auth -- accept every other connection unconditionally.
    await websocket.accept()
    if _registry.is_closed(table):
        # an abandoned table's id is never recycled (docs/architecture.md §8.2)
        frame = {"v": 1, "t": "error", "seq": 1, "ts": now_ms(), "d": dict(TABLE_CLOSED_ERROR)}
        await websocket.send_text(json.dumps(frame))
        await websocket.close()
        return
    table_obj = _get_or_create_table(table, seed, practice, ruleset, rules)
    session = Session(websocket, table_obj)
    if spectate:
        # explicit connect-time opt-in, not a passive default -- would race the real
        # hello-before-join handshake.
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
        # disconnect is detected only by the socket closing -- no heartbeat/dead-socket timeout.
        # session_id (not just seat) guards a newer reconnect already reclaiming this seat first.
        if session.seat is not None:
            table_obj.mark_disconnected(session.seat, session.session_id)
        else:
            # no-op for a connection that never registered as a spectator.
            table_obj.unregister_spectator(session.session_id)
        session.outbox.close()
        with contextlib.suppress(Exception):
            await writer_task
