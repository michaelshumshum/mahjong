# 0004. A mid-claim-window disconnect forfeits the offer

- **Status:** Accepted (supersedes re-arm-on-reconnect)
- **Date:** 2026-09

## Context

The first design kept a disconnected seat's live claim offer open and, on reconnect, re-armed the
seat's `TimerHeap` entry to a fresh full window.

That path was never actually reachable through a full-`state_sync` reconnect — the common case once
a page reload persists its own seat. `state_sync.claim_options` carries no `window_id`
([protocol.md §3](../protocol.md)), so the client had nothing to render a dialog against or submit
a `claim` with, while the server was still waiting on it. The seat reconnected into a table that
looked paused, with no way to act on the thing pausing it.

## Decision

A seat that disconnects while holding a live, unresolved claim offer forfeits it immediately —
`Pass`, through the same path a claim-window timeout uses
([architecture.md §8](../architecture.md)).

## Consequences

- A reconnect never has a claim to resolve; it's ordinary replay or `state_sync`.
- A brief disconnect during a claim window costs that claim.
