# 0019. `ORACLE` improvements plan

- **Status:** Accepted, partially built (§12)
- **Date:** 2026-10-04

## 1. Context

`ORACLE` is a plain `FaanBot()` fed `_omniscient_seat_view` ([bots.md §9](../bots.md),
[ADR 0013](0013-oracle-full-information.md)). Shipped: +27.693 pts/game vs `FaanBot`, 95% CI
[25.098, 30.288], 200 duplicate sets. Goal: make it win more — points first (the merge gate),
win rate tracked alongside. Wall-order knowledge is out of scope (measured anyway, §8).

Constraints every change below keeps:

| Constraint | Source | Guard |
| --- | --- | --- |
| `SeatView` never carries `game_seed`/`hand_seed`; one `_omniscient_seat_view` call site | bots.md §9 | `tests/test_oracle_containment.py` (AST) |
| `FaanBot` byte-identical when `view.hands is None` | ml.md §12 (RL baseline), bots.md §10 | per-helper `hands_none_matches_*` tests; §5.0 adds a trajectory pin |
| merge gate: paired-difference CI excludes zero | bots.md §7 | arena duplicate seeding |
| low-frequency mechanisms: 200+ sets or a decision-divergence count | ADR 0013 notes | §6 |

## 2. Measurement method (what was actually run)

Scratch harness (not committed): `bots/arena.py`'s duplicate seeding and `_ARENA_RULESET`, the
`ORACLE` seat fed `_omniscient_seat_view`, three `FaanBot`s, seeds 1–200, plus per-decision
counters. Variants were `FaanBot` subclasses overriding `_best_discard`.

- **Harness check:** baseline reproduced the shipped +27.693 [25.098, 30.288] exactly; a
  re-implemented `_best_discard` with all variant switches off reproduced the 8-set number exactly.
- **Variant vs baseline:** same seeds, same opponents, so per-set `(variant − FaanBot) −
  (baseline − FaanBot)` is a valid paired sample. "Δ" below is its mean and normal 95% CI.
  Win rate is paired the same way: per set, `(variant wins − baseline wins) / 16` hands.
- `ORACLE` is not in `bots/arena.py`'s `BOT_REGISTRY` — the containment test forbids a second
  `_omniscient_seat_view` call site in `bots/` (§5.0 fixes this).

## 3. Where `ORACLE` still loses points

Baseline, 200 sets = 3,200 hands per `ORACLE` seat, 50,118 own-turn decisions.

| Signal | Count | Reading |
| --- | --- | --- |
| `ORACLE` wins | 1,018 (31.8%); 695 ron, 323 self-draw | avg 4.30 faan |
| `ORACLE` deal-ins | 67 (2.1%), avg 4.0 faan | **66 of 67 chosen while a zero-risk legal discard existed** |
| deal-in timing (own discard count) | turns 4–7: 5, 8–11: 43, 12–15: 18, 20+: 1 | mid-game, where `w_safety` = 0.3 |
| opponent wins | 1,456: 868 ron off another opponent, 521 self-draw, 67 off `ORACLE` | only self-draw and deal-in cost `ORACLE` points (`DiscardPayment.ALL`) |
| opponent won after claiming an `ORACLE` discard that hand | 42 (2.9% of opponent wins); 164 `ORACLE` discards claimed in total | upper bound on claim-blocking's reach |
| fold mode active | 130 decisions (0.26%) | |
| legal self-kong offered | 492 decisions (1.0%); 0 declared | |
| tenpai-after-discard decisions | 11,958 | |
| — wait copies in live wall / in opponents' hands | 22,871 / 24,061 | over half the wait copies sit in opponents' hands |
| — waits with zero copies in the wall | 1,894 (15.8%) | win only by ron |
| — waits with zero copies anywhere | 223 (1.9%) | dead tenpai |
| wait copies in opponents' hands later discarded that hand | surplus¹: 625 / 2,387 (26.2%); needed: 332 / 4,357 (7.6%) | vs `FaanBot` opponents |

