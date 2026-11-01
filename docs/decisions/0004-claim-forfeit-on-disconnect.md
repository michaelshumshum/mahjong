# 0004. A mid-claim-window disconnect keeps the offer

- **Status:** Accepted (2026-11; reverses the 2026-09 forfeit-on-disconnect)
- **Date:** 2026-09, revised 2026-11

## Context

The first design kept a disconnected seat's live claim offer open and, on reconnect, re-armed the
seat's `TimerHeap` entry to a fresh full window.

That path was never actually reachable through a full-`state_sync` reconnect — the common case once
a page reload persists its own seat. `state_sync.claim_options` carried no `window_id`, so the
client had nothing to render a dialog against or submit a `claim` with, while the server was still
waiting on it. The seat reconnected into a table that looked paused, with no way to act on the
thing pausing it.

So the 2026-09 decision was: a seat that disconnects holding a live, unresolved offer forfeits it
immediately (`Pass`, through the claim-timeout path), queued as a `SeatDisconnected` inbox event.
A brief disconnect during a claim window cost that claim.

In 2026-11 `state_sync` gained `claim_offer`, window id and deadline included
([protocol.md §3](../protocol.md)), which removed the blocker.

## Decision

A disconnect no longer touches the claim window. The offer stays open on its own deadline:

| Case | Result |
| --- | --- |
| Deadline passes while offline | the claim-timeout `Pass`, same as a silent connected seat |
| Grace expires first (`claim_seconds` above `disconnect_grace_seconds`) | the seat goes `autoplay` and the bot answers |
| Reconnect inside the window | `resume()` re-arms the seat's deadline to a fresh `claim_seconds` and hands the offer back (`state_sync.claim_offer`, or one `claim_offer` frame after a ring replay) |
| Second reconnect in the same window | the offer comes back with the deadline already armed; no second extension |

The one-extension cap (`Table._rearmed_claims`) exists because each re-arm restarts the whole
window: without it a client that reconnects in a loop holds the table on one discard forever. A
resync that isn't a disconnect (seq gap, backpressure collapse) goes through the same `resume()`
and shares the cap.

## Consequences

- A brief disconnect, including a page reload, no longer costs the claim.
- A window can run up to about twice `claim_seconds` for a seat that drops and returns, once.
- `SeatDisconnected` and `Table._handle_seat_disconnected` are gone; `mark_disconnected` only flips
  the status and arms the grace timer.
