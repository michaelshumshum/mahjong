# RL learnings

What training the self-play agent ([ml.md](ml.md)) has shown so far: curriculum progress, how the
training metrics move, evaluation against the heuristic bots and between checkpoints, and how the
agent plays. A living record — later runs append rows to the tables and findings to §6. Milestone
results (the R2 and R3 gate criteria) are kept in [ml.md §14](ml.md); this doc has the series and
per-opponent detail behind them.

| Run | Milestone | Config | Decisions | Checkpoint names |
| --- | --- | --- | --- | --- |
| 1 | R2 cold start (C0 → C1 exit at 220.4M), then the C1 hold | `rl_ppo_c0.yaml`, `hold_final: true` | 0 → 464.3M | cumulative decisions: `220.4M` (C1 exit), `462.0M` (last hold eval checkpoint, the pre-league gate candidate), `464.3M` (hold end, `ckpt_hold_final.pt`, the league's starting policy) |
| 2 | R3 league (C2) | `rl_league.yaml`, `init_ckpt` = 464.3M | counter restarts at 0 | `L` + decisions since the league started: `L274.3M` = 274.3M league decisions on top of 464.3M |

Terms: *sub-min tenpai* is `tenpai_rate_on_sub_minimum_hand`: of a side's hands tenpai at
exhaustive draw, the share whose waits can't reach `min_faan` ([bots.md §4](bots.md),
[ml.md §4](ml.md)); *head-to-head* is policy vs policy on duplicate hands (§4); *PFSP* is the
league's opponent sampling ([ml.md §11](ml.md)). Points are per hand throughout, except the
heuristic arena's per-game figure in §4.

## 1. Setup

| | Run 1 (R2, `rl_ppo_c0.yaml`, `hold_final: true`) | Run 2 (R3, `rl_league.yaml`) |
| --- | --- | --- |
| hardware | RTX 2060 6 GB (learner + rollout forward), i5-10400F 6 cores / 12 threads (envs), WSL2 ([ml.md §13](ml.md)) | same |
| envs | 10 workers × 16 = 160 envs; 12.5% blind envs; torch 2 threads | same; league opponents per hand ([ml.md §11](ml.md)) |
| update | batch 4,096 learner decisions, 2 epochs × minibatch 512, AdamW 3e-4, clip 0.2, entropy 0.01 ([ml.md §9](ml.md)) | same, `policy_loss: ppo` |
| model | `PolicyNet` 459k params + `OracleCritic` 427k (96 ch × 6 blocks), initialised from the R1 auxiliary-pretrained checkpoint | same nets, whole learner (critic, PopArt, AdamW) loaded from run 1's hold end (464.3M) |
| ruleset | `hk_classic` (`min_faan` stepped by the curriculum, [ml.md §10](ml.md)) | C2: `hk_classic` `min_faan` 3, 10% `hk_casual`, 10% `hk_strict` hands |
| throughput | end to end 1.1–1.7k decisions/s (1.58–1.65k through the hold); rollout 2.6–3.8k/s, learner ~2.9–3.0k/s | ~1.1k learner decisions/s end to end (segment means 1.05–1.18k, §3; rollout 2.17 s + update 1.50 s per 4,096-decision batch early on): 0.7× run 1's hold, frozen seats step without producing samples |

Metrics before 98.6M decisions are under an earlier scoring table (engine 1.0.0,
[ADR 0020](decisions/0020-hk-scoring-table-alignment.md)); compare within a segment.

Evaluation seed sets (`eval_policy --seed`, the first duplicate set's `HandEnv` episode seed,
[ml.md §12](ml.md)). A range used for a gate is never reused for tuning or another gate; pick the
next free range for a new one. Below 2,000,000 belongs to `bots.arena`'s heuristic-bot tuning and
the `OracleFaanBot`-era `ORACLE` gates (seeds 1+, 1,000,000+, [bots.md §7, §9](bots.md)); `eval_policy`'s default `--seed`
(1,000,000) falls there, so always pass one.

| Seeds | Sets | Used for |
| --- | --- | --- |
| 2,000,000+ | 200 | R2 smoke checkpoint vs `EfficiencyBot` (§7) |
| 3,000,000+ | 700 | R2 gate (C1 exit) and the 230.9M checks (§4) |
| 4,100,000+ | 500 → 1,000 | progress series vs `FaanBot`, both runs (§4); fixed, so checkpoints compare on identical hands |
| 5,000,000+ | 1,000 / 700 | pre-league gate, 462.0M (§4) |
| 6,000,000+ | 3,000 per direction | league head-to-head series vs the starting policy (§4) |
| 6,100,000+ – 6,400,000+ | 1,500–2,000 | head-to-head analysis, results not kept in the repo: sampled-mode head-to-head (6.1M, 2,000 sets), hold 462.0M vs 429.2M control (6.2M), `hk_strict` / `hk_casual` head-to-heads (6.3M, 1,500 sets), learner L91.8M vs snapshot `past1` (6.4M) |
| 7,000,000+, 7,100,000+ | 1,000 / 700; 1,500 head-to-head | R3 gate, L274.3M and 464.3M (§4); later league checkpoints are compared against L274.3M here |
| 8,000,000+ | 1,000 | evals vs `OracleFaanBot` (then named `ORACLE`): L274.3M, 464.3M and `FaanBot` ×1 vs it ×3; it / `FaanBot` ×1 vs L274.3M ×3; L274.3M vs `FaanBot` (§4) |
| 9,000,000+ | 1,000 / 700 | R4 gate re-run, `LearnedBot` (the shipped numpy path) (§4); 9,500,000+ and 9,900,000+ hold the R4 action-agreement and pool-load samples (`HandEnv` states, not evals) |
| 10,000,000+ | 1,000 | `OracleLearned` prototype (tuning, not a gate): both seatings vs `LearnedBot` ×3, vs `FaanBot` ×3, `OracleFaanBot` vs `LearnedBot` ×3 ([ADR 0022](decisions/0022-oracle-learned-tier.md)) |
| 11,000,000+ | 1,000 / 700 | Impossible gate for `learned.npz` L274.3M ([ADR 0022](decisions/0022-oracle-learned-tier.md)): `ORACLE` both seatings vs `LearnedBot` ×3 (1,000), `ORACLE` vs `FaanBot` ×3 (700); plus `OracleFaanBot` vs `LearnedBot` ×3 (1,000) and `LearnedBot` vs `FaanBot` ×3 (700) |
| 12,000,000+ | 1,000 / 700 | behaviour analysis (§5), not a gate: L274.3M, 464.3M, L358.5M and `FaanBot` (as candidate) each vs `FaanBot` ×3 (1,000); L274.3M vs `EfficiencyBot` ×3, `EfficiencyBot` vs `FaanBot` ×3, L274.3M vs `LearnedBot` ×3 (700). The candidate seat sees identical tiles in every file |
| 13,000,000+ | 1,000 / 700 | Expert gate re-run after concealed kongs became public, same `learned.npz` ([ADR 0023](decisions/0023-concealed-kong-public.md)) |
| 14,000,000+ | 1,000 / 700 | Impossible gate re-run, same change ([ADR 0023](decisions/0023-concealed-kong-public.md)) |
| 15,000,000+ | — | next free range |

