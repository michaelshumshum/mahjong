# RL learnings

What training the self-play agent ([ml.md](ml.md)) has shown so far: curriculum progress, how the
training metrics move, evaluation against the heuristic bots, and how the agent plays. A living
record — later runs append rows to the tables and findings to §6.

## 1. Setup

| | Run 1 (R2, `rl_ppo_c0.yaml`, `hold_final: true`) |
| --- | --- |
| hardware | RTX 2060 6 GB (learner + rollout forward), i5-10400F 6 cores / 12 threads (envs), WSL2 ([ml.md §13](ml.md)) |
| envs | 10 workers × 16 = 160 envs; 12.5% blind envs; torch 2 threads |
| update | batch 4,096 learner decisions, 2 epochs × minibatch 512, AdamW 3e-4, clip 0.2, entropy 0.01 ([ml.md §9](ml.md)) |
| model | `PolicyNet` 459k params + `OracleCritic` 427k (96 ch × 6 blocks), initialised from the R1 auxiliary-pretrained checkpoint |
| ruleset | `hk_classic` (`min_faan` stepped by the curriculum, [ml.md §10](ml.md)) |
| throughput | end to end 1.1–1.7k decisions/s; rollout 2.6–3.8k/s, learner ~2.9–3.0k/s; ~43 h of training for 233M decisions |

Metrics before 98.6M decisions are under an earlier scoring table; compare within a segment.

## 2. Curriculum progress

| Stage | Updates | Decisions | Anneal | Exit |
| --- | --- | --- | --- | --- |
| C0 | 1–51 | 0 → 0.21M | — | rolling win ≥ 0.40 at update 51 (0.398 one update earlier) |
| C0b | 52–4,853 | 0.21M → 20.32M | 20M, complete at 20.22M | rolling blind win 0.405 (threshold 0.25). The 50-update mean of batch blind win was already ≥ 0.25 at 0.43M: the anneal was the binding constraint |
| C1 | 4,854–52,402 | 20.33M → 220.40M | 200M; `min_faan` 0 → 1 at 120.33M, → 3 at 220.33M (update 52,385) | 17 updates after the anneal: rolling win 0.1995, sub-min tenpai 0.108 (251 tenpai draws), draws 20.2%, deal-in 0.099 over 4,000 hands |
| C1 held | 52,403– | 220.40M → (233.3M at last record) | — | runs until R3 (`hold_final`) |

C1 exit thresholds: win ≥ 0.15, sub-min tenpai ≤ 0.32 ([ml.md §10](ml.md)).

## 3. Training metrics

Segment means of the per-update `metrics.jsonl` records (batch rates are per learner seat-hand;
C0/C0b against tsumogiri opponents, C1 self-play over four learner seats).

| Decisions (M) | Stage, `min_faan` | k / keep / β | Win (blind) | Draw | Deal-in | Entropy | KL | Clip | Expl. var | PopArt σ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0–0.21 | C0, 0 | 13 / 1 / 1.0 | 0.22 (0.23) | 0.78 | 0 | 1.56 | 0.0019 | 0.014 | 0.90 | 1.30 |
| 0.21–2 | C0b, 0 | 12.4 / 1 / 0.98 | 0.60 (0.35) | 0.40 | 0 | 0.72 | 0.0056 | 0.057 | 0.79 | 1.51 |
| 2–10 | C0b, 0 | 9.3 / 1 / 0.86 | 0.70 (0.37) | 0.30 | 0 | 0.40 | 0.0075 | 0.063 | 0.75 | 1.56 |
| 10–20.3 | C0b, 0 | 3.3 / 1 / 0.63 | 0.72 (0.39) | 0.28 | 0 | 0.32 | 0.0078 | 0.057 | 0.71 | 1.47 |
| 20.3–40 | C1, 0 | 0 / 0.95 / 0.48 | 0.233 | 0.070 | 0.159 | 0.70 | 0.0101 | 0.104 | 0.62 | 0.75 |
| 40–60 | C1, 0 | 0 / 0.85 / 0.43 | 0.229 | 0.083 | 0.146 | 0.75 | 0.0115 | 0.109 | 0.71 | 0.58 |
| 60–80 | C1, 0 | 0 / 0.75 / 0.38 | 0.233 | 0.067 | 0.149 | 0.67 | 0.0101 | 0.092 | 0.65 | 0.54 |
| 80–98.6 | C1, 0 | 0 / 0.66 / 0.33 | 0.237 | 0.051 | 0.155 | 0.66 | 0.0090 | 0.083 | 0.57 | 0.51 |
| 98.6–120.3 | C1, 0 | 0 / 0.55 / 0.28 | 0.245 | 0.019 | 0.169 | 0.66 | 0.0078 | 0.076 | 0.84 | 0.37 |
| 120.3–140 | C1, 1 | 0 / 0.45 / 0.23 | 0.243 | 0.028 | 0.160 | 0.69 | 0.0078 | 0.077 | 0.71 | 0.34 |
| 140–160 | C1, 1 | 0 / 0.35 / 0.18 | 0.242 | 0.031 | 0.162 | 0.70 | 0.0075 | 0.074 | 0.57 | 0.31 |
| 160–180 | C1, 1 | 0 / 0.25 / 0.13 | 0.237 | 0.050 | 0.160 | 0.78 | 0.0074 | 0.073 | 0.35 | 0.35 |
| 180–200 | C1, 1 | 0 / 0.15 / 0.08 | 0.234 | 0.063 | 0.159 | 0.79 | 0.0073 | 0.071 | 0.23 | 0.36 |
| 200–220.3 | C1, 1 | 0 / 0.05 / 0.03 | 0.233 | 0.066 | 0.159 | 0.80 | 0.0069 | 0.066 | 0.20 | 0.36 |
| 220.33–220.40 | C1, 3 (exit window) | 0 / 0 / 0 | 0.194 | 0.225 | 0.093 | 0.80 | 0.0067 | 0.061 | 0.30 | 0.52 |
| 220.4–226 | held, 3 | 0 / 0 / 0 | 0.157 | 0.373 | 0.092 | 0.86 | 0.0075 | 0.071 | 0.26 | 0.55 |
| 226–233.3 | held, 3 | 0 / 0 / 0 | 0.167 | 0.331 | 0.102 | 0.85 | 0.0072 | 0.069 | 0.26 | 0.56 |

