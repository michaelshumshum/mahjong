# 0023. Concealed kongs are public

- **Status:** Accepted
- **Date:** 2026-10

## Context

A concealed kong (暗槓) was redacted to `{count: 4}` for every seat but its owner, for the whole
hand and in `hand_history`; the client drew it as four backs, the win screen included. Bots and
the ML encoders skipped other seats' concealed kongs to match.

That is the Taiwanese convention, not Hong Kong's. HK sources:

| Source | Says |
| --- | --- |
| [zh.wikipedia 香港麻雀](https://zh.wikipedia.org/zh-hk/香港麻雀), 行牌 | 「與臺灣麻雀不同的是，暗槓也必須翻開供其他玩家察看」 — unlike Taiwanese mahjong, a concealed kong must also be shown for the other players to check |
| [Sloperama FAQ 20](https://sloperama.com/mjfaq/mjfaq20.html) | display varies by ruleset — all face-down, or the two end tiles face-down; it must be melded so others see why you hold an extra tile |
| [moegirl 四暗刻](https://zh.moegirl.org.cn/%E5%9B%9B%E6%9A%97%E5%88%BB) | anti-cheating etiquette: show all four, then flip two face-down |

## Decision

| Layer | Change |
| --- | --- |
| Rules | a concealed kong is laid with both end tiles face-down and the middle two face-up; its identity is public. Scoring is unchanged: it still counts as a concealed set for 四暗刻 ([rules.md §5, §7](../rules.md)) |
| Protocol | `meld` carries `tiles` for every kind to everyone; `MeldPayload.count` and `ConcealedKongWire` removed; `hand_history.winner_melds` unredacted |
| Client | `lib/table/meld-face.ts`'s `meldTileFace` draws the end tiles as backs, on the table and on the win screen alike |
| Bots | `features.seen34` counts other seats' concealed kongs (3 per kong, like any meld) |
| ML | `raw.visible_meld_counts34`, `fast_encode`, `encode_v2.policy_raw` include them in the meld planes; the concealed-kong count scalar stays (concealment still affects scoring). The auxiliary hidden-tile target no longer counts them as unseen |

`ENGINE_VERSION` is unchanged: `mahjong_core` and the encoder's tensor shapes are untouched, so
the shipped `learned.npz` loads as-is.

## The shipped policy

L274.3M was trained with opponents' concealed kongs absent from its meld planes; now they appear
there. No retraining or weight surgery: the planes already carry exposed kongs, so the input is
in-distribution apart from one new combination (a kong in an opponent's meld plane alongside a
non-zero concealed-kong count). They're rare: the agent declares about 0.03 concealed kongs per
seat-hand and the heuristic bots none ([rl-learnings.md §5](../rl-learnings.md)). The bar was the [bots.md §2](../bots.md) runbook's
Expert and Impossible gates, zero-shot, on fresh seeds:

| Gate | Matchup | Sets | Paired diff, new encoding | Before (same weights) |
| --- | --- | --- | --- | --- |
| Expert (seeds 13,000,000+) | `LearnedBot` vs `FaanBot` ×3 | 1,000 | **+11.53 [+10.37, +12.68]** | +10.75 [+9.64, +11.86] |
| | vs `EfficiencyBot` ×3 | 700 | +14.41 [+12.99, +15.82] | +15.19 |
| | vs `FaanBotAggressive` ×3 | 700 | +12.31 [+10.90, +13.72] | +11.62 |
| | vs `FaanBotDefensive` ×3 | 700 | +11.33 [+9.98, +12.68] | +10.85 |
| | vs `FaanBotFlushChasing` ×3 | 700 | +12.09 [+10.67, +13.51] | +11.72 |
| Impossible (seeds 14,000,000+) | `ORACLE` ×1 vs `LearnedBot` ×3 | 1,000 | **+3.56 [+3.08, +4.04]** | +3.60 [+3.15, +4.06] |
| | `LearnedBot` ×1 vs `ORACLE` ×3 | 1,000 | **−4.90 [−5.58, −4.23]** | −4.51 [−5.15, −3.88] |
| | `ORACLE` ×1 vs `FaanBot` ×3 | 700 | +12.54 [+11.19, +13.88] | +12.54 [+11.21, +13.87] |

"Before" is the R4 gate ([ml.md §14](../ml.md)) and [ADR 0022](0022-oracle-learned-tier.md)'s
gate, on other seeds. Every CI clears its bar and contains, or sits next to, the earlier estimate.
`FaanBot`'s own `seen34` changed too, so the opponents also see the kongs. Points per hand,
`hk_classic`, numpy serving path.

If a gate had regressed, the fallback was a short PPO fine-tune from L274.3M under the new
encoder, not a re-train.

## Consequences

- Datasets and rollouts generated before 2026-10-14 (v3 danger data, `rl_aux`, the league run's
  rollouts) hid other seats' concealed kongs; `DangerNet` was trained that way too. Mixing old and
  new data mixes the two encodings.
- The league run on the training box encodes with the old rule until its worktree pulls this
  change.
- The oracle channel "opponents' concealed-kong types" is now redundant; it stays so the critic's
  input shape doesn't change.
