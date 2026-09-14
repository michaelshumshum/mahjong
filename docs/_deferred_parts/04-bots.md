# Deferred from 04-bots.md

Cut per audit decision D16. Original source: `docs/04-bots.md`, pre-audit versions of §2 (T3
row), §6 ("T3 — search"), and §7 (bot personas paragraph, Expert row detail).

## T3 `SearchBot`

Provenance: `04-bots.md` §2, tier table row for T3 (pre-audit).

| Tier | What it is | Effort | Use |
| --- | --- | --- | --- |
| **T3** `SearchBot` | determinized rollouts / MCTS over the pure engine | large | "Expert", post-launch |

## T3 — search

Provenance: `04-bots.md` §6, "T3 — search" (pre-audit; cut because T1/T2 alone satisfy the M4
done-gate per the D9/§4 fix, and the 300–800ms budget below is incompatible with the
single-worker, single-event-loop process described in `07-infra.md` — it would block every room,
every socket, and every heartbeat on that process if run inline, and even off-loop it competes
for the same `ProcessPoolExecutor` capacity flagged as a real constraint in §3).

With a pure engine, determinized MCTS is straightforward:

1. Sample N worlds consistent with the redacted view (unseen tiles distributed among opponents
   and wall, respecting counts and light discard-based inference).
2. Run rollouts with T2 policies as the default policy.
3. Average action values across worlds; pick the best.

Budget 300–800ms per decision, inside human think time. The known weakness is **strategy
fusion** (the search assumes it can act differently per world when it can't); information-set
MCTS mitigates it. Read [arXiv:1904.07491](https://arxiv.org/pdf/1904.07491) on MDP abstraction
for mahjong before building this.

Before reviving this: re-derive the per-decision CPU budget against whatever the
`ProcessPoolExecutor` sizing turns out to be (see `04-bots.md` §3) — 300–800ms per decision at
200 concurrent tables × 3 bot seats is a much larger capacity ask than the T1/T2 shanten-table
path and needs its own worker-pool sizing pass, not a shared one.

## Bot personas

Provenance: `04-bots.md` §7, paragraph following the difficulty table (pre-audit); the Expert row
that referenced this tier is also cut, see above.

Give each bot a **persona** — a name, an avatar, a play-style bias (aggressive / defensive /
flush-lover) and a think-time distribution. A bot that reliably chases full flushes is more
memorable than one that's marginally more optimal.

| Level | How |
| --- | --- |
| Expert | T3 with search budget |