New weights take two fresh ranges, one for the Expert gate and one for the Impossible gate
([bots.md §2](bots.md) "Shipping new weights", steps 4–5).

The head-to-head harness is `runs/ppo_league_snap/tools/h2h_eval.py` on the training box
(gitignored, not in `ml/`).

## 2. Curriculum progress

| Stage | Updates | Decisions | Anneal | Exit |
| --- | --- | --- | --- | --- |
| C0 | 1–51 | 0 → 0.21M | — | rolling win ≥ 0.40 at update 51 (0.398 one update earlier) |
| C0b | 52–4,853 | 0.21M → 20.32M | 20M, complete at 20.22M | rolling blind win 0.405 (threshold 0.25). The 50-update mean of batch blind win was already ≥ 0.25 at 0.43M: the anneal was the binding constraint |
| C1 | 4,854–52,402 | 20.33M → 220.40M | 200M; `min_faan` 0 → 1 at 120.33M, → 3 at 220.33M (update 52,385) | 17 updates after the anneal: rolling win 0.1995, sub-min tenpai 0.108 (251 tenpai draws), draws 20.2%, deal-in 0.099 over 4,000 hands |
| C1 held | 52,403–110,201 | 220.40M → 464.27M | — | stopped for the R3 league run (`hold_final`) |
| C2 (run 2) | 1– | L0 → L358.5M (2026-10-12), still running | — | none (the league runs to the 2B budget); R3 gate passed at L274.3M ([ml.md §14](ml.md)) |

C1 exit thresholds: win ≥ 0.15, sub-min tenpai ≤ 0.32 ([ml.md §10](ml.md)).

## 3. Training metrics

Run 1 segment means of the per-update `metrics.jsonl` records (batch rates are per learner
seat-hand; C0/C0b against tsumogiri opponents, C1 self-play over four learner seats).

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

Run 1, held at `min_faan` 3, rolling window (4,000 hands):

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

Run 2 segment means (per-update records; win / draw / deal-in are per learner seat-hand across
all league tables). The league config changed at 190.0M (per-preset reward scaling, points-based
PFSP/Elo, 400-update personas; [ml.md §11](ml.md), §6 below):

| Decisions (M) | Win | Draw | Self-play draw | Deal-in | Sub-min tenpai (rolling) | Entropy | KL | Expl. var | PopArt σ | Decisions/s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0–50 | 0.160 | 0.344 | 0.347 | 0.099 | 0.055 | 0.93 | 0.004 | 0.17 | 1.64 | 1,178 |
| 50–100 | 0.158 | 0.358 | 0.357 | 0.096 | 0.058 | 0.95 | 0.004 | 0.15 | 1.73 | 1,129 |
| 100–150 | 0.163 | 0.343 | 0.339 | 0.101 | 0.055 | 0.93 | 0.004 | 0.15 | 1.75 | 1,089 |
| 150–190 | 0.162 | 0.344 | 0.345 | 0.100 | 0.053 | 0.95 | 0.004 | 0.15 | 1.77 | 1,083 |
| **190–210** (redesign) | 0.168 | 0.328 | 0.327 | 0.100 | 0.047 | 0.85 | 0.004 | 0.27 | 0.74 | 1,066 |
| 210–250 | 0.168 | 0.329 | 0.329 | 0.099 | 0.049 | 0.84 | 0.004 | 0.27 | 0.74 | 1,059 |
| 250–296.7 | 0.169 | 0.323 | 0.322 | 0.101 | 0.049 | 0.84 | 0.004 | 0.27 | 0.77 | 1,051 |
| 296.7–330 | 0.173 | 0.310 | 0.308 | 0.102 | 0.048 | 0.82 | 0.004 | 0.27 | 0.74 | 1,028 |
| 330–358.5 | 0.167 | 0.331 | 0.333 | 0.097 | 0.045 | 0.82 | 0.004 | 0.27 | 0.74 | 1,043 |

Each 50M snapshot adds a past snapshot and two persona forks (≤ 32 past, ≤ 8 personas kept); a
fork pauses training ~565 s at 100 persona updates, 2,170–2,255 s at 400 (measured at the 200M–350M forks). The step at 190M is the
reward scaling: PopArt σ, explained variance and entropy returned to the hold's levels within
~1M decisions and stayed there.

PopArt μ tracks the mean shaped return (1.6–3.1 in C0/C0b, 0.91 → 0.03 over C1, ~0.01 held):
self-play payments are zero-sum, so μ → 0 as β → 0 is a sanity check on the shaping.

## 4. Evaluation over training

Candidate × 1 vs bot × 3, paired-duplicate per hand, `hk_classic` (`min_faan` 3), points per hand
([ml.md §12](ml.md)). Checkpoints were trained at the `min_faan` shown in §3 but are always
evaluated at 3.

Run 1 progress vs `FaanBot`, fixed seeds 4,100,000+, 500 sets:

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

Run 1 on fresh seeds 3,000,000+, 700 sets (the R2 gate seed set):

