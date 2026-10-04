# 0013. `ORACLE` as a full-information `FaanBot`

- **Status:** Accepted (supersedes the rollout-based `OracleBot`)
- **Date:** 2026-09-27

## Context

`ORACLE` originally shipped as `bots/oracle.py`'s `OracleBot`: a `SearchBot`-style determinized
rollout search ([ADR 0012](0012-searchbot-removed.md)) differing only in how the root `GameState`
was built — `view.hands` fixes hand composition, so only wall draw order was sampled. It had its
own `_shared_oracle_bot_pool` (`max_workers=2`) on the assumption of search-sized cost.

It inherited `SearchBot`'s ceiling despite full information: every candidate was still scored
through the same noisy `FaanBot`-driven rollout. Full information changed which worlds were
sampled, not how candidates were evaluated.

It was also originally reserved as an offline analysis tool, never reachable from a live table, on
the theory that handing a bot every seat's tiles was irreconcilable with redaction.

## Decision

`ORACLE` is a plain `FaanBot()` fed `_omniscient_seat_view`, with no search
([bots.md §9](../bots.md)). `bots/oracle.py` and its pool are deleted.

The one thing full information eliminates is the uncertainty `bots/safety.py` exists to estimate —
whether a discard deals in. With every hand known, that is an exact, cheap check. Making the safety
helpers hands-aware lets `FaanBot`'s unmodified `_best_discard` exploit full information directly.

It is safe on a live table because a `SeatView` never carries `game_seed`/`hand_seed`, the
omniscient builder has one call site (AST-pinned), and disconnect handover always uses `T2`. It is
offered as practice mode's "Impossible" difficulty — reversing the earlier "never a difficulty"
call, which was never about safety: the omniscient view only ever drives `bot`-status seats.

## Implementation history

Four hands-aware changes, each measured with a scratch `tools/oracle_arena_check` script reusing
`bots/arena.py`'s duplicate seeding, seed 1, `ORACLE` (A) vs `FaanBot` (B):

| Change | Sets | Paired diff (pts/game) | 95% CI | ORACLE win / deal-in | FaanBot win / deal-in |
| --- | --- | --- | --- | --- | --- |
| exact `tile_risk` | 15 | +11.644 | [6.220, 17.069] | 0.1750 / 0.0083 | 0.1472 / 0.1542 |
| + hands-aware `opponent_threat_level` | 15 | +11.644 | [6.220, 17.069] | 0.1750 / 0.0083 | 0.1472 / 0.1542 |
| same, larger sample | 200 | +12.100 | [10.247, 13.953] | 0.2047 / 0.0106 | 0.1671 / 0.1523 |
| + hands-aware `seen34` | 200 | +27.693 | [25.098, 30.288] | 0.3181 / 0.0209 | 0.1517 / 0.1628 |
| + `kong_rob_risk` | 200 | +27.693 | [25.098, 30.288] | identical | identical |

Notes:

- **`tile_risk`.** The run caught a real bug unit tests hadn't: `_synthetic_tile_id` collided with
  an opponent hand already holding all four copies, now returning `None` (risk 0).
- **Threat level.** The fold gate was still computed from the meld/tempo proxy even with exact
  per-tile danger available, so it could stay closed against a real tenpai opponent. The 15-set
  numbers didn't move; instrumenting `_best_discard` over 20 games showed `threatening` flipped on
  39 of 1399 own-turn decisions (2.8%), changing the discard on 22 (1.6%) — real but too thin for
  60 games. The 200-set rerun resolved it. Lesson: for low-frequency mechanisms, use a larger
  sample or a decision-level divergence count, not the 15-set convention.
- **`seen34`.** Opponents' real hidden tiles still read as live, overstating ukeire. Touching every
  turn's speed term, it produced the largest jump. Deal-in rose slightly (0.0106 → 0.0209) as
  `ORACLE` pushed hands further — still ~8× below `FaanBot`. Concealed kongs needed explicit
  counting: the engine removes their tiles from `concealed`, so they were otherwise in neither
  `.hands` nor the meld loop.
- **`kong_rob_risk`.** Bit-for-bit identical numbers, provably: shanten is monotonic in a tile
  type's count, so `_act_on_turn`'s kong loop can never satisfy `s < best_kong_shanten` and no tier
  ever declares a self-kong. Confirmed by 500,000 random hands per kong kind and by 50 self-play
  games (12,709 decisions, 97 with a legal kong offered, zero declared). Kept as correct, minimal
  insurance if the kong heuristic ever changes; its `FaanBot.act`-level test stubs `shanten` to
  reach the branch.

## Consequences

- `ORACLE` costs the same as `T2` per decision and shares the default pool.
- Every hands-aware helper is byte-identical for `view.hands is None`, pinned by regression tests.
- Known gap: `kong_rob_risk` reuses `_exact_deal_in_faan` with `is_robbing_kong=False`, so 搶槓's
  own +1 faan isn't counted toward `min_faan` ([bots.md §10](../bots.md)).
- `_best_discard` still prices an exact, certain deal-in as a soft `w_safety` cost; fix and
  further improvements planned in [ADR 0019](0019-oracle-improvements-plan.md).
