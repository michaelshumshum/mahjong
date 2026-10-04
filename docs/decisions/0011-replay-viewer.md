# 0011. Replay viewer needs a server re-redaction endpoint

- **Status:** Deferred
- **Date:** 2026-09

## Context

The intent was "the same client reducer, fed from a recorded event log." That doesn't match what's
persisted: games are stored as `(ruleset, seed, action_log)` ([infra.md §6](../infra.md)) —
*actions*, with no seat-of-view and no redaction (`redact_event()` runs per outbound message at
play time and isn't stored).

## Design sketch

A server endpoint re-runs `reduce()` over the stored `(seed, action_log)` and re-applies
`redact_event(state, seat, event)` to produce the same per-seat event stream a live client
consumes. Client-side it's the same reducer ([frontend.md §6](../frontend.md)); only the source
differs.

## Needs before reviving

- Endpoint shape, and the default seat-of-view — most likely the spectator composite unless the
  requester was one of the four players.
- Only records matching the current `ENGINE_VERSION` replay ([ml.md §2](../ml.md)).
- `/replay/[id]` exists as a placeholder route until then.