| Checkpoint | Opponent | Diff [95% CI] (bootstrap) | Win | Deal-in | Avg win faan | Sub-min tenpai | Tenpai at draw | Turns to win | Table draws |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **220.4M, C1 exit (R2 gate)** | `EfficiencyBot` | **+8.74 [7.67, 9.80]** ([7.69, 9.81]) | 0.299 / 0.145 | 0.043 / 0.092 | 4.64 / 3.22 | 0.140 / 0.335 | 0.448 / 0.983 | 59.4 / 53.6 | 26.7% |
| 230.9M, held | `EfficiencyBot` | +12.50 [11.30, 13.71] ([11.32, 13.73]) | 0.331 / 0.141 | 0.032 / 0.108 | 5.04 / 3.21 | 0.095 / 0.352 | 0.336 / 0.984 | 63.1 / 51.6 | 24.5% |
| 230.9M, held | `FaanBot` | +10.67 [9.32, 12.03] ([9.34, 12.07]) | 0.280 / 0.157 | 0.070 / 0.110 | 5.10 / 3.33 | 0.059 / 0.029 | 0.387 / 0.514 | 60.1 / 57.8 | 25.0% |

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
opponent's but `FaanBotAggressive`'s (0.049 / 0.046). `FaanBotDefensive` is the closest matchup and
the drawiest table (33%).