¹ surplus: removing that copy doesn't raise its holder's shanten. Each copy is counted once per
hand, discarded or not, regardless of whether `ORACLE` was still waiting on it by then.

**The deal-in finding is the largest controllable leak found.** Under
`view.hands`, `tile_risk > 0` means a certain deal-in (every tier always takes `_WIN`), yet
`_best_discard` weighs it as `w_safety * faan` — 0.15–0.9 × ~4 faan — against `_SHANTEN_UNIT = 5`
per shanten step. An exact, certain loss is priced like a soft risk.

## 4. Results

Two rounds, seeds 1–200, 3,200 `ORACLE` hands per row. Round 1 compares to the shipped
`ORACLE`; round 2 stacks on the best round-1 change (hard-avoid).

| Variant | vs `FaanBot` [95% CI] | Δ pts/game [95% CI] | Δ win rate, pp [95% CI] | Wins | Avg win faan | Deal-ins |
| --- | --- | --- | --- | --- | --- | --- |
| **Round 1, Δ vs shipped `ORACLE`** | | | | | | |
| shipped `ORACLE` | +27.693 [25.098, 30.288] | — | — | 1,018 (31.8%) | 4.30 | 67 |
| hard-avoid certain deal-ins (§5.1) | +29.247 [26.634, 31.860] | **+1.553 [+1.113, +1.994]** | — ¹ | 1,023 | 4.30 | 1 |
| ron credit λ=0.25, proxy value | +28.187 [25.587, 30.787] | +0.493 [−0.168, +1.155] | — ¹ | 1,032 | 4.30 | 66 |
| `w_value` × 1.3 | +27.947 [25.331, 30.562] | +0.253 [−0.393, +0.900] | — ¹ | 1,018 | 4.32 | 68 |
| **Round 2, Δ vs hard-avoid** | | | | | | |
| + ron credit λ=1.0 (surplus) / 0.1 (needed), proxy value | +29.200 [26.588, 31.812] | −0.047 [−1.111, +1.018] | +0.09 [−0.61, +0.80] | 1,026 | — | 1 |
| + exact tenpai valuation, ron credit λ=0.5 (§5.2) | +34.113 [31.437, 36.790] | **+4.867 [+3.724, +6.010]** | **+2.88 [+2.05, +3.70]** | 1,115 (34.8%) | 4.36 | 0 |
| **Round 2, Δ vs exact tenpai valuation** | | | | | | |
| + free self-kongs (121 declared) | +34.033 [31.401, 36.666] | −0.080 [−0.647, +0.487] | −0.03 [−0.33, +0.26] | 1,114 | — | 0 |
| + claims to tenpai (§5.3) | +34.560 [31.817, 37.303] | +0.447 [−1.053, +1.947] | **+3.00 [+1.95, +4.05]** | 1,211 (37.8%) | 4.17 | 0 |
| + wall preview, 4 own draws (§8, out of scope) | +39.113 [36.294, 41.933] | +5.000 [+3.589, +6.411] | +2.56 [+1.99, +3.13] | 1,197 (37.4%) | 4.33 | 0 |
| + wall preview, 8 own draws (§8, out of scope) | +42.153 [39.173, 45.133] | +8.040 [+6.199, +9.881] | +4.66 [+3.75, +5.57] | 1,264 (39.5%) | 4.30 | 0 |

¹ round 1 didn't record per-set wins; only totals.

- **Win rate.** The defensive fix barely moves it (+5 wins). Exact tenpai valuation adds 2.9pp;
  claims, stacked on it, add another 3.0pp — 32.0% → 37.8% together.
- **Exact tenpai valuation** also cut `ORACLE`'s tenpai-at-draw from 510 to 301 of ~700 draws:
  it stops sitting on waits that can't clear `min_faan` or have no live copies.
