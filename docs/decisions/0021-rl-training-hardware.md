# 0021. RL training hardware: laptop CPU, cloud plan, 2060 desktop

- **Status:** Historical
- **Date:** 2026-10-04 (laptop measurement and cloud plan), superseded the same day by the 2060
  desktop measurement

## Context

R2's PPO loop was first built and measured on the development laptop (i7-1265U, 12 threads:
2 P-cores + 8 E-cores, CPU only). The projection from that measurement recommended a cloud GPU box.
The run went to a home desktop instead (RTX 2060 6 GB + i5-10400F, WSL2), whose measurements and
setup are in [ml.md §13](../ml.md); the R2 and R3 runs' actual throughput is in
[rl-learnings.md §1](../rl-learnings.md). This record keeps the laptop numbers and the plan they led
to.

## Laptop measurement (R2 PPO, CPU)

`rl_ppo_c0.yaml`: 96 envs × 6 workers, torch 2 threads, full-size `PolicyNet` + `OracleCritic`
(96 × 6), batch 4,096, 2 epochs × 512. A decision here is a surfaced learner decision; in C0 each
one also steps three tsumogiri seats in-env.

| Leg | Throughput |
| --- | --- |
| learner update (16 minibatch steps, policy + critic + aux) | 11.7 s per update ≈ 356 decisions/s, 0.085 updates/s |
| rollout incl. batched policy forward | ~2,100 decisions/s (1.96 s per 4,096) |
| end to end | ~305 decisions/s (~1.1M decisions/h) — learner-bound, 86% of wall time |
| env only, random actions, 96 × 6 (no forward) | C0 seating 4.0k/s, C1 self-play 5.2k/s (`policy_raw` + `oracle_raw` + shanten + 10% labels per decision) |

## Plan it led to (not taken)

Wall-clock to C1 exit at the then-estimated 0.3–1B budget: CPU-only on the laptop 11–38 days of
sustained full load, which the 65 W charger cannot hold (it throttles to 400 MHz). With the learner
on a GPU the laptop becomes rollout-bound at ~2–5k decisions/s: 0.3–1B in ~1–6 days, still
throttled. The recommendation was a cloud box (one GPU, ≥ 32 cores for env workers): env workers
scale per core (~0.7k decisions/s per worker here), so ~20–30k decisions/s would put C1 exit at
~3–14 h. The curriculum's own minimum is ~0.22B (C0b anneal 20M + C1 anneal 200M).

## Outcome

- The 2060 desktop measured ~1.1–1.2k decisions/s end to end with neither leg the bottleneck
  ([ml.md §13](../ml.md)); the R2 run then trained at 1.1–1.7k/s and the R3 league at ~1.1k/s.
- C1 exited at 220.4M decisions, about the curriculum's minimum and below the 0.3–1B estimate:
  roughly 1.5–2.5 days at those rates, so the cloud box was never needed.
