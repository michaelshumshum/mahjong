# 0003. Product scope

- **Status:** Accepted
- **Date:** 2026-09-14

## Context

The roadmap needed a launch target: the last milestone was open-ended, and several scope
questions were left open.

## Decision

| Question | Answer |
| --- | --- |
| Scale target | single node, ~200 concurrent tables. Thousands-of-tables routing is out of scope ([ADR 0006](0006-multi-node-and-durability.md)) |
| Stakes | cosmetic points only, never real money — real-stakes mahjong is a licensing question in most jurisdictions |
| Default ruleset | `min_faan=3`, `faan_cap=10`, half spicy, discarder pays all, `CLASSIC+NEW_6+NEW_18`, `EAST_ONLY` |
| Finding players | private tables shared by link, aimed at friend groups who already coordinate a time. Public matchmaking (queue, skill pairing, always-on strangers) is a separate, harder problem and out of scope |
| Solo play | practice mode against bots is a complete product on its own |
| Rules scope | the default hand sets + `min_faan=3`. Everything else (pao, aborts, regional variants) behind a `RuleSet` flag |

**v1** = solo play against bots that win at a normal rate, plus real multiplayer where four
browsers on four devices finish a game with a deliberate disconnect. Post-launch, triaged against
real usage: replay viewer, sound, stats, rating, leaderboard, matchmaking.

## Consequences

- **Cold start** is the primary product risk for a 4-player realtime game: nothing mitigates it
  beyond bots and bring-your-own-group links.
- The 200-table target × 3 bot seats is a real CPU load (~470 shanten evaluations per bot decision,
  [bots.md §3](../bots.md)); a load test at that target has not been run.
- Deployment, backups and observability must exist before real users
  ([infra.md §7–§8](../infra.md)).
