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


# One union for both directions: a discriminator needs >=2 members, and each
# direction currently has too few message types of its own for a standalone
# union (server has only `pong` so far). Split into ClientMessage/ServerMessage
# once both sides have enough members — every future sub-task just adds its
# Envelope subclass to this Union.
AnyMessage = Annotated[Hello | Ping | Pong, Field(discriminator="t")]
