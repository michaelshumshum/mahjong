# 0014. Ruleset-aware bots

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

Ruleset presets (`hk_classic`/`hk_casual`/`hk_strict`) and custom rulesets let a table run with
`min_faan=1`, or `min_faan=5` with `NEW_18` off. Bots only ever see `SeatView`, which had no
ruleset, and `FaanBot` was tuned against the defaults with several hardcoded assumptions.

## Decision

Add `ruleset: RuleSet` to `SeatView` (`Entitlement.PUBLIC`, populated from `state.ruleset`) and
read every ruleset-dependent value from it ([bots.md §8](../bots.md)). Closed in two tiers by blast
radius:

| Item | Tier | Change |
| --- | --- | --- |
| `min_faan` | 1 | `_ASSUMED_MIN_FAAN` deleted; `_should_claim` takes `view.ruleset.min_faan` |
| `hand_sets` | 2 | `shanten()`/`ukeire()` gain `hand_sets: frozenset[HandSet] = frozenset(HandSet)`; Seven Pairs gated on `NEW_18`. Highest blast radius — the oracle-validated engine core — but the default reproduces old behaviour, so oracle cross-checks are unaffected. Thirteen Orphans is `CLASSIC` and needed no gate |
| `faan_overrides` | 2 | `bots/valuation.py`'s `route_faan_for` remaps `ROUTE_FAAN` via a route → Chinese-pattern-name table; empty overrides return `ROUTE_FAAN` itself |
| `wall_reserve` (and `flowers_enabled`) | 2 | fixed `_LATE_TURN=12`/turn-6 replaced by `_turn_breakpoints(ruleset)` over `mahjong_core.wall.max_turns_per_seat`, calibrated to reproduce `(6, 12)` exactly at the default |
| `score_table` | — | not a gap: `payout.points()` already reads it; bots rank by faan, never points |
| `game_length` | — | not a gap: it sets hands per match; bot weights key off discards within a hand |

Every tier-2 change was required to be byte-identical at the default ruleset, so it needed only a
regression check, not a re-tune. `bots/arena.py`'s own tenpai/winning-tile stats became
`hand_sets`-aware later via `bots/labels.py` (`is_tenpai`, `winning_tile_types`).

## Verification

`FaanBot` vs `EfficiencyBot`, default ruleset, 500 duplicate sets, after `faan_overrides` and again
after `wall_reserve`:

| Metric | FaanBot | EfficiencyBot |
| --- | --- | --- |
| win_rate | 0.1744 | 0.2238 |
| deal_in_rate | 0.1110 | 0.1400 |
| avg_winning_faan | 4.2444 | 3.7151 |
| tenpai_rate_on_sub_minimum_hand | 0.2251 | 0.3260 |
| avg_points_per_hand | 0.2380 | -0.0793 |

Paired difference **+1.269, 95% CI [-0.128, +2.667]** — within noise of the 1000-set baseline
([bots.md §7](../bots.md)), and bit-for-bit identical between the two runs, as the calibration
constraint predicts.

Tests: `test_should_claim_reads_min_faan_from_the_live_ruleset`,
`test_seven_pairs_gated_by_hand_sets`, `test_discard_stops_chasing_seven_pairs_when_new_18_is_off`,
`test_discard_follows_faan_overrides_boosting_a_route`,
`test_discard_with_empty_faan_overrides_matches_default_route_faan`,
`test_turn_breakpoints_match_the_old_hand_tuned_constants_at_default_ruleset`,
`test_turn_breakpoints_shift_earlier_under_a_smaller_turn_budget`,
`test_fold_mode_triggers_earlier_under_a_smaller_turn_budget`.

## Consequences

- Non-default weights are extrapolated, not tuned: `FaanBot` was only ever tuned at the defaults.
