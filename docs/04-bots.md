# 04 — Computer players

## 1. Bot interface

A bot receives exactly the output of `seat_view(state, seat)` — the same redacted `SeatView` a
human gets — and returns an intent. It has no access to `GameState`, the wall, or other hands.
(`redact_event` is the separate wire-facing function for outbound events; bots don't use it. See
[00-architecture.md](00-architecture.md).)

```python
class Bot(Protocol):
    async def act(self, view: SeatView, mask: list[bool], deadline: float) -> int:
        """-> an action id from the fixed 109-action space (docs/06-ml.md §3)."""
```

`mask` is `legal_mask(state, seat) -> list[bool]` (docs/06-ml.md §1) — `GameState`-based, not
`SeatView`-based: `mahjong_core` must never depend on `app.views`, so whoever drives a bot (the
self-play harness, the arena, or the Table) computes the mask from the real `GameState` it
already holds and hands `(view, mask, deadline)` to `Bot.act` together. `mahjong_core` is
stdlib-only — no numpy, plain `list[bool]`. A bot never calls `decode_action` itself either, for
the same reason: it needs the real `GameState`, which a bot never has (`SeatView` is the whole
point). Decoding the returned id back into a concrete `Action` is always the caller's job — a
learned policy drops into the same slot later with no refactor. See
[06-ml.md](06-ml.md)/`server/bots/base.py`'s module docstring.

**Scheduling.** Bot decisions do not run inside the table's `asyncio` task — a shanten/ukeire scan
is tens of milliseconds of pure-Python CPU (§3), which would stall the event loop for every other
table on the same process. Instead:

1. The table enqueues `(bot_id, view, mask, deadline, window_id, state_version)` to a
   `ProcessPoolExecutor` (the GIL makes a thread pool useless for CPU-bound pure-Python search —
   a process pool is the only scheduling primitive that actually parallelises this work).
2. The worker computes an action id and returns `(window_id, state_version, action_id)` to the
   table's inbox.
3. The table compares the tag against its *current* `window_id`/`state_version`. If they don't
   match — the claim window closed, or the hand moved on before the worker replied — the result
   is **dropped silently**, exactly like a stale human claim. This is the same staleness
   protection humans get; bots get no special path around it.
4. If no (matching) result lands before `deadline`, the table applies a safe default (tsumogiri /
   pass) and logs it. A bot must never wedge a table.

**Humanising think delay: 400–1400ms, uniform per decision.** `app/table.py`'s `_await_bot_job`
sleeps this once the worker replies, before re-entering the result through `self.inbox` —
applied by the table, not inside the worker, so it never touches
`_BOT_JOB_TIMEOUT_SECONDS`/`turn_seconds`/`claim_seconds` deadline math (a real tier answers in
single-digit milliseconds; without this, turns and claims resolve faster than a human watching
the table can follow). Seeded off the same per-decision `seed` `_submit_bot_job` already derives
(reproducible, not unseeded), sleeping in that job's own task so it delays only that seat's
result. **Deferred:** varying the delay by how close the decision was — no tier currently
returns a confidence/margin signal alongside its chosen action id, so there's nothing to scale
the delay by yet.