Held at `min_faan` 3, rolling window (4,000 hands) through the first 13M decisions:

| Decisions (M) | Win | Draw | Deal-in | Sub-min tenpai |
| --- | --- | --- | --- | --- |
| 220.40 (exit) | 0.200 | 0.202 | 0.099 | 0.108 |
| 220.8 | 0.160 | 0.361 | 0.086 | 0.065 |
| 223.3 | 0.120 | 0.518 | 0.073 | 0.041 |
| 224.6 | 0.172 | 0.311 | 0.100 | 0.077 |
| 227.1 | 0.173 | 0.309 | 0.104 | 0.045 |
| 230.9 | 0.158 | 0.368 | 0.095 | 0.029 |
| 233.3 | 0.173 | 0.307 | 0.103 | 0.041 |

PopArt μ tracks the mean shaped return (1.6–3.1 in C0/C0b, 0.91 → 0.03 over C1, ~0.01 held):
self-play payments are zero-sum, so μ → 0 as β → 0 is a sanity check on the shaping.

## 4. Evaluation over training

Candidate × 1 vs bot × 3, paired-duplicate per hand, `hk_classic` (`min_faan` 3), points per hand
([ml.md §12](ml.md)). Checkpoints were trained at the `min_faan` shown in §3 but are always
evaluated at 3.

Progress vs `FaanBot`, fixed seeds 4,100,000+, 500 sets:

| Decisions | Training `min_faan` | Diff [95% bootstrap CI] | Win (agent / bot) | Deal-in | Avg win faan | Sub-min tenpai | Table draws |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 98.6M | 0 | +0.66 [0.13, 1.22] | 0.180 / 0.169 | 0.081 / 0.074 | 3.51 / 3.33 | 0.192 / 0.038 | 31% |
| 157.5M | 1 | +3.14 [2.43, 3.90] | 0.257 / 0.158 | 0.075 / 0.084 | 3.70 / 3.34 | 0.149 / 0.025 | 27% |
| 161.0M | 1 | +5.26 [4.26, 6.33] | 0.262 / 0.158 | 0.074 / 0.087 | 4.11 / 3.32 | 0.159 / 0.026 | 26% |
| 167.1M | 1 | +4.29 [3.46, 5.17] | 0.247 / 0.153 | 0.070 / 0.086 | 3.95 / 3.29 | 0.159 / 0.030 | 29% |
| 220.4M (C1 exit) | 3 | +6.36 [5.26, 7.48] | 0.269 / 0.158 | 0.071 / 0.098 | 4.37 / 3.32 | 0.104 / 0.027 | 26% |
| 230.9M (held) | 3 | +8.82 [7.58, 10.10] | 0.272 / 0.153 | 0.064 / 0.109 | 4.95 / 3.32 | 0.045 / 0.030 | 27% |

