# 0022. `ORACLE` serves `OracleLearned`: the Expert policy plus exact vetoes

- **Status:** Accepted
- **Date:** 2026-10-12

## Context

`ORACLE` ("Impossible") was a plain `FaanBot()` fed `_omniscient_seat_view`
([ADR 0013](0013-oracle-full-information.md), tuned in [ADR 0019](0019-oracle-improvements-plan.md)).
Once the self-play policy shipped as `T4` ("Expert", `LearnedBot`), Impossible lost to Expert from
both seatings: `ORACLE` ×1 vs L274.3M ×3 −1.53 [−2.22, −0.84] on seeds 8,000,000+
([rl-learnings.md §4](../rl-learnings.md)), −1.90 [−2.59, −1.21] vs `LearnedBot` ×3 on 10,000,000+.
Information can't make up for `FaanBot`'s hand-building and claim logic: the policy out-plays it
on offence, and `ORACLE`'s zero deal-ins only cost the policy its ron income.

## Decision

`bots/worker.py`'s `_make_bot("ORACLE")` builds `bots/oracle_learned.py`'s `OracleLearnedBot`
([bots.md §9](../bots.md)):

- **policy:** `LearnedBot.logits` on the view with `.hands` stripped — the network input is
  bit-equal to a plain `seat_view`'s, so the public-information policy is used as trained and
  `LearnedBot` still refuses an omniscient view;
- **vetoes** from `bots.safety`'s exact helpers on `.hands`: always take a legal win; never discard
  a certain deal-in (`tile_risk > 0`) while a safe discard exists, else the cheapest; never declare
  a self-kong `kong_rob_risk` proves robbed.

| Area | Change |
| --- | --- |
| names | `BOT_REGISTRY["ORACLE"]` (also `["OracleLearned"]`) is the served tier; the old bot is `["OracleFaanBot"]`, omniscient, arena/eval only, not a tier. Numbers labelled `ORACLE` before this record mean `OracleFaanBot` |
| `app/` | no logic change for the tier: `Table._submit_bot_job` already builds the omniscient view for `ORACLE`, and the bot runs in the shared pool |
| containment | unchanged: still two `_omniscient_seat_view` call sites (`tests/test_oracle_containment.py`) |
| `ml/eval_policy.py` | serves every `BOT_REGISTRY` seat, candidate included, through `bots.arena._view_for`, so an omniscient bot can sit ×1 vs ×3; a `PolicyBot` (checkpoint) seat still only gets `seat_view` |
| missing weights | no fallback to `OracleFaanBot`: constructing the bot raises, like `T4`. The api checks the file at startup and runs degraded (`T4`/`ORACLE` disabled, `/healthz` `"degraded"`) rather than refusing to start, and the table logs failed bot jobs ([bots.md §2](../bots.md) "Missing weights"). Before, `Table._await_bot_job` swallowed worker exceptions, so a broken file made both tiers play the turn timer's default every turn, silently |

**Rejected variant:** `OracleLearnedPush` — when the policy's discard raised shanten above the best
safe discard's, play the best-logit safe discard at that shanten instead (the policy folds against
threats the oracle can see are harmless). It measured worse than plain vetoes and was removed.

## Measurements

Points per hand, paired duplicate hands (candidate ×1 minus the mean of ×3), normal 95% CI
(bootstrap CI in parentheses), `hk_classic`.

**Prototype** (laptop, i7-1265U, seeds 10,000,000+, 1,000 sets):

| Matchup | Paired diff |
| --- | --- |
| `OracleLearned` ×1 vs `LearnedBot` ×3 | +3.33 [+2.89, +3.76] |
| `LearnedBot` ×1 vs `OracleLearned` ×3 | −4.20 [−4.77, −3.62] |
| `OracleFaanBot` ×1 vs `LearnedBot` ×3 | −1.90 [−2.59, −1.21] |
| `OracleLearned` minus `OracleFaanBot`, paired vs `LearnedBot` ×3 | +5.23 [+4.42, +6.03] |
| `OracleLearned` ×1 vs `FaanBot` ×3 | +13.14 [+12.04, +14.24] (`LearnedBot`: +12.29) |