`bots/worker.py`'s `compute_action` drives the real `Bot.act` tiers. A worker process never
receives `GameState` (the table's `game_seed` must never leave its own process), so it can't call
`decode_action(aid, state, seat)` itself — `compute_action` builds the requested tier
(`T0`/`T1`/`T2`, `app/table.py`'s `Table.__init__(bot_tier=...)`, default `T2`/`FaanBot`) and drives
its real `act(view, mask, deadline)` via `asyncio.run` (the worker has no running event loop of
its own — same pattern `bots/arena.py`'s `ProcessPoolExecutor` entry point uses), returning a
bare action id. `app/table.py`'s `_handle_bot_result` decodes it, since it already holds the real
`GameState`.

## 2. Tiers

| Tier | What it is | Effort | Use |
| --- | --- | --- | --- |
| **T0** `RandomBot` | uniform over legal actions | 20 lines | fuzzing, engine tests, never shipped |
| **T1** `EfficiencyBot` | shanten-minimising discard, ukeire tiebreak | ~400 lines | "Easy". Ship in M4. |
| **T2** `FaanBot` | T1 + hand-value planning + discard safety | ~900 lines | "Normal"/"Hard". Moved into M4 (see §4) — the real product. **Built (M4)** — see §4/§5/§8 for the shipped design and real arena numbers. |
| **T3** `SearchBot` | determinized rollouts / MCTS over the pure engine | large | Deferred — see [99-deferred.md](99-deferred.md). |
| **T4** learned policy | supervised on self-play or human logs | research | optional, later |

Ship T1 and T2 in M4 (§4 explains why T1 alone can't satisfy M4's done-gate). T3 is out of scope
for now — see [99-deferred.md](99-deferred.md).

## 3. Shanten and ukeire

**Shanten** = tiles away from tenpai (`0` = tenpai, `-1` = won). Compute over the 34-count
array; take the minimum of three parses:

1. **Standard** — 4 melds + 1 pair. Recursive decomposition: greedily extract melds, then
   partial sets (pairs, ryanmen/kanchan/penchan), memoised per suit.
   `shanten = (4 - melds)*2 - partials - has_pair`, **with the block-count cap
   `melds + partials <= 5` (and `<= 4` if no pair has been banked as the pair slot) applied
   before scoring** — i.e. once you've counted enough blocks to fill 4 melds + 1 pair, extra
   partial sets stop helping and must not be counted. Skipping this cap is the classic shanten
   bug: a hand with six partial sets (e.g. six ryanmen shapes with no pair) will otherwise score
   as if all six count, understating shanten far below what's reachable. Clamp the final result
   at 0.
2. **Seven Pairs** (七對子) — `6 - pairs + max(0, 7 - distinct)`, where `distinct` is the number
   of distinct tile types held. The `max(0, 7 - distinct)` term is required, not optional: a hand
   with 6 pairs of the *same* tile plus one extra copy is not one tile from Seven Pairs shanten
   (you need 7 *distinct* pairs), and `6 - pairs` alone undercounts it. Seven Pairs is a
   mandatory parse — the default ruleset includes NEW_18, so 七對子 is legal and must be checked
   for every hand, not treated as an optional/regional pattern (see [01-rules-spec.md](01-rules-spec.md)).
3. **Thirteen Orphans** (十三么) — `13 - distinct_terminals_honors - (1 if has_pair else 0)`.

Validate against [MahjongRepository/mahjong](https://github.com/MahjongRepository/mahjong)'s
`Shanten` class — same 34-index layout, checked against 26M Tenhou hands. Use it as a test
oracle even if you write your own for speed. For the fast path,
[arXiv:2108.06832](https://arxiv.org/pdf/2108.06832) gives an efficient deficiency-number
algorithm.

**The shanten lookup table is a scheduled M1/M4 deliverable, not an optimisation to discover
later.** A single ukeire scan is ~34 shanten evaluations per candidate discard (13 hand tiles +
21ish unseen tile types checked) × ~14–15 candidate discards ≈ **470 shanten evaluations per bot
decision**. In pure Python that's tens of milliseconds — call it 20–50ms. The roadmap's target is
200 concurrent tables with 3 bot seats each; even at modest bot-decision frequency that is
multiple CPU-*seconds* of work per wall-clock second on a single worker process. This is a real
capacity constraint, not a "Low"-risk line item — size the `ProcessPoolExecutor` and the
precomputed per-suit lookup table (O(1) lookup replacing the recursive scan) accordingly, and
build the table alongside T1, not after load-testing surfaces the problem.
"Bots run outside the table's task" bounds the table's `asyncio` loop, not total CPU — it does not
by itself make this cheap.

**Built (M4): lazily-populated, not an eagerly-built ~500k-entry table.** `mahjong_core/shanten.py`'s
`_frontier` is the per-suit table, `functools.cache`-memoised on a suit's (or honors') count
vector. The full table has 5\*\*9 ≈ 1.95M possible states (shared by man/pin/sou, since they're
structurally identical; honors get a smaller 5\*\*7 ≈ 78k table) — measured at **~104s** to
populate eagerly, cold, which is too slow to pay on every `ProcessPoolExecutor` worker's import.
A real game only ever visits a few hundred to a few thousand *distinct* suit shapes in its
lifetime, and a single ukeire scan's ~470 evaluations share almost all of their sub-shapes, so
the cache is warm within the first hand or two and every subsequent lookup is the O(1) hit this
section calls for — see `mahjong_core/shanten.py`'s module docstring for the full tradeoff and
`tests/test_shanten.py`'s perf/import-time tests for what pins it down.

**Ukeire** (受入れ) = for each candidate discard, how many unseen tiles reduce shanten:

```python
def ukeire(hand34, seen34) -> dict[Discard, tuple[int, int]]:
    """-> {discard: (kinds_accepted, tiles_accepted)}"""
    for d in distinct(hand34):
        after = hand34 - d
        base = shanten(after)
        kinds = tiles = 0
        for t in range(34):
            live = 4 - seen34[t]
            if live and shanten(after + t) < base:
                kinds += 1; tiles += live
        yield d, (kinds, tiles)
```

`seen34` counts your hand, all melds on the table, all discards, and all revealed flowers —
everything publicly visible plus your own concealed tiles. **Never** the wall.

T1's discard rule: minimise shanten; tiebreak on `tiles_accepted`; then on `kinds_accepted`;
then prefer discarding terminals/honors. Call chow/pung only if it strictly reduces shanten.

## 4. Hand value under `min_faan`

With `min_faan = 3`, a pure efficiency bot reaches tenpai constantly and then cannot declare a
win: a fast all-sequences hand scores 1 faan (平糊), below the minimum. Riichi bots don't have
this problem (riichi is itself a declarable yaku), so riichi-derived tutorials and libraries are
wrong for HK on exactly this point. **A T1-only bot loses by construction in HK** — this holds
regardless of how well it minimises shanten, because the failure is in what it's optimising for,
not how well it does it.

**Consequence for the roadmap:** T1 alone cannot satisfy M4's done-gate ("play a full game
against three bots and it feels good" — a bot that reaches tenpai and then cannot win does not
feel good). This is why T2 `FaanBot` is moving from M6 into M4 (see [05-roadmap.md](05-roadmap.md)
for the milestone change) — value-targeting isn't a "depth" feature here, it's a correctness
requirement for the bot to be playable at all under `min_faan=3`.

T2 must plan toward a **value target**, not just speed. The realistic 3-faan routes:

| Route | Faan | When to commit |
| --- | --- | --- |
| Half Flush 混一色 | 3 | ≥7 tiles in one suit + honors by turn 6 |
| All Pungs 對對糊 | 3 | ≥2 pairs/triplets early, few sequence shapes |
| Half Flush + dragon/wind pung | 4–5 | strongest common line |
| Full Flush 清一色 | 6 | ≥9 tiles in one suit by turn 5 |
| Small Three Dragons 小三元 | 3 | two dragon pairs |
| Seven Pairs 七對子 | 4 | ≥4 pairs by turn 5, honors-heavy |
| Voided Suit 缺一門 | 2 | cheap top-up on almost any hand |
| Self-draw + concealed | +2 | keeps a cheap hand viable if you stay closed |

T2's evaluation:

```
score(discard) = w_speed  * ukeire_after
               + w_value  * E[faan | best reachable pattern]
               + w_safety * (-deal_in_risk)
               + w_flex   * pattern_optionality
```

Weights shift across the hand: **speed early (turns 1–6) → value mid (6–12) → safety late
(12+)**, shifting hard toward safety once the wall is short or an opponent is visibly
threatening. Tune by self-play against the arena harness (§8).

**Fold logic.** A bot at 3+ shanten on turn 12 against a threatening opponent discards safe
tiles rather than chasing.

`tenpai_rate_on_sub_minimum_hand` is the canary metric for this whole section — track it
explicitly in the arena harness (§8). A regression there means a candidate bot has quietly
reverted toward pure-efficiency play.

**Built (M4):** `server/bots/valuation.py` (the `E[faan | best reachable pattern]` estimator —
a structural proxy validated against the real scorer, not the scorer itself, since the real
scorer only ever scores a *complete* hand; see that module's docstring for the measured drift)
and `server/bots/faanbot.py` (the weighted score, fold logic, and value-aware claim guard). Real
arena numbers, and the tuning story behind the shipped weights, are in §8.

## 5. Safety (defence)

**Heuristic only — read this section as statistical evidence, not proof of safety.** Hong Kong
rules have no furiten lock: a player is never barred from winning on a tile they themselves
discarded. Every signal below is inferential; none of them *guarantees* a tile won't deal in, and
the bot's risk model must treat them as likelihood shifts, not hard filters.

1. **Genbutsu — weak in HK, not a guarantee.** In riichi, furiten makes a tile in an opponent's
   own discard pool provably safe against them (they're locked out of winning on it). **HK has no
   furiten, so that guarantee does not exist here.** An opponent can and does win on a tile
   identical to one they already discarded (most commonly self-draw, or a wait shape that
   includes it after their hand changed). Genbutsu in HK is only evidence that the *specific
   winning tile-type mattering to their old wait* was probably not this one at the time they
   discarded it — it says nothing about their current hand. Treat it as the weakest-guarantee,
   highest-volume signal in the model: still worth a large likelihood adjustment (opponents do
   still avoid tiles that were live against them), just never a hard "safe" flag. **Do not build
   an "is_safe(tile)" boolean on genbutsu alone** — that is the concrete mistake this section
   exists to prevent.
2. **Suji — derives its force entirely from furiten, so it is weaker still in HK.** In riichi,
   suji (e.g. opponent discarded 5s, so 2s/8s are safer against a ryanmen) works *because*
   furiten would have barred them from a matching wait earlier. Without furiten, an opponent can
   discard 5s early and legally win on 2s or 8s later once their hand reshapes. Use suji only as
   a low-confidence prior in the same `P(deal_in | tile)` model below — never as a standalone
   rule, and weight it below genbutsu.
3. **One-chance / no-chance** — if all four 3s are visible, nobody has a 4-5 wait needing a 3.
   This one *is* a hard constraint (it's about tile counts, not opponent psychology), unlike 1–2.
4. **Meld reading** — three melds in one suit plus honor discards means half flush; a dragon
   pung on the table means the next dragon is expensive.
5. **Discard tempo** — fast discards, then a long think and a middle-tile discard, often marks
   a hand that just settled into tenpai.
6. **Wall pressure** — fewer tiles left means higher deal-in cost per discard.

Model as `P(deal_in | tile)` × expected cost and fold into the T2 score (§4). A logistic
regression over these features, trained on self-play logs, beats hand-tuned weights — and matters
more here than in riichi ports, precisely because signals 1 and 2 are structurally weaker without
furiten.

**Built (M4): hand-tuned, not trained — a deliberate scope decision.** `server/bots/safety.py`
implements all six signals above as bounded multipliers on a baseline deal-in rate
(`no_chance` the sole hard-zero override, matching item 3's "hard constraint" framing), combined
into `P(deal_in | tile) * expected_cost`. The logistic-regression model this section recommends
needs a labelled self-play corpus (`(features at discard time, did this tile deal in)` pairs)
that doesn't exist yet — docs/06-ml.md §3's "no Hong Kong equivalent of the Tenhou corpus" applies
here too, and bootstrapping one means self-play against a bot that doesn't have a safety model
yet to label danger against, a real follow-on project (generate logs, extract features, fit and
validate a model, re-integrate), not a same-sub-task extension. Flagged as the natural next step,
not silently skipped — see `bots/safety.py`'s module docstring for the same disclosure closer to
the code. Nineteen unit tests (`tests/test_safety.py`) pin each signal's *direction*, not its
calibrated accuracy.

## 6. T3 / search, and bot personas

Deferred — see [99-deferred.md](99-deferred.md).

## 7. Difficulty levels

| Level | How |
| --- | --- |
| Easy | T1, no safety model, calls melds too eagerly |
| Normal | T2 with mild weights, occasional suboptimal discard (ε ≈ 0.1), no fold logic |
| Hard | T2 tuned, full safety model, fold logic |
| Expert | Deferred — see [99-deferred.md](99-deferred.md). |

## 8. Evaluation harness

Build this alongside T1, not after:

```
python -m bots.arena --a FaanBot --b EfficiencyBot --games 20000 --seed 1 --parallel 8
```

Report: average points/hand, win rate, deal-in rate, average winning faan, tenpai-at-draw
rate, average turns to win, and **the rate of reaching tenpai on a sub-minimum-faan hand**
(`tenpai_rate_on_sub_minimum_hand`, the HK-specific failure metric from §4 — track it explicitly).

**Raw win totals over N games are not a statistical test.** HK scoring has high variance per hand
— limit hands (清一色, etc.) swing points sharply, and a 2% true edge between two bots can easily
sit inside the noise of 20k games' worth of point totals. The engine is pure and seeded, so paired
comparison is free and should be used instead of (not in addition to, at extra cost) more raw
games:

1. **Duplicate seeding.** For each seed, deal the same wall and play it out once per seat
   rotation (4 permutations of which bot sits in which seat), so both candidate and incumbent see
   *the same hands* across the run rather than relying on random assignment to average out.
2. **Paired difference.** Compute the per-duplicate-set point difference (candidate − incumbent),
   not raw win rate — pairing cancels the variance contributed by which bot got dealt the good
   hand.
3. **Report a confidence interval**, not a point estimate: mean paired difference ± 95% CI
   (bootstrap or normal-approximation over the paired differences is fine given the sample size).
   A candidate only merges if the CI for the paired difference excludes zero in the candidate's
   favor — "won more games out of 20k" alone is not sufficient.

Make "candidate's paired-difference CI excludes zero, in the candidate's favor" the merge gate for
any bot change (replacing a bare win-count threshold).

### Current arena numbers: T2 `FaanBot` vs T1 `EfficiencyBot`

`python -m bots.arena --a FaanBot --b EfficiencyBot --games 1000 --seed 1 --parallel 12` (1000
duplicate sets = 4000 games = 16,000 `FaanBot` hands, 48,000 `EfficiencyBot` hands, per §8's
duplicate-seeding method). Current shipped weights (`bots/faanbot.py`'s `_weights_for_turn` —
retuned twice against this harness; its docstring carries the full tuning history):

| Metric | FaanBot (A) | EfficiencyBot (B) |
| --- | --- | --- |
| win_rate | 0.1752 | 0.2239 |
| deal_in_rate | 0.1096 | 0.1389 |
| avg_winning_faan | 4.2294 | 3.7456 |
| tenpai_rate_on_sub_minimum_hand | 0.2243 | 0.3243 |
| avg_points_per_hand | 0.1108 | -0.0369 |

Paired difference (A − B): **+0.591 points/game, 95% CI [-0.393, +1.575]** — positive point
estimate, but the CI still includes zero, so this doesn't yet clear §8's merge gate on points
alone. `tenpai_rate_on_sub_minimum_hand` (0.224 vs T1's 0.324) is the number that does clear a
real bar: **T2 reaches a sub-minimum tenpai ~31% less often than T1**, the HK-specific failure
mode §4 exists to fix. Deal-in rate stays below T1's (better defence); win rate is still lower.
`w_safety` moved the needle further than `w_value`/`w_speed` in the retuning so far, so trimming
it further (or revisiting `bots/safety.py`'s own per-signal multipliers) is the open next step,
not a sign the approach is wrong.

## 9. Ruleset awareness

**Gap, not speculative.** [05-roadmap.md M6](05-roadmap.md) already ships `RULESET_PRESETS`
(`hk_classic`/`hk_casual`/`hk_strict`) plus a `custom` `RuleSet.from_dict` path via `POST
/tables` — a table can run today with `min_faan=1` (`hk_casual`) or `min_faan=5` with NEW_18
off (`hk_strict`, `mahjong_core/presets.py`). `Bot.act` only ever sees `SeatView` (§1); as of
Tier 1 it carries `ruleset: RuleSet`, and as of Tier 2's first two items (below)
`mahjong_core.shanten` and both bot tiers read `hand_sets` off it too, and `bots/valuation.py`
reads `faan_overrides` — `wall_reserve` is the one remaining hardcoded assumption.

| Hardcoded assumption | Where | Effect under a non-default ruleset |
| --- | --- | --- |
| ~~`min_faan = 3`~~ **closed, Tier 1** | was `bots/faanbot.py`'s `_ASSUMED_MIN_FAAN`; now `_should_claim` reads `view.ruleset.min_faan` | `_should_claim`'s claim guard now checks the table's real threshold under any preset |
| ~~`hand_sets` (which patterns are legal)~~ **closed, Tier 2** | was `mahjong_core/shanten.py`'s `shanten()` running Seven Pairs unconditionally whenever `closed=True`; now gated on `HandSet.NEW_18 in hand_sets` | `shanten()`/`ukeire()` (and both `EfficiencyBot`/`FaanBot`, which pass `view.ruleset.hand_sets` through) no longer chase a Seven Pairs shape that can't legally win under `hk_strict` |
| ~~`faan_overrides`~~ **closed, Tier 2** | was `bots/valuation.py`'s `ROUTE_FAAN` (fixed dict); now `route_faan_for(view.ruleset.faan_overrides)` remaps it via a route-name → `scoring/patterns.py` Chinese-pattern-name table, computed once per `FaanBot` decision and threaded into `estimate_best_faan`/`pattern_optionality` | T2's discard ranking follows a table's real per-pattern faan overrides instead of the fixed defaults; empty `faan_overrides` (every existing preset) is byte-identical to before (`route_faan_for({}) is ROUTE_FAAN`) |
| ~~`score_table`~~ **not actually a bot gap** | `mahjong_core/scoring/payout.py`'s `points()` already takes `ruleset` directly and reads `ruleset.score_table` — checked via `find_referencing_symbols`, `score_table` has no reference anywhere in `bots/` | None — this was miscategorized in an earlier pass of this table by being adjacent to `faan_overrides` (both are `RuleSet` scoring fields), not because any bot logic hardcoded it. `score_table` is a faan→**points** payout conversion scale (`ScoreTable.HALF_SPICY`/`FULL_SPICY`); `ROUTE_FAAN`/`estimate_best_faan` rank discards by estimated **faan**, never points, so there was never a value here for a bot to read |
| `wall_reserve`/`game_length` | `bots/faanbot.py`'s `_LATE_TURN`/`_weights_for_turn` breakpoints, hand-tuned against the default turn-count regime | "speed early → value mid → safety late" (§4) fires at the wrong point in a shorter/longer game |

**Plan, tiered by blast radius — Tier 2's remaining scope and revival requirements live in
[99-deferred.md](99-deferred.md):**

- **Built: `min_faan` only (Tier 1).** `ruleset: RuleSet` added to `SeatView` (`app/views.py`,
  `Entitlement.PUBLIC` field, populated in `seat_view()` from `state.ruleset` — `GameState`
  already carries `ruleset` directly, so none of `seat_view()`'s four call sites (`app/table.py`
  ×2, `bots/arena.py`, `bots/selfplay.py`) needed changes). `bots/faanbot.py`'s `_should_claim`
  now takes `min_faan` as a parameter and reads it from `view.ruleset.min_faan` at both call
  sites in `_act_on_claim`; the `_ASSUMED_MIN_FAAN` constant is deleted. `tests/test_faanbot.py`
  adds `test_should_claim_reads_min_faan_from_the_live_ruleset`, pinning the opposite claim
  decision (pung taken vs. passed) between `min_faan=1` and the `min_faan=3` default on the same
  scripted hand. `tests/test_redaction.py`'s entitlement walker (`_assert_wire_entitlement`)
  covers the new field automatically — it iterates `dataclasses.fields()`, not a hardcoded list —
  and `tests/test_safety.py`/`tests/test_efficiency.py`'s direct `SeatView(...)` test fixtures
  were updated to pass `ruleset=RuleSet()` for the new required field.
- **Built: `hand_sets` (Tier 2, first item).** Seven Pairs (七對子) is `HandSet.NEW_18`;
  Thirteen Orphans (十三么) is `HandSet.CLASSIC` (`mahjong_core/scoring/patterns.py`'s registry
  is the source of truth, not inference — every ruleset is assumed to carry `CLASSIC`, same
  assumption the rest of the pattern table already makes for the ~20 other `CLASSIC` patterns),
  so only the Seven Pairs parse needed gating. `mahjong_core/shanten.py`'s `shanten()`/`ukeire()`
  take a new `hand_sets: frozenset[HandSet] = frozenset(HandSet)` keyword param (imports
  `HandSet` from `mahjong_core/config.py` — same package, no cycle: `config.py` stays
  stdlib-only and doesn't import `shanten.py`); the default reproduces the old unconditional
  behavior exactly, so every existing caller (oracle cross-checks in `tests/test_shanten.py`,
  `bots/arena.py`'s tenpai/winning-tile helpers) is unaffected. `bots/efficiency.py` and
  `bots/faanbot.py` thread `view.ruleset.hand_sets` through every `shanten()`/`ukeire()` call
  site. `bots/safety.py` and `bots/valuation.py` don't call either function directly (checked via
  `find_referencing_symbols`), so neither needed changes. `bots/arena.py`'s own direct `shanten()`
  calls (tenpai-rate/winning-tile stats, not a bot decision) were deliberately left as-is — out
  of this item's scope; see note below. New tests:
  `tests/test_shanten.py::test_seven_pairs_gated_by_hand_sets` (same shape as
  `test_closed_false_skips_seven_pairs_and_kokushi`, pins `hand_sets` without `NEW_18` at
  `standard_shanten`'s value, strictly worse than with it, default unchanged) and
  `tests/test_faanbot.py::test_discard_stops_chasing_seven_pairs_when_new_18_is_off` (a
  6-honor-pairs + manzu-ryanmen hand where `FaanBot` sacrifices the ryanmen for a Seven Pairs
  tenpai under `hk_classic` but keeps it under `hk_strict`'s `hand_sets`).
- **Built: `faan_overrides` (Tier 2, second item).** Investigated first, per the item's own
  scoping note — `score_table`/`faan_overrides` were previously listed as one combined row, but
  they're unrelated: `mahjong_core/scoring/payout.py`'s `points()` already takes `ruleset`
  directly and is a faan→**points** payout conversion (`ScoreTable.HALF_SPICY`/`FULL_SPICY`),
  with zero references anywhere in `bots/` (checked via `find_referencing_symbols`) — never a bot
  gap at all, see the table above. `faan_overrides` (a `{pattern_name: faan}` map keyed by the
  Chinese name `scoring/patterns.py`'s `PATTERNS` registry uses, applied in
  `scoring/faan.py`'s `_candidate_breakdown`) *does* change a pattern's real faan value, and is
  the only one of the two `bots/valuation.py`'s `ROUTE_FAAN` needed to track. `bots/valuation.py`
  adds `route_faan_for(faan_overrides) -> dict[str, int]`, remapping `ROUTE_FAAN` through a
  private `_ROUTE_PATTERN_NAMES` table (`"full_flush" -> "清一色"`, `"half_flush" -> "混一色"`,
  etc. — every entry cross-checked 1:1 against `ROUTE_FAAN`'s own base values in
  `tests/test_valuation.py`); empty `faan_overrides` (every existing preset) returns `ROUTE_FAAN`
  itself unchanged (`is`, not just `==`), so every caller that doesn't thread a ruleset through is
  byte-identical to before. `reachable_routes`/`estimate_best_faan`/`pattern_optionality` take a
  new `route_faan: dict[str, int] = ROUTE_FAAN` keyword param instead of reading the module
  constant directly. No `functools.cache`/`lru_cache` was used: `RuleSet` is a frozen dataclass
  but not actually hashable (`faan_overrides: dict[str, int]` is a mutable field, so
  `dataclasses`' auto-generated `__hash__` raises `TypeError` on a bare `hash(ruleset)` —
  confirmed directly), so memoizing on the `RuleSet` itself isn't safe; `route_faan_for` is called
  once per `FaanBot` decision (top of `_act_on_claim`/`_best_discard`) and the resulting dict
  reused across that decision's candidate loop, rather than rebuilt per candidate or unsafely
  cached. `bots/faanbot.py` threads the resulting `route_faan` into every
  `estimate_best_faan`/`pattern_optionality` call site (`_act_on_claim`, `_should_claim`,
  `_best_discard`). New tests: `tests/test_valuation.py` (`route_faan_for`'s empty-override
  identity and pattern-name-mapped override, plus `estimate_best_faan` picking a different best
  route once an override is applied) and `tests/test_faanbot.py::
  test_discard_follows_faan_overrides_boosting_a_route` (same marginal-value hand as
  `test_does_not_chase_a_marginal_value_signal` — 南 wins by default at every turn bucket;
  boosting `混一色` to 15 via `faan_overrides` flips the discard to 5p at every turn bucket,
  verified directly against `FaanBot.act`) plus
  `test_discard_with_empty_faan_overrides_matches_default_route_faan` pinning the empty-override
  regression requirement at the bot level, not just inside `bots/valuation.py`.

  Arena regression check (docs/99-deferred.md's Tier 2 revival requirement) — default ruleset,
  no `faan_overrides`, so this is a pure regression check that threading `ruleset` through
  `bots/valuation.py` didn't perturb anything, not a re-tune:
  `docker compose --profile tools run --rm arena uv run python -m bots.arena --a FaanBot --b
  EfficiencyBot --games 500 --parallel 8` (500 duplicate sets, smaller sample than §8's
  documented 1000-set run — same seed default):

  | Metric | FaanBot (A) | EfficiencyBot (B) |
  | --- | --- | --- |
  | win_rate | 0.1744 | 0.2238 |
  | deal_in_rate | 0.1110 | 0.1400 |
  | avg_winning_faan | 4.2444 | 3.7151 |
  | tenpai_rate_on_sub_minimum_hand | 0.2251 | 0.3260 |
  | avg_points_per_hand | 0.2380 | -0.0793 |

  Paired difference (A − B): **+1.269 points/game, 95% CI [-0.128, +2.667]** — every metric sits
  within a few thousandths to a few hundredths of §8's documented 1000-set baseline (win_rate
  0.1752/0.2239, deal_in_rate 0.1096/0.1389, avg_winning_faan 4.2294/3.7456,
  tenpai_rate_on_sub_minimum_hand 0.2243/0.3243), and the paired-difference point estimate keeps
  the same sign with an overlapping CI (baseline +0.591, [-0.393, +1.575]) — the wider CI here is
  expected at half the duplicate-set count, not a sign of drift. Confirms threading `ruleset`
  through `bots/valuation.py` didn't perturb default-ruleset (empty `faan_overrides`) behavior.
- **`wall_reserve` (Tier 2, still deferred).** `bots/faanbot.py`'s `_LATE_TURN`/
  `_weights_for_turn` breakpoints, hand-tuned against the default turn-count regime — re-deriving
  them as a fraction of the ruleset's actual turn budget invalidates the shipped
  `_weights_for_turn` tuning (§4/§8) the same way `faan_overrides` did, so it needs its own full
  arena re-run before merging (`--games 1000+`, paired-difference CI excludes zero, §8) —
  re-tuning cost, not implementation cost, is what makes this Tier 2. Out of scope for the
  `faan_overrides` item above; not touched here. (`bots/arena.py`'s own `shanten()` calls, used
  only for tenpai/win-rate stats rather than a bot's actual decision, are still not
  `hand_sets`-aware either — noted here rather than the table above since it isn't bot behavior,
  but worth revisiting alongside a future item since an `hk_strict` arena run's tenpai-rate stat
  currently over-counts hands that are only tenpai via a Seven Pairs shape that table can't
  complete.)
