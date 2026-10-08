# RL learnings

What training the self-play agent ([ml.md](ml.md)) has shown so far: curriculum progress, how the
training metrics move, evaluation against the heuristic bots, and how the agent plays. A living
record — later runs append rows to the tables and findings to §6.

## 1. Setup

| | Run 1 (R2, `rl_ppo_c0.yaml`, `hold_final: true`) | Run 2 (R3, `rl_league.yaml`) |
| --- | --- | --- |
| hardware | RTX 2060 6 GB (learner + rollout forward), i5-10400F 6 cores / 12 threads (envs), WSL2 ([ml.md §13](ml.md)) | same |
| envs | 10 workers × 16 = 160 envs; 12.5% blind envs; torch 2 threads | same; league opponents per hand ([ml.md §11](ml.md)) |
| update | batch 4,096 learner decisions, 2 epochs × minibatch 512, AdamW 3e-4, clip 0.2, entropy 0.01 ([ml.md §9](ml.md)) | same, `policy_loss: ppo` |
| model | `PolicyNet` 459k params + `OracleCritic` 427k (96 ch × 6 blocks), initialised from the R1 auxiliary-pretrained checkpoint | same nets, whole learner (critic, PopArt, AdamW) loaded from run 1's hold end (464.3M) |
| ruleset | `hk_classic` (`min_faan` stepped by the curriculum, [ml.md §10](ml.md)) | C2: `hk_classic` `min_faan` 3, 10% `hk_casual`, 10% `hk_strict` hands |
| throughput | end to end 1.1–1.7k decisions/s (1.58–1.65k through the hold); rollout 2.6–3.8k/s, learner ~2.9–3.0k/s | ~1.15k learner decisions/s end to end (rollout 2.17 s + update 1.50 s per batch): 0.7× run 1's hold, frozen seats step without producing samples |

Metrics before 98.6M decisions are under an earlier scoring table; compare within a segment.

## 2. Curriculum progress

| Stage | Updates | Decisions | Anneal | Exit |
| --- | --- | --- | --- | --- |
| C0 | 1–51 | 0 → 0.21M | — | rolling win ≥ 0.40 at update 51 (0.398 one update earlier) |
| C0b | 52–4,853 | 0.21M → 20.32M | 20M, complete at 20.22M | rolling blind win 0.405 (threshold 0.25). The 50-update mean of batch blind win was already ≥ 0.25 at 0.43M: the anneal was the binding constraint |
| C1 | 4,854–52,402 | 20.33M → 220.40M | 200M; `min_faan` 0 → 1 at 120.33M, → 3 at 220.33M (update 52,385) | 17 updates after the anneal: rolling win 0.1995, sub-min tenpai 0.108 (251 tenpai draws), draws 20.2%, deal-in 0.099 over 4,000 hands |
| C1 held | 52,403–110,201 | 220.40M → 464.27M | — | stopped for the R3 league run (`hold_final`) |
| C2 (run 2) | 1– | 0 → (counter restarts in a new run) | — | R3 gates ([ml.md §14](ml.md)) |

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
| 233.3–260 | held, 3 | 0 / 0 / 0 | 0.166 | 0.338 | 0.098 | 0.85 | 0.0073 | 0.069 | 0.27 | 0.57 |
| 260–300 | held, 3 | 0 / 0 / 0 | 0.166 | 0.334 | 0.097 | 0.81 | 0.0069 | 0.065 | 0.27 | 0.57 |
| 300–340 | held, 3 | 0 / 0 / 0 | 0.171 | 0.318 | 0.100 | 0.81 | 0.0066 | 0.061 | 0.27 | 0.59 |
| 340–380 | held, 3 | 0 / 0 / 0 | 0.173 | 0.309 | 0.102 | 0.80 | 0.0062 | 0.058 | 0.28 | 0.59 |
| 380–420 | held, 3 | 0 / 0 / 0 | 0.176 | 0.296 | 0.102 | 0.79 | 0.0060 | 0.056 | 0.28 | 0.59 |
| 420–464.3 | held, 3 | 0 / 0 / 0 | 0.179 | 0.286 | 0.103 | 0.77 | 0.0057 | 0.053 | 0.28 | 0.58 |

