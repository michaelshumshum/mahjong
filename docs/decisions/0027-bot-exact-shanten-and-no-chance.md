# 0027. Bots read exact shanten and a correct no-chance

- **Status:** Accepted
- **Date:** 2026-11-01

## Context

Two known bot bugs ([bots.md §3](../bots.md), §5):

| Bug | Effect |
| --- | --- |
| `no_chance` counts your own hand | `deal_in_probability` returned 0 whenever every copy of a tile was accounted for. You can only discard a tile you hold, so this always meant "you hold the last copy", and an opponent can still win on it through a run (3m+5m waits on 4m holding no 4m). Hit 3.4% of 32,080 sampled `FaanBot` candidate discards |
| whole-hand shanten | `T1`/`T2` scored shanten/ukeire on concealed + exposed meld tiles as 4 sets + pair, so a parse could regroup locked meld tiles into waits the hand doesn't have, and all three chow variants scored alike |

## Decision

| Fix | Change |
| --- | --- |
| no-chance | `no_chance` now only rules out waits needing a held copy (pair/pung/tanki/Seven Pairs). The hard zero (`_provably_safe`) also needs every run through the tile walled (`walls_every_run`, moved from learn-mode grading) and no open Thirteen Orphans wait. No-chance with a run still open scales by `_NO_CHANCE_FACTOR` (0.2) |
| exact shanten | `EfficiencyBot`, `FaanBot`, `labels.is_tenpai`/`winning_tile_types`, arena stats and the hands-aware `safety` helpers use `shanten`/`ukeire`'s `melds=n` mode on the concealed tiles. Claims are scored on `features.after_claim34`, so each chow variant is scored separately. `FaanBot`'s value proxies keep the whole hand (they count suits across melds) |
| ML labels pinned | `danger_labels_for_opponents` (`is_tenpai(..., melds_fixed=False)`), `ml.generate_aux.shanten_labels` and `ml.train_env`'s `cur_shanten` stay whole-hand: the shipped datasets, aux heads and PPO shaping were built on it. `tests/test_ml_ppo_cpu_pin.py` and the ML suite pass unchanged |

`tests/test_faanbot_trajectory_pin.py` digests were regenerated in each commit (no-chance:
`hk_classic`, `hk_strict`; exact shanten: `hk_casual`, `hk_strict`).
`tests/test_engine_trajectory_pin.py` is unchanged (its policies don't use `bots/`).

## Measurement

`python -m bots.arena`, 1,500 duplicate sets (6,000 games) per run, seeds 30,000,000+,
`--parallel 12`, `hk_classic`, engine 1.3.0, laptop (i7-1265U). Each fix is compared with the
version before it on the same seeds and the same opponent (`--baseline-diffs`, bots.md §7), so
`(new − B) − (old − B)` is a paired sample. `LearnedBot` (`T4`) is the fixed opponent: neither fix
touches it. Δ = new − old, points/game and win rate, 95% CI:

| Change | A ×1 vs B ×3 | A − B before → after | Δ points/game | Δ win rate (pp) |
| --- | --- | --- | --- | --- |
| no-chance | `FaanBot` vs `LearnedBot` | −36.01 → −35.83 | +0.17 [−0.23, +0.57] | +0.27 [+0.15, +0.39] |
| no-chance | `FaanBot` vs `EfficiencyBot` | +2.42 → +2.46 | +0.04 [−0.13, +0.20] | +0.01 [−0.11, +0.13] |
| exact shanten | `FaanBot` vs `LearnedBot` | −35.83 → −35.86 | −0.03 [−0.18, +0.12] | −0.01 [−0.05, +0.03] |
| exact shanten | `EfficiencyBot` vs `LearnedBot` | −49.51 → −48.20 | **+1.32 [+0.47, +2.16]** | **+1.27 [+1.05, +1.49]** |

Ladder after both: `FaanBot` vs `EfficiencyBot` **+1.29 [+0.70, +1.88]** (was +2.42 [+1.83,
+3.01] on the same seeds). The gap shrank because `T1` got stronger, not because `T2` got weaker.

- **No-chance:** neutral on points, a small win-rate gain against `LearnedBot`.
- **Exact shanten:** neutral for `FaanBot` (its value terms dominate where melds matter), a clear
  gain for `EfficiencyBot`, which acts purely on shanten/ukeire, so false waits misled it most.
- **Cost:** no regression. Warm decision latency over 5,009 seeded decision points went from T1
  median/p99 0.52/1.51 ms to 0.39/1.34 ms, and T2 from 0.80/1.47 ms to 0.72/1.53 ms. The
  concealed-only arrays are smaller, and the merge caches key on `sets`.
- **Not run:** a direct old-vs-new head-to-head. Two versions of `bots/` can't share one arena
  process, and the fixed-opponent pairing above answers the same question on identical seeds.

## Consequences

- The Normal-vs-Easy ladder row and bots.md §7's table use the new numbers.
- `FaanBot` is the RL evaluation baseline ([ml.md §12](../ml.md)), and its gate numbers predate
  this change. Re-run the baseline before comparing a new policy against old `FaanBot` numbers.
- The ML labels now disagree with the bots' tenpai definition when exposed melds can be regrouped.
  Moving them to the exact form needs a dataset `SCHEMA_VERSION` bump and new aux data.
