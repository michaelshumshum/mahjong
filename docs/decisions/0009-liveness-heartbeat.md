# 0009. Liveness heartbeat

- **Status:** Deferred
- **Date:** 2026-09

## Context

Disconnect is detected only when the WebSocket closes ([protocol.md §8](../protocol.md)). A mobile
browser's socket can sit open for minutes after the network dies without firing `onclose` — TCP
keepalive defaults run minutes to hours, and carrier NATs silently drop idle mappings — so a dead
seat isn't flagged and the grace-period clock never starts.

## Design sketch

| Direction | Behaviour |
| --- | --- |
| Client → server | `ping` at least every `heartbeat_interval` (15s), whether or not a clock-offset reading is needed. `ping`/`pong` already exist; the client never sends them on a timer |
| Server → client | if no frame went out in `heartbeat_interval`, send an unsolicited `pong{t0: null, t1: now}` keepalive |
| Dead-socket detection | nothing heard from a connection in `heartbeat_timeout` (45s) → close it, mark the seat `DISCONNECTED`, start the normal grace/bot-takeover clock ([architecture.md §8](../architecture.md)) |

The same periodic `ping` would feed clock-offset correction for `deadline_ts`
([protocol.md §4](../protocol.md)), also not implemented.

## Needs before reviving

- `pong{t0: null}` support in the protocol models and client reducer.
- A per-connection last-heard timestamp checked from the table's timer heap or the session.