Held at `min_faan` 3, rolling window (4,000 hands):

| Decisions (M) | Win | Draw | Deal-in | Sub-min tenpai |
| --- | --- | --- | --- | --- |
| 220.40 (exit) | 0.200 | 0.202 | 0.099 | 0.108 |
| 220.8 | 0.160 | 0.361 | 0.086 | 0.065 |
| 223.3 | 0.120 | 0.518 | 0.073 | 0.041 |
| 224.6 | 0.172 | 0.311 | 0.100 | 0.077 |
| 227.1 | 0.173 | 0.309 | 0.104 | 0.045 |
| 230.9 | 0.158 | 0.368 | 0.095 | 0.029 |
| 233.3 | 0.173 | 0.307 | 0.103 | 0.041 |
| 260.0 | 0.161 | 0.357 | 0.098 | 0.008 |
| 300.0 | 0.173 | 0.306 | 0.104 | 0.024 |
| 340.0 | 0.176 | 0.294 | 0.108 | 0.027 |
| 380.0 | 0.177 | 0.291 | 0.101 | 0.052 |
| 420.0 | 0.186 | 0.257 | 0.105 | 0.042 |
| 464.2 (hold end) | 0.184 | 0.264 | 0.106 | 0.041 |

Over the hold the slow trends are monotone in the segment means: self-play draws 0.33 → 0.29,
win 0.166 → 0.179, entropy 0.85 → 0.77, KL 0.0073 → 0.0057, explained variance 0.26 → 0.28. The
rolling window still swings ±0.05 in draws around them (attack-heavy and defence-heavy phases of
a few million decisions each).

Run 2 (league), first 0.46M decisions: self-play draws 0.31 (`league_draw_self`), past 0.29,
persona 0.29; rolling win 0.166, deal-in 0.091, sub-min tenpai 0.084 (the 20% `hk_casual` /
`hk_strict` hands are new to the policy); entropy 0.94, explained variance 0.22. Learner vs the
hold-end snapshot 0.50, vs the personas 0.49 (aggressive) / 0.51 (defensive): at parity, as
expected for copies of itself.

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
| 256.4M (held) | 3 | +7.81 [6.67, 9.01] | 0.262 / 0.161 | 0.070 / 0.104 | 4.83 / 3.33 | 0.063 / 0.024 | 25% |
| 326.0M (held) | 3 | +9.12 [7.81, 10.47] | 0.260 / 0.158 | 0.052 / 0.105 | 5.01 / 3.31 | 0.029 / 0.034 | 27% |
| 361.3M (held) | 3 | +8.76 [7.51, 10.07] | 0.291 / 0.151 | 0.069 / 0.110 | 4.73 / 3.30 | 0.024 / 0.027 | 26% |
| 395.8M (held) | 3 | +8.62 [7.46, 9.84] | 0.289 / 0.157 | 0.079 / 0.108 | 4.75 / 3.32 | 0.025 / 0.025 | 24% |
| 429.2M (held) | 3 | +8.24 [7.09, 9.40] | 0.309 / 0.148 | 0.062 / 0.105 | 4.43 / 3.32 | 0.029 / 0.020 | 25% |
| 462.0M (held) | 3 | +8.65 [7.34, 10.05] | 0.269 / 0.151 | 0.068 / 0.097 | 4.84 / 3.35 | 0.018 / 0.029 | 28% |

Neighbouring checkpoints swing by ~±1 point (161.0M vs 167.1M). The CI covers seed noise for one
checkpoint, not checkpoint-to-checkpoint variance: read the trend, not a single step.

From 230.9M to 462.0M the score is flat at +7.8 to +9.1 with every CI overlapping, while the mix
behind it moves: 326.0M wins least (0.260) with the biggest hands (5.01 faan) and lowest deal-in
(0.052); 429.2M wins most (0.309) with the smallest (4.43). Sub-min tenpai keeps falling (0.045 →
0.018–0.029), level with or below `FaanBot`'s.

Fresh seeds 3,000,000+, 700 sets (the R2 gate seed set):

