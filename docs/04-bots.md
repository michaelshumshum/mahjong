# 04 — Computer players

## 1. Bot interface

A bot receives exactly the output of `seat_view(state, seat)` — the same redacted `SeatView` a
human gets — and returns an intent. It has no access to `GameState`, the wall, or other hands.
(`redact_event` is the separate wire-facing function for outbound events; bots don't use it. See
[00-architecture.md](00-architecture.md).)

**One deliberate exception: `"ORACLE"` (§10).** A worker process never receives real hidden
information beyond `view.own_hand` — with exactly one exception, contained to one tier and one
call site. `"ORACLE"` is a plain `FaanBot()` (`bots/worker.py`'s `_make_bot`) driven by a
`SeatView` with `.hands` populated (every seat's concealed tiles), built by `app/views.py`'s
`_omniscient_seat_view` —
the only call site for that function anywhere in the codebase is `app/table.py`'s
`_submit_bot_job`, in its oracle-tier branch, verified structurally
(`tests/test_oracle_containment.py`). This is safe to cross the `ProcessPoolExecutor` boundary
specifically because `SeatView` never carries `game_seed`/`hand_seed` — the "`game_seed` never
leaves this process" invariant ([00-architecture.md §3](00-architecture.md)) is about the seed,
not about tile visibility — and it never reaches a real client: disconnect-handover always uses
`T2`/`FaanBot` regardless of the table's configured tier, so a human's own seat can never be
driven by `"ORACLE"`, and no wire-facing function (`seat_view_wire`, `state_sync_wire`) ever
calls `_omniscient_seat_view`. See §10 for the full design.

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
(`T0`-`T2`/`ORACLE`, `bots.worker.BOT_TIERS`; `app/table.py`'s `Table.__init__(bot_tier=...)`,
default `T2`/`FaanBot`) and drives
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
| **T3** `SearchBot` | determinized-world rollout search over the pure engine | ~350 lines | **Built (M6), then removed** — statistically worse than `FaanBot` after two real debugging rounds; a structural ceiling, not a bug. No tier currently occupies "Expert" — see §6/§7. |
| **T4** learned policy | supervised on self-play or human logs | research | optional, later — see §6's closing note on what would make a future search-based tier viable |
| **`ORACLE`** | a plain `FaanBot()` fed full-information (`view.hands`) instead of the ordinary view | 0 extra lines (reuses `FaanBot`) | **not on this ladder** — explicitly opt-in only, a table has to be deliberately configured to run it; never a difficulty option (§7). **Built** — see §10 for the shipped design and the safety argument. |

Ship T1 and T2 in M4 (§4 explains why T1 alone can't satisfy M4's done-gate). T3 was out of scope
for M4 and shipped later, in M6, once the per-tier pool-routing precondition existed — see §6 for
the shipped design, the arena result, and why it was removed rather than kept and re-tuned.

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

## 6. T3 `SearchBot` — built, debugged twice, removed

**Removed.** Was `server/bots/search.py`: determinized-world Monte Carlo rollout search. Per
decision (only for a real `Phase.AWAIT_ACTION` turn): sample N worlds consistent with the
redacted `SeatView`, for each legal root action roll forward up to `rollout_depth` further
decisions with `FaanBot` acting for every seat, value a rollout by its real point delta if it
reached `HAND_OVER` or a shanten/reachable-faan/ukeire proxy if it hit the depth cap first,
average each action's value across the worlds it was evaluated in, return the best. Full
original design — `determinize()`'s tile-conservation argument, the scope cuts
(`AWAIT_ACTION`-only search, bounded-depth rollout instead of full hand-to-`HAND_OVER`, strategy
fusion accepted-not-solved, the dedicated pool sizing), and the arena numbers below — is
preserved as the historical record in [99-deferred.md](99-deferred.md)'s "T3 `SearchBot`" entry,
which also carries the real requirements for a future revival.

### What happened

Two real debugging rounds (the same session that also redesigned `ORACLE`, §10) found and fixed
three genuine bugs in the rollout search — not tuning:

1. **Sampling bias.** A fixed ascending `legal_ids` iteration order, combined with deadline
   pressure cutting a world's candidate sweep short (routine under the real time budget),
   systematically starved every candidate after the cutoff point of samples, on every world,
   every decision — a bias toward low action ids, not neutral variance. Fixed by shuffling
   candidate order per world.
2. **Tie-break bias.** The value-estimate proxy is small-integer-valued, so an exact tie for the
   best average action value is common, not a corner case — confirmed directly against real
   self-play decisions: 20 of 40 sampled decisions had a multi-way tie, and `max()`'s
   first-encountered-wins tie-break resolved every one of those 20 to the lowest action id. Fixed
   by breaking ties uniformly at random.
3. **Missing ukeire term.** The value-estimate proxy combined only shanten and reachable-faan,
   both frequently tied across candidates too — leaving the rollout with no signal to break the
   tie-break bug's own tie, exactly on "which of these equally-safe discards actually opens up
   more tiles." Fixed by adding a scaled ukeire term, mirroring `bots/faanbot.py`'s own
   `_speed_term`.

All three are real, independently diagnosed, and independently justified. Despite that, the
flagship arena metric (tenpai rate) barely moved. The final validation run (15 duplicate sets,
paired-duplicate methodology, §8) with all three fixes live:

```
paired difference (SearchBot - FaanBot), mean points/game: -13.156
95% CI: [-25.581, -0.730]  -- excludes zero, in FaanBot's favor
tenpai_at_draw_rate: SearchBot 6.35% vs FaanBot 51.85%
```

Decisively worse than the tier it was supposed to sit a rung above, and the core symptom —
almost never reaching tenpai — essentially unchanged from the smaller (8 duplicate sets),
CI-includes-zero plausibility check this section originally reported before the fixes.

### Why removed, not re-tuned

Same root-cause diagnosis §10's "History" subsection already reached for `OracleBot`'s
predecessor: both bots rolled out every candidate through the same noisy, few-sample,
`FaanBot`-driven rollout, so search could only ever be as good as "which root action leads to the
best downstream `FaanBot`-driven outcome" — a noisy value estimate could, and did, pick a worse
root action than `FaanBot` would have chosen directly. Three unrelated, correctly-diagnosed
implementation bugs fixed with zero movement on the flagship metric is the signature of hitting
that ceiling, not of needing one more fix.

The literature agrees, and predicts this specific failure mode:

- **Determinized/"perfect information Monte Carlo" (PIMC) search has two named pathologies**:
  *strategy fusion* (the search plans a different continuation per sampled world, which a real
  player can't do across their own single hidden hand) and *non-locality* (a subtree's true value
  depends on the opponent's actual strategy, not just what a rollout policy happens to do in it).
  `SearchBot`'s own module docstring already named strategy fusion as an accepted, unsolved
  weakness — it isn't a fringe concern: Cazenave & Ventos's αμ search
  ([arXiv:1911.07960](https://arxiv.org/abs/1911.07960)) exists specifically because PIMC's
  strategy-fusion/non-locality pathologies are severe enough in Bridge (a comparable
  hidden-information trick game) to need a structurally different search algorithm, not a better
  heuristic inside the same PIMC loop.
- **[arXiv:1904.07491](https://arxiv.org/abs/1904.07491)** (Kurita & Hoki, already cited by this
  doc for strategy fusion) does not build a naive determinized-rollout MCTS over mahjong's raw
  game tree at all — its whole contribution is an MDP *abstraction* specifically to make search
  tractable and meaningful under mahjong's imperfect information. A real, published mahjong-AI
  approach in the same design space avoiding exactly the algorithm shape `SearchBot` used is
  independent evidence that plain PIMC with a heuristic rollout policy is a known-weak fit here,
  not a novel discovery of this project's own arena runs.
- **Suphx** ([arXiv:2003.13590](https://arxiv.org/abs/2003.13590)) and **Mortal**
  (`docs/06-ml.md`'s other reference architecture) are both learned value/policy-function
  approaches — Suphx a deep network trained via self-play RL, Mortal a pure forward pass through a
  trained network — neither a heuristic-rollout search. That the two strongest published mahjong
  AIs both spent their engineering budget on a learned evaluator instead of search depth is
  consistent with PIMC's known dependence on rollout/evaluation quality: averaging over sampled
  worlds only beats the policy itself if the per-node value estimate carries real signal, and a
  hand-tuned heuristic's own scoring is already close to whatever a shallow rollout of it can
  discover — so the search layer mostly adds small-sample noise, not new signal.

None of this indicts `FaanBot` (§4/§8's numbers stand on their own) or the engineering of
`bots/search.py` (`determinize()`'s tile-conservation guarantee, the deadline discipline, the
three bug fixes above are all real, correct work) — it indicts the specific combination of
"determinized rollout" plus "the same static heuristic as both the acting policy and the leaf
evaluator," as an approach, for this game, at this evaluation-function quality.

### What would make a future attempt viable

Not attempted in this pass; full requirements captured in
[99-deferred.md](99-deferred.md) so a revival starts from the real constraint list instead of
re-discovering it. In rough order of realism: (a) a rollout leaf evaluator meaningfully better
than a shallow rollout of the same heuristic used as the policy — realistically a learned value
function (T4), itself blocked on compute-budget/training-corpus/success-metric decisions nobody
has made yet; (b) real information-set MCTS (solves strategy fusion/non-locality properly, unlike
determinization) — already flagged as non-trivial, undone design work, not a parameter change;
(c) materially more rollout budget — arithmetically incompatible with the measured ~4.7ms/decision
× ~83 decisions/hand economics at this project's target concurrency (200 tables × 3 bot seats)
unless that target or the hardware budget changes.

### Bot personas

Still deferred — see [99-deferred.md](99-deferred.md)'s "Bot personas" entry. Unaffected by `T3`
shipping or its later removal: a persona (name, play-style bias, think-time distribution) is
layered on top of whichever tier answers, not a tier itself.

## 7. Difficulty levels

| Level | How |
| --- | --- |
| Easy | T1, no safety model, calls melds too eagerly |
| Normal | T2 with mild weights, occasional suboptimal discard (ε ≈ 0.1), no fold logic |
| Hard | T2 tuned, full safety model, fold logic |

**No "Expert" row currently ships.** T3 `SearchBot` was built and was meant to fill it, but was
removed after arena validation showed it decisively worse than `FaanBot`/"Hard" — see §6 for the
full history and why. "Hard" (tuned T2) is the strongest tier a normal player can select today;
revisit this table if/when §6's "What would make a future attempt viable" is ever acted on.

`ORACLE` (§10) is **not** a candidate for this table either way, past or future — it isn't a
difficulty a player picks, it's a full-information analysis/showcase tier a table opts into
explicitly (UI for that opt-in is a separate, later task). It was never meant to be read as
"harder than Expert" on the same continuum; the actual difference is information level, not
skill.

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

**Was a gap; now closed.** [05-roadmap.md M6](05-roadmap.md) already ships `RULESET_PRESETS`
(`hk_classic`/`hk_casual`/`hk_strict`) plus a `custom` `RuleSet.from_dict` path via `POST
/tables` — a table can run today with `min_faan=1` (`hk_casual`) or `min_faan=5` with NEW_18
off (`hk_strict`, `mahjong_core/presets.py`). `Bot.act` only ever sees `SeatView` (§1); it
carries `ruleset: RuleSet` (Tier 1), and every Tier 2 item below is now closed too —
`mahjong_core.shanten` and both bot tiers read `hand_sets` off it, `bots/valuation.py` reads
`faan_overrides`, and `bots/faanbot.py`'s turn-based weight schedule reads `wall_reserve`/
`flowers_enabled`. **Tier 2 is fully closed as of this row** — see
[99-deferred.md](99-deferred.md) for the historical record of what was deferred and why.

| Hardcoded assumption | Where | Effect under a non-default ruleset |
| --- | --- | --- |
| ~~`min_faan = 3`~~ **closed, Tier 1** | was `bots/faanbot.py`'s `_ASSUMED_MIN_FAAN`; now `_should_claim` reads `view.ruleset.min_faan` | `_should_claim`'s claim guard now checks the table's real threshold under any preset |
| ~~`hand_sets` (which patterns are legal)~~ **closed, Tier 2** | was `mahjong_core/shanten.py`'s `shanten()` running Seven Pairs unconditionally whenever `closed=True`; now gated on `HandSet.NEW_18 in hand_sets` | `shanten()`/`ukeire()` (and both `EfficiencyBot`/`FaanBot`, which pass `view.ruleset.hand_sets` through) no longer chase a Seven Pairs shape that can't legally win under `hk_strict` |
| ~~`faan_overrides`~~ **closed, Tier 2** | was `bots/valuation.py`'s `ROUTE_FAAN` (fixed dict); now `route_faan_for(view.ruleset.faan_overrides)` remaps it via a route-name → `scoring/patterns.py` Chinese-pattern-name table, computed once per `FaanBot` decision and threaded into `estimate_best_faan`/`pattern_optionality` | T2's discard ranking follows a table's real per-pattern faan overrides instead of the fixed defaults; empty `faan_overrides` (every existing preset) is byte-identical to before (`route_faan_for({}) is ROUTE_FAAN`) |
| ~~`score_table`~~ **not actually a bot gap** | `mahjong_core/scoring/payout.py`'s `points()` already takes `ruleset` directly and reads `ruleset.score_table` — checked via `find_referencing_symbols`, `score_table` has no reference anywhere in `bots/` | None — this was miscategorized in an earlier pass of this table by being adjacent to `faan_overrides` (both are `RuleSet` scoring fields), not because any bot logic hardcoded it. `score_table` is a faan→**points** payout conversion scale (`ScoreTable.HALF_SPICY`/`FULL_SPICY`); `ROUTE_FAAN`/`estimate_best_faan` rank discards by estimated **faan**, never points, so there was never a value here for a bot to read |
| ~~`wall_reserve`~~ **closed, Tier 2 (last item)** | was `bots/faanbot.py`'s fixed `_LATE_TURN=12`/turn-6 constants in `_weights_for_turn`; now `_turn_breakpoints(ruleset)` scales them off `mahjong_core.wall.max_turns_per_seat(ruleset)` | `_weights_for_turn`'s speed/value/safety schedule and fold-mode's lateness gate now shift proportionally earlier under a smaller real per-hand turn budget (`wall_reserve` up, or `flowers_enabled` off), instead of always firing at the fixed turn 6/12 tuned against the default regime |
| ~~`game_length`~~ **not actually a bot gap** | `mahjong_core/engine.py`'s `start_next_hand` reads `ruleset.game_length` via `_ALLOWED_ROUNDS` to decide when a *match* (not a hand) ends — checked via `find_referencing_symbols`, `GameLength`/`game_length` has no reference anywhere in `bots/` | None — this was miscategorized in the doc-9 gap table by being adjacent to `wall_reserve` (both flow-control `RuleSet` fields under "flow"), not because any bot logic hardcoded it. `game_length` controls how many *hands* make up a match (4/8/16 for EAST_ONLY/EAST_SOUTH/FULL); `bots/faanbot.py`'s turn-based weights key off `turn = len(view.discard_pools[view.seat])`, this seat's discard count *within the current hand* — a completely different axis, unaffected by how many hands the match runs for |

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
- **Built: `wall_reserve` (Tier 2, last item — Tier 2 now fully closed).** `mahjong_core/wall.py`
  gains `max_turns_per_seat(ruleset) -> int`, a pure function of `RuleSet` alone: total physical
  tiles (144 with `flowers_enabled`, 136 without, see `new_wall`) minus the initial deal
  (`13*4 + 1` dealer extra = 53, see `deal_hands`) minus `wall_reserve`, split evenly across 4
  seats. It counts front (normal-turn) draws only — a kong/flower replacement draws from the
  *back* of the same wall (no separate dead wall) without ending that seat's turn, so this is a
  deliberate upper-bound approximation, not an exact simulation: exactly how many replacement
  draws happen in a given hand depends on how many flowers get dealt/drawn and how many kongs get
  declared, both per-hand randomness this function ignores to stay allocation-time-pure.

  `bots/faanbot.py`'s fixed `_LATE_TURN = 12` constant and `_weights_for_turn`'s hardcoded
  turn-6/turn-12 schedule are gone; `_turn_breakpoints(ruleset)` derives `(early, late)` by
  scaling `_EARLY_TURN_AT_REFERENCE = 6`/`_LATE_TURN_AT_REFERENCE = 12` by
  `max_turns_per_seat(ruleset) / _REFERENCE_MAX_TURN`, where `_REFERENCE_MAX_TURN =
  max_turns_per_seat(RuleSet())`. **Calibration arithmetic** (also in `bots/faanbot.py`'s own
  comment): at the default ruleset, `144 - 53 - 0 = 91` available draws `// 4` seats `= 22 =
  _REFERENCE_MAX_TURN`, so `early = round(6 * 22 / 22) == 6` and `late = round(12 * 22 / 22) ==
  12` exactly, by construction, for every ruleset with `max_turns_per_seat(ruleset) ==
  _REFERENCE_MAX_TURN` — every shipped preset. `_best_discard` threads `_turn_breakpoints(view.
  ruleset)` into both `_weights_for_turn` and the fold-mode lateness gate (`turn >= late_turn`,
  replacing `turn >= _LATE_TURN`).

  New tests in `tests/test_faanbot.py`:
  `test_turn_breakpoints_match_the_old_hand_tuned_constants_at_default_ruleset` (structural pin:
  `max_turns_per_seat(RuleSet()) == 22` and `_turn_breakpoints(RuleSet()) == (6, 12)` exactly, not
  "close to"), `test_turn_breakpoints_shift_earlier_under_a_smaller_turn_budget`
  (`RuleSet(wall_reserve=40)` → `max_turns_per_seat` 12 → breakpoints `(3, 7)`, proportionally
  scaled down from `(6, 12)`), and `test_fold_mode_triggers_earlier_under_a_smaller_turn_budget`
  (the same far-past-3-shanten, threatening-opponent scripted hand as
  `test_folds_to_a_safe_tile_late_against_a_threatening_opponent`, at turn 8 instead of 13: the
  default ruleset still treats turn 8 as mid-game — `FaanBot` picks a different discard, not the
  safe genbutsu tile — while `RuleSet(wall_reserve=40)`'s late-turn value of 7 makes turn 8
  already late, and the bot folds to the same safe tile the turn-13 test pins; verified directly
  against `FaanBot.act` before pinning, per this module's convention).

  Arena regression check (docs/99-deferred.md's Tier 2 revival requirement) — default ruleset,
  `wall_reserve=0`, so `_turn_breakpoints` reproduces the old fixed `(6, 12)` exactly and this is
  a pure regression check that the threading didn't perturb anything, not a re-tune (no new
  arena run was needed *because* the calibration constraint in this item guarantees the default
  path is untouched by construction — run anyway, to prove it rather than assert it):
  `docker compose --profile tools run --rm -e UV_CACHE_DIR=/tmp/uv-cache arena uv run --no-sync
  python -m bots.arena --a FaanBot --b EfficiencyBot --games 500 --parallel 8` (500 duplicate
  sets, same seed default as the `faan_overrides` item's regression run):

  | Metric | FaanBot (A) | EfficiencyBot (B) |
  | --- | --- | --- |
  | win_rate | 0.1744 | 0.2238 |
  | deal_in_rate | 0.1110 | 0.1400 |
  | avg_winning_faan | 4.2444 | 3.7151 |
  | tenpai_rate_on_sub_minimum_hand | 0.2251 | 0.3260 |
  | avg_points_per_hand | 0.2380 | -0.0793 |

  Paired difference (A − B): **+1.269 points/game, 95% CI [-0.128, +2.667]** — every metric is
  byte-identical to the `faan_overrides` item's own 500-set regression run above, which is exactly
  what the calibration constraint predicts: `_turn_breakpoints(RuleSet()) == (6, 12)` means
  `FaanBot`'s discard/claim decisions under the default ruleset are unchanged bit-for-bit by this
  change, so re-running the same seeded arena harness against the same two bots reproduces the
  same numbers rather than merely "the same ballpark."

  Unrelated housekeeping note carried over from this item's investigation: `bots/arena.py`'s own
  direct `shanten()` calls (tenpai-rate/winning-tile stats, not a bot decision) are still not
  `hand_sets`-aware — noted here since it isn't bot behavior and was out of scope for the
  `hand_sets` item too, but worth revisiting since an `hk_strict` arena run's tenpai-rate stat
  currently over-counts hands that are only tenpai via a Seven Pairs shape that table can't
  complete.

## 10. `"ORACLE"` tier

**Built, redesigned.** A plain `FaanBot()` (`bots/worker.py`'s `_make_bot`) driven by a `SeatView`
with every seat's concealed tiles populated (`.hands`) instead of only `view.own_hand` — no
dedicated class, no search, no rollout. Same `Bot.act(view, mask, deadline) -> int` shape as every
other tier, unchanged from `faanbot.py`. **Not on the T0-T2 difficulty ladder** (§2/§7): explicitly
opt-in only, a live table has to be deliberately configured to run it — UI/protocol work for
actually offering that choice in table setup (`CreateTableDialog.svelte`/`POST /tables`) is a
separate, later task; a table *could* run it today via direct `Table(bot_tier="ORACLE")`
construction, just not through the lobby yet.

### History: why the original rollout-based design got replaced

The tier originally shipped as `bots/oracle.py`'s `OracleBot`: a `SearchBot`-style determinized-
wall rollout search, differing from `SearchBot` only in how the root `GameState` was built
(`view.hands` fixes hand composition exactly, so only wall *draw order* needed sampling). Two
rounds of debugging `SearchBot`'s shared rollout algorithm found and fixed three real bugs there
(sampling bias, tie-break bias, missing ukeire signal), but `SearchBot` stayed statistically worse
than `FaanBot` in arena validation, and `OracleBot` inherited the same ceiling despite full
information. The root cause was structural, not a tuning problem: both bots rolled out every
candidate action using `FaanBot` as the policy for every future decision, so search could only ever
be as good as "which root action leads to the best downstream `FaanBot`-driven outcome" — a noisy
few-sample value estimate could (and did) pick a worse root action than `FaanBot` would have chosen
directly. Full information wasn't fixing this: it only changed which *worlds* got sampled (wall
order), not how a candidate got evaluated — every candidate was still scored through the same
noisy rollout machinery.

The actual fix needed no search at all. `bots/safety.py`'s `tile_risk` exists because a normal bot
can't know whether a discard deals in — it estimates `P(deal_in | tile)` from genbutsu/suji/meld-
reading/wall-pressure, explicitly documented as "statistical evidence, not proof" (§5). That is the
one thing full information genuinely eliminates: with every opponent's hand known, "does this exact
tile complete seat X's exact hand right now" is a direct, cheap, exact check — no rollout, no
sampling, no noise. Making `tile_risk` hands-aware (below) means `FaanBot`'s own existing
`_best_discard` — completely unmodified — already exploits full information correctly the moment
it's handed an omniscient view. `bots/oracle.py` is deleted; nothing from its rollout loop was worth
keeping (`_omniscient_state`'s tile-accounting logic was the one piece that looked reusable, but the
exact-win check below needed a different shape — a candidate `SeatState` per opponent per candidate
tile, not a whole determinized `GameState` — so it was rewritten rather than reused).

### The exact-danger mechanism

`bots/safety.py`'s `tile_risk(view, tile_type)` branches on `view.hands`:

- **`view.hands is None`** (every tier except `"ORACLE"`): byte-identical to the original
  probabilistic model — `sum(deal_in_probability(view, opp, tile_type) * expected_cost(view, opp,
  tile_type) for opp in ...)`. A strict superset, not a replacement (`tests/test_safety.py::
  test_tile_risk_hands_none_matches_the_original_probabilistic_formula` pins this).
- **`view.hands is not None`**: for each opponent, `_exact_deal_in_faan` builds the candidate hand
  they'd have if this exact tile landed in their real concealed tiles (`(*view.hands[opp],
  synthetic_tile)`), and mirrors `mahjong_core.engine._can_win_with`'s own candidate-hand pattern —
  the same one `actions.can_declare_win` uses for the self-draw path — but built directly from
  `SeatView` fields instead of a live `GameState`/claim window, since this is a hypothetical "what
  if this seat discards this tile" check, not resolving a real claim:
  1. `mahjong_core.actions.hand_is_winning_shape(SeatState(concealed=candidate, melds=opp_melds))`
     — structural completeness (standard melds+pair, Seven Pairs, or Thirteen Orphans).
  2. If structurally complete, build a `mahjong_core.scoring.patterns.ScoringContext` (seat wind,
     prevailing wind, `self_drawn=False`, the opponent's real flowers, `ruleset.flowers_score`) and
     call `mahjong_core.scoring.faan.score_winning_hand(candidate, opp_melds, ctx, view.ruleset)`.
  3. Return the real `total_faan` if `result.clears_min_faan`, else `0.0` — a structurally-complete
     hand that doesn't clear the ruleset's `min_faan` is not a deal-in (§4), and never was under
     the probabilistic model either.

  The synthetic candidate tile's *physical id* doesn't matter for correctness — every function in
  this chain reads a tile's type back out (`tile_id_type`), never its specific id — except that
  `decompose()` materializes real `Meld` objects from the candidate, and `Meld.__post_init__`
  rejects two equal physical ids in one meld. `_synthetic_tile_id` picks an id in that type's 4-copy
  block not already present in the opponent's hand, and returns `None` (read as `0.0` risk, not a
  crash) if all 4 real copies are already accounted for in that hand — a 5th physical tile of that
  type cannot exist, so this discard provably can't deal in via it. (This was a real bug caught by
  the arena verification script, not by unit tests alone — see "Verification" below.)

Since `FaanBot`'s `_best_discard` already calls `tile_risk(view, d)` for every candidate discard,
and does not read `view.hands` itself anywhere, no change to `faanbot.py` was needed at all —
`tile_risk` becoming hands-aware is sufficient for the whole tier.

### The fold-timing gap: `opponent_threat_level` needed the same treatment

`tile_risk` being exact under `view.hands` only ever changes *which tile* `_best_discard` picks
once it's already decided to play defensively — it says nothing about *when* to switch into
defence. That decision is a separate gate, `bots/faanbot.py`'s `fold_mode = turn >= late_turn and
base_shanten >= _FOLD_SHANTEN and threatening`, and `threatening` was still computed by
`opponent_threat_level`'s original meld-count/discard-tempo proxy — purely inferential, and blind
to `view.hands` even when it was populated. An `"ORACLE"` seat could sit on exact per-tile deal-in
math while still deciding *whether to use it* off the same guesswork every other tier relies on:
an opponent with no exposed melds and steady discard tempo read as zero threat regardless of
whether their real hand was genuinely tenpai, and a meld-heavy, fast-discarding opponent read as
dangerous regardless of whether their real hand was nowhere close. This is very likely why the
original redesign's win-rate gain (17.5% vs 14.7%, below) was modest relative to its points/
deal-in swing — the fold gate could stay closed against a real tenpai opponent, or open
unnecessarily against a harmless one, independent of how exact `tile_risk` itself was.

`opponent_threat_level` (`bots/safety.py`) now branches on `view.hands` the same way `tile_risk`
does:

- **`view.hands is None`** (every tier except `"ORACLE"`): byte-identical to the original
  `melds * 0.3 + tempo_bump` formula (`tests/test_safety.py::
  test_opponent_threat_level_hands_none_matches_the_original_probabilistic_formula` pins it).
- **`view.hands is not None`**: `_opponent_real_shanten` computes `opponent_seat`'s exact shanten
  (`mahjong_core.shanten.shanten`) from their real hand (`_opponent_hand34` — `view.hands[opp]`
  plus their own melds, the same 34-array shape `bots.features.own_hand34` builds for this seat)
  and maps it onto the proxy's own scale: `max(0.0, (_SHANTEN_THREAT_BASE - real_shanten) *
  _SHANTEN_THREAT_STEP)`, with `_SHANTEN_THREAT_BASE = 3` (deliberately equal to `faanbot.py`'s
  own `_FOLD_SHANTEN`, not imported — `faanbot` already imports this module, so importing back
  would cycle) and `_SHANTEN_THREAT_STEP = 0.3` (deliberately equal to the proxy's per-meld
  weight). Concretely, against `_THREAT_THRESHOLD = 0.3`: real shanten 0 (tenpai) scores 0.9, real
  shanten 1 scores 0.6 — both decisively past the threshold, matching "near-tenpai should clear
  it decisively" — real shanten 3+ clamps to 0.0, clearly safe, and an opponent who already has a
  complete hand (shanten `-1`, e.g. mid-decision before their win is taken) scores 1.2, the top of
  the scale. One shanten step closer to tenpai reads as threatening as one more exposed meld did
  under the old proxy — the two branches stay on a comparable scale by construction rather than
  inventing an unrelated unit.

  Deliberately shanten-only, not faan-weighted, even though a bigger threatened hand is more
  dangerous — the same idea `tile_risk`'s exact faan already captures for defence. This gate only
  decides *whether* `_best_discard` enters pure-defence mode at all; once it does, `tile_risk` —
  already hands-aware — prices each candidate discard's real faan exactly, including returning
  `0.0` for a structurally-complete-but-sub-`min_faan` opponent hand (§4). Folding a beat early
  against a tenpai opponent who turns out to be sub-minimum costs only tie-break quality among
  already-safe discards, not a real deal-in avoided that shouldn't have been; duplicating
  `tile_risk`'s value/`min_faan` logic here would re-run that check one level up for no
  behavioural gain.

`tests/test_safety.py` proves the fix catches what the proxy misses, not just that it runs: an
opponent with no melds and too short a discard pool to raise the tempo signal reads as zero threat
under the proxy but is genuinely tenpai under the omniscient view, and hands-aware
`opponent_threat_level` flags them while the proxy — evaluated on the identical position — does
not (`test_opponent_threat_level_hands_aware_flags_a_near_tenpai_opponent_the_proxy_misses`); an
opponent with two exposed melds and a settled discard tempo reads as clearly threatening under the
proxy but is genuinely far from tenpai (shanten 4) under the omniscient view, and hands-aware
`opponent_threat_level` correctly reads them as safe (`0.0`) while the proxy does not
(`test_opponent_threat_level_hands_aware_clears_an_opponent_that_looks_threatening_by_proxy`).
`tests/test_oracle.py::
test_omniscient_view_folds_against_a_tenpai_opponent_the_proxy_reads_as_safe` proves the fix
reaches a real `FaanBot.act` decision, not just the helper in isolation: an opponent with zero
melds and an empty discard pool is genuinely tenpai, tanki-waiting on exactly the tile
`_best_discard`'s ordinary value-weighted scoring would pick anyway. Under the ordinary
(probabilistic) view the fold gate never opens (proxy threat stays below `_THREAT_THRESHOLD`) and
`FaanBot` walks straight into the deal-in; under the omniscient view, real shanten correctly opens
the gate and — combined with `tile_risk`'s own exact per-tile danger — `FaanBot` avoids that tile
specifically. Both fixes have to fire together for that outcome: fold mode alone (a threat flag
with no exact per-tile danger) wouldn't single out the one dangerous tile, and exact `tile_risk`
alone with fold mode never engaging wouldn't change `_best_discard`'s scoring formula at all.

### Why full information genuinely eliminates the noise, not just reduces it

Under the probabilistic model, genbutsu is deliberately never a hard "safe" signal (§5 item 1) —
HK has no furiten, so an opponent can discard a tile and legally win on it later once their hand
reshapes. That's exactly the gap exact information closes: with `view.hands` populated, "would
opponent's *current* real hand complete on this tile" has a definite yes/no answer, no matter what
they discarded earlier. `tests/test_oracle.py::
test_omniscient_view_avoids_a_real_deal_in_the_probabilistic_view_walks_into` is a scripted
instance of exactly this: an opponent who discarded 北 early (creating weak genbutsu "safety"
evidence) but whose real hand has since reshaped into a live Seven Pairs wait on 北 — the
probabilistic-only view has `FaanBot` discard straight into it, the omniscient view avoids it.

### Why a full-information bot is safe to wire into a live table

A prior pass at this idea assumed it had to stay an offline-only arena-analysis tool, never
reachable from a live table, on the theory that handing a bot every seat's tiles was
irreconcilable with the redaction boundary ([00-architecture.md §5](00-architecture.md)). That
turned out to be more conservative than necessary once re-examined against the actual code:

- `SeatView` (`app/views.py`) already has a `hands: tuple[tuple[TileId, ...], ...] | None`
  field — used today for the spectator-only `BOTS` showcase table
  (`spectators_see_hands`/`reveal_hands`, [00-architecture.md §5](00-architecture.md)).
- **`SeatView` never carries `game_seed`/`hand_seed`** — check its field list
  ([00-architecture.md §5](00-architecture.md)) — so a `SeatView` with `.hands` populated
  crossing the `ProcessPoolExecutor` boundary does **not** violate
  [00-architecture.md §3](00-architecture.md)'s "`game_seed` never leaves this process"
  invariant. That invariant is about the seed specifically (it determines every *future* hand's
  wall), not about whether a bot ever sees the *current* hand's tiles.
- `seat_view()`'s `_check_reveal` guard still raises if `seat is not None` when
  `reveal_hands=True` — spectator-only, unchanged, still the real security boundary for every
  real WS-facing client. `app/views.py` instead adds a **new, separate, dangerously-named**
  function, `_omniscient_seat_view(state, seat) -> SeatView`, that builds an omniscient view for
  a real acting seat — the one thing `_check_reveal` forbids — used by exactly one caller:
  `app/table.py`'s `_submit_bot_job`, in its oracle-tier branch. This is verified structurally,
  not just asserted: `tests/test_oracle_containment.py` AST-scans every production source file
  under `server/` and fails if `_omniscient_seat_view` is ever called from anywhere but
  `Table._submit_bot_job`. `tests/test_redaction.py` separately pins that `Table.state_sync_wire`
  — what a real WS client actually receives — never populates `.hands` for a real seat, for
  every `bot_tier` including `ORACLE`.
- `_submit_bot_job` already builds the `view` that crosses the process-pool boundary; the fix is
  entirely in `app/table.py`: when the *effective* tier for a seat's decision is `ORACLE`, build
  the view via `_omniscient_seat_view` instead of the normal `seat_view(state, seat)`. No change
  to `compute_action`'s signature, no new `Bot` protocol member, and — critically — no
  `GameState` ever crosses the process boundary; the `"ORACLE"`-tier `FaanBot` still only ever
  sees a `SeatView`.

### Disconnect-handover carve-out

**The one explicit product requirement here:** disconnect-handover (a real human's seat gone
`autoplay`) always runs `T2`/`FaanBot`, never the table's configured `bot_tier` — regardless of
what tier the table itself uses. `Table._effective_bot_tier(seat)` (`app/table.py`) is the one
place this is decided: a `seat_bindings[seat].status == "autoplay"` seat is pinned to
`_DISCONNECT_HANDOVER_BOT_TIER` (`"T2"`) unconditionally; only a `bot`-status seat (practice
mode / `all_bots`, bound at construction, never a real human) uses `self._bot_tier` as
configured. This carve-out matters exactly as much post-redesign as before it: `"ORACLE"` and
`"T2"` are both `FaanBot` underneath now, but a human's seat must still never be driven by the
*omniscient view* — the bot class is no longer the risk, the view is.
`tests/test_table.py::test_disconnect_handover_always_uses_t2_even_when_table_bot_tier_is_oracle`
pins this directly: an `autoplay`-status seat on an `ORACLE`-tier table still gets an ordinary
(`.hands is None`) view.

### Pool routing

No dedicated pool. The original rollout-based `OracleBot` got its own `_shared_oracle_bot_pool`
(`ProcessPoolExecutor(max_workers=2)`) on the assumption its per-decision cost was at least as
expensive as `SearchBot`'s 300-800ms budget — true for a rollout search, false for a plain
`FaanBot` decision, which costs the same single-digit milliseconds as `T2` always has (root-state
construction changed from "sample every opponent's hand" to "read `view.hands` directly," and
there's no rollout loop left to dominate the cost). `_shared_oracle_bot_pool` is deleted;
`"ORACLE"` jobs route to the same pool every tier now shares (`app/table.py`'s
`_submit_bot_job`) — `T3`'s own isolated pool existed for the same reason `SearchBot`'s
per-decision cost justified not head-of-line-blocking other tables, and was removed along with
`SearchBot` itself (§6).

### Verification

`docker compose run --rm --no-deps api uv run python -m tools.oracle_arena_check --games 15
--seed 1` — a scratch script (not shipped; reused `bots/arena.py`'s duplicate-seeding/paired-
difference machinery, rotating which seat gets the omniscient view across the same 4 seeds
`bots/arena.py`'s own duplicate sets use) comparing the `"ORACLE"` tier against plain `FaanBot`,
15 duplicate sets (60 games):

| Metric | ORACLE (A) | FaanBot (B) |
| --- | --- | --- |
| win_rate | 0.1750 | 0.1472 |
| deal_in_rate | 0.0083 | 0.1542 |
| avg_winning_faan | 4.1667 | 4.0566 |
| tenpai_at_draw_rate | 0.6848 | 0.5616 |
| tenpai_rate_on_sub_minimum_hand | 0.1429 | 0.1613 |
| avg_points_per_hand | 2.1833 | -0.7278 |

Paired difference (A − B): **+11.644 points/game, 95% CI [6.220, 17.069]** — excludes zero,
decisively in the redesigned tier's favor, at a fraction of the sample size the old rollout-based
`OracleBot`'s own (inconclusive) comparison used. `deal_in_rate` falling by roughly 18x (0.1542 →
0.0083) is the headline number and exactly what the redesign targets: the residual 0.0083 is real
opponents winning on a tile before this seat's *own* hand had a chance to reach a decision point
favoring some other discard, not a gap in the exact-danger check itself. This result is the
expected one by construction (same `FaanBot` formula, exact-or-better safety information going
into the identical `w_safety * risk` term) — a worse result would have meant something was broken,
and the arena run is in fact how `_synthetic_tile_id`'s physical-id-collision bug (a hand already
holding all 4 copies of the candidate type) was actually caught: a scripted unit test wouldn't
have hit a hand shaped exactly that way by chance, but a real 60-game run did on its first attempt.

### Re-verification after the fold-timing fix (`opponent_threat_level` hands-aware)

Same scratch script, same invocation, same seed, re-run after making `opponent_threat_level`
hands-aware (above) — 15 duplicate sets (60 games):

| Metric | ORACLE (A) | FaanBot (B) |
| --- | --- | --- |
| win_rate | 0.1750 | 0.1472 |
| deal_in_rate | 0.0083 | 0.1542 |
| avg_winning_faan | 4.1667 | 4.0660 |
| tenpai_at_draw_rate | 0.6522 | 0.5580 |
| tenpai_rate_on_sub_minimum_hand | 0.1500 | 0.1558 |
| avg_points_per_hand | 2.1833 | -0.7278 |

Paired difference (A − B): **+11.644 points/game, 95% CI [6.220, 17.069]** — `win_rate`,
`deal_in_rate`, `avg_points_per_hand`, and the paired-difference CI are *bit-for-bit identical* to
the pre-fix numbers above; only `avg_winning_faan`/`tenpai_at_draw_rate`/
`tenpai_rate_on_sub_minimum_hand` moved slightly, proving some hands really did play out
differently, just not in a way that flipped a win/loss/deal-in outcome at this sample size. Taken
at face value this looks like the fix did nothing — it doesn't, and re-running the identical
15-set check is exactly how that gets caught rather than papered over with the points number
alone (the CI still excludes zero, but it's the *same* CI as before, which is the tell).

**Investigation: the fix is real but rare per-decision, and 60 games is too few to see it.**
Instrumenting `FaanBot._best_discard` directly (comparing, at every own-turn decision the
`"ORACLE"` seat faced across 20 self-play games — seeds 1–5, all 4 rotations — what it would have
discarded under the pre-fix proxy-only `opponent_threat_level` against what it actually discards
now, both computed against the identical `SeatView` so this isolates only this session's change):
`fold_mode`'s `threatening` flag flipped on 39 of 1399 own-turn decisions (2.8%), and the flip
actually changed the chosen discard on 22 of those 1399 (1.6%) — the rest picked the same tile
either way because the old and new modes' tie-breaks happened to agree on that position. A ~1.6%
per-decision change rate, spread across many decisions per hand and many hands per game, is a real
but thin signal — nowhere near guaranteed to flip a whole hand's winner within any given 60-game
sample, which is exactly what the identical 15-set numbers above show happening (or rather, not
happening) here.

Re-running the same script at **200 duplicate sets (800 games)**, same seed, confirms the effect
is real once the sample is large enough to resolve it:

| Metric | ORACLE (A) | FaanBot (B) |
| --- | --- | --- |
| win_rate | 0.2047 | 0.1671 |
| deal_in_rate | 0.0106 | 0.1523 |
| avg_winning_faan | 4.1786 | 4.2020 |
| tenpai_at_draw_rate | 0.5632 | 0.5618 |
| tenpai_rate_on_sub_minimum_hand | 0.1434 | 0.1551 |
| avg_points_per_hand | 2.2687 | -0.7562 |

Paired difference (A − B): **+12.100 points/game, 95% CI [10.247, 13.953]** — `win_rate` moved
from 0.1750 to **0.2047**, meaningfully above both the pre-fix 15-set number and the 17.5%
figure the fold-timing gap was named as the likely cause of (above); the paired-difference point
estimate holds at roughly the same level as the 15-set run (+12.100 vs +11.644) with a much
tighter CI, as expected from ~13x the sample. **Conclusion: the win-rate gap does close, but only
visibly at a larger sample size than the 15-set/60-game convention this tier's checks have used
so far** — the fix's real per-decision effect (~1.6% of own-turn decisions) is too thin to reliably
move a binary per-hand outcome (won or didn't) within 60 games, the same statistical-power point
§8 makes about raw win totals generally. This is a sample-size limitation
of the existing 15-set convention for *this specific, low-frequency* mechanism, not evidence the
fix is inert — the 200-set run, the direct decision-level instrumentation above, and the scripted
`tests/test_oracle.py` proof all agree it does something real; a future change to this tier's
verification convention (a larger default sample, or a decision-level divergence count alongside
the game-level metrics) would catch this earlier than "the 15-set numbers didn't move."

### The offense-side gap: `seen34` needed the same treatment

`tile_risk` and `opponent_threat_level` are both defense-side: they change how dangerous a
candidate discard looks, and when to start caring. Neither touches the other half of
`_best_discard`'s formula — the speed term, `w_speed * _speed_term(result_shanten, tiles)`, where
`tiles` comes from `mahjong_core.shanten.ukeire`'s live-tile count, `4 - seen34[t]`. `bots/features.
seen34(view)` builds that count from everything *this seat* can see: its own hand, every seat's
*non-concealed* melds, and every discard pool — deliberately never `view.hands`, since a normal
bot has no such field to read. Under the omniscient view, `view.hands` is populated but `seen34`
never looked at it: any tile actually sitting in an opponent's real concealed hand still read as
"maybe still in the wall," so `ukeire` overstated how many draws would advance the hand. Full
information was already sitting in the view; `seen34` just wasn't using it.

`seen34` now branches on `view.hands` the same way both other fixes do:

- **`view.hands is None`** (every tier except `"ORACLE"`): byte-identical to the original —
  own hand, every seat's non-concealed melds, every discard pool; a concealed kong is still
  skipped, since a real bot genuinely can't see it
  (`tests/test_features.py::test_seen34_hands_none_matches_the_original_probabilistic_behavior`).
- **`view.hands is not None`**: every opponent's real concealed tiles (`view.hands[opponent]` for
  `opponent != view.seat`) count as seen too — they're genuinely known, not merely inferred, so a
  tile sitting there is exactly as dead to the wall as one sitting in this seat's own hand.

**The concealed-kong subtlety.** The probabilistic branch's `if meld.concealed: continue` exists
because a real bot can't see a concealed kong's tile type at all. Under `view.hands`, naively
keeping that same skip would look harmless — surely the kong's 4 tiles show up in `view.hands`
anyway? They don't: `mahjong_core.engine._apply_self_kong` removes all 4 of a concealed kong's
tiles from `SeatState.concealed` the instant it's declared, and `_omniscient_seat_view` builds
`.hands` directly from `state.seats[s].concealed` — so those 4 tiles are absent from *both* the
melds loop (if still skipped) *and* `view.hands[opponent]` (already excluded by the engine). Left
unfixed, this would have made an opponent's concealed kong tiles silently vanish from the count
entirely under the very view that's supposed to know everything — the opposite of the intended
direction, and a real correctness bug, not a missed optimization. The fix: once `view.hands` is
populated, a concealed meld is no longer skipped — it's added the same way every other meld is
(`_add_meld`, which already contributes 3 for any kong, matching this module's existing
convention). `tests/test_features.py::test_seen34_hands_aware_counts_an_opponents_concealed_kong`
pins this directly, mirroring `tests/test_safety.py`'s own concealed-kong regression test for
`tile_risk`.

### Tests

`tests/test_features.py` (new file): the `view.hands is None` regression pin above; a scripted
position where an opponent holds 3 of 4 real copies of a tile type invisible to the probabilistic
branch, showing `seen34` undercounts it (`seen[t] == 0`) while the hands-aware branch counts it
correctly (`seen[t] == 3`) and `ukeire`'s live-tile count for a discard genuinely waiting on that
tile drops from 4 to 1 accordingly; and the concealed-kong regression above.
`tests/test_oracle.py::test_omniscient_view_prefers_a_discard_with_more_real_live_tiles` proves
the fix reaches a real `FaanBot.act` decision: a scripted 2-shanten hand, empirically found by
direct search (not hand-derived), where the probabilistic view's widest-ukeire candidate discard
(9筒, 16 kinds/58 tiles — inflated because an opponent's 3 real hidden copies of 1東 read as still
live) loses its edge once `seen34` correctly counts those 3 copies as dead (ukeire drops to 14
kinds/51 tiles), flipping `FaanBot`'s actual choice to a different discard (北). `tile_risk` is
checked directly in that test and shown to read identically for both candidates in both views —
proving the flip is `seen34`'s doing, not incidental interaction with the already-hands-aware
danger check.

### Re-verification after the `seen34` fix

Same scratch script and duplicate-seeding/paired-difference methodology as both fixes above
(reusing `bots/arena.py`'s machinery directly), 200 duplicate sets (800 games), same seed, run
both before and after this fix to isolate its effect from the two already-shipped ones:

| Metric | ORACLE (A), pre-fix | FaanBot (B), pre-fix | ORACLE (A), post-fix | FaanBot (B), post-fix |
| --- | --- | --- | --- | --- |
| win_rate | 0.2047 | 0.1671 | **0.3181** | 0.1517 |
| deal_in_rate | 0.0106 | 0.1523 | 0.0209 | 0.1628 |
| avg_winning_faan | 4.1786 | 4.2020 | 4.3035 | 4.1559 |
| tenpai_at_draw_rate | 0.5632 | 0.5618 | 0.6970 | 0.5367 |
| tenpai_rate_on_sub_minimum_hand | 0.1434 | 0.1551 | 0.2273 | 0.1463 |
| avg_points_per_hand | 2.2687 | -0.7562 | 5.1925 | -1.7308 |

Paired difference (A − B): pre-fix **+12.100 points/game, 95% CI [10.247, 13.953]** (the
fold-timing baseline above) → post-fix **+27.693 points/game, 95% CI [25.098, 30.288]** — more
than double the point estimate, both CIs decisively excluding zero, and the pre-fix row here is
bit-for-bit identical to the fold-timing section's own 200-set numbers (same script, same seed,
confirming nothing else drifted between runs). `win_rate` moves from 0.2047 to **0.3181** — a
much larger jump than either previous fix produced at this sample size, consistent with `seen34`
touching every turn's speed term rather than gating a comparatively rare decision (fold-timing's
own effect was only visible in 1.6% of decisions, above). `tenpai_at_draw_rate` (0.5632 → 0.6970)
and `tenpai_rate_on_sub_minimum_hand` (0.1434 → 0.2273) both rise too — ORACLE reaches tenpai
distinctly more often, exactly what a corrected (lower) live-tile undercount predicts, since
`FaanBot` was previously discounting some genuinely-live-but-miscounted draws. `deal_in_rate`
ticks up slightly (0.0106 → 0.0209) — still roughly 8x below `FaanBot`'s own 0.1628, and a
reasonable trade: an ORACLE seat now pushes hands further and discards more often before a hand
ends, giving the (already much smaller) residual real-deal-in mechanism marginally more
opportunities to fire, while the net points/win-rate swing is decisively positive. The win-rate
effect this time needed no larger-sample investigation the way the fold-timing fix did — it's
visible directly at the same 200-set size this tier's checks were already using.

### The kong-rob gap: `_act_on_turn`'s self-kong loop needed the same treatment

`tile_risk`/`opponent_threat_level`/`seen34` all make `_best_discard` hands-aware. They don't
touch a separate decision point in the same file: `FaanBot._act_on_turn`'s kong loop, which
declares whichever legal concealed/added kong strictly reduces shanten furthest, with **no safety
check of any kind** — not even the probabilistic one every ordinary discard gets via `tile_risk`.
This matters because robbing a kong (搶槓) is real and expensive in this ruleset:
`mahjong_core.engine._apply_self_kong` calls `_kong_rob_offers`, which checks every other seat's
*real* hand for a win on the tile the kong exposes; if it fires, `mahjong_core.scoring.payout`'s
discard-payment rule makes the kong-declarer pay the whole winning payout alone, plus a +1 faan
搶槓 bonus (`scoring/patterns.py`'s `_detect_robbing_the_kong`). Structurally this is the same
shape of loss `tile_risk` already exists to avoid for a discard — it just was never consulted for
a kong decision at all. Declining is always legal: `mahjong_core.actions._turn_actions` offers
plain `Discard` actions alongside every kong option in the same legal-action set.

**Which tile a kong exposes.** `mahjong_core.ml.action_id` keys both `DeclareConcealedKong` and
`DeclareAddedKong` off `meld.tile_type` — the same `t` the kong loop already iterates over — and
`_apply_self_kong` derives the exposed tile from that same type for both kinds: an *added* kong's
`new_tile` is the concealed 4th copy just folded into the existing pung; a *concealed* kong's is
any of its 4 identical tiles (`meld.tiles[-1]`, arbitrary — all one type). So "the tile this
candidate kong would expose" is simply `t`, unchanged, for both loop branches.

**Which kong kinds can actually be robbed.** `_kong_rob_offers` gates this per `RuleSet`, and the
fix mirrors that gating exactly rather than over-flagging a kong the engine itself would never
open a claim window for:

- `ruleset.kong_rob_enabled` (default `True`) gates both kinds.
- An *added* kong is open to **any** opponent win on the exposed tile once that's on.
- A *concealed* kong only matters at all when `ruleset.concealed_kong_robbable` is also on — it
  **defaults to `False`** (`mahjong_core/config.py`) — and even then only for an opponent whose
  candidate hand specifically completes Thirteen Orphans (十三么), real HK convention, not "any
  winning hand." Under the default ruleset, concealed-kong-robbing is unreachable, full stop —
  test coverage for that path stays a direct unit check of the gating logic (below), not an
  elaborate `FaanBot.act`-level scenario for a path no default table can ever reach.

**The fix.** `bots/safety.py` gets one new function, `kong_rob_risk(view, tile_type, *,
concealed)`, `"ORACLE"`-only (asserts `view.hands is not None` — callers must not invoke it at all
otherwise). It reuses `_exact_deal_in_faan` per opponent — the identical exact win check
`tile_risk` already uses for a discard of the same tile type — after applying the two gates above
(`kong_rob_enabled`, and for a concealed kong, `concealed_kong_robbable` plus a
`mahjong_core.actions._is_thirteen_orphans` check on the candidate hand). `FaanBot._act_on_turn`'s
kong loop calls it once per legal candidate, before the shanten comparison:

```python
if view.hands is not None and kong_rob_risk(view, t, concealed=concealed) > 0.0:
    continue
```

`view.hands is None` (every tier but `"ORACLE"`) short-circuits before `kong_rob_risk` is ever
called — zero behavior change for `T0`–`T2`, pinned by
`tests/test_faanbot.py::test_never_declares_a_self_kong_when_hands_is_none`.

**Policy: hard-avoid, not risk-weighted.** `_best_discard` already has a real value/risk tradeoff
formula (§4) because a discard is chosen every turn regardless of danger — folding isn't optional.
A kong is different: it's one candidate among several, discarding is always available as a safe
fallback, and `_should_claim` already sets precedent elsewhere in this file for "never do X if it
provably backfires" over a weighted comparison (it refuses a claim that drops the hand below
`min_faan`, no exception). Reusing that shape here — hard-skip a kong this seat can *prove* deals
in, fall through to the next-best kong or an ordinary discard — needs no new scoring formula for a
decision point this rare, and never turns down a kong on a probabilistic guess (there is no
probabilistic branch for `kong_rob_risk` at all; every non-`"ORACLE"` tier is exactly as exposed to
this risk today as before this change, unchanged, since only an omniscient view can know for sure).

**Known, accepted gap.** `_exact_deal_in_faan` hardcodes `is_robbing_kong=False` when it builds the
opponent's `ScoringContext` (it exists for the discard case, where that's correct). Reused as-is
here, a hand exactly one faan under `min_faan` that would only clear it with 搶槓's own +1 bonus
faan reads as safe. Narrow and rare; fixing it means either modifying `_exact_deal_in_faan` (out of
scope — already validated, reuse-don't-modify per this fix's own ground rules) or duplicating its
scoring call with the bonus threaded through, which isn't worth it for one faan-level edge case at
an already-rare decision point.

### Tests

`tests/test_safety.py`: six `kong_rob_risk` unit tests mirroring `tile_risk`'s own conventions —
an added kong flags a real exact deal-in (reuses the identical Seven-Pairs fixture
`test_tile_risk_hands_aware_flags_an_exact_deal_in` already uses) and clears a safe tile;
`kong_rob_enabled=False` zeroes a would-be flag; the concealed-kong path is unreachable at
`concealed_kong_robbable`'s real default even against a genuine Thirteen-Orphans wait, flags one
once that ruleset flag is explicitly on, and still ignores a non-Thirteen-Orphans completion on the
identical tile/hand even then (the engine's own restriction, mirrored exactly).
`tests/test_faanbot.py::test_never_declares_a_self_kong_when_hands_is_none` is the regression pin
above. `tests/test_oracle.py::test_omniscient_view_avoids_a_kong_that_would_be_robbed` is the
bot-level proof, with one honestly-documented wrinkle: it stubs `shanten` for the exact post-kong
candidate array only (every other call falls through to the real function) to force the kong
loop's own `s < best_kong_shanten` comparison to succeed at all — see "Why this fix is measured as
a no-op today," directly below, for why that precondition doesn't occur naturally.

### Why this fix is measured as a no-op today

Unlike the three fixes above, this one does not move any arena number, and the reason is provable,
not a sampling artifact. `mahjong_core.shanten.shanten` is monotonic in any single tile type's
count — increasing `tiles34[t]` can never *raise* shanten, only lower or hold it, for both the
standard-shape and (where applicable) Seven-Pairs/Thirteen-Orphans formulas. Declaring a self-kong
is exactly "remove one redundant copy from an already-complete group" (`_act_on_turn`'s
`candidate[t] -= 1`, mirroring `bots/features._add_meld`'s "kong contributes 3" convention) — the
reverse direction, which the same monotonicity makes non-improving. Exhaustive random search (both
kong kinds, 500,000 random hands each, `server/tools/kong_rob_check.py`, deleted after use)
confirmed zero counterexamples: `_act_on_turn`'s kong loop can never actually satisfy its own
`s < best_kong_shanten` test today, so `best_kong_aid` stays `None` — this bot has never
voluntarily declared a self-kong, on any tier, regardless of this fix.

Direct decision-level instrumentation against real self-play (50 games, plain `FaanBot` × 4,
ordinary views, same scratch script) confirms this empirically rather than just algebraically:
12,709 own-turn decisions, 97 of them with a legal self-kong actually offered in the mask (25 of
the 50 games saw at least one) — **zero** kongs declared. The full 200-duplicate-set (800-game)
`"ORACLE"` vs `FaanBot` arena run, same script/methodology/seed as the three fixes above, is the
clearest evidence of all: every metric comes back **bit-for-bit identical** to the pre-fix,
post-`seen34` baseline —

| Metric | ORACLE (A) | FaanBot (B) |
| --- | --- | --- |
| win_rate | 0.3181 | 0.1517 |
| deal_in_rate | 0.0209 | 0.1628 |
| avg_winning_faan | 4.3035 | 4.1559 |
| tenpai_at_draw_rate | 0.6970 | 0.5367 |
| tenpai_rate_on_sub_minimum_hand | 0.2273 | 0.1463 |
| avg_points_per_hand | 5.1925 | -1.7308 |

Paired difference (A − B): **+27.693 points/game, 95% CI [25.098, 30.288]** — identical to the
`seen34` section's own 200-set numbers to four decimal places, not merely "close." Given the
mathematical proof above, this is the expected result, not a disappointing one: there is no game
state this fix can possibly steer away from, because the branch it guards is never entered.

This fix is still worth keeping: it's correct, minimal, fully tested, and a strict no-op for every
tier but `"ORACLE"` by construction. It's insurance against a future change to the kong-shanten
heuristic ever making `best_kong_aid` reachable (at which point this gate would already be
protecting it, untested-in-production but not untested), and it closes the one remaining
kong-declaration decision point `docs/04-bots.md §5`'s safety model didn't cover. But reporting
this as a measured win would overstate a change that, today, guards a branch the bot never takes —
the honest finding is that the arena/instrumentation numbers do not move, and the reason is a
separate, pre-existing, out-of-scope property of `mahjong_core.shanten` rather than anything about
this fix's own correctness.
