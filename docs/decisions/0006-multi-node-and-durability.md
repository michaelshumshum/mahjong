# 0006. Multi-node scaling and mid-game durability

- **Status:** Deferred
- **Date:** 2026-09-14

## Context

The server is one process with no mid-game durability: process death abandons every live table
([architecture.md §7](../architecture.md)). The single-writer-per-table invariant
([architecture.md §3](../architecture.md)) must survive any future scaling.

## Design sketch

**Stage 2 — N nodes, sticky tables.** Each table pinned to one node for its lifetime. A
lightweight router holds only a table→node directory, the matchmaking queue and lobby presence,
redirecting `GET /tables/{id}/route` to the node's WebSocket URL (`ws://node-N/ws?table=...`).
Shard by table, never split a table.

**Stage 3 — durability.** Two write-granularity options, not interchangeable:

| Option | Tradeoff |
| --- | --- |
| Per-action append | a Postgres write awaited inside reduce-and-publish breaks "no `await` between read and write of shared state". Safe only via a separate writer task fed by a non-awaited queue, which reopens a crash window between "applied" and "persisted" |
| Batch per hand | cheaper and off the hot path, but loses exactly the in-progress hand — the one durability exists to protect |

Either way, **exact replay is the unsolved part**: `reduce` is pure only over its explicit inputs,
and two sources of non-determinism happen outside it and aren't logged as actions:

- **Bot decisions** — replaying "what the bot decided" needs the decision logged, not bot logic
  re-run against replayed state.
- **Timer expiries** (tsumogiri-on-timeout, auto-pass, bot-deadline defaults) — server-clock
  driven; each needs logging as the action it produced, with why it fired.

**Infrastructure abstraction.** A Redis-shaped `Protocol` layer (`app/infra/ports.py`) was drafted
and cut — written for a Redis that doesn't exist, fronting one process that doesn't need the
indirection:

```python
class KV(Protocol):
    async def get(self, k: str) -> bytes | None: ...
    async def set(self, k: str, v: bytes, ttl: int | None = None) -> None: ...

class Queue(Protocol):                       # matchmaking
    async def push(self, q: str, item: bytes) -> None: ...
    async def pop_n(self, q: str, n: int) -> list[bytes]: ...   # atomic

class Bus(Protocol):                         # lobby presence fan-out, never in-table
    async def publish(self, ch: str, msg: bytes) -> None: ...
    def subscribe(self, ch: str) -> AsyncIterator[bytes]: ...
```

## Needs before reviving

- One process with hundreds of tables actually becoming load-bearing.
- A chosen write granularity, the async-invariant fix, and a non-determinism log format.
- Until then, in-process state stays plain module-level structures, not a `Protocol`.