Run 2 (league) checkpoints, vs `FaanBot` on seeds 4,100,000+ (500 sets to L96.3M, 1,000 after;
the first 500 seeds are shared with run 1's series) and head-to-head against the league's starting
policy (464.3M) at `hk_classic`: `PolicyBot` vs `PolicyBot` duplicate, 3,000 sets each of league
×1 vs start ×3 and ×3 vs ×1 on seeds 6,000,000+, combined as the mean of the two diffs (bootstrap
CI):

| Checkpoint | vs `FaanBot` | Sub-min tenpai (agent / bot) | Head-to-head vs start [95% CI] |
| --- | --- | --- | --- |
| L23.2M | +8.53 [7.29, 9.82] | 0.026 / 0.027 | — |
| L48.4M | +8.37 [7.11, 9.69] | 0.027 / 0.032 | — |
| L72.0M | +9.07 [7.77, 10.42] | 0.038 / 0.027 | −0.42 / +0.38 (×1 / ×3 separately, vs 462.0M rather than 464.3M; no CI recorded) |
| L96.3M | +9.61 [8.33, 10.93] | 0.048 / 0.040 | — |
| L119.1M | +11.00 [9.90, 12.15] | 0.067 / 0.036 | −0.28 [−0.72, +0.16] |
| L142.4M | +10.04 [8.98, 11.11] | 0.037 / 0.036 | −0.27 [−0.69, +0.16] |
| L165.0M | +9.28 [8.29, 10.30] | 0.031 / 0.037 | −0.32 [−0.75, +0.10] |
| L188.2M | +9.31 [8.31, 10.35] | 0.025 / 0.028 | **−0.83 [−1.27, −0.39]** |
| *redesign at 190.0M* | | | |
| L208.7M | +9.88 [8.84, 10.94] | 0.036 / 0.031 | −0.05 [−0.47, +0.38] |
| L231.3M | +10.57 [9.53, 11.63] | 0.041 / 0.038 | +0.14 [−0.29, +0.57] |
| L251.7M | +9.66 [8.68, 10.66] | 0.032 / 0.039 | −0.39 [−0.79, +0.02] |
| L274.3M | +10.66 [9.62, 11.73] | 0.043 / 0.035 | +0.14 [−0.29, +0.58] |
| L296.6M | +9.54 [8.57, 10.57] | 0.018 / 0.036 | −0.08 [−0.50, +0.34] |
| L316.3M | +10.59 [9.55, 11.69] | 0.035 / 0.038 | +0.47 [+0.03, +0.91] |
| L338.5M | +9.70 [8.72, 10.72] | 0.016 / 0.032 | −0.11 [−0.54, +0.31] |
| L358.5M | +10.40 [9.32, 11.50] | 0.040 / 0.040 | +0.26 [−0.15, +0.67] |

Since the redesign the head-to-head averages +0.05 over eight checkpoints (−0.39 to +0.47).
L316.3M's +0.47 was the only CI above zero and the next checkpoint fell back to −0.11, so it
reads as the top of the noise band, not a step. Against itself the league policy trades the same
way it does against the bots: it wins less often (0.16–0.19 vs 0.19–0.22 for the starting
policy) and, through L338.5M, deals in more (0.11–0.13 vs 0.09–0.11), making it up in hand size.
At L358.5M the deal-in gap closed (0.104 / 0.105 at ×1 vs ×3, 0.102 / 0.102 at ×3 vs ×1) with
average winning faan still ~5.2 vs `FaanBot` ×3, and its deal-in vs `FaanBot` (0.057) was the
lowest of either run.

R3 gate (2026-10-11), per-side detail: L274.3M, chosen as the latest checkpoint, and the league's
starting policy on the same fresh seeds 7,000,000+ (head-to-head 7,100,000+). The criteria and
their status are in [ml.md §14](ml.md):

| Opponent / test | Sets | Starting policy (464.3M) | **L274.3M** | Win (L274.3M / opp) | Avg win faan | Sub-min tenpai (L274.3M / opp; start / opp) |
| --- | --- | --- | --- | --- | --- | --- |
| **`FaanBot`** | 1,000 | +9.99 [9.02, 10.96] | **+10.94 [9.87, 12.10]** | 0.266 / 0.164 | 5.28 / 3.33 | 0.031 / 0.034; 0.045 / 0.035 |
| `EfficiencyBot` | 700 | +11.32 [10.12, 12.53] | **+14.48 [13.12, 15.85]** | 0.326 / 0.148 | 5.41 / 3.18 | 0.100 / 0.339; 0.082 / 0.341 |
| `FaanBotAggressive` | 700 | +10.74 [9.55, 11.92] | +12.30 [10.93, 13.66] | 0.284 / 0.165 | 5.38 / 3.33 | 0.048 / 0.032; 0.032 / 0.034 |
| `FaanBotDefensive` | 700 | +9.60 [8.46, 10.74] | +9.88 [8.53, 11.23] | 0.237 / 0.145 | 5.25 / 3.33 | 0.037 / 0.041; 0.047 / 0.027 |
| `FaanBotFlushChasing` | 700 | +10.03 [8.86, 11.22] | +10.73 [9.42, 12.06] | 0.265 / 0.160 | 5.27 / 3.35 | 0.025 / 0.036; 0.041 / 0.028 |
| `FaanBot`, `hk_strict` (`min_faan` 5) | 700 | +17.42 [15.98, 18.90] | **+25.04 [23.28, 26.87]** | 0.326 / 0.009 | 6.63 / 5.81 | 0.208 / 0.919; 0.292 / 0.919 |
| `FaanBot`, `hk_casual` (`min_faan` 1) | 700 | +14.50 [9.87, 19.96] | +18.98 [11.56, 29.07] | 0.125 / 0.281 | 4.54 / 1.85 | — |
| head-to-head L274.3M ×1 vs start ×3, `hk_strict` | 1,500 | | **+2.47 [+1.51, +3.48]** | 0.155 / 0.135 | | |
| same, `hk_casual` | 1,500 | | +4.04 [−4.44, +13.39] | 0.164 / 0.207 | | |

`hk_strict` tables draw 65–72% of hands: `FaanBot` almost never reaches 5 faan (win 0.009).
`hk_casual` payouts are heavy-tailed (13-faan cap on the full-spicy table), hence the wide CIs.

**R4 gate re-run** (2026-10-12, [ml.md §14](ml.md) R4): the same L274.3M weights through the
shipped path — `BOT_REGISTRY["LearnedBot"]`, numpy forward from `bots/weights/learned.npz` —
via `eval_policy --candidate-bot LearnedBot --parallel 6`, `hk_classic`, fresh seeds 9,000,000+
(every opponent on the same seeds, as R3). Points per hand; the R3 column is `PolicyBot` (torch)
on 7,000,000+:

| Opponent ×3 | Sets | R3 (7,000,000+) | **R4 re-run [95% CI]** (bootstrap) | Win (agent / opp) | Deal-in | Avg win faan | Sub-min tenpai | Table draws |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `FaanBot` | 1,000 | +10.94 | **+10.75 [9.64, 11.86]** ([9.67, 11.89]) | 0.267 / 0.160 | 0.076 / 0.105 | 5.26 / 3.37 | 0.033 / 0.032 | 25.4% |
| `EfficiencyBot` | 700 | +14.48 | **+15.19 [13.74, 16.64]** ([13.73, 16.62]) | 0.329 / 0.143 | 0.027 / 0.112 | 5.44 / 3.26 | 0.095 / 0.349 | 24.1% |
| `FaanBotAggressive` | 700 | +12.30 | **+11.62 [10.34, 12.90]** ([10.35, 12.96]) | 0.284 / 0.168 | 0.074 / 0.119 | 5.28 / 3.37 | 0.042 / 0.036 | 21.1% |
| `FaanBotDefensive` | 700 | +9.88 | **+10.85 [9.52, 12.19]** ([9.52, 12.26]) | 0.251 / 0.146 | 0.067 / 0.092 | 5.28 / 3.35 | 0.036 / 0.039 | 31.2% |
| `FaanBotFlushChasing` | 700 | +10.73 | **+11.72 [10.43, 13.01]** ([10.42, 13.03]) | 0.285 / 0.154 | 0.072 / 0.109 | 5.22 / 3.37 | 0.046 / 0.033 | 25.3% |

Every R3 estimate falls inside the re-run's CI; the agent's win rate is within 0.02 and its
average winning faan within 0.1 of R3's per-side detail above. The `FaanBot` run predates the overflow-free sigmoid in
`ml/export.py` (equal within float error); the other four ran with it.

**vs `ORACLE`** (2026-10-12, `hk_classic`, 1,000 sets on seeds 8,000,000+, `eval_policy
--opponent ORACLE`; the 1 × policy-table rows from a scratch harness on the same seeds). `ORACLE`
here is the hands-aware `FaanBot`, the tier before [ADR 0022](decisions/0022-oracle-learned-tier.md)
(now `--opponent OracleFaanBot`). Points per
hand, paired diff = the ×1 side minus the mean of the ×3 side:

| ×1 vs ×3 | Paired diff [95% CI] (bootstrap) | ×1 win / deal-in / avg faan | ×3 win / deal-in / avg faan |
| --- | --- | --- | --- |
| L274.3M vs `ORACLE` | **+2.88 [+1.75, +4.01]** ([+1.77, +4.00]) | 0.112 / 0.162 / 5.93 | 0.217 / 0.000 / 3.47 |
| 464.3M vs `ORACLE` | +3.06 [+1.98, +4.15] | 0.136 / 0.149 / 5.36 | 0.215 / 0.000 / 3.44 |
| `FaanBot` vs `ORACLE` | −3.69 [−4.08, −3.30] | 0.097 / 0.149 / 3.56 | 0.220 / 0.000 / 3.44 |
| L274.3M vs `FaanBot` (same seeds) | +11.44 [+10.33, +12.56] | 0.271 / 0.067 / 5.35 | 0.155 / 0.106 / 3.34 |
| `ORACLE` vs L274.3M | −1.53 [−2.22, −0.84] | 0.266 / 0.000 / 3.30 | 0.168 / 0.128 / — |
| `FaanBot` vs L274.3M | −9.26 [−10.14, −8.39] | 0.170 / 0.165 / 3.32 | 0.206 / 0.104 / — |

Draws 22–27% on every table; sub-min tenpai 0.021 (L274.3M) / 0.040 (`ORACLE`). The agent
outscores `ORACLE` from either seating. Paired on identical hands, L274.3M ×1 does +6.56
[+5.45, +7.70] better than `FaanBot` ×1 against `ORACLE` ×3; the league didn't move this number
(464.3M +3.06 vs L274.3M +2.88). Where its points go against `ORACLE` ×3, compared with a
`FaanBot` ×3 table on the same seeds (per agent seat-hand):

| Source | vs `FaanBot` ×3 | vs `ORACLE` ×3 | Δ |
| --- | --- | --- | --- |
| own ron wins | +5.29 (0.173 / hand) | 0 (none) | −5.29 |
| own self-draw wins | +5.48 (0.098) | +6.89 (0.112) | +1.41 |
| deal-ins | −0.75 (0.067) | −1.62 (0.162) | −0.87 |
| opponents' self-draws | −1.44 (0.253) | −3.11 (0.490) | −1.67 |

`ORACLE` never deals in (0 of 12,000 seat-hands), so the agent's ron income goes to zero; it
plays closed (6% of its seat-hands open a meld, 92% of its wins concealed), so its tenpai has no
meld tell. The agent's 630 discards that dealt in (decision replay with `ml.env.replay_hand`):
629 had a really safe alternative; 292 / 148 / 190 at 0 / 1 / 2+ shanten after the discard; the
agent's own danger head rated the tile median P(deal-in) 0.008 (safest alternative 0.001) and
the real winner's tenpai median 0.16. Of `ORACLE`'s 72,039 decisions that differ from plain
`FaanBot` on a public view at the same state, 88% are full-information speed (`seen34`), 7%
tenpai valuation, 5% avoided deal-ins (1,469 of them avoided dealing into the agent), and 86 claims.

**Impossible tier: `OracleLearned`** ([ADR 0022](decisions/0022-oracle-learned-tier.md)). The
`ORACLE` tier now plays `LearnedBot`'s policy (L274.3M, `learned.npz`) with exact-information
vetoes: it never discards into a known deal-in when a safe alternative exists; the network input
is a plain `seat_view`. `hk_classic`, points per hand, paired diff [95% CI]:

| ×1 vs ×3 | Prototype (10,000,000+, 1,000 sets) | **Gate (11,000,000+)** |
| --- | --- | --- |
| `OracleLearned` vs `LearnedBot` | +3.33 [+2.89, +3.76] | **+3.60 [+3.15, +4.06]** |
| `LearnedBot` vs `OracleLearned` | −4.20 [−4.77, −3.62] | **−4.51 [−5.15, −3.88]** |
| `OracleLearned` vs `FaanBot` | +13.14 [+12.04, +14.24] | +12.54 [+11.21, +13.87] (700 sets) |
| `OracleFaanBot` vs `LearnedBot` | −1.90 [−2.59, −1.21] | −0.78 [−1.46, −0.10] |
| `LearnedBot` vs `FaanBot` | +12.29 [+11.16, +13.41] | +11.62 [+10.27, +12.98] (700 sets) |

Prototype variants on the same seeds: a shanten-floor "push" override, level with `LearnedBot`
(+0.18 [−0.68, +1.05]; average winning faan fell to 4.24, dropped); the frozen oracle adapter
(`learner.adapter`, unchanged since `keep_prob` reached 0 at the C1 end) alone +1.82 [+0.75,
+2.90], with the vetoes +4.41 [+3.40, +5.43], +1.09 [+0.03, +2.14] over the vetoes alone (not
shipped). Paired on identical hands `OracleLearned` scores +5.23 [+4.42, +6.03] more than
`OracleFaanBot` against `LearnedBot` ×3 (gate seeds: +4.38 [+3.58, +5.19]); against `FaanBot`
×3 the vetoes add +0.85 to +0.92 to the plain policy. `OracleLearned` deals in at 0.0015 per
seat-hand and wins at 5.2 faan; `OracleFaanBot` at 0 and 3.3. Laptop p99 per decision: 2.13 ms
(`OracleFaanBot` 11.57 ms, `LearnedBot` 1.67 ms).

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

**Decision level** (2026-10-12, seeds 12,000,000+, §1). Every candidate decision with more than
one legal action replayed with `ml.env.replay_hand`'s recipe: the policy's probabilities from the
plain `seat_view`, shanten after each legal discard, and each discard's exact deal-in (omniscient,
analysis only). Columns are the candidate seat on identical tiles: L274.3M (the shipped Expert
weights, torch path) and `FaanBot`, each ×1 vs `FaanBot` ×3, 4,000 seat-hands and ~67k discards
each; `EfficiencyBot` ×1 vs `FaanBot` ×3, 2,800. Scripts and rows:
`server/runs/behaviour/` (gitignored). Measured facts first; the reading of them is in italics.