Decision latency, one process: `OracleLearned` p50 1.7 / p99 2.1 ms; `LearnedBot` 1.5 / 1.7;
`OracleFaanBot` 4.2 / 11.6.

**Gate** (fresh seeds 11,000,000+, `ml.eval_policy --ruleset hk_classic --seed 11000000
--candidate-bot … --opponent … --records …`, run in a cloud dev container). Pass bar: CI entirely above zero for
`ORACLE` from both seatings vs `LearnedBot` ×3.

| Matchup | Sets | Paired diff | Bootstrap | ×1 win / deal-in / faan | ×3 win / deal-in / faan |
| --- | --- | --- | --- | --- | --- |
| `ORACLE` ×1 vs `LearnedBot` ×3 | 1,000 | **+3.60 [+3.15, +4.06]** | [+3.16, +4.08] | 0.199 / 0.003 / 5.21 | 0.175 / 0.130 / 5.35 |
| `LearnedBot` ×1 vs `ORACLE` ×3 | 1,000 | **−4.51 [−5.15, −3.88]** | [−5.17, −3.90] | 0.123 / 0.168 / 5.85 | 0.161 / 0.004 / 5.49 |
| `ORACLE` ×1 vs `FaanBot` ×3 | 700 | +12.54 [+11.21, +13.87] | [+11.24, +13.90] | 0.280 / 0.001 / 5.34 | 0.150 / 0.121 / 3.32 |
| `OracleFaanBot` ×1 vs `LearnedBot` ×3 | 1,000 | −0.78 [−1.46, −0.10] | [−1.45, −0.11] | 0.278 / 0.000 / 3.34 | 0.171 / 0.132 / 5.29 |
| `LearnedBot` ×1 vs `FaanBot` ×3 | 700 | +11.62 [+10.27, +12.98] | [+10.31, +13.02] | 0.271 / 0.071 / 5.38 | 0.159 / 0.111 / 3.29 |

Paired per set over the same seeds and opponents (from `--records`): `ORACLE` minus `OracleFaanBot`
vs `LearnedBot` ×3 **+4.38 [+3.58, +5.19]** (bootstrap [+3.59, +5.17]); `ORACLE` minus `LearnedBot`
vs `FaanBot` ×3 +0.92 [+0.56, +1.28]. Exhaustive draws 21–39% of hands.

**Passes**: both seatings vs `LearnedBot` ×3 exclude zero in `ORACLE`'s favour, and every
prototype estimate falls inside the gate's CI except `OracleFaanBot` vs `LearnedBot` (−1.90 there,
−0.78 here; the intervals overlap). Against `FaanBot` ×3 most of `ORACLE`'s edge is the policy's:
the vetoes add +0.92 on top of `LearnedBot`'s +11.62.

**Latency on the cloud box** (Xeon @ 2.1 GHz, slower than the laptop), `compute_action` run alone,
three runs: `ORACLE` p50 3.4–3.6 ms, p99 6.9–7.7 ms; `T4` p50 3.2–3.5 ms, p99 6.1–8.5 ms. Both miss
[ml.md §6](../ml.md)'s 5 ms on this CPU, `T4` included, so this box measures the hardware; the
laptop numbers above are the comparable ones. The prod CPU (i5-10400F) is unmeasured for either.

## Consequences

- The difficulty ladder is strictly ordered: Impossible beats Expert from both seatings
  ([bots.md §6](../bots.md)).
- **Impossible is coupled to Expert's weights.** `OracleLearnedBot` loads the same
  `bots/weights/learned.npz` `T4` ships, so a new policy changes both tiers. This gate is step 5 of
  [bots.md §2](../bots.md)'s "Shipping new weights" runbook and re-runs with every new file.
- `ORACLE` costs about what `T4` does per decision, well under `OracleFaanBot`'s.
- `FaanBot`'s hands-aware branches (ADR 0019) now serve only `OracleFaanBot`; `tile_risk` and
  `kong_rob_risk` serve both.