| Checkpoint | Opponent | Diff [95% CI] (bootstrap) | Win | Deal-in | Avg win faan | Sub-min tenpai | Tenpai at draw | Turns to win | Table draws |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **220.4M, C1 exit (R2 gate)** | `EfficiencyBot` | **+8.74 [7.67, 9.80]** ([7.69, 9.81]) | 0.299 / 0.145 | 0.043 / 0.092 | 4.64 / 3.22 | 0.140 / 0.335 | 0.448 / 0.983 | 59.4 / 53.6 | 26.7% |
| 230.9M, held | `EfficiencyBot` | +12.50 [11.30, 13.71] | 0.331 / 0.141 | 0.032 / 0.108 | 5.04 / 3.21 | 0.095 / 0.352 | 0.336 / 0.984 | 63.1 / 51.6 | 24.5% |
| 230.9M, held | `FaanBot` | +10.67 [9.32, 12.03] | 0.280 / 0.157 | 0.070 / 0.110 | 5.10 / 3.33 | 0.059 / 0.029 | 0.387 / 0.514 | 60.1 / 57.8 | 25.0% |

Pre-league R3 gate: the 462.0M hold checkpoint, chosen in advance, on fresh seeds 5,000,000+
(not used for any other eval). `eval_policy` seats one opponent type ×3, so "mixed tables" is
measured as each `FaanBot` weight profile and `EfficiencyBot` in turn:

| Opponent | Sets | Diff [95% CI] (bootstrap) | Win | Deal-in | Avg win faan | Sub-min tenpai | Tenpai at draw | Turns to win | Table draws |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **`FaanBot`** | 1,000 | **+9.76 [8.72, 10.79]** ([8.75, 10.81]) | 0.272 / 0.158 | 0.070 / 0.110 | 5.00 / 3.33 | 0.030 / 0.048 | 0.389 / 0.495 | 59.6 / 57.1 | 25.5% |
| `EfficiencyBot` | 700 | +11.69 [10.49, 12.89] ([10.52, 12.90]) | 0.319 / 0.143 | 0.032 / 0.108 | 4.97 / 3.20 | 0.044 / 0.351 | 0.193 / 0.985 | 59.0 / 52.7 | 25.1% |
| `FaanBotAggressive` | 700 | +10.57 [9.35, 11.79] ([9.41, 11.83]) | 0.291 / 0.162 | 0.076 / 0.117 | 5.02 / 3.32 | 0.049 / 0.046 | 0.395 / 0.529 | 59.8 / 57.7 | 22.2% |
| `FaanBotDefensive` | 700 | +9.42 [8.20, 10.64] ([8.22, 10.69]) | 0.251 / 0.140 | 0.067 / 0.094 | 5.01 / 3.35 | 0.029 / 0.051 | 0.376 / 0.311 | 58.7 / 54.8 | 32.9% |
| `FaanBotFlushChasing` | 700 | +10.17 [8.98, 11.36] ([9.01, 11.42]) | 0.288 / 0.154 | 0.072 / 0.111 | 4.96 / 3.33 | 0.023 / 0.045 | 0.370 / 0.472 | 59.4 / 57.1 | 25.1% |

The R3 exit criteria's numbers ([ml.md §14](ml.md)) are already met before the league: CI > 0 vs
`FaanBot` on ≥ 1,000 fresh sets, positive against every profile, sub-min tenpai at or below each
opponent's. `FaanBotDefensive` is the closest matchup and the drawiest table (33%).

For scale: `FaanBot` over `EfficiencyBot` in the heuristic arena is +2.67 points/game [1.92, 3.42]
over full games ([bots.md §7](bots.md)) — win 0.197 / 0.163, deal-in 0.042 / 0.069, faan 3.30 /
3.22, sub-min tenpai 0.039 / 0.337, ~31% draws.

## 5. Observed agent behaviour

From the gate hand records (2,800 candidate seat-hands and 8,400 bot seat-hands per file; the
462.0M / `FaanBot` column is the pre-league R3 gate, 4,000 / 12,000 on seeds 5,000,000+),
replayed with `ml.env.replay_hand`. Shares of wins are over that side's wins; per-hand counts are
exposed melds standing at hand end.

