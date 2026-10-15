"""Wire protocol models. Single source of truth -- TS types and JSON Schema are generated from
this file, never hand-written. Adding a message type: define its payload model, an Envelope
subclass with a Literal `t` and that payload as `d`, then add it to `AnyMessage`'s Union.

`discard` reuses its wire tag across directions (client intent vs. server broadcast, different
payload shapes) -- a flat discriminated union can't hold two members with the same tag, so
`ClientMessage`/`ServerMessage` are each their own discriminated union and `AnyMessage` is a
plain union of the two; pydantic's "smart" mode picks the right side by trying each (the two
`discard` shapes have disjoint required fields under `extra="forbid"`, so there's no ambiguity).
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Envelope(BaseModel):
    """Common frame fields. `t` and `d` are added by each concrete subclass."""

    model_config = ConfigDict(extra="forbid")

    v: Literal[1] = 1
    seq: int | None = None
    id: str | None = None  # client->server only: idempotency key
    ts: int  # server clock, ms


class HelloPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    last_seq: int | None = None
    client_version: str
    # reconnect target on an already-bound seat; client-asserted, verified via secret below.
    # Omit for a fresh connection awaiting `join`.
    seat: int | None = None
    # reconnect_secret from join's ack (AckPayload) -- required to reclaim seat; wrong or
    # missing -> bad_secret.
    secret: str | None = None
    # no name field here -- a reconnect never resends it; JoinPayload.name is the only place
    # a guest display name is ever set.


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


class JoinPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seat: int | None = None  # omit for "first open seat"
    # guest display name, sent once at first join; normalized server-side, never rejected.
    name: str | None = None


class ReadyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StartWithBotsPayload(BaseModel):
    """host-only, no fields -- the server already knows the host seat and which seat this
    session is bound to."""

    model_config = ConfigDict(extra="forbid")


class HandEndAckPayload(BaseModel):
    """no fields -- server keys acks by (seat, current hand_no) server-side."""

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


class Join(Envelope):
    t: Literal["join"] = "join"
    d: JoinPayload


class Ready(Envelope):
    t: Literal["ready"] = "ready"
    d: ReadyPayload


class StartWithBots(Envelope):
    t: Literal["start_with_bots"] = "start_with_bots"
    d: StartWithBotsPayload


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


class FairnessPayload(BaseModel):
    """One hand's reveal: hex `hand_seed` and `nonce`; never `game_seed`."""

    model_config = ConfigDict(extra="forbid")

    hand_seed: str
    nonce: str


class HandHistoryEntryPayload(BaseModel):
    """One completed hand, carried on `state_sync.hand_history`. Same fields as `HandEndPayload`
    minus `deadline_ts`, plus `dealer`/`prevailing`/`winner_melds` -- a live client derives
    those from `hand_end` itself, but a client with only a fresh `state_sync` has no live state
    to derive them from, so the server captures them here instead."""

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
    dealer: int
    prevailing: str
    winner_melds: list[dict[str, Any]] | None
    fairness: FairnessPayload | None = None


class StateSyncPayload(BaseModel):
    """Mirrors `app/views.py`'s `SeatView`, already redacted for the one seat it was built for.
    `legal_actions`/`claim_options` are the JSON-safe dicts `action_to_dict`/the claim-offer
    serializer produce -- a full typed model per variant would just re-derive the same shape."""

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
    # per-seat display name, same indexing as seat_status -- null only for an unjoined seat.
    names: list[str | None]
    scores: list[int]
    legal_actions: list[dict[str, Any]]
    claim_options: list[dict[str, Any]]
    deadline_ts: int | None
    # whichever seat's join was first; never actually null on the wire.
    host_seat: int | None
    # every seat's concealed tiles -- spectators of a `spectators_see_hands` table only
    # (`app/table.py`'s `TableSettings`), `null` everywhere else
    hands: list[list[int]] | None = None
    # every completed hand, oldest first, so a client whose only view is this snapshot can still
    # show the full scoresheet. Defaults to [] for older fixtures; a real Table always populates it.
    hand_history: list[HandHistoryEntryPayload] = []
    # fixed at construction, never mutated mid-game. ruleset_preset is null for a custom
    # ruleset; ruleset is always the full resolved values either way.
    ruleset_preset: str | None = None
    ruleset: dict[str, Any] = {}
    # per-seat bot tier (`bots.tiers.BOT_TIERS`), `null` for a non-`bot` seat
    bot_levels: list[str | None] = []
    # provable_fairness only, omitted otherwise: the current hand's hand_start.seed_commit
    seed_commit: str | None = None


class HandStartPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hand_no: int
    prevailing: str
    dealer: int
    # per-seat status, seat_view's shape: connected/disconnected/autoplay/bot/empty
    seats: list[str]
    # provable_fairness only, omitted otherwise: SHA256(hand_seed || nonce), hex
    seed_commit: str | None = None


class DealPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    your_hand: list[int]
    counts: dict[int, int]
    flowers: list[list[str]]
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
    tiles: list[int]
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
    # hand-end hold: every seat gets this same deadline, held until all four ack or it elapses.
    deadline_ts: int
    # provable_fairness only, omitted otherwise
    fairness: FairnessPayload | None = None


class ScorePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    totals: dict[int, int]


class GameEndPayload(BaseModel):
    """`{hand_no, scores}` -- matches `app/views.py`'s `GameEndWire`, which already mirrors
    `engine.GameEnded` 1:1."""

    model_config = ConfigDict(extra="forbid")

    hand_no: int
    scores: list[int]


class SeatStatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seat: int
    status: Literal["connected", "disconnected", "autoplay", "bot"]
    # carried on every seat_state broadcast, not just the one from join.
    name: str | None = None


class ServerShutdownPayload(BaseModel):
    """Broadcast once a graceful-shutdown drain starts, so clients can show a "reconnect
    shortly" banner instead of reading the dropped socket as an error."""

    model_config = ConfigDict(extra="forbid")

    deadline_ts: int


class AckPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    ok: bool
    error: str | None = None
    # populated only on a successful join's own ack -- the one-time reconnect credential.
    reconnect_secret: str | None = None


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


class ServerShutdown(Envelope):
    t: Literal["server_shutdown"] = "server_shutdown"
    d: ServerShutdownPayload


class Ack(Envelope):
    t: Literal["ack"] = "ack"
    d: AckPayload


ClientMessage = Annotated[
    Hello | Ping | Join | Ready | StartWithBots | Discard | Claim | Declare | Auto | HandEndAck,
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
    | Ack,
    Field(discriminator="t"),
]

# non-discriminated (see module docstring's discard note); ws.py validates against this so a
# wrong-direction message parses and is ignored rather than rejected as malformed.
AnyMessage = ClientMessage | ServerMessage
