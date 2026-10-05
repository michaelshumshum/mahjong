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

- `ENGINE_VERSION` 1.2.0: faan totals, rewards and danger labels changed; older training
  checkpoints and replays are refused.
- FaanBot persona tests tied to 缺一門-era value gaps are `xfail`; persona calibration needs an
  arena re-run (`docs/bots.md §7`).
- Not changed, still uncertain: 平糊 pair rules, 門前清 on self-draw, two-tier limit values, 七對子
  opt-in.
