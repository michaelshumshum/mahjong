# 0020. Scoring table aligned with standard HK mahjong

- **Status:** Accepted
- **Date:** 2026-10

## Context

An audit of `mahjong_core/scoring/patterns.py` against standard Hong Kong faan tables found patterns
that are not HK faan and values that diverged from the usual table.

## Decision

| Change | Detail |
| --- | --- |
| Removed | 缺一門, 三暗刻, 全求人, 雙箭, 一般高, 三般高, 三步高, 四步高, 河底撈魚 (merged into 海底撈月) |
| Added | 四暗刻 (8), 十八羅漢 (limit); `ScoringContext.winning_tile` makes concealed-pung counting ron-aware |
| Values | 清一色 7, 小三元 5, 大三元 8, 小四喜 6, 大四喜 limit |
| Stacking | supersede rules (`apply_supersedes`) run after hand-set/override filtering so an inclusive total never loses its pattern when a component is disabled |
| Bots | voided-suit route removed from `ROUTE_FAAN` |

## Consequences

- `ENGINE_VERSION` 1.2.0 (superseded by 1.3.0 below): faan totals, rewards and danger labels changed; older training
  checkpoints and replays are refused.
- FaanBot persona tests tied to 缺一門-era value gaps are `xfail`; persona calibration needs an
  arena re-run (`docs/bots.md §7`).

## Follow-up (engine 1.3.0)

Opus audit items previously left open, now applied:

| Change | Detail |
| --- | --- |
| 平糊 | any pair (no dragon/wind-pair exclusion) |
| 門前清 | also on a self-draw (stacks with 自摸); concealed kong breaks it; not on 七對子; 四暗刻 replaces it |
| 混么九 → 花么九 | 4 faan, `CLASSIC`, replaces 對對糊 |
| Flowers | 座位花 → 正花 (1 each, excluding tiles inside a set); old 正花 (set, 3) → 一台花 (2 per set) |
| Limits | two tiers: 字一色/清么九/九蓮寶燈 = 10, others 13; pays `min(tier, faan_cap)`; `faan_cap` gains 8 |
| 雞糊 | 0 faan, only at `min_faan == 0`, no longer gated by `NEW_6` |
| 四暗刻 | moved to `CLASSIC` |
| 七對子 | opt-in: `NEW_18` off in `hk_classic` and the default `RuleSet`; on in `hk_casual` |
| 連槓開花 | new `NEW_6` pattern, 8 faan, replaces 槓上開花 + 自摸; `GameState.kong_replacement_streak` |

- Skipped: 人糊 (optional variant).
- Assumption: 連槓開花's value and its superseding 自摸 follow common house tables, not a single
  authoritative source.
- Known gap: `bots/valuation.py` still offers a `seven_pairs` route regardless of `hand_sets`;
  shanten is gated, the value estimate is not.
- `ENGINE_VERSION` 1.3.0: totals, labels and the encoded `hand_sets` mask changed; retrain from
  scratch. PPO and trajectory pins regenerated.
- The R2 PPO run did not retrain from scratch: `ml.migrate_ckpt` carries an engine-1.0.0 checkpoint
  over with identical outputs on `hk_classic` (`docs/ml.md §9`). It was migrated at 98.6M
  decisions, still at `min_faan` 0, before the faan-sensitive part of C1.

## Measured impact (2026-10-05)

Same winning hands, both scorers: 1,362 wins captured from 60 `FaanBot`-vs-`EfficiencyBot` duplicate
sets played at engine 1.3.0, `hk_classic` with `min_faan` 0 (so every completed shape is a win),
each scored by the 1.0.0 and the 1.3.0 `score_winning_hand` at `min_faan` 3.

| Share of winning hands | 1.0.0 | 1.3.0 |
| --- | --- | --- |
| ≥ 3 faan (wins at `hk_classic`) | 0.345 | 0.142 |
| ≥ 5 faan | 0.053 | 0.006 |
| mean faan | 2.11 | 1.55 |
| total changed / fell below 3 / rose to ≥ 3 | | 0.319 / 0.218 / 0.015 |

缺一門 (2 faan, on 26% of wins) was on 93% of the hands that fell below 3, 一般高 on 14%. Flower scoring is unchanged in practice (座位花 → 正花 at the same rate).

Arena, `FaanBot` vs `EfficiencyBot`, 1,000 sets, seed 1, `hk_classic` (`docs/bots.md §7` has the
1.3.0 table):

| Metric (A / B) | 1.0.0 | 1.3.0 |
| --- | --- | --- |
| win rate | 0.175 / 0.224 | 0.197 / 0.163 |
| deal-in rate | 0.110 / 0.139 | 0.042 / 0.069 |
| avg winning faan | 4.23 / 3.75 | 3.30 / 3.22 |
| sub-minimum tenpai | 0.224 / 0.324 | 0.039 / 0.337 |
| exhaustive draws (derived) | ~15% | ~31% |
| paired diff, points/game | +0.59 [−0.39, +1.58] | +2.67 [+1.92, +3.42] |

Reaching 3 faan is now the binding constraint: draws double, deal-ins fall (fewer hands are live),
and a faan-aware bot gains a clear edge over a faan-blind one. The C1 exit win threshold moved
0.18 → 0.15 accordingly (`docs/ml.md §10`).
