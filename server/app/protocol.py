"""Wire protocol models. Single source of truth (docs/02-protocol.md §6) —
TS types and JSON Schema get generated from this file, never hand-written.

Adding a message type: define its payload model, define an Envelope subclass
with a Literal `t` tag and that payload as `d`, then add the subclass to
`AnyMessage`'s Union. Nothing else needs to change for the union to keep
discriminating correctly.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class Envelope(BaseModel):
    """Common frame fields. `t` and `d` are added by each concrete subclass."""

    model_config = ConfigDict(extra="forbid")

    v: Literal[1] = 1
    seq: int | None = None  # server->client only: per-seat, dense, gapless
    id: str | None = None  # client->server only: idempotency key
    ts: int  # server clock, ms


class HelloPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    last_seq: int | None = None
    client_version: str


class PingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    t0: int


class PongPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    t0: int | None = None  # null on an unsolicited keepalive pong (§8)
    t1: int


class Hello(Envelope):
    t: Literal["hello"] = "hello"
    d: HelloPayload


class Ping(Envelope):
    t: Literal["ping"] = "ping"
    d: PingPayload


class Pong(Envelope):
    t: Literal["pong"] = "pong"
    d: PongPayload


class ErrorPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class Error(Envelope):
    t: Literal["error"] = "error"
    d: ErrorPayload


# Both directions now have >=2 members, so split by direction for typing/codegen
# (docs/02-protocol.md §2 vs §3) — every future sub-task adds its Envelope
# subclass to ClientMessage or ServerMessage, whichever it belongs to.
ClientMessage = Annotated[Hello | Ping, Field(discriminator="t")]
ServerMessage = Annotated[Pong | Error, Field(discriminator="t")]

# ws.py validates incoming frames against the full union, not ClientMessage
# alone: a client sending a server-direction message (e.g. `pong`) is ignored,
# not rejected as malformed (see the comment in ws.py) — that needs Pong/Error
# to parse successfully, just not to be acted on.
AnyMessage = Annotated[Hello | Ping | Pong | Error, Field(discriminator="t")]