- **Claims** win more but cheaper (avg 4.17 vs 4.36 faan; open hands lose 門前清/self-draw
  bonuses), so points don't move. 5,044 offers that would have improved shanten were still
  passed — the threshold is the lever.
- **Cost.** Whole-run wall time, 4 sets, 4 cores (dominated by the three `FaanBot`s): hard-avoid
  15.2 s, exact valuation 15.2 s, claims 15.7 s, 8-draw wall preview 23.5 s. No per-decision
  timing was taken.

Everything else in this plan is **estimated, not measured**.

## 5. Recommended changes

### 5.0 Prerequisites (tooling, no behaviour change)

**a. `ORACLE` in the arena.** Every measurement in this plan needed a scratch harness because
`bots/arena.py` can't build an omniscient view. Add a second sanctioned call site:

```python
# bots/arena.py
BOT_REGISTRY["ORACLE"] = _faan_bot_factory          # same class as T2
_OMNISCIENT = frozenset({"ORACLE"})

def _view_for(state, seat, name):                    # the only arena caller
    return _omniscient_seat_view(state, seat) if name in _OMNISCIENT else seat_view(state, seat)
```

- `_play_instrumented_game` takes per-seat names, not just `Bot`s.
- `tests/test_oracle_containment.py`: allowlist becomes exactly
  `{"Table._submit_bot_job", "_view_for"}` (in `bots/arena.py`), plus a new AST check that no
  module under `app/` imports `bots.arena`. Offline-only, never on a WS path.
- Add `--diffs-out PATH` (per-set paired differences **and per-set candidate wins** as JSON) and
  `--baseline-diffs PATH` (prints Δ points and Δ win rate, each with a paired CI, vs a previous
  run on the same seeds) — the comparison used in §4. Candidate `ORACLE` variants are
  `BOT_REGISTRY` entries during development (as the `FaanBot` weight profiles are), never live
  tiers.

**b. `FaanBot` trajectory pin.** `tests/test_engine_trajectory_pin.py` pins the engine, not
`FaanBot`. Add `tests/test_faanbot_trajectory_pin.py`: 4 × `FaanBot` (plain `seat_view`), a few
seeds × presets, hash every action id. Every `ORACLE` change in §5 must leave it unchanged — the
whole-bot form of the per-helper "byte-identical when `hands is None`" tests.

Commits:

1. `test(bots): pin FaanBot self-play trajectory digests`
2. `feat(arena): ORACLE seat via sanctioned omniscient view` (+ containment test, bots.md §7/§9)
3. `feat(arena): dump and compare per-set paired differences and win rates`

### 5.1 Hard-avoid certain deal-ins — defensive, do first

- **What:** under `view.hands`, never discard a tile with `tile_risk > 0` while a zero-risk
  legal discard exists. Same precedent as kong-rob avoidance and `_should_claim`: never do what
  provably backfires.
- **Where:** `bots/faanbot.py`'s `FaanBot._best_discard`.
- **Design:**

  ```python
  risks = {d: tile_risk(view, d) for d in range(34) if mask[_DISCARD_BASE + d]}
  candidates = risks.keys()
  if view.hands is not None:
      # exact risk is a certain deal-in, not a likelihood
      safe = [d for d, r in risks.items() if r == 0.0]
      if safe:
          candidates = safe
  for d in candidates: ...   # unchanged scoring; reuse risks[d]
  ```

  Applies in fold and non-fold mode; when every legal discard deals in, scoring falls back to the
  existing `w_safety * risk` trade-off (i.e. picks the cheapest). Hoisting `tile_risk` into a
  dict computed once is behaviour-neutral for `hands is None` (same calls, same order) — the §5.0b
  pin proves it.
- **Measured:** Δ **+1.553 [+1.113, +1.994]**, deal-ins 67 → 1, wins 1,018 → 1,023. Passes the
  points gate on its own; doesn't move win rate.