Neighbouring checkpoints swing by ~±1 point (161.0M vs 167.1M). The CI covers seed noise for one
checkpoint, not checkpoint-to-checkpoint variance: read the trend, not a single step.

Fresh seeds 3,000,000+, 700 sets (the R2 gate seed set):

| Checkpoint | Opponent | Diff [95% CI] (bootstrap) | Win | Deal-in | Avg win faan | Sub-min tenpai | Tenpai at draw | Turns to win | Table draws |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **220.4M, C1 exit (R2 gate)** | `EfficiencyBot` | **+8.74 [7.67, 9.80]** ([7.69, 9.81]) | 0.299 / 0.145 | 0.043 / 0.092 | 4.64 / 3.22 | 0.140 / 0.335 | 0.448 / 0.983 | 59.4 / 53.6 | 26.7% |
| 230.9M, held | `EfficiencyBot` | +12.50 [11.30, 13.71] | 0.331 / 0.141 | 0.032 / 0.108 | 5.04 / 3.21 | 0.095 / 0.352 | 0.336 / 0.984 | 63.1 / 51.6 | 24.5% |
| 230.9M, held | `FaanBot` | +10.67 [9.32, 12.03] | 0.280 / 0.157 | 0.070 / 0.110 | 5.10 / 3.33 | 0.059 / 0.029 | 0.387 / 0.514 | 60.1 / 57.8 | 25.0% |

For scale: `FaanBot` over `EfficiencyBot` in the heuristic arena is +2.67 points/game [1.92, 3.42]
over full games ([bots.md §7](bots.md)) — win 0.197 / 0.163, deal-in 0.042 / 0.069, faan 3.30 /
3.22, sub-min tenpai 0.039 / 0.337, ~31% draws.

## 5. Observed agent behaviour

From the gate hand records (2,800 candidate seat-hands and 8,400 bot seat-hands per file),
replayed with `ml.env.replay_hand`. Shares of wins are over that side's wins; per-hand counts are
exposed melds standing at hand end.

**Hand value over speed.** It wins twice as often as the bots *and* with bigger hands:

| Winning faan | C1 exit / `EfficiencyBot` | 230.9M / `EfficiencyBot` | 230.9M / `FaanBot` |
| --- | --- | --- | --- |
| 3 (the minimum) | 33% / 86% | 21% / 86% | 21% / 75% |
| 4 | 24% / 11% | 27% / 12% | 24% / 20% |
| 5–7 | 34% / 2.5% | 39% / 2.2% | 41% / 4.5% |
| 8–9 | 8.0% / 0.1% | 11.2% / 0.2% | 11.0% / 0.1% |
| 10 (cap) | 1.1% / 0.7% | 2.0% / 0.5% | 2.8% / 0.3% |
| points per win | 28.5 / 13.7 | 33.7 / 13.5 | 36.4 / 14.0 |

**Flush and pung hands; the bots scrape 3 faan from minor patterns.** Patterns present in winning
hands:

| Pattern | C1 exit / `EfficiencyBot` | 230.9M / `EfficiencyBot` | 230.9M / `FaanBot` |
| --- | --- | --- | --- |
| 混一色 half flush | 52% / 0.9% | 62% / 1.2% | 63% / 1.4% |
| 清一色 full flush | 7.3% / < 1% | 9.2% / < 1% | 10.8% / < 1% |
| 對對糊 all pungs | 16% / 1.8% | 23% / 2.8% | 16% / 2.3% |
| 箭刻 dragon pung | 33% / 22% | 36% / 21% | 35% / 14% |
| 平糊 all chows | 26% / 56% | 15% / 54% | 17% / 61% |
| 門前清 concealed | 16% / 39% | 14% / 37% | 16% / 93% |
| 自摸 self-draw | 37% / 70% | 28% / 72% | 33% / 55% |

**Open, claim-driven, and shifting from chows to pungs.**

| Per seat-hand | C1 exit / `EfficiencyBot` | 230.9M / `EfficiencyBot` | 230.9M / `FaanBot` |
| --- | --- | --- | --- |
| hands with an exposed meld | 82% / 84% | 69% / 84% | 75% / 6.8% |
| chows | 0.78 / 0.78 | 0.38 / 0.81 | 0.42 / 0.01 |
| pungs | 0.77 / 0.61 | 0.89 / 0.61 | 0.89 / 0.11 |
| exposed + added kongs | 0.094 / 0 | 0.112 / 0 | 0.096 / 0 |
| concealed kongs | 0.025 / 0 | 0.025 / 0 | 0.025 / 0 |
| wins with an exposed meld | 84% / 60% | 86% / 62% | 84% / 6.3% |

