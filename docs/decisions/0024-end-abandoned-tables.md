# 0024. End a started table once every human has left

- **Status:** Accepted
- **Date:** 2026-10

## Context

A disconnected seat flips to `autoplay` after `disconnect_grace_seconds` (20s) and a bot plays it
([architecture.md §8](../architecture.md)). With every human gone, that meant all four seats were
bot-driven to `GAME_OVER`, each decision a `ProcessPoolExecutor` job, for a game nobody would see.

`POST /tables` and `/ws?table=<new id>` have no rate limit. A production load test opened ~150
practice tables and closed the tabs:

| Measure | Value |
| --- | --- |
| Cost of one bot-driven table | ~1.2% of a core |
| Abandoned tables left running | 149 |
| CPU on the 2-vCPU prod box | ~170%, until the api was restarted |

## Decision

A started table with at least one human-bound seat and none `connected` is ended after
`ABANDONED_TABLE_GRACE_SECONDS` (default 120s); mechanics in
[architecture.md §8.2](../architecture.md).

| Choice | Why |
| --- | --- |
| Spectators don't count | otherwise one idle spectator tab per table defeats it |
| 120s default, ≥ 6× the disconnect grace | a refresh or network blip must never end a game |
| Grace on the table's own `TimerHeap` | one more deadline in the existing heap, no sleeper task racing the table loop |
| Not persisted | `games` holds finished games only; an abandoned game is treated like a crash-abandoned one |
| Evict, tombstone the id | frees the `Table` (ring buffers, state) while a late connect gets `error{code:"table_closed"}` instead of a fresh empty table under a dead game's id |
| Reuse `error{code}` | no new message type: `ErrorPayload.code` is a free string, so no `make proto` |
| Showcase exempt | all-bot by design, one table, already bounded |

### Rejected: keep playing to completion

The prior behaviour — "Player never returns: bot plays out the game, result recorded". It gives
an abandoned seat a recorded result, but nobody is left to read it, and the cost is unbounded in
the number of tables anyone can open. Kept only while at least one human is still `connected`.

## Consequences

- An all-humans-gone game leaves no record. A player who comes back after the grace finds
  `table_closed`, not their game.
- The tombstone set grows by one id per ended table and is never pruned — a few dozen bytes each.
- Rate limiting table creation is still unbuilt; this caps the cost of abandoned tables, not of
  live ones.
