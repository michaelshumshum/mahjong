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

`mask` is `legal_mask(state, seat) -> list[bool]` (docs/06-ml.md §1's real signature —
**resolved, was written here as `legal_mask(view)`**: `mahjong_core` must never depend on
`app.views`, so `legal_mask` stays `GameState`-based; whoever drives a bot — the self-play
harness, the arena, or the Room — computes the mask from the real `GameState` it already holds
and hands `(view, mask, deadline)` to `Bot.act` together. `mahjong_core` is stdlib-only (see
README / roadmap "zero deps" rule) — **no numpy**, plain `list[bool]`. A bot never calls
`decode_action` itself, for the same reason: it needs the real `GameState`, which a bot never
has (`app/views.py`'s `SeatView` is the whole point). Decoding the returned id back into a
concrete `Action` is always the caller's job — near-zero cost, and a learned policy drops into
the same slot later with no refactor. See [06-ml.md](06-ml.md), and `server/bots/base.py`'s
module docstring for the implementation of this resolution.

**Scheduling.** Bot decisions do not run inside the room's `asyncio` task — a shanten/ukeire scan
is tens of milliseconds of pure-Python CPU (§3), which would stall the event loop for every other
room on the same process. Instead:

1. The room enqueues `(bot_id, view, mask, deadline, window_id, state_version)` to a
   `ProcessPoolExecutor` (the GIL makes a thread pool useless for CPU-bound pure-Python search —
   a process pool is the only scheduling primitive that actually parallelises this work).
2. The worker computes an action id and returns `(window_id, state_version, action_id)` to the
   room's inbox.
3. The room compares the tag against its *current* `window_id`/`state_version`. If they don't
   match — the claim window closed, or the hand moved on before the worker replied — the result
   is **dropped silently**, exactly like a stale human claim. This is the same staleness
   protection humans get; bots get no special path around it.
4. If no (matching) result lands before `deadline`, the room applies a safe default (tsumogiri /
   pass) and logs it. A bot must never wedge a table.

Add a humanising think delay — 400–1400ms, longer for close decisions — applied by the room when
scheduling the deadline, not inside the worker.

**`bots/worker.py`'s `compute_action` stays separate from `Bot.act`, deliberately, even after
the M4 interface migration below.** A worker process never receives `GameState` (D2: the room's
`game_seed` must never leave its own process), but decoding a `Bot.act`-returned id back into a
concrete `Action` needs one (`decode_action(aid, state, seat)`). Routing the live
disconnect-handover path through `Bot.act` would move that decode step into the Room after the
result comes back — a real change to `app/room.py`'s result handling, not a refactor this
sub-task's scope covers. `compute_action` keeps its own uniform-random-over-`legal_actions`
implementation against `SeatView` directly; revisit this only when a non-uniform tier needs to
run disconnect-handover for real. See `server/bots/worker.py`'s module docstring.

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
"Bots run outside the room's task" bounds the room's `asyncio` loop, not total CPU — it does not
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

### Real proof run (M4): T2 `FaanBot` vs T1 `EfficiencyBot`

`python -m bots.arena --a FaanBot --b EfficiencyBot --games 1000 --seed 1 --parallel 12`, run
live end to end (~27 minutes; T2's per-decision cost is far higher than T1's — every candidate
discard runs a `bots.valuation`/`bots.safety` pass on top of the shared shanten/ukeire scan, see
[07-infra.md](07-infra.md)/the roadmap's bot-perf risk row). 1000 duplicate sets = 4000 games =
16,000 `FaanBot` hands and 48,000 `EfficiencyBot` hands (T2 occupies one seat per rotation, T1
the other three, per §8's duplicate-seeding method).

**First pass — a real regression, reported honestly rather than re-tuned away silently.** The
weights this sub-task shipped with first (mid-game `w_value=1.5`, `w_speed=0.5`) scored:

| Metric | FaanBot (A) | EfficiencyBot (B) |
| --- | --- | --- |
| win_rate | 0.1354 | 0.2251 |
| deal_in_rate | 0.0932 | 0.1334 |
| avg_winning_faan | 4.30 | 3.75 |
| tenpai_rate_on_sub_minimum_hand | 0.1627 | 0.3263 |
| avg_points_per_hand | -0.4537 | 0.1512 |

Paired difference (A − B): **-2.420 points/game, 95% CI [-3.337, -1.503]** — excludes zero in
`EfficiencyBot`'s favor. `tenpai_rate_on_sub_minimum_hand` roughly halved (the canary this whole
sub-task exists to move), but win rate dropped by ~40% relative and points went net negative: the
first weight calibration chased *every* structurally-reachable route (including the ubiquitous,
weakly-committal 2-faan Voided Suit — reachable on any hand touching exactly two suits) almost as
eagerly as a genuine Half/Full Flush commitment, spending far more win rate than the extra faan
per win was worth. This is exactly the failure mode §8's merge gate exists to catch before a
"structurally more sophisticated" bot ships as a regression.

**Retuned once, same seed range, real re-run — narrowed but did not close the gap.** Mid-game
`w_value` dropped 1.5 → 0.9 (`w_speed` up 0.5 → 0.7; early/late nudged the same direction — see
`bots/faanbot.py`'s `_weights_for_turn` for the exact numbers and reasoning):

| Metric | FaanBot (A) | EfficiencyBot (B) |
| --- | --- | --- |
| win_rate | 0.1539 | 0.2246 |
| deal_in_rate | 0.0981 | 0.1368 |
| avg_winning_faan | 4.25 | 3.74 |
| tenpai_rate_on_sub_minimum_hand | 0.2038 | 0.3208 |
| avg_points_per_hand | -0.1703 | 0.0568 |

Paired difference (A − B): **-0.908 points/game, 95% CI [-1.857, +0.041]** — includes zero
(barely: the upper bound sits 0.04 points from crossing it), so this does **not** yet clear §8's
merge gate on points alone. Deal-in rate stays lower than T1's (better defence) and average
winning faan stays higher (bigger wins when they land), but the two don't yet fully offset a
still-lower win rate. `tenpai_rate_on_sub_minimum_hand` (0.204 vs T1's 0.321) is the number that
does clear a clear, real bar: **T2 reaches a sub-minimum tenpai roughly 37% less often than T1**,
the specific, documented HK-only failure mode (§4: "a T1-only bot loses by construction in HK")
this sub-task exists to fix. That number moving this much, this consistently, across both
calibrations is the real evidence T2's value-planning is structurally doing its job even though
the points race isn't fully won yet.

**Honest status, not spun:** T2 is a genuine structural improvement on the HK-specific failure
mode this whole section is about, and a real (if not yet statistically decisive) step toward
parity on raw points — not a clean "beats T1" result by §8's own merge-gate wording. Further
weight tuning via self-play against this same harness (§4's own stated method) is real,
concrete follow-up work, not a hand-wave: one retuning pass moved the paired-difference point
estimate from -2.42 to -0.91 and the CI's upper bound from -1.50 to +0.04 on the same seed
range, so the remaining gap looks closeable with the same technique, not a sign the approach is
wrong.