Neither heuristic bot declares kongs in these hands; the agent does, about once every 9 hands.

**Wins on discards; the table pays it.** 63–72% of its wins are ron vs 28–45% for the bots.
Who fed each discard win:

| Feeds | C1 exit / `EfficiencyBot` | 230.9M / `EfficiencyBot` | 230.9M / `FaanBot` |
| --- | --- | --- | --- |
| bot → agent | 531 | 665 | 527 |
| bot → bot | 240 | 244 | 398 |
| agent → bot | 121 | 89 | 195 |

Most of the bots' deal-ins go to the agent: it is the table's main threat and the bots don't read it.

**Folds instead of chasing a dead hand.** Tenpai at exhaustive draw 0.45 → 0.34 (vs `EfficiencyBot`
0.98, `FaanBot` 0.51), sub-min tenpai 0.14 → 0.095 vs `EfficiencyBot`'s 0.34, deal-in 0.043 →
0.032 vs 0.092–0.108. Its hands take longer (59–63 turns to win vs 52–58): it builds value and
doesn't race.

**Trend over training** (C1 exit → 10.5M decisions later, same seeds): fewer 3-faan wins (33% →
21%), fewer chows (0.78 → 0.38 per hand) and 平糊 wins (26% → 15%), more 對對糊 (16% → 23%), lower
deal-in and sub-min tenpai — the `min_faan` 3 policy is still moving away from speed.

Not yet measured, worth doing next: push/fold timing (discard danger vs own shanten and opponents'
visible melds), claim acceptance rate per offer (claims taken / claims offered), win-decline
(`PASS` on a legal win) frequency, and the same breakdown against `ORACLE` and mixed tables.

## 6. Findings for future runs

| Finding | Evidence | Implication |
| --- | --- | --- |
| Curriculum anneals, not thresholds, set the pace | C0 exited at 0.21M; C0b's blind-win threshold was met by ~0.43M but the stage ran its full 20M anneal; C1 exited 17 updates after its 200M anneal | candidate to shorten the C0b anneal (and test a shorter C1 anneal) in the next run |
| Explained variance falls as the oracle and shaping anneal | C1 0.6–0.8 at keep ≥ 0.5, 0.20 at keep / β → 0, ~0.26 held | expected: the shaping term is predictable, unshaped zero-sum payouts are not. Low EV at the end of C1 is not by itself a critic failure; watch it within a held segment |
| Self-play per-seat win = (1 − draws) / 4 | C1 batch win 0.233 with 7% draws; exit window 0.194 with 22.5% draws | the C1 win threshold is a draw cap (≤ 40%), not a strength measure; strength comes from the held-out eval (§4) |
| At `min_faan` 0–1 the agents learn speed | C1 self-play draws 2–8%, deal-in ~0.16; eval sub-min tenpai stays 0.15–0.19 through 167M | low `min_faan` stages build hand-making, not value-building; the value play only appears once `min_faan` 3 is trained |
| Sub-min tenpai only falls once `min_faan` 3 is trained | eval 0.192 (98.6M, `min_faan` 0) → 0.149–0.159 (`min_faan` 1) → 0.104 at exit → 0.045 after 10.5M at `min_faan` 3 | the step to 3 does more in 10M decisions than 100M at 1 did; most training budget belongs at the target ruleset |
| The C1 exit window mostly measures the transition | the 4,000-hand window fills in ~17 updates after `min_faan` hits 3; exit draws 20%, settled held draws 31–37% (one dip to 52% at 223M) | the exit numbers are a snapshot of a policy trained at `min_faan` 1; don't read them as the converged C1 behaviour |
| Rising self-play draws were mutual defence, not passivity | held self-play draws 20% → ~31–40% while eval diff vs `FaanBot` rose +6.36 → +8.82, agent deal-in fell 0.071 → 0.064, and eval-table draws stayed 26–27% | read the draw canary together with held-out eval: higher draws among learners with rising strength vs heuristics is learners defending against each other |
| Entropy rises as the oracle is removed | C1 0.66 → 0.80; held ~0.85; KL 0.007, clip 0.07 throughout | no collapse; the policy stays stochastic at the target ruleset |
| Checkpoint-to-checkpoint variance ~±1 point | 161.0M +5.26 vs 167.1M +4.29 on the same seeds | gate a checkpoint chosen in advance (or average several), never the best of a sweep on the gate seeds ([ml.md §12](ml.md)) |

What to watch in R3 (league): self-play draw rate together with held-out eval (above);
`FaanBot`-table sub-min tenpai still falling; whether the flush-heavy, claim-driven style survives
against learned opponents that read open hands, since the heuristic bots largely don't (§5).