**Hand value over speed.** It wins twice as often as the bots *and* with bigger hands:

| Winning faan | C1 exit / `EfficiencyBot` | 230.9M / `EfficiencyBot` | 230.9M / `FaanBot` | 462.0M / `FaanBot` |
| --- | --- | --- | --- | --- |
| 3 (the minimum) | 33% / 86% | 21% / 86% | 21% / 75% | 26% / 77% |
| 4 | 24% / 11% | 27% / 12% | 24% / 20% | 22% / 18% |
| 5–7 | 34% / 2.5% | 39% / 2.2% | 41% / 4.5% | 40% / 4.6% |
| 8–9 | 8.0% / 0.1% | 11.2% / 0.2% | 11.0% / 0.1% | 10.3% / 0.5% |
| 10 (cap) | 1.1% / 0.7% | 2.0% / 0.5% | 2.8% / 0.3% | 2.7% / 0.2% |
| points per win | 28.5 / 13.7 | 33.7 / 13.5 | 36.4 / 14.0 | 34.9 / 14.0 |

**Flush and pung hands; the bots scrape 3 faan from minor patterns.** Patterns present in winning
hands:

| Pattern | C1 exit / `EfficiencyBot` | 230.9M / `EfficiencyBot` | 230.9M / `FaanBot` | 462.0M / `FaanBot` |
| --- | --- | --- | --- | --- |
| 混一色 half flush | 52% / 0.9% | 62% / 1.2% | 63% / 1.4% | 46% / 1.5% |
| 清一色 full flush | 7.3% / < 1% | 9.2% / < 1% | 10.8% / < 1% | 10.0% / < 1% |
| 對對糊 all pungs | 16% / 1.8% | 23% / 2.8% | 16% / 2.3% | 21% / 2.9% |
| 箭刻 dragon pung | 33% / 22% | 36% / 21% | 35% / 14% | 30% / 13% |
| 平糊 all chows | 26% / 56% | 15% / 54% | 17% / 61% | 29% / 62% |
| 門前清 concealed | 16% / 39% | 14% / 37% | 16% / 93% | 29% / 93% |
| 自摸 self-draw | 37% / 70% | 28% / 72% | 33% / 55% | 37% / 52% |

**Open, claim-driven, and shifting from chows to pungs.**

| Per seat-hand | C1 exit / `EfficiencyBot` | 230.9M / `EfficiencyBot` | 230.9M / `FaanBot` | 462.0M / `FaanBot` |
| --- | --- | --- | --- | --- |
| hands with an exposed meld | 82% / 84% | 69% / 84% | 75% / 6.8% | 65% / 6.6% |
| chows | 0.78 / 0.78 | 0.38 / 0.81 | 0.42 / 0.01 | 0.37 / 0.01 |
| pungs | 0.77 / 0.61 | 0.89 / 0.61 | 0.89 / 0.11 | 0.77 / 0.11 |
| exposed + added kongs | 0.094 / 0 | 0.112 / 0 | 0.096 / 0 | 0.076 / 0 |
| concealed kongs | 0.025 / 0 | 0.025 / 0 | 0.025 / 0 | 0.031 / 0 |
| wins with an exposed meld | 84% / 60% | 86% / 62% | 84% / 6.3% | 71% / 7.0% |

Neither heuristic bot declares kongs in these hands; the agent does, about once every 9 hands.

**Wins on discards; the table pays it.** 63–72% of its wins are ron vs 28–45% for the bots.
Who fed each discard win:

| Feeds | C1 exit / `EfficiencyBot` | 230.9M / `EfficiencyBot` | 230.9M / `FaanBot` | 462.0M / `FaanBot` (1,000 sets) |
| --- | --- | --- | --- | --- |
| bot → agent | 531 | 665 | 527 | 683 |
| bot → bot | 240 | 244 | 398 | 634 |
| agent → bot | 121 | 89 | 195 | 278 |

Most of the bots' deal-ins go to the agent: it is the table's main threat and the bots don't read it.