**Direction is set by discard 3–6 and is public by discard 6.** It throws middle tiles and keeps
honours; the bots do the reverse:

| Own discards 1–3 | L274.3M | `FaanBot` | `EfficiencyBot` |
| --- | --- | --- | --- |
| dragons | 1.3% | 17.8% | 21.4% |
| seat / prevailing wind | 1.5% | 17.2% | 18.0% |
| other winds | 3.0% | 20.3% | 22.0% |
| terminals | 17% | 23% | 25% |
| 2–8 | 77% | 22% | 14% |
| holding a lone value honour (discards 1–6): discards one that turn | 5.1% | 52% | 62% |
| shanten-raising discards, discards 1–3 / 4–6 / 7–9 | 29% / 25% / 16% | 27% / 35% / 35% | 0 |

The honours come out late instead (14% of its discards from the 13th on are dragons, `FaanBot` 9%).
Hands with ≤ 2 tiles outside one suit (+ honours) at its 4th / 7th / 10th / 13th discard: 12% /
39% / 61% / 69%; `FaanBot` ≤ 1.3% throughout. 74% of its wins are half or full flushes (`FaanBot`
1.4%). Over its 816 flush wins, the suit it had discarded least over its first 3 discards was the winning
suit (and unique) in 77%, over its first 6 in 96% — a reader of its pool alone knows the suit.

**Claims follow the direction.** Taken / offered, offers without a win option:

