"""Wire protocol models. Single source of truth (docs/02-protocol.md §6) —
TS types and JSON Schema get generated from this file, never hand-written.

Adding a message type: define its payload model, define an Envelope subclass
with a Literal `t` tag and that payload as `d`, then add the subclass to
`AnyMessage`'s Union. Nothing else needs to change for the union to keep
discriminating correctly.

**`discard` reuses its wire tag across directions** (docs/02-protocol.md §2 vs §3: the client
intent and the server broadcast are both `t:"discard"`, different payload shapes). A single
flat `Field(discriminator="t")` union can't hold two members with the same tag, so
`ClientMessage`/`ServerMessage` are each their own discriminated union and `AnyMessage` is a
plain (non-discriminated) union of the two -- pydantic v2's "smart" union mode picks the right
side by trying each and keeping whichever validates (the two `discard` shapes have disjoint
required fields under `extra="forbid"`, so there's never a genuine ambiguity). `ws.py` still
validates every incoming frame against `AnyMessage`, same lenient-on-wrong-direction behavior
as before. `tools/gen_protocol.py`'s `_union_members` was extended to flatten this one extra
level of nesting; nothing else about codegen changed.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Envelope(BaseModel):
    """Common frame fields. `t` and `d` are added by each concrete subclass."""

    model_config = ConfigDict(extra="forbid")

    v: Literal[1] = 1
    seq: int | None = None  # server->client only: per-seat, dense, gapless
    id: str | None = None  # client->server only: idempotency key
    ts: int  # server clock, ms


# --- shared leaf payloads --------------------------------------------------------------------


class HelloPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    last_seq: int | None = None
    client_version: str
    # reconnect target on an already-bound seat (02-protocol.md §2/§5) -- client-asserted,
    # permanently (00-architecture.md §2.1 cuts real accounts/tickets entirely; there is no
    # verified identity to bind this to instead). Omit for a fresh connection awaiting `join`,
    # unchanged M0 behavior.
    seat: int | None = None
    # deliberately no `name` field here -- `hello` is the reconnect/session message (`seat` only
    # ever makes sense for an already-bound seat reclaiming itself, per the field above), and the
    # server already has this seat's chosen name from its original `join`. `JoinPayload.name`
    # below is the one place a guest display name is ever set (02-protocol.md §2, M5).


class PingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    t0: int


class PongPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    t0: int | None = None  # null on an unsolicited keepalive pong (§8)
    t1: int


class ErrorPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class Hello(Envelope):
    t: Literal["hello"] = "hello"
    d: HelloPayload


class Ping(Envelope):
    t: Literal["ping"] = "ping"
    d: PingPayload


class Pong(Envelope):
    t: Literal["pong"] = "pong"
    d: PongPayload


class Error(Envelope):
    t: Literal["error"] = "error"
    d: ErrorPayload


# --- client -> server intents (docs/02-protocol.md §2) ----------------------------------------


class JoinPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seat: int | None = None  # omit for "first open seat"
    # guest display name (M5, docs/00-architecture.md §2.1): client-chosen, persisted client-side
    # (localStorage), sent once at first `join` -- a reconnecting seat's `hello` never resends it,
    # the server already has it on `SeatBinding.name`. No wire-level length limit here: an
    # empty/missing/over-length name is normalized server-side (trim, cap, default), never
    # rejected -- a low-stakes guest field doesn't get a hard-error validation path.
    name: str | None = None


class ReadyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HandEndAckPayload(BaseModel):
    """`hand_end_ack` (hand-end hold): no fields -- the server keys acks by `(seat, current
    hand_no)` server-side (`app/room.py`'s `Room.mark_hand_end_ack`), same shape as `ReadyPayload`
    above."""

    model_config = ConfigDict(extra="forbid")


class DiscardPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tile_id: int


class ClaimPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_id: int
    choice: Literal["pass", "chow", "pung", "kong", "win"]
    tiles: list[int] | None = None  # disambiguates a chow; unused otherwise


class DeclarePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["concealed_kong", "added_kong", "win"]
    tiles: list[int] | None = None  # meld tiles; unused for "win"


class AutoPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    no_calls: bool | None = None
    auto_pass_chow: bool | None = None


class ChatPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str


class Join(Envelope):
    t: Literal["join"] = "join"
    d: JoinPayload


class Ready(Envelope):
    t: Literal["ready"] = "ready"
    d: ReadyPayload


class HandEndAck(Envelope):
    t: Literal["hand_end_ack"] = "hand_end_ack"
    d: HandEndAckPayload


class Discard(Envelope):
    t: Literal["discard"] = "discard"
    d: DiscardPayload


class Claim(Envelope):
    t: Literal["claim"] = "claim"
    d: ClaimPayload


class Declare(Envelope):
    t: Literal["declare"] = "declare"
    d: DeclarePayload


class Auto(Envelope):
    t: Literal["auto"] = "auto"
    d: AutoPayload


class Chat(Envelope):
    t: Literal["chat"] = "chat"
    d: ChatPayload


# --- server -> client events (docs/02-protocol.md §3) ------------------------------------------


class StateSyncPayload(BaseModel):
    """Mirrors `app/views.py`'s `SeatView`, already redacted for the one seat it was built for
    (`seat=None` for a spectator). `legal_actions`/`claim_options` are the JSON-safe dicts
    `mahjong_core.actions.action_to_dict`/`ws.py`'s claim-offer serializer produce -- a full
    typed model per `Action`/`ClaimOffer` variant would just re-derive that same shape with no
    redaction benefit (same reasoning `SeatView`'s own docstring gives for reusing those types
    directly instead of inventing wire-only ones)."""

    model_config = ConfigDict(extra="forbid")

    seat: int | None
    hand_no: int
    prevailing: str
    dealer: int
    turn: int
    phase: str
    own_hand: list[int]
    concealed_counts: list[int]
    melds: list[list[dict[str, Any]]]
    discard_pools: list[list[int]]
    flowers: list[list[str]]
    wall_remaining: int
    seat_status: list[str]
    # per-seat chosen guest display name (M5), same indexing as seat_status -- `null` for a seat
    # nobody has ever joined ("empty"); always a resolved, non-empty string for any bound seat
    # (human or bot), never null for those -- see `app/room.py`'s `_normalize_name`.
    names: list[str | None]
    scores: list[int]
    legal_actions: list[dict[str, Any]]
    claim_options: list[dict[str, Any]]
    deadline_ts: int | None


class HandStartPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hand_no: int
    prevailing: str
    dealer: int
    # per-seat status, seat_view's shape: connected/disconnected/autoplay/bot/empty
    seats: list[str]


class DealPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    your_hand: list[int]
    counts: dict[int, int]
    wall_remaining: int


class FlowerReplacePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seat: int
    flower: str
    replacement: int | None = None  # only ever populated for the seat's own stream


class DrawPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seat: int
    tile_id: int | None = None  # populated only for the drawing seat's own stream


class DiscardEventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seat: int
    tile_id: int
    tile: str
    pool_index: int


class ClaimOfferPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_id: int
    options: list[dict[str, Any]]
    deadline_ts: int


class ClaimResolvedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_id: int
    claim_kind: str
    seat: int | None
    action_kind: str | None


class MeldPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seat: int
    meld_kind: str
    tiles: list[int] | None
    count: int | None = None  # concealed_kong, non-owner stream only
    from_seat: int | None = None


class KongReplacePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seat: int
    tile_id: int | None = None  # populated only for the drawing seat's own stream


class TurnPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seat: int
    phase: str
    deadline_ts: int
    legal: list[dict[str, Any]] | None = None  # unicast to the acting seat only


class HandEndPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hand_no: int
    outcome: str
    winner: int | None
    win_type: str | None
    discarder: int | None
    faan: int | None
    faan_breakdown: dict[str, int] | None
    points: int | None
    payments: dict[int, int] | None
    revealed: bool
    winning_hand: list[int] | None
    # hand-end hold (docs/00-architecture.md §3 "Hand-end hold"): every seat gets this same
    # deadline, held until all four ack (`hand_end_ack`) or it elapses, whichever first.
    deadline_ts: int


class ScorePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    totals: dict[int, int]


class GameEndPayload(BaseModel):
    """`{hand_no, scores}`, not `02-protocol.md §3`'s original `{standings, game_id}` sketch --
    `app/views.py`'s `GameEndWire` (landed in the earlier redaction sub-task) already mirrors
    `engine.GameEnded` 1:1 as `{hand_no, scores}`; reconciled here rather than reshaping
    already-tested redaction code to match a sketch that predates it."""

    model_config = ConfigDict(extra="forbid")

    hand_no: int
    scores: list[int]


class SeatStatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seat: int
    status: Literal["connected", "disconnected", "autoplay", "bot"]
    # this seat's resolved display name (M5) -- carried on every seat_state broadcast, not just
    # the one from `join`, so an already-connected seat never has to wait for a full `state_sync`
    # to learn a name that was already resolved earlier in the game.
    name: str | None = None


class ChatEventPayload(BaseModel):
    """Broadcast form of a chat message (docs/02-protocol.md §3 `chat`). `name` is the sender's
    resolved guest display name -- `Room._names_tuple()`'s existing per-seat resolution, carried
    here so a chat bubble doesn't need a second lookup against `state_sync.names`. No timestamp
    field beyond the envelope's own `ts` -- same convention `server_shutdown` already uses."""

    model_config = ConfigDict(extra="forbid")

    seat: int
    text: str
    name: str


class ServerShutdownPayload(BaseModel):
    """docs/00-architecture.md §8.1 step 2 -- broadcast once a graceful-shutdown drain starts,
    so clients can show a "reconnect shortly" banner instead of reading the eventual dropped
    socket as an error. `deadline_ts` is the same bounded grace window every room in this drain
    shares (server epoch ms, same convention as every other `deadline_ts` on the wire)."""

    model_config = ConfigDict(extra="forbid")

    deadline_ts: int


class AckPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    ok: bool
    error: str | None = None


class StateSync(Envelope):
    t: Literal["state_sync"] = "state_sync"
    d: StateSyncPayload


class HandStart(Envelope):
    t: Literal["hand_start"] = "hand_start"
    d: HandStartPayload


class Deal(Envelope):
    t: Literal["deal"] = "deal"
    d: DealPayload


class FlowerReplace(Envelope):
    t: Literal["flower_replace"] = "flower_replace"
    d: FlowerReplacePayload


class Draw(Envelope):
    t: Literal["draw"] = "draw"
    d: DrawPayload


class DiscardEvent(Envelope):
    t: Literal["discard"] = "discard"
    d: DiscardEventPayload


class ClaimOffer(Envelope):
    t: Literal["claim_offer"] = "claim_offer"
    d: ClaimOfferPayload


class ClaimResolved(Envelope):
    t: Literal["claim_resolved"] = "claim_resolved"
    d: ClaimResolvedPayload


class Meld(Envelope):
    t: Literal["meld"] = "meld"
    d: MeldPayload


class KongReplace(Envelope):
    t: Literal["kong_replace"] = "kong_replace"
    d: KongReplacePayload


class Turn(Envelope):
    t: Literal["turn"] = "turn"
    d: TurnPayload


class HandEnd(Envelope):
    t: Literal["hand_end"] = "hand_end"
    d: HandEndPayload


class Score(Envelope):
    t: Literal["score"] = "score"
    d: ScorePayload


class GameEnd(Envelope):
    t: Literal["game_end"] = "game_end"
    d: GameEndPayload


class SeatState(Envelope):
    t: Literal["seat_state"] = "seat_state"
    d: SeatStatePayload


class ChatEvent(Envelope):
    """Server->client rebroadcast of a chat message. Reuses the `chat` wire tag the client
    intent (`Chat`, above) already occupies -- same dual-tag pattern the module docstring
    documents for `discard`: `ClientMessage`/`ServerMessage` are separate discriminated unions,
    and the two payloads have disjoint required fields (`{text}` vs `{seat, text, name}`) under
    `extra="forbid"`, so `AnyMessage`'s smart-union validation never has a genuine ambiguity."""

    t: Literal["chat"] = "chat"
    d: ChatEventPayload


class ServerShutdown(Envelope):
    t: Literal["server_shutdown"] = "server_shutdown"
    d: ServerShutdownPayload


class Ack(Envelope):
    t: Literal["ack"] = "ack"
    d: AckPayload


ClientMessage = Annotated[
    Hello | Ping | Join | Ready | Discard | Claim | Declare | Auto | Chat | HandEndAck,
    Field(discriminator="t"),
]
ServerMessage = Annotated[
    Pong
    | Error
    | StateSync
    | HandStart
    | Deal
    | FlowerReplace
    | Draw
    | DiscardEvent
    | ClaimOffer
    | ClaimResolved
    | Meld
    | KongReplace
    | Turn
    | HandEnd
    | Score
    | GameEnd
    | SeatState
    | ServerShutdown
    | ChatEvent
    | Ack,
    Field(discriminator="t"),
]

# Non-discriminated on purpose -- see module docstring's `discard` note. ws.py validates
# incoming frames against this so a wrong-direction message (e.g. a client sending `pong`)
# parses and is ignored rather than rejected as malformed.
AnyMessage = ClientMessage | ServerMessage
