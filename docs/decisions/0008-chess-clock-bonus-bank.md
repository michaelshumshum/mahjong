# 0008. Chess-clock bonus bank

- **Status:** Deferred
- **Date:** 2026-09-14

## Context

Each player would get `bonus_seconds` (default 20) for the whole game, drawn down only after the
per-turn budget is spent — like a chess byoyomi bank. The timer model is built on one immutable
absolute `deadline_ts` per prompt ([protocol.md §4](../protocol.md)), with no message that pushes
a revised deadline.

## Decision

Cut. The `bonus_seconds` field was removed from `RuleSet`; the client has no bank meter.

## Needs before reviving

- A server→client event (or a mutable prompt field) that updates `deadline_ts` when a player draws
  on the bank, and client handling to extend an already-running countdown.
- Whether spending the bank is automatic or an explicit intent (e.g. `use_bonus`), and what the
  timer UI shows before it's spent.
- A late or backpressure-dropped revised-deadline event must never leave a client counting down
  against a stale deadline.
- A distinct meter once there's a UX reason to separate bonus time from turn time.
- Add `bonus_seconds` back to `RuleSet` alongside the extension message.