- **Risks:** none known for bots. Against humans the certainty assumption is slightly strong (a
  human may skip a sub-ideal win), which only makes the filter conservative.
- **Tests (regression first):**
  - `tests/test_oracle.py::test_omniscient_view_never_discards_a_certain_deal_in_when_a_safe_tile_exists`
    — mid-game (turn 8–11, `w_safety` = 0.3) state where the shanten-best discard completes an
    opponent's real hand; fails on today's code.
  - `..._discards_the_cheapest_deal_in_when_every_discard_deals_in`.
  - `tests/test_faanbot.py`: same state with `hands=None` returns today's discard.
- **Docs:** bots.md §9 (new "Certain deal-ins" paragraph next to kong-rob avoidance; measured
  line updated), ADR 0013 Consequences (one line pointing here).
- **Commit:** `fix(bots): ORACLE never discards a certain deal-in when a safe tile exists`

### 5.2 Exact tenpai valuation with ron credit — offensive, the main win-rate lever

- **What:** at every candidate discard that leaves `ORACLE` tenpai, replace the structural proxy
  with the real outcome of each wait:
  - **acceptance** = Σ over waits that *clear `min_faan`* of (live wall copies + ron credit for
    copies in opponents' hands). A wait that can't clear `min_faan` counts 0, so a sub-minimum or
    dead tenpai stops looking fast.
  - **value** = copy-weighted mean real faan over those waits (self-draw context for wall copies,
    discard context for ron copies), replacing `estimate_best_faan` for that candidate; 0 when no
    wait clears.
  - **ron credit** per copy held by an opponent: 0.5 if it's surplus to them (removing it doesn't
    raise their shanten), else 0. §3 measured real discard rates of 26% / 7.6%; 0.5 was the value
    run. Tune `(surplus, needed)` on seeds 1–200.
- **Where:**
  - `bots/valuation.py`: `exact_wait_value(view, after_concealed, waits, ron) ->
    (acceptance, value)` — calls `mahjong_core.scoring.faan.score_winning_hand` per wait, with
    `ScoringContext` built like `safety._exact_deal_in_faan` but for `view.seat`; reuses
    `safety._synthetic_tile_id` (promote to a shared helper, no leading underscore, since two
    modules now use it).
  - `bots/safety.py` (or `bots/features.py`): `ron_credit(view, waits) -> dict[int, float]`,
    hands-only, asserting `view.hands is not None` like `kong_rob_risk`; reuses
    `_opponent_hand34`.
  - `bots/faanbot.py`'s `_best_discard`: under `view.hands is not None and result_shanten == 0`,
    `tiles, value_est = exact_wait_value(...)`; everything else unchanged.
- **Design:**

  ```python
  if view.hands is not None and result_shanten == 0:
      waits = winning_tile_types(after, closed=closed, hand_sets=hand_sets)
      ron = ron_credit(view, waits)
      acc = val = 0.0
      for w in waits:
          live = 4 - seen[w]                       # hands-aware seen34: wall copies only
          if live and (f := wait_faan(w, self_drawn=True)):
              acc += live; val += live * f
          if ron[w] and (f := wait_faan(w, self_drawn=False)):
              acc += ron[w]; val += ron[w] * f
      tiles, value_est = acc, (val / acc if acc else 0.0)
  ```

- **Why `ORACLE`-gated:** acceptance needs `view.hands` (wall copies, ron credit). The
  value-only half needs just the own hand and would help `FaanBot` too, but changing `FaanBot`
  moves the RL baseline (ml.md §12) — a separate, between-gate-runs change.
- **Measured:** stacked on §5.1: Δ **+4.867 [+3.724, +6.010]** pts/game, win rate **+2.88pp
  [+2.05, +3.70]** (32.0% → 34.8%), avg winning faan 4.30 → 4.36, tenpai-at-draw 510 → 301.
  Ron credit alone (proxy value, λ up to 1.0) was null both rounds, so the gain is the exact
  valuation; exact valuation *without* ron credit wasn't run — run it first to decide whether
  `ron_credit` earns its keep.