| Offer | L274.3M | `FaanBot` | `EfficiencyBot` |
| --- | --- | --- | --- |
| pung, all | 70% (5,607) | 5.6% (6,868) | 49% (3,484) |
| pung of a dragon / seat-prevailing wind / other wind | 89% / 86% / 78% | 10% / 9% / 7% | 53% / 60% / 58% |
| pung of a 2–8 tile | 59% | 3.5% | 40% |
| pung, tile in / outside its main suit | 70% / 32% | 4.0% / 4.5% | 48% / 43% |
| pung that doesn't lower shanten | 37% (1,132) | 0 | 0 |
| chow, all | 26% (6,979) | 0.5% | 27% |
| chow, tile in / outside its main suit | 33% / 0.8% | 0.7% / 0.4% | 24% / 29% |
| chow, own discards 1–6 / 13+ | 16% / 28% | 0.8% / 0.2% | 59% / 5.5% |
| exposed kong offer: kong / pung / pass | 0 / 18% / 80% (405) | 0 / 0.4% / 99.6% | 0 / 4% / 96% |

The policy is near-deterministic on claims (mean probability of its chosen claim action 0.95; on
own-turn decisions 0.66, below 0.6 in 47% of them).

**Declines cheap rons to build, never declines a self-draw.** `PASS` (or a pung / chow) on a legal
win:

| Legal win | 464.3M | L274.3M | L358.5M | `FaanBot` | `EfficiencyBot` |
| --- | --- | --- | --- | --- | --- |
| ron, 3 faan | 20% (255) | 11% (162) | 3.0% (167) | 0 (241) | 0 (115) |
| ron, 4 faan | 2.9% (207) | 9.4% (180) | 3.5% (202) | 0 | 0 |
| ron, 5–6 faan | 0.4% (233) | 12% (263) | 2.5% (238) | 0 | 0 |
| ron, 7+ faan | 0 (137) | 4.0% (198) | 2.7% (149) | 0 | 0 |
| ron, all | 7.1% | 9.3% | 2.9% | 0 | 0 |
| self-draw, any faan | 0 (420) | 0 (374) | 0 (385) | 0 (354) | 0 (344) |

L274.3M's 75 declines: median wall 48 (accepted wins: 24), mean declined value 4.7 faan; 51 of the
75 hands it went on to win, at a mean 5.5 faan, and the hand ended at +26.9 points per decline
against +23.5 had it taken the ron (selection-biased: the comparison holds the declined win's value
fixed). On the `EfficiencyBot` table it declines 2.3%, on its own table 8.1%. *The decline rule is
not stable across checkpoints (464.3M declined 3-faan rons, L274.3M 5–6 faan, L358.5M almost none):
an early-wall "this hand can still grow" bet that the league keeps re-learning, not a fixed trait.*

**Keeps tenpai unless the wait is dead.** With a tenpai discard available (10,452 decisions) it
keeps tenpai 95% (`FaanBot` 97%, `EfficiencyBot` 100%); 97% when some wait clears `min_faan`, 80%
when every wait is dead or sub-minimum (`FaanBot` 96%, `EfficiencyBot` 100%). Choosing among
several tenpai discards it takes the highest-value wait 96% of the time, the widest 88%
(`FaanBot` 91% / 87%).

**Push/fold.** Fold = a shanten-raising discard; per discard, L274.3M / `FaanBot`:

| Max opponent exposed melds | own tenpai after | 1-shanten | 2+-shanten |
| --- | --- | --- | --- |
| 0 | fold 5.0% / 3.5% | 11% / 23% | 21% / 29% |
| 2 | 7.3% / 2.3% | 11% / 15% | 21% / 31% |
| 3+ | 8.5% / 2.3%, deal-in 2.7% / 1.2% | 19% / 8.5% | 25% / 18% |

With an opponent really tenpai and a live tile in hand, it discards a live tile 12.5% of the time
when tenpai itself (`FaanBot` 9.2%), 7.7% at 1-shanten (5.9%), 8.7% at 2+ (5.8%); deal-in per
discard is level with `FaanBot`'s (1.1–1.7%). Genbutsu against the most-melded opponent (≥ 2
melds): 33–36% of its discards vs 20–23% of its legal tiles (`FaanBot` 30–36% vs 18–27%). In the
last 5 wall tiles it folds 18% of discards (`FaanBot` 2.9%) at the same deal-in per discard (1.3% /
1.9%). *Unlike `FaanBot`, its folding rises with the table's meld count, not just with turn; at
2+-shanten it folds less than `FaanBot` because it is still building (its shanten-raising
discards early are flush-building, not defence).*

**No suit reading.** Against an opponent whose ≥ 2 exposed suited melds are all one suit, its
discards are in that suit 27% of the time vs 25% of its legal tiles (262 decisions; `FaanBot` 20%
vs 32%). On its own table (12,364 decisions) 42% vs 31%, and those in-suit discards deal in 1.8%
vs 1.1% for its other discards.

**Kongs: about one opportunity in two.** Concealed kong: declared on 65% of (hand, tile)
opportunities, 56% at the first chance; added kong 72% / 60%; neither rate moves with being
tenpai, wall, or an opponent being tenpai. Neither heuristic bot ever declares one (483 / 46
concealed / added kong decisions for `FaanBot`). Exposed kong offers are passed (above).

**Seat and flowers.** Dealer +10.4 points/hand vs +8.3 non-dealer (win 31% / 26%), `FaanBot`
+0.25 / −0.08. With no flowers it wins 31% (1–3 flowers 26–28%), as does `FaanBot` (25% vs
12–17%): 無花 is a free faan toward `min_faan`. 門風 / 圈風 appear in 13% / 12% of its wins.

**Over training** (464.3M → L274.3M → L358.5M, same 4,000 seat-hands): points/hand +7.8 / +8.9 /
+7.9; average win faan 4.95 / 5.40 / 5.12; flush wins 63% / 74% / 73%; all-pungs wins 17% / 20% /
13%; hands one-suited by the 10th discard 53% / 61% / 63%; lone value honour thrown early 11% / 5.1%
/ 5.2%; chow acceptance 16% / 26% / 18%; pung of an off-suit tile 28% / 32% / 19%; exposed-kong
offers ponged 40% / 18% / 67%; tenpai at exhaustive draw 34% / 47% / 37%. *The league kept the
direction (earlier and more committed flush building, honours held longer) and swings the claim and
decline thresholds checkpoint to checkpoint.*

