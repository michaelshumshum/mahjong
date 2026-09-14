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

`mask` is `legal_mask(view) -> list[bool]`, the engine-produced legal-action mask. `mahjong_core`
is stdlib-only (see README / roadmap "zero deps" rule) — **no numpy**, plain `list[bool]`. Heuristic
bots decode the chosen id via `decode_action(view, aid)`; near-zero cost, and a learned policy
drops into the same slot later with no refactor. See [06-ml.md](06-ml.md).

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

## 2. Tiers

| Tier | What it is | Effort | Use |
| --- | --- | --- | --- |
| **T0** `RandomBot` | uniform over legal actions | 20 lines | fuzzing, engine tests, never shipped |
| **T1** `EfficiencyBot` | shanten-minimising discard, ukeire tiebreak | ~400 lines | "Easy". Ship in M4. |
| **T2** `FaanBot` | T1 + hand-value planning + discard safety | ~900 lines | "Normal"/"Hard". Moved into M4 (see §4) — the real product. |
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
precomputed per-suit lookup table (~500k entries, O(1) lookup replacing the recursive scan)
accordingly, and build the table alongside T1 in M1, not after load-testing surfaces the problem.
"Bots run outside the room's task" bounds the room's `asyncio` loop, not total CPU — it does not
by itself make this cheap.

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