- **Risks:** ron credit is calibrated against `FaanBot` opponents; humans hold differently. A
  real scoring call per wait per tenpai candidate — no measurable run-time change (§4), but take
  a per-decision timing before merging.
- **Tests:** `exact_wait_value`: a sub-minimum wait contributes 0; a dead wait (all copies seen)
  contributes 0; ron copies use the discard context. Decision tests in `tests/test_oracle.py`:
  prefers a narrower wait that clears `min_faan` over a wider one that doesn't; prefers a live
  wait over a dead one at equal shanten. `hands=None` unchanged (pin).
- **Commits:** `feat(bots): ron_credit helper for omniscient tenpai waits`,
  `feat(bots): exact_wait_value scores tenpai waits with the real scorer`,
  `feat(bots): ORACLE values tenpai candidates by exact waits`.

### 5.3 Claims to a clearing tenpai — offensive, needs a value threshold

- **What:** `_act_on_claim` claims only when shanten strictly drops *and* `_should_claim`'s proxy
  allows it, and `ORACLE` claimed just 109 of 15,423 chow/pung offers. Add: under `view.hands`,
  when the default would pass and the hand is ≥ 1-shanten, claim a pung/chow if some safe
  (`tile_risk == 0`) post-claim discard reaches tenpai with §5.2 acceptance ≥ 1 copy.
- **Where:** `bots/faanbot.py`'s `_act_on_claim` (new hands-gated branch after the existing
  logic); `exact_wait_value` from §5.2 extended to take the hypothetical meld list (the new
  `Meld` built from the real tile ids and `from_seat=view.turn`).
- **Measured (scratch, threshold 1 copy):** win rate **+3.00pp [+1.95, +4.05]** over §5.2
  (34.8% → 37.8%), claims 109 → 750, but Δ points +0.447 [−1.053, +1.947] — wins are cheaper
  (4.36 → 4.17 avg faan). **Fails the points gate as built.**
- **Next experiment:** claim only when the claimed tenpai's expected value beats keeping the
  closed hand: `acceptance × value(claimed) > k × acceptance × value(closed best)` or a
  simpler `value(claimed) ≥ min_faan + 1`; sweep on seeds 1–200, gate on fresh seeds. Points
  gate; report win rate.
- **Risks:** an exposed meld changes `is_closed`, so every later `_best_discard` uses the open
  path — the measurement already includes that.
- **Tests:** claims into a clearing tenpai; passes when the only reachable tenpai is sub-minimum;
  passes when every post-claim discard deals in; `hands=None` unchanged.
- **Commit:** `feat(bots): ORACLE claims into a clearing tenpai`.

## 6. Measurement protocol

All runs: `_ARENA_RULESET`, `--parallel` = cores, `ORACLE` vs `FaanBot` × 3 via §5.0a. Report Δ
points (gate) and Δ win rate (tracked) with paired CIs.

| Change | Tune seeds | Gate seeds / sets | Gate | Also read |
| --- | --- | --- | --- | --- |
| §5.0b pin | — | — | digests unchanged | — |
| §5.1 hard-avoid | 1–200 (done) | 1,000,000+, 200 sets | Δ points CI > 0 | deal-ins → ~0 |
| §5.2 exact valuation | 1–200: ron credit on/off, `(surplus, needed)` grid | fresh, 200 sets (Δ ≈ 4.9, SD ≈ 8 per set) | Δ points CI > 0 | win rate, tenpai-at-draw, `tenpai_rate_on_sub_minimum_hand`, ms/decision |
| §5.3 claims | 1–200: threshold sweep | fresh, 700 sets | Δ points CI > 0 | win rate, claims made, avg winning faan |
| §7 weight profile | 1–200 | fresh, 700 sets | Δ points CI > 0 | win rate |