Not yet measured, worth doing next: the same decision-level breakdown against `ORACLE` and mixed
tables; a controlled suit-reading probe (the same state with an opponent's melds moved to another
suit).

## 6. Findings for future runs

| Area | Finding | Evidence | Implication |
| --- | --- | --- | --- |
| Curriculum | Curriculum anneals, not thresholds, set the pace | C0 exited at 0.21M; C0b's blind-win threshold was met by ~0.43M but the stage ran its full 20M anneal; C1 exited 17 updates after its 200M anneal | candidate to shorten the C0b anneal (and test a shorter C1 anneal) in the next run |
| Curriculum | Explained variance falls as the oracle and shaping anneal | C1 0.6–0.8 at keep ≥ 0.5, 0.20 at keep / β → 0, ~0.26 held | expected: the shaping term is predictable, unshaped zero-sum payouts are not. Low EV at the end of C1 is not by itself a critic failure; watch it within a held segment |
| Curriculum | Self-play per-seat win = (1 − draws) / 4 | C1 batch win 0.233 with 7% draws; exit window 0.194 with 22.5% draws | the C1 win threshold is a draw cap (≤ 40%), not a strength measure; strength comes from the held-out eval (§4) |
| Curriculum | At `min_faan` 0–1 the agents learn speed | C1 self-play draws 2–8%, deal-in ~0.16; eval sub-min tenpai stays 0.15–0.19 through 167M | low `min_faan` stages build hand-making, not value-building; the value play only appears once `min_faan` 3 is trained |
| Curriculum | Sub-min tenpai only falls once `min_faan` 3 is trained | eval 0.192 (98.6M, `min_faan` 0) → 0.149–0.159 (`min_faan` 1) → 0.104 at exit → 0.045 after 10.5M at `min_faan` 3 | the step to 3 does more in 10M decisions than 100M at 1 did; most training budget belongs at the target ruleset |
| Curriculum | The C1 exit window mostly measures the transition | the 4,000-hand window fills in ~17 updates after `min_faan` hits 3; exit draws 20%, settled held draws 31–37% (one dip to 52% at 223M) | the exit numbers are a snapshot of a policy trained at `min_faan` 1; don't read them as the converged C1 behaviour |
| Curriculum | Entropy rises as the oracle is removed | C1 0.66 → 0.80; held ~0.85; KL 0.007, clip 0.07 throughout | no collapse; the policy stays stochastic at the target ruleset |
| C1 hold | Rising self-play draws were mutual defence, not passivity | held self-play draws 20% → ~31–40% while eval diff vs `FaanBot` rose +6.36 → +8.82, agent deal-in fell 0.071 → 0.064, and eval-table draws stayed 26–27% | read the draw canary together with held-out eval: higher draws among learners with rising strength vs heuristics is learners defending against each other |
| C1 hold | Slow self-play trends continue after the eval plateau | over the hold: draws 0.33 → 0.29, win 0.166 → 0.179, entropy 0.85 → 0.77, KL and clip fraction falling, explained variance 0.26 → 0.28 | these trends say the learners are still adapting to each other, not that they're getting stronger against outsiders; held-out eval decides |
| C1 hold | Checkpoints trade win rate against hand size at equal strength | 326.0M win 0.260 / 5.01 faan / deal-in 0.052; 429.2M win 0.309 / 4.43 faan / deal-in 0.062; both ≈ +8.2–9.1 | behaviour claims need several checkpoints; a single checkpoint's style is a phase of the attack/defence cycle |
| C1 hold | The style diversifies late | half-flush wins 63% → 46% and concealed wins 16% → 29% from 230.9M to 462.0M at unchanged points per win (§5) | the open-flush route the bots don't read is no longer the agent's only source of value; the league tests whether that holds against opponents that do |
| C1 hold | Self-play against heuristics plateaus fast at the target ruleset | vs `FaanBot` +8.82 at 230.9M, then +7.8 to +9.1 across six checkpoints to 462.0M, all CIs overlapping; the step to `min_faan` 3 took +6.36 → +8.82 in 10.5M decisions | budget ~10–30M decisions at the target ruleset after a curriculum exit, then move on (league); a long pure-self-play hold buys style drift, not measurable strength |
| Evaluation | Checkpoint-to-checkpoint variance ~±1 point | 161.0M +5.26 vs 167.1M +4.29 on the same seeds | gate a checkpoint chosen in advance (or average several), never the best of a sweep on the gate seeds ([ml.md §12](ml.md)) |
| Evaluation | The pre-league policy already passes R3's numbers | 462.0M on fresh seeds: +9.76 [8.72, 10.79] vs `FaanBot` (1,000 sets), +9.42 to +11.69 vs every profile and `EfficiencyBot`, sub-min tenpai ≤ each opponent's (§4) | the heuristic gate no longer discriminates between candidates; the league's progress has to be read from learned-only measures (Elo, per-snapshot win rate) and later from exploiter gain, with the heuristic gate as a regression floor |
| Evaluation | Head-to-head between near-equal policies needs ~6,000 sets per checkpoint | combined ×1/×3 head-to-head CI ±0.43 points/hand at 3,000 + 3,000 sets; neighbouring checkpoints move ±0.3 (−0.39 → +0.14 → −0.08) | read the mean over several checkpoints; a single checkpoint can't separate a 0.2-point gain from noise |
| League | League rollout costs ~0.7× | run 2: ~1.1k vs the hold's ~1.6k learner decisions/s on the same box | frozen seats take env steps and forwards without producing samples; `seat_learners: 2` is the lever if throughput matters more than opponent coverage |
| League | A 10% alt-preset share can dominate the return variance | C2, 165M decisions: per-hand payment SD (reward units) 0.87 `hk_classic`, 0.98 `hk_strict`, 3.6 `hk_casual` (max 48), so the `hk_casual` 10% supplied ~65% of the variance; PopArt σ 0.6 → 1.4–2.0 (spikes 4–6), explained variance 0.28 → 0.13–0.17, entropy 0.77 → 0.9; head-to-head vs the league's starting policy −0.3 points/hand [−0.75, +0.10] | normalise each preset's rewards to the main ruleset's scale before mixing presets in one batch (`reward_scale_by_ruleset`, [ml.md §9](ml.md)) |
| League | Reward scaling fixed the league's regression | at 188.2M the head-to-head vs the starting policy was −0.83 [−1.27, −0.39]; after `reward_scale_by_ruleset` at 190.0M: −0.05 at 208.7M and −0.05 mean over five checkpoints to 296.6M. PopArt σ 1.8 → 0.74, explained variance 0.15 → 0.27, entropy 0.95 → 0.84 within ~1M decisions | mixing presets with different payout scales in one batch is a correctness issue, not a tuning one: scale before mixing, from the first update |
| League | The pairwise win share measures style, not strength | the C2 policy drifted to "win less often, win bigger": x ≈ 0.48 against equal-strength snapshots, PFSP (`pfsp_power` 2) effectively uniform, Elo falling | rank opponents by points difference (`pfsp_metric: points`, [ml.md §11](ml.md)); keep x as a style read-out |
| League | Short persona forks are not distinct opponents | `persona_updates` 100 at ×1.3 / ×1.5: KL from the parent 0.06–0.15 nats, top-1 agreement 0.81–0.85, less than checkpoint drift over 2M decisions | 400 updates, ×1.6 / ×2.0; measure persona KL from the parent after each fork before trusting the persona share |
| League | A single head-to-head checkpoint can cross zero by chance | L316.3M +0.47 [+0.03, +0.91], then L338.5M −0.11 and L358.5M +0.26; eight post-redesign checkpoints average +0.05 | require two consecutive checkpoints with CI > 0 (or a mean over several) before calling a gain |
| League | The league eventually matched the starting policy's defence while keeping the bigger hands | head-to-head deal-in 0.11–0.13 vs 0.09–0.11 from L72 to L338.5M; 0.102–0.104 vs 0.102–0.105 at L358.5M, average winning faan ~5.2 vs ~4.9 | the cost of the bigger-hand style shrank over ~170M post-redesign decisions without moving the points total; watch whether it turns into a points gain |
| League | The league's gain is robustness across presets, not `hk_classic` strength | 300M league decisions: `hk_classic` head-to-head vs the starting policy level (mean −0.05); L274.3M vs the starting policy on identical seeds: `hk_strict` head-to-head +2.47 [+1.51, +3.48], vs `FaanBot` at `hk_strict` +25.0 vs +17.4, vs `EfficiencyBot` +14.5 vs +11.3; `FaanBot` at `hk_classic` +10.9 vs +10.0 (CIs overlap) | the starting policy had already plateaued at `hk_classic` (§4); the 20% alt-preset hands are what the league added. Judge league checkpoints on all served presets, not the main one alone |