**Folds instead of chasing a dead hand.** Tenpai at exhaustive draw 0.45 → 0.34 (vs `EfficiencyBot`
0.98, `FaanBot` 0.51), sub-min tenpai 0.14 → 0.095 vs `EfficiencyBot`'s 0.34, deal-in 0.043 →
0.032 vs 0.092–0.108. Its hands take longer (59–63 turns to win vs 52–58): it builds value and
doesn't race.

**Trend over training** (C1 exit → 10.5M decisions later, same seeds): fewer 3-faan wins (33% →
21%), fewer chows (0.78 → 0.38 per hand) and 平糊 wins (26% → 15%), more 對對糊 (16% → 23%), lower
deal-in and sub-min tenpai — the `min_faan` 3 policy is still moving away from speed.

**Hold end: less one-dimensional, same value** (230.9M → 462.0M vs `FaanBot`, different seed sets
of 700 and 1,000). Half-flush wins 63% → 46%, concealed wins (門前清) 16% → 29%, 平糊 17% → 29%,
hands with an exposed meld 75% → 65%, pungs per hand 0.89 → 0.77, while points per win (36.4 →
34.9), the 5+ faan share (55% → 53%) and full flushes (~10%) hold. The early policy reached value
mostly through one route (open half flush); by the hold's end it also builds closed hands, which a
reader of discards and melds has less to go on. The agent's deal-in rate per seat-hand is
unchanged (0.070), and the bots still feed it 2.5× what it feeds them (683 vs 278).

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

| Self-play against heuristics plateaus fast at the target ruleset | vs `FaanBot` +8.82 at 230.9M, then +7.8 to +9.1 across six checkpoints to 462.0M, all CIs overlapping; the step to `min_faan` 3 took +6.36 → +8.82 in 10.5M decisions | budget ~10–30M decisions at the target ruleset after a curriculum exit, then move on (league); a long pure-self-play hold buys style drift, not measurable strength |
| Slow self-play trends continue after the eval plateau | over the hold: draws 0.33 → 0.29, win 0.166 → 0.179, entropy 0.85 → 0.77, KL and clip fraction falling, explained variance 0.26 → 0.28 | these trends say the learners are still adapting to each other, not that they're getting stronger against outsiders; held-out eval decides |
| Checkpoints trade win rate against hand size at equal strength | 326.0M win 0.260 / 5.01 faan / deal-in 0.052; 429.2M win 0.309 / 4.43 faan / deal-in 0.062; both ≈ +8.2–9.1 | behaviour claims need several checkpoints; a single checkpoint's style is a phase of the attack/defence cycle |
| The style diversifies late | half-flush wins 63% → 46% and concealed wins 16% → 29% from 230.9M to 462.0M at unchanged points per win (§5) | the open-flush route the bots don't read is no longer the agent's only source of value; the league tests whether that holds against opponents that do |
| The pre-league policy already passes R3's numbers | 462.0M on fresh seeds: +9.76 [8.72, 10.79] vs `FaanBot` (1,000 sets), +9.42 to +11.69 vs every profile and `EfficiencyBot`, sub-min tenpai ≤ each opponent's (§4) | the heuristic gate no longer discriminates between candidates; the league's progress has to be read from learned-only measures (Elo, per-snapshot win rate) and later from exploiter gain, with the heuristic gate as a regression floor |
| League rollout costs ~0.7× | run 2: ~1.15k vs the hold's ~1.6k learner decisions/s on the same box | frozen seats take env steps and forwards without producing samples; `seat_learners: 2` is the lever if throughput matters more than opponent coverage |

What to watch in R3 (league): self-play draw rate together with held-out eval (above);
`FaanBot`-table sub-min tenpai staying ≤ the bots'; sub-min tenpai under the new `hk_casual` /
`hk_strict` hands (0.084 rolling at the league's start vs ~0.04 at the hold's end); whether the
learner pulls ahead of its own past snapshots (win rate vs `past*` above 0.5, Elo rising) while
the heuristic score holds at +8–10; whether the closed-hand share keeps growing against opponents
that read open hands, since the heuristic bots largely don't (§5).
