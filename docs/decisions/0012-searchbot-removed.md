# 0012. T3 `SearchBot` built and removed

- **Status:** Rejected (built, then removed 2026-09-27)
- **Date:** 2026-09-27

## Context

The tier ladder reserved an "Expert" rung for determinized-world search over the pure engine:
sample worlds consistent with the redacted view, run rollouts with T2 policies, average action
values across worlds, budget 300–800ms per decision. It was out of scope for the first bot
milestone because T1/T2 alone made practice mode playable, and because the budget head-of-line
blocks the shared bot `ProcessPoolExecutor`: one slow decision stalls every other table's bot turn
queued behind it.

## What was built

`server/bots/search.py`, with a dedicated `_shared_search_bot_pool()`
(`ProcessPoolExecutor(max_workers=2)`, routed by `Table._bot_tier`) so `T3` jobs never blocked
`T1`/`T2`.

- **Algorithm** (`Phase.AWAIT_ACTION` only): sample N worlds (`determinize()`), for each legal root
  action roll forward up to `rollout_depth` decisions with `FaanBot` acting for every seat, value a
  rollout by real point delta at `HAND_OVER` or a shanten/reachable-faan/ukeire proxy
  (`value_estimate`) at the depth cap, average per action, return the best. Defaults
  `time_budget=0.5s`, `max_worlds=8`, `rollout_depth=4`.
- **`determinize(view, rng)`**: every `TileId` not in own hand + melds + discards is unseen,
  shuffled once and dealt — `concealed_counts[s]` to each opponent, the rest to the wall. Flowers
  needed only wall position. Tile conservation verified directly. Claim-window decisions delegated
  to `FaanBot`: a `SeatView` never carries another seat's offers/`window_id`, so a legal
  `ClaimWindow` can't be reconstructed.
- **Bounded depth, not full hand:** `FaanBot.act` measured ~4.7ms/decision × ~83 decisions/hand, so
  one full-hand rollout for one (world, candidate) pair cost ~390ms — the entire budget.
- Strategy fusion accepted, not solved. Time-boxing checked between worlds, between candidates,
  and inside each rollout.

## What happened

Two debugging rounds found and fixed three real bugs:

1. **Sampling bias.** Fixed ascending candidate order + deadline cut-offs starved high action ids
   of samples on every world. Fixed by shuffling candidate order per world.
2. **Tie-break bias.** The proxy is small-integer-valued, so ties are common (20 of 40 sampled real
   decisions), and `max()` always picked the lowest action id. Fixed by random tie-breaking.
3. **Missing ukeire term** in `value_estimate`, leaving ties nothing to break on. Fixed by adding a
   scaled ukeire term mirroring `FaanBot._speed_term`.

Final validation, 15 duplicate sets, all fixes live:

```
paired difference (SearchBot - FaanBot), mean points/game: -13.156
95% CI: [-25.581, -0.730]  -- excludes zero, in FaanBot's favor
tenpai_at_draw_rate: SearchBot 6.35% vs FaanBot 51.85%
```

The core symptom — almost never reaching tenpai — was essentially unchanged from the pre-fix
8-set run.

## Decision

Remove `SearchBot` and its pool rather than re-tune. Every tier shares `_shared_bot_pool()` again.

Three independently diagnosed bugs fixed with no movement on the flagship metric is the signature
of a structural ceiling. Rolling out with the same static heuristic as both the acting policy and
the leaf evaluator can only add variance around that heuristic's own judgment; a noisy few-sample
estimate can pick a worse root action than `FaanBot` would choose directly. The literature
predicts this:

- Determinized / "perfect information Monte Carlo" search has two named pathologies — *strategy
  fusion* (planning a different continuation per sampled world, which a player can't do across
  one hidden hand) and *non-locality* (a subtree's value depends on the opponent's real strategy).
  Cazenave & Ventos's αμ search for Bridge ([arXiv:1911.07960](https://arxiv.org/abs/1911.07960))
  exists because these are severe enough to need a different algorithm.
- Kurita & Hoki ([arXiv:1904.07491](https://arxiv.org/abs/1904.07491)) build an MDP abstraction
  rather than naive determinized MCTS over mahjong's raw tree.
- Suphx ([arXiv:2003.13590](https://arxiv.org/abs/2003.13590)) and Mortal are learned value/policy
  approaches, not heuristic-rollout search.

The original rollout-based `OracleBot` shared this machinery and hit the same ceiling
([ADR 0013](0013-oracle-full-information.md)).

## Needs before reviving

1. **A leaf evaluator meaningfully better than a shallow rollout of the policy** — realistically a
   learned value function (the RL critic, [ml.md](../ml.md)). Load-bearing; the rest is secondary
   without it.
2. **Real information-set MCTS** instead of determinization, including search over claim-window
   decisions (reconstructing a legal `ClaimWindow` from what a `SeatView` carries).
3. **More rollout budget** — arithmetically incompatible with ~4.7ms × ~83 decisions/hand at 200
   tables × 3 bot seats unless the concurrency target or hardware changes. More samples of a biased
   estimate narrow variance, not bias.
4. Per-tier pool sizing validated against real per-core throughput.