```
uv run python -m bots.arena --a ORACLE --b FaanBot --games 200 --seed 1 --parallel 4 \
    --diffs-out base.json
uv run python -m bots.arena --a OracleCandidate --b FaanBot --games 200 --seed 1 --parallel 4 \
    --baseline-diffs base.json
```

- Each change is measured stacked on everything merged before it; re-baseline after each merge.
- Per-set SDs measured: Δ points 3.2–10.8, Δ win rate 2–8pp. 700 sets resolve δ ≈ 0.5 pts at SD
  4.8; a small-gain change like §5.3 with a threshold needs it.
- Divergence count for rare mechanisms: run baseline and candidate on the same view at every
  `ORACLE` decision of a fixed 20-set run, count differing action ids (the ADR 0013 method).
- Cost: ~20 min per 200 sets on 4 cores (measured).

## 7. Weight profile for `ORACLE`

`_make_bot("ORACLE")` could pass `FaanBot(weight_profile=ORACLE_PROFILE)`; `FaanBot` unaffected.
Measured `w_value` × 1.3 (round 1): Δ +0.253 [−0.393, +0.900] — null. After §5.1, `w_safety` only
acts when every discard deals in; after §5.2, value at tenpai is exact. Re-run a small
`w_speed`/`w_value`/`w_flex` grid only after §5.2–§5.3. Commit: `feat(bots): ORACLE weight
profile`.

## 8. Wall-order knowledge — measured, out of scope

Out of scope by decision (2026-10-04). Measured only to size what it's worth.

- **Scratch design:** the harness handed the bot `state.wall.tiles` through a side attribute
  (never `SeatView`). The bot assumed its own next draws are front-wall tiles 3, 7, 11, … after
  its discard (no claims, flowers skipped), simulated them greedily (draw; win if the hand
  completes and clears `min_faan`; else discard the shanten-minimising tile), and among safe
  discards picked the one that self-draws a win soonest, else the §5.2 choice.
- **Result:** over §5.2, 4 own draws: Δ +5.000 pts [+3.589, +6.411], win rate +2.56pp; 8 own
  draws: Δ +8.040 [+6.199, +9.881], win rate **+4.66pp** (39.5%), self-draw wins 355 → 639. A
  crude, claim-blind greedy; a proper planner would get more.
- **Why still out:** (1) a new `SeatView` field widens what the one sanctioned bypass carries
  (redaction schema-walker and AST guards would need to cover it); (2) ml.md §12 uses `ORACLE` as
  the gap-to-ceiling reference, and future draws are information no policy can ever have;
  (3) its gain is comparable to §5.2 + §5.3, which need no new information. If revived:
  `wall_preview: tuple[TileId, ...] | None`, set only by `_omniscient_seat_view`, `None` on every
  wire path; precedent `ml/encode_v2.py`'s `oracle_raw` (next draws, training-only critic).

## 9. Order of work

| # | Commit | Depends on |
| --- | --- | --- |
| 1 | `test(bots): pin FaanBot self-play trajectory digests` | — |
| 2 | `feat(arena): ORACLE seat via sanctioned omniscient view` | — |
| 3 | `feat(arena): dump and compare per-set paired differences and win rates` | 2 |
| 4 | `test(bots): ORACLE discards a certain deal-in when a safe tile exists` (failing) | — |
| 5 | `fix(bots): ORACLE never discards a certain deal-in when a safe tile exists` | 1, 4 |
| 6 | `feat(bots): ron_credit helper for omniscient tenpai waits` | — |
| 7 | `feat(bots): exact_wait_value scores tenpai waits with the real scorer` | — |
| 8 | `feat(bots): ORACLE values tenpai candidates by exact waits` | 3, 5, 6, 7 |
| 9 | `feat(bots): ORACLE claims into a clearing tenpai` (only if the threshold passes the gate) | 8 |
| 10 | `feat(bots): ORACLE weight profile` (optional) | 9 |

Each behaviour commit updates bots.md §9's table / measured line and ADR 0013's Consequences in
the same commit. bots.md section numbers don't change, so no citation sweep is needed.

## 10. Considered and rejected

| Candidate | Why not (now) |
| --- | --- |
| **Voluntary self-kongs** (`ORACLE`-only, rob-checked) | Measured null: 121 kongs declared, Δ −0.080 [−0.647, +0.487], win rate −0.03pp. Legal on only 1.0% of decisions. Side finding if ever revisited: `bots/features.py`'s `is_closed` returns `False` for a hand whose only meld is its own concealed kong, so valuation drops the closed bonus and Seven Pairs although scoring keeps 門前清. |
| **Ron credit without exact valuation** | Null twice (λ = 0.25: +0.493 [−0.168, +1.155]; λ = 1.0/0.1: −0.047 [−1.111, +1.018]). Kept only as a component of §5.2, pending the on/off check. |
| **Claim-blocking** — price discards that give an opponent a useful chow/pung | Reach is small: 164 `ORACLE` discards claimed in 3,200 hands, and the claimer went on to win only 42 times (2.9% of opponent wins) — an upper bound. Needs a new cost scale competing with the exact deal-in term. |
| **Smarter fold gate** | Fold mode fires on 0.26% of decisions. After §5.1 a certain deal-in is excluded in every mode, so the gate only reorders safe tiles. |
| **Hands-aware `E[faan]` route feasibility before tenpai** | Unmeasured; §5.2 fixes the tenpai case exactly. A second proxy on top of the first. |
| **Wall-order knowledge** | Out of scope; measured in §8. |
| **Retuning shared weights** (`_weights_for_turn`) | Would move `FaanBot` (RL baseline). A separate `ORACLE` profile (§7) is the only route. |
| **Declining a cheap win to wait for a bigger one** | `act` always takes `_WIN`. Without wall order the bigger win isn't knowable. Not measured. |
| **Search / rollouts over the omniscient view** | ADR 0012 / 0013: same heuristic as policy and leaf evaluator, structural ceiling. |

## 11. Consequences

- Built so far: §12. Numbers in §3–§4 are against the 2026-10-04 baseline (seeds 1–200); gate runs
  in §12 are on fresh seeds.
- §5.1 (defensive, +1.55) and §5.2 (offensive, +4.87 pts, +2.9pp win rate) both pass the points
  gate in scratch measurement; they land first, in that order. §5.3 raises win rate but needs a
  value threshold to pass on points.

## 12. Build log

All gate runs: `bots/arena.py`, `ORACLE` vs `FaanBot` × 3, 200 duplicate sets, seeds
1,000,000–1,000,199, Δ paired per set against the previous `ORACLE` (`--baseline-diffs`). The
arena reproduced §2's scratch baseline exactly on seeds 1–200 (+27.693 [25.098, 30.288]).

| Change | Commit | vs `FaanBot` [95% CI] | Δ pts/game [95% CI] | Δ win rate, pp [95% CI] | Wins | Deal-ins |
| --- | --- | --- | --- | --- | --- | --- |
| previous `ORACLE` (gate baseline) | — | +27.073 [24.421, 29.726] | — | — | 1,008 (31.5%) | 59 |
| §5.0a/b arena seat, `--diffs-out`/`--baseline-diffs`, `FaanBot` pin | `test(bots)`/`feat(arena)` × 2 | — | — | — | — | — |
| §5.1 hard-avoid certain deal-ins | `fix(bots): ORACLE never discards a certain deal-in …` | +28.667 [26.037, 31.296] | **+1.593 [+1.086, +2.101]** | +0.25 [+0.08, +0.42] | 1,016 (31.75%) | 0 |