| Bots | `ORACLE`'s weakness was hand value, not information | `OracleFaanBot` never deals in yet loses to `LearnedBot` (−1.90) and wins at 3.3 faan; the same exact vetoes on `LearnedBot`'s policy beat it by +5.23 and beat `LearnedBot` from both seatings (§4) | to make an omniscient tier strong, give it a strong blind policy and spend the information on vetoes; a dedicated oracle RL run (25–50 GPU-hours) wasn't needed to clear "Impossible > Expert" |
| Bots | The shipped numpy path reproduces the torch gate | R4 re-run through `LearnedBot` on fresh seeds: every R3 estimate inside the CI; 2,479 of 2,479 decisions identical to `PolicyBot` (max logit difference 6.5e-5) | re-gate through the shipped path whenever weights change ([bots.md §2](bots.md) runbook), not only through the checkpoint |

What to watch next: whether the league's post-redesign head-to-head turns into a sustained gain on
L274.3M (two consecutive checkpoints with CI > 0); sub-min tenpai, which alternates around
`FaanBot`'s (0.016–0.067, 20–25 events per 1,000-set check); new weights for Expert, which also
change Impossible and need both gates ([bots.md §2](bots.md)); and the ACH ablation.

## 7. Earlier runs

**R1 auxiliary pretraining** ([ml.md §14](ml.md)), run cost:

| Stage | Cost on the i7-1265U |
| --- | --- |
| generation, 10 workers | 0.55–0.93 games/s (thermal/power throttling), ~4.8 h |
| training, 8 / 4 / 2 threads | 0.57 / 0.44 / 0.445 s/step: step time doesn't scale past 2 threads, and 8 threads drained the battery on a 65 W charger; train at 2 |

**R2 smoke run** (15 min from R1 `ckpt_best.pt`, C0 config, i7-1265U, CPU): 271k decisions, 65 updates.

| Updates | Batch win rate vs tsumogiri | Blind-env win rate | Entropy | Critic explained var |
| --- | --- | --- | --- | --- |
| 1–10 | 0.031 | 0.019 | 1.87 | 0.72 |
| 21–30 | 0.183 | 0.235 | 1.58 | 0.97 |
| 41–50 | 0.452 | 0.468 | 1.20 | 0.92 |
| 61–65 | 0.529 | 0.531 | 1.05 | 0.88 |

C0's exit (rolling win ≥ 0.40 over 4,000 hands) was met at update 54 (~226k decisions) and the
run advanced to C0b. Blind and oracle win rates track each other: this early, the policy gains
little from the oracle (the adapter starts at zero). The run crashed at update 65 on a latent
`bots.arena._tenpai_can_reach_min_faan` bug (a wait on the seat's own kong type has no physical
copy left), since fixed with a regression test; resuming from update 60 ran cleanly in C0b.

Its update-60 checkpoint vs `EfficiencyBot` × 3 at `hk_classic` (`min_faan` 3), 200 fresh sets
(seeds 2,000,000+): **+4.47 points/hand, 95% CI [+2.66, +6.28] (bootstrap [+2.72, +6.25])**;
candidate win 0.264 / deal-in 0.119 / avg faan 4.57 / sub-min tenpai 0.174 vs `EfficiencyBot`'s
0.210 / 0.153 / 3.83 / 0.390; exhaustive draws 0.108. A smoke result, not the R2 gate (C1 exit
first, then a fresh-seed gate); it says more about `EfficiencyBot`'s weakness under `min_faan` 3
than about the policy, which has never played `min_faan` > 0.