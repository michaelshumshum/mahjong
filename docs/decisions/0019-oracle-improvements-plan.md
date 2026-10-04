# 0019. `ORACLE` improvements plan

- **Status:** Deferred (plan, not built)
- **Date:** 2026-10-04

## 1. Context

`ORACLE` is a plain `FaanBot()` fed `_omniscient_seat_view` ([bots.md §9](../bots.md),
[ADR 0013](0013-oracle-full-information.md)). Shipped: +27.693 pts/game vs `FaanBot`, 95% CI
[25.098, 30.288], 200 duplicate sets. Goal: make it win more.

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

| Variant | Paired vs `FaanBot` [95% CI] | Δ vs baseline [95% CI] | Sets changed | Deal-ins | Wins |
| --- | --- | --- | --- | --- | --- |
| baseline | +27.693 [25.098, 30.288] | — | — | 67 | 1,018 |
| hard-avoid certain deal-ins (§5.1) | +29.247 [26.634, 31.860] | **+1.553 [+1.113, +1.994]** | 52/200 | 1 | 1,023 |
| ron-aware tenpai acceptance, λ=0.25 (§5.2) | +28.187 [25.587, 30.787] | +0.493 [−0.168, +1.155] | 60/200 | 66 | 1,032 |
| hard-avoid + ron-aware λ=0.5 | +29.680 [27.063, 32.297] | +1.987 [+1.144, +2.829]; vs hard-avoid alone +0.433 [−0.280, +1.147] | 103/200 | 1 | 1,035 |
| `w_value` × 1.3 (§7) | +27.947 [25.331, 30.562] | +0.253 [−0.393, +0.900] | 54/200 | 68 | 1,018 |

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
- Add `--diffs-out PATH` (per-set paired differences as JSON) and `--baseline-diffs PATH`
  (prints Δ vs a previous run on the same seeds) — the diff-of-diffs used in §4. Candidate
  `ORACLE` variants are registered as `BOT_REGISTRY` entries during development (as the
  `FaanBot` weight profiles are), never as live tiers.

**b. `FaanBot` trajectory pin.** `tests/test_engine_trajectory_pin.py` pins the engine, not
`FaanBot`. Add `tests/test_faanbot_trajectory_pin.py`: 4 × `FaanBot` (plain `seat_view`), a few
seeds × presets, hash every action id. Every `ORACLE` change in §5 must leave it unchanged — the
whole-bot form of the per-helper "byte-identical when `hands is None`" tests.

Commits:

1. `test(bots): pin FaanBot self-play trajectory digests`
2. `feat(arena): ORACLE seat via sanctioned omniscient view` (+ containment test, bots.md §7/§9)
3. `feat(arena): dump and compare per-set paired differences`

### 5.1 Hard-avoid certain deal-ins — **do first**

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
  gate on its own.
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

### 5.2 Ron-aware tenpai acceptance — measure further before merging

- **What:** `seen34`'s hands-aware branch treats every tile in an opponent's hand as dead. Right
  for draws, wrong for ron: an opponent discards a surplus copy 26% of the time, a needed one
  7.6% (§3). Credit those copies when a candidate discard leaves `ORACLE` tenpai.
- **Where:** `bots/faanbot.py`'s `_best_discard` (the `tiles` fed to `_speed_term`); a new
  `bots/safety.py` (or `bots/features.py`) helper `ron_acceptance(view, waits) -> float`,
  hands-only, asserting `view.hands is not None` like `kong_rob_risk`. Reuses
  `safety._opponent_hand34` and `bots/labels.py`'s `winning_tile_types`.
- **Design:**

  ```python
  if view.hands is not None and result_shanten == 0:
      waits = winning_tile_types(after, closed=closed, hand_sets=hand_sets)
      tiles += ron_acceptance(view, waits)

  def ron_acceptance(view, waits):
      total = 0.0
      for opp in opponents:
          base = shanten(opp_hand34)
          for w in waits held by opp (count c):
              surplus = shanten(opp_hand34 - w) <= base
              total += c * (_RON_SURPLUS if surplus else _RON_NEEDED)
      return total
  ```

  `_RON_SURPLUS = 0.26`, `_RON_NEEDED = 0.08` from §3; refine to the probability of discard
  *before the hand ends* by the opponent's shanten if a larger sample supports it. Optionally
  also weight by whether the copy would clear `min_faan` for `ORACLE` (a ron and a self-draw
  can score differently).
- **Measured:** flat λ on surplus copies only. Alone, λ = 0.25: Δ +0.493 [−0.168, +1.155].
  Stacked on §5.1, λ = 0.5: +0.433 [−0.280, +1.147] over §5.1 alone. Consistently positive
  (~+0.45), CI includes zero both times, so not yet a gate pass.
- **Risks:** the discard rates are `FaanBot`'s; humans hold differently. Per-candidate cost is
  ~3 opponents × few waits × 1 shanten call, only on tenpai candidates — negligible.
- **Gate:** 700 sets. The per-set SD of Δ measured 3.2 (§5.1) to 4.8 (this variant); 80% power
  at δ = 0.5 with SD 4.8 needs ~720 sets. Read the Δ CI, not the vs-`FaanBot` CI. Tune λ on seeds 1–200, gate on
  fresh seeds (1,000,000+) — winner's curse.
- **Tests:** helper unit tests (surplus copy credited, needed copy credited less, own-seat
  excluded); `tests/test_oracle.py` decision test where two tenpai shapes tie on wall copies but
  one wait sits as an isolated tile in an opponent's hand; `hands=None` path unchanged.
- **Commits:** `feat(bots): ron_acceptance helper for omniscient tenpai waits`, then
  `feat(bots): ORACLE credits ron-able wait copies in opponents' hands`.

### 5.3 Exact tenpai valuation

- **What:** at a tenpai-after-discard candidate, replace `estimate_best_faan`'s structural proxy
  with the real scorer: for each wait, `score_winning_hand` on the completed hand (ron and
  self-draw contexts), keep `total_faan` where `clears_min_faan`, weight by that wait's copies
  (wall copies + §5.2's ron credit). A wait that can't clear `min_faan` contributes 0.
- **Where:** new `bots/valuation.py` helper `exact_wait_value(view, after) -> float`; called from
  `_best_discard` under `view.hands is not None and result_shanten == 0`.
- **Why `ORACLE`-gated though it only needs the own hand:** changing `FaanBot` would move the RL
  baseline (ml.md §12). The copy weighting does need `view.hands`. If it wins for `ORACLE`, a
  `FaanBot` version is a separate, between-gate-runs change (bots.md §10 policy).
- **Measured:** nothing. The proxy's mean absolute error is 2.46 faan (valuation.py docstring);
  `ORACLE`'s dead-in-wall waits (15.8%) and sub-minimum tenpai are where it should show.
  Add `tenpai_rate_on_sub_minimum_hand` for `ORACLE` to the §5.0a arena report before/after.
- **Risks:** cost — a scoring call per wait per tenpai candidate (~2–6 per decision); measure
  ms/decision. Scale: the real faan must replace, not add to, `w_value * value_est` for those
  candidates, or tenpai candidates get double-counted value.
- **Commit:** `feat(bots): ORACLE values tenpai waits with the real scorer`

### 5.4 Voluntary self-kongs (`ORACLE`-only)

- **What:** `_act_on_turn`'s kong loop compares `s < best_kong_shanten`, which can never be true
  (bots.md §10). Replace with a heuristic that declares a kong when it is free:

  ```python
  if view.hands is not None:                       # exact rob check available
      after_kong = hand - one copy of t
      if shanten(after_kong) == base                  # kong doesn't break the shape
         and ukeire(after_kong) >= ukeire_best_discard(hand)   # waits not narrowed
         and kong_rob_risk(view, t, concealed=...) == 0.0:
          declare
  ```

  Gain: one extra (back-of-wall) draw and a 槓上開花 chance. Concealed kongs keep 門前清
  (`scoring/patterns.py` treats `CONCEALED_KONG` as concealed).
- **Gating:** `view.hands is not None` only — `FaanBot` stays byte-identical (ml.md §12), and
  only `ORACLE` can prove the kong isn't robbed.
- **Bug to fix first:** `bots/features.py`'s `is_closed` returns `False` for a hand whose only
  meld is its own concealed kong, so `estimate_best_faan` drops `_SELF_DRAW_CONCEALED_BONUS` and
  the Seven Pairs route after any concealed kong. Fix it hands-gated or not at all for `FaanBot`
  (its own kong never fires today, so the `FaanBot` path is unaffected in practice — confirm
  with the §5.0b pin).
- **Measured:** opportunity rate only: 492 / 50,118 decisions (1.0%) had a legal kong. Expected
  effect small (≲ +0.3 pts/game, estimate). Read the declared-kong count and the decision-level
  divergence count first; 700+ sets for points.
- **Tests:** `tests/test_oracle.py`: declares a free concealed kong; declines one that narrows
  ukeire; declines one `kong_rob_risk` flags (replaces the current test that stubs `shanten`);
  `hands=None` never declares.
- **Commits:** `fix(bots): is_closed counts an own concealed kong as closed` (hands-gated),
  `feat(bots): ORACLE declares free self-kongs`. bots.md §9 kong paragraph, §10 row removed or
  narrowed to "`FaanBot` still never declares".

## 6. Measurement protocol

All runs: `_ARENA_RULESET`, `--parallel` = cores, `ORACLE` vs `FaanBot` × 3 via §5.0a.

| Change | Tune seeds | Gate seeds / sets | Primary metric | Secondary / divergence |
| --- | --- | --- | --- | --- |
| §5.0b pin | — | — | digests unchanged | — |
| §5.1 hard-avoid | 1–200 (done) | 1,000,000+, 200 sets | Δ CI excludes 0 | deal-in count → ~0 |
| §5.2 ron-aware | 1–200 | 1,000,000+, 700 sets | Δ CI excludes 0 | ron-win count, dead-in-wall tenpai % |
| §5.3 exact wait value | 1–200 | fresh, 700 sets | Δ CI | `ORACLE` `tenpai_rate_on_sub_minimum_hand`, ms/decision |
| §5.4 self-kongs | 1–200 | fresh, 700+ sets | Δ CI | kongs declared, decisions changed |
| §7 weight profile | 1–200 | fresh, 700 sets | Δ CI | — |

```
uv run python -m bots.arena --a ORACLE --b FaanBot --games 200 --seed 1 --parallel 4 \
    --diffs-out base.json
uv run python -m bots.arena --a OracleCandidate --b FaanBot --games 200 --seed 1 --parallel 4 \
    --baseline-diffs base.json
```

- Each change is measured stacked on everything merged before it; re-baseline after each merge.
- Divergence count for rare mechanisms: run baseline and candidate `_best_discard`/`act` on the
  same view at every `ORACLE` decision of a fixed 20-set run, count differing action ids (the
  ADR 0013 threat-level method).
- Cost: ~20 min per 200 sets on 4 cores (measured).

## 7. Weight profile for `ORACLE`

`_make_bot("ORACLE")` could pass `FaanBot(weight_profile=ORACLE_PROFILE)`; `FaanBot` unaffected.
Measured `w_value` × 1.3: Δ +0.253 [−0.393, +0.900] — null. After §5.1, `w_safety` only acts
when every discard deals in, so the useful axes are `w_speed`/`w_value`/`w_flex`. Low priority:
a small grid on seeds 1–200, gate the winner on fresh seeds, only after §5.1–§5.3.
Commit: `feat(bots): ORACLE weight profile`.

## 8. Order of work

| # | Commit | Depends on |
| --- | --- | --- |
| 1 | `test(bots): pin FaanBot self-play trajectory digests` | — |
| 2 | `feat(arena): ORACLE seat via sanctioned omniscient view` | — |
| 3 | `feat(arena): dump and compare per-set paired differences` | 2 |
| 4 | `test(bots): ORACLE discards a certain deal-in when a safe tile exists` (failing) | — |
| 5 | `fix(bots): ORACLE never discards a certain deal-in when a safe tile exists` | 1, 4 |
| 6 | `feat(bots): ron_acceptance helper for omniscient tenpai waits` | — |
| 7 | `feat(bots): ORACLE credits ron-able wait copies in opponents' hands` | 3, 5, 6 |
| 8 | `feat(bots): ORACLE values tenpai waits with the real scorer` | 7 |
| 9 | `fix(bots): is_closed counts an own concealed kong as closed` | 1 |
| 10 | `feat(bots): ORACLE declares free self-kongs` | 9 |
| 11 | `feat(bots): ORACLE weight profile` | 8 |

Each behaviour commit updates bots.md §9's table / measured line and ADR 0013's Consequences in
the same commit. bots.md section numbers don't change, so no citation sweep is needed.

## 9. Considered and rejected

| Candidate | Why not (now) |
| --- | --- |
| **Claim-blocking** — price discards that give an opponent a useful chow/pung | Reach is small: 164 `ORACLE` discards claimed in 3,200 hands, and the claimer went on to win only 42 times (2.9% of opponent wins) — an upper bound, since many of those wins didn't hinge on the claim. Pricing "advances toward tenpai/value" needs a new cost scale competing with the exact deal-in term. Revisit only if §5.1–§5.3 are exhausted. |
| **Smarter fold gate** (fold only when a needed discard hits a real wait) | Fold mode fires on 0.26% of decisions. After §5.1, a certain deal-in is already excluded in every mode, so the gate only reorders safe tiles (ukeire vs value). Mostly subsumed; no measurable lever. |
| **Hands-aware `E[faan]` route feasibility** (e.g. a route whose needed tiles all sit in opponents' hands) | Real but unmeasured and overlapping §5.3, which fixes the tenpai case exactly. Route-level feasibility before tenpai is a second proxy on top of the first; do §5.3 first. |
| **Exact-wall exploitation** (draw order in the view) | Recommend against for now. (1) Cost: a new `SeatView` field (`wall_preview: tuple[TileId, ...] \| None`, set only by `_omniscient_seat_view`, `None` in `seat_view_wire` and every redaction path, schema-walker and AST pinned) — doesn't leak the seed but widens what the one sanctioned bypass carries. (2) A seat's own future draws depend on claims and kong replacements (back of the wall), so turning the front N tiles into "my next draws" needs a turn-order simulation that every opponent claim invalidates. (3) It changes what `ORACLE` *is*: ml.md §12 uses it as the "gap to ceiling" reference; a future-seeing bot inflates that gap with information no policy can ever have. (4) The full-information view is not yet exploited — §5.1 alone found +1.55 that was left on the table. Precedent if revived: `ml/encode_v2.py`'s `oracle_raw` already reads the next draws for the training-only critic. |
| **Retuning shared weights** (`_weights_for_turn`) | Would move `FaanBot` (RL baseline). A separate `ORACLE` profile (§7) is the only route. |
| **Voluntary kongs for every tier** | Moves `FaanBot`; other tiers can't check 搶槓 exactly. `ORACLE`-only (§5.4). |
| **Declining a cheap win to wait for a bigger one** | `act` always takes `_WIN`. HK has no furiten, so passing is legal, but the hand can still end on someone else's win or a draw, and without wall order (rejected above) the bigger win isn't knowable. Not measured; low expected value next to §5.1–§5.3. |
| **Search / rollouts over the omniscient view** | ADR 0012 / 0013: same heuristic as policy and leaf evaluator, structural ceiling. |

## 10. Consequences

- Nothing here is built. Before starting, re-read bots.md §9/§10 and ADR 0013 — numbers here are
  against the 2026-10-04 baseline.
- §5.1 is the one change measured to pass the gate on its own; it should land first and become
  the new baseline for everything after it.
