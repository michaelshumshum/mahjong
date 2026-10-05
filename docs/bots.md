# Computer players

## 1. Interface

A bot receives exactly the output of `seat_view(state, seat)` — the same redacted `SeatView` a
human gets ([architecture.md §5](architecture.md)) — and returns an action id. It has no access to
`GameState`, the wall, or other hands. The one exception is the `ORACLE` tier (§9), contained to
one live call site plus the offline arena.

```python
class Bot(Protocol):
    async def act(self, view: SeatView, mask: list[bool], deadline: float) -> int:
        """-> an action id from the fixed 109-action space (ml.md §1)."""
```

`mask` is `legal_mask(state, seat) -> list[bool]` ([ml.md §1](ml.md)), computed from the real
`GameState` by whoever drives the bot (self-play harness, arena, or Table) — `mahjong_core` must
never depend on `app.views`, and is stdlib-only (plain `list[bool]`, no numpy). A bot never calls
`decode_action` either, since that needs `GameState`; decoding is always the caller's job. A
learned policy drops into the same slot ([ml.md](ml.md), `server/bots/base.py`).

**Scheduling.** Bot decisions never run inside the table's `asyncio` task — a shanten/ukeire scan is
tens of milliseconds of pure-Python CPU (§3), which would stall every other table.

1. The table submits `(bot_id, view, mask, deadline, window_id, state_version)` to a
   `ProcessPoolExecutor` (the GIL makes a thread pool useless for CPU-bound work).
2. The worker (`bots/worker.py`'s `compute_action`) builds the requested tier
   (`bots.worker.BOT_TIERS`), drives its `act(view, mask, deadline)` via `asyncio.run`, and returns
   `(window_id, state_version, action_id)` to the table's inbox.
3. The table compares the tag against its current `window_id`/`state_version`; a stale result is
   **dropped silently**, exactly like a stale human claim.
4. `app/table.py`'s `_handle_bot_result` decodes the id against the real `GameState`.
5. If no matching result lands, the per-seat turn/claim timers apply the same safe default a human
   gets (tsumogiri / pass) ([architecture.md §8](architecture.md)). A bot never wedges a table.

All tiers share one pool (`app/table.py`'s `_shared_bot_pool()`).

**Humanising think delay: 400–1400ms, uniform per decision.** `app/table.py`'s `_await_bot_job`
sleeps after the worker replies, before re-entering the result — applied by the table, so it never
touches `_BOT_JOB_TIMEOUT_SECONDS`/`turn_seconds`/`claim_seconds` deadline math. Without it, turns
resolve faster than a human can follow. Seeded off the per-decision seed `_submit_bot_job` derives
(reproducible), and slept in that job's own task so it delays only that seat. The delay does not
vary with decision difficulty — no tier returns a confidence signal to scale it by.

## 2. Tiers

| Tier | Class | What it is | Offered as |
| --- | --- | --- | --- |
| `T0` | `RandomBot` | uniform over legal actions | never — fuzzing and engine tests only |
| `T1` | `EfficiencyBot` | shanten-minimising discard, ukeire tiebreak (§3) | Easy |
| `T2` | `FaanBot` | T1 + hand-value planning (§4) + discard safety (§5) | Normal; also the default tier and the disconnect-handover tier |
| `ORACLE` | `FaanBot` | a plain `FaanBot()` fed a full-information view (§9) | Impossible |
| T4 | learned policy | self-play RL, independent of `FaanBot` | in development ([ml.md](ml.md)) |

`FaanBot` also ships weight-profile variants (`bots/faanbot.py`'s `WeightProfile`: `AGGRESSIVE`,
`DEFENSIVE`, `FLUSH_CHASING`), registered in `bots/arena.py`'s `BOT_REGISTRY` as
`FaanBotAggressive`/`FaanBotDefensive`/`FaanBotFlushChasing` for training variety. They are not
selectable at a live table ([ADR 0015](decisions/0015-bot-personas.md)).

There is no search tier: a determinized-rollout `SearchBot` was built and removed for scoring
decisively worse than `FaanBot` ([ADR 0012](decisions/0012-searchbot-removed.md)).

## 3. Shanten and ukeire

**Shanten** = tiles away from tenpai (`0` = tenpai, `-1` = won), computed over the 34-count array
as the minimum of three parses (`mahjong_core/shanten.py`):

1. **Standard** — 4 melds + 1 pair. Recursive per-suit decomposition into melds, then partial sets
   (pairs, ryanmen/kanchan/penchan). `shanten = (4 - melds)*2 - partials - has_pair`, **with the
   block-count cap `melds + partials <= 5` (`<= 4` if no pair is banked) applied before scoring.**
   Skipping the cap is the classic shanten bug: six partial sets with no pair would all count,
   understating shanten. Clamped at 0.
2. **Seven Pairs** (七對子) — `6 - pairs + max(0, 7 - distinct)`. The `max(0, 7 - distinct)` term
   is required: 6 pairs of one tile plus a spare is not one tile from Seven Pairs. Only run when
   `HandSet.NEW_18` is in `hand_sets` (§8).
3. **Thirteen Orphans** (十三么) — `13 - distinct_terminals_honors - (1 if has_pair else 0)`.

Validated against [MahjongRepository/mahjong](https://github.com/MahjongRepository/mahjong)'s
`Shanten` class (same 34-index layout, checked against 26M Tenhou hands) as a test oracle.
[arXiv:2108.06832](https://arxiv.org/pdf/2108.06832) describes a faster deficiency-number
algorithm.

**Cost.** One ukeire scan is ~34 shanten evaluations per candidate × ~14 candidates ≈ **470 shanten
evaluations per decision**, 20–50ms in pure Python uncached. The per-suit table
(`mahjong_core/shanten.py`'s `_frontier`) is `functools.cache`-memoised on a suit's count vector,
populated lazily: the full table (5⁹ ≈ 1.95M man/pin/sou states + 5⁷ ≈ 78k honor states) takes
~104s to build eagerly — too slow for every worker's import — while a real game visits a few
thousand distinct suit shapes and a scan's evaluations share most sub-shapes, so the cache is warm
within a hand or two. `tests/test_shanten.py`'s perf/import-time tests pin this. A 200-table load
test has not been run ([ADR 0003](decisions/0003-product-scope.md)).

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

`seen34` (`bots/features.py`) counts your hand, every non-concealed meld, every discard, and every
revealed flower. **Never** the wall.

**T1's rule:** minimise shanten; tiebreak on `tiles_accepted`, then `kinds_accepted`, then prefer
discarding terminals/honors. Call chow/pung only if it strictly reduces shanten.

## 4. Hand value under `min_faan`

With `min_faan = 3`, a pure efficiency bot reaches tenpai constantly and then cannot declare a
win: a fast all-sequences hand scores 1 faan (平糊). Riichi bots don't have this problem (riichi is
itself a declarable yaku), so riichi-derived tutorials and libraries are wrong for HK on exactly
this point. **A T1-only table produces endless exhaustive draws** — the failure is in what T1
optimises for, not how well. Value targeting is a correctness requirement for a playable bot.

T2 plans toward a **value target**. The realistic 3-faan routes (`bots/valuation.py`'s
`ROUTE_FAAN`):

| Route | Faan | When to commit |
| --- | --- | --- |
| Half Flush 混一色 | 3 | ≥7 tiles in one suit + honors by turn 6 |
| All Pungs 對對糊 | 3 | ≥2 pairs/triplets early, few sequence shapes |
| Half Flush + dragon/wind pung | 4–5 | strongest common line |
| Full Flush 清一色 | 7 | ≥9 tiles in one suit by turn 5 |
| Small Three Dragons 小三元 | 5 | two dragon pairs |
| Seven Pairs 七對子 | 4 | ≥4 pairs by turn 5, honors-heavy |
| Self-draw + concealed | +2 | keeps a cheap hand viable if you stay closed |

```
score(discard) = w_speed  * ukeire_after
               + w_value  * E[faan | best reachable pattern]
               + w_safety * (-deal_in_risk)
               + w_flex   * pattern_optionality
```

| Module | Role |
| --- | --- |
| `bots/valuation.py` | `E[faan \| best reachable pattern]` — a structural proxy validated against the real scorer (which only scores *complete* hands); the module docstring records measured drift |
| `bots/faanbot.py` | the weighted score, fold logic, and value-aware claim guard |

- **Weight schedule** (`_weights_for_turn`): speed early → value mid → safety late. Breakpoints are
  turns 6 and 12 at the default ruleset, scaled by `_turn_breakpoints(ruleset)` for shorter walls
  (§8).
- **Fold logic:** `fold_mode = turn >= late_turn and shanten >= _FOLD_SHANTEN (3) and
  threatening` — a far-from-tenpai hand against a threatening opponent discards safe tiles
  instead of chasing.
- **Claim guard** (`_should_claim`): never claim a meld that drops the hand's reachable value below
  `view.ruleset.min_faan`. `ORACLE` can still claim past it into an exactly-valued tenpai (§9).

`tenpai_rate_on_sub_minimum_hand` is the canary metric for this section (§7). A regression means a
candidate has drifted back toward pure-efficiency play.

## 5. Safety (defence)

**Heuristic only — statistical evidence, not proof.** HK has no furiten: a player may win on a tile
they themselves discarded. Every signal below is a likelihood shift, not a hard filter (except
no-chance).

1. **Genbutsu — weak in HK.** In riichi, furiten makes a tile in an opponent's own pool provably
   safe against them. Without furiten, an opponent can win on a tile identical to one they
   discarded (self-draw, or a reshaped wait). Genbutsu here only says the tile probably didn't
   matter to their *old* wait. Still the highest-volume signal, worth a large adjustment — but
   **never an `is_safe(tile)` boolean.**
2. **Suji — weaker still.** Its force in riichi comes entirely from furiten. A low-confidence prior,
   weighted below genbutsu.
3. **One-chance / no-chance** — if all four 3s are visible, nobody has a 4-5 wait needing a 3. A
   hard constraint (tile counts, not psychology).
4. **Meld reading** — three melds in one suit plus honor discards means half flush; a dragon pung on
   the table makes the next dragon expensive.
5. **Discard tempo** — fast discards, then a long think and a middle-tile discard, often marks a
   hand that just reached tenpai.
6. **Wall pressure** — fewer tiles left means a higher deal-in cost per discard.

`server/bots/safety.py` implements all six as bounded multipliers on a baseline deal-in rate
(`no_chance` the sole hard-zero override), combined into `tile_risk = Σ P(deal_in | tile) ×
expected_cost` over opponents. **Hand-tuned, not trained.** A logistic regression over these
features, fit on labelled self-play logs, is the better model — and matters more in HK than riichi
because signals 1–2 are structurally weaker — but needs a labelled corpus first
([ml.md](ml.md)). `tests/test_safety.py` pins each signal's *direction*, not its calibration.

`opponent_threat_level` (meld count × 0.3 + a tempo bump, against `_THREAT_THRESHOLD = 0.3`) feeds
§4's fold gate.

## 6. Difficulty levels

Practice mode's per-seat picker (`web/src/lib/ui/PracticeSetupDialog.svelte`,
[frontend.md §7](frontend.md) "Practice mode", `POST /tables`'s `bot_tiers` —
[protocol.md §10](protocol.md)):

| Level | Bot | Tier |
| --- | --- | --- |
| Easy | `EfficiencyBot` — shanten/ukeire only, no value targeting, no safety model (§3) | `T1` |
| Normal | `FaanBot` — value targeting, safety model, fold logic (§4/§5) | `T2` |
| Impossible | `FaanBot` with a full-information view (§9) | `ORACLE` |

`T0` is never offered.

## 7. Evaluation harness

```
python -m bots.arena --a FaanBot --b EfficiencyBot --games 20000 --seed 1 --parallel 8
```

(`make arena A=… B=… N=…` runs it in the `tools` Compose profile.)

`--a ORACLE` plays the `ORACLE` tier: `BOT_REGISTRY["ORACLE"]` is the same `FaanBot` factory as
`FaanBot`, and `bots/arena.py`'s `_view_for` feeds every name in `OMNISCIENT_BOTS` an
`_omniscient_seat_view` (§9). Harnesses that only build plain `seat_view`s (`ml/eval_policy.py`,
`ml/generate_dataset.py`) refuse those names.

Reports per bot: average points/hand, win rate, deal-in rate, average winning faan, tenpai-at-draw
rate, average turns to win, and `tenpai_rate_on_sub_minimum_hand` (§4).

**Raw win totals are not a statistical test.** HK scoring has high per-hand variance — limit hands
swing points sharply — so a 2% true edge can hide inside 20k games of noise. The engine is pure and
seeded, so the arena pairs instead:

1. **Duplicate seeding.** Each seed's wall is played once per seat rotation (4 permutations), so
   both bots see the same hands.
2. **Paired difference.** Per duplicate set, candidate − incumbent points. Pairing cancels the
   variance of who got dealt the good hand.
3. **Confidence interval.** Mean paired difference ± 95% CI.

**Merge gate for any bot change:** the paired-difference CI excludes zero in the candidate's favour.

**Candidate vs previous version.** `--diffs-out PATH` writes each set's paired difference and the
candidate's wins/hands per set as JSON; `--baseline-diffs PATH` (a previous run, same `--b` and
seeds) also prints Δ points/game and Δ win rate (pp), each paired per set with a 95% CI. Same
seeds and opponents make `(candidate − B) − (baseline − B)` a valid paired sample.

```
python -m bots.arena --a ORACLE --b FaanBot --games 200 --seed 1000000 --parallel 4 --diffs-out base.json
python -m bots.arena --a <candidate> --b FaanBot --games 200 --seed 1000000 --parallel 4 \
    --baseline-diffs base.json
```

### Current numbers: `FaanBot` vs `EfficiencyBot`

`python -m bots.arena --a FaanBot --b EfficiencyBot --games 1000 --seed 1 --parallel 4` (1000
duplicate sets = 4000 games), engine 1.3.0, `hk_classic`. Shipped weights: `bots/faanbot.py`'s
`_weights_for_turn` (its docstring carries the tuning history).

| Metric | FaanBot (A) | EfficiencyBot (B) |
| --- | --- | --- |
| win_rate | 0.1974 | 0.1632 |
| deal_in_rate | 0.0416 | 0.0685 |
| avg_winning_faan | 3.3029 | 3.2179 |
| tenpai_at_draw_rate | 0.6084 | 0.9869 |
| tenpai_rate_on_sub_minimum_hand | 0.0394 | 0.3374 |
| avg_points_per_hand | 0.5002 | -0.1668 |

Paired difference (A − B): **+2.668 points/game, 95% CI [+1.916, +3.420]**: `FaanBot` clears the
merge gate against `T1`. It wins more, deals in less, and almost never sits tenpai on a hand that
can't reach `min_faan` (0.04 vs 0.34). Exhaustive draws are ~31% of hands, about double the
engine-1.0.0 table, because far fewer hands reach 3 faan without 缺一門. The engine-1.0.0 numbers,
where the CI still spanned zero, are in [ADR 0020](decisions/0020-hk-scoring-table-alignment.md).

## 8. Ruleset awareness

`SeatView.ruleset` carries the table's `RuleSet` ([architecture.md §5](architecture.md)); every
ruleset-dependent bot decision reads it there ([ADR 0014](decisions/0014-ruleset-aware-bots.md)).

| `RuleSet` field | Read by | Effect |
| --- | --- | --- |
| `min_faan` | `FaanBot._should_claim` | claim guard uses the table's real threshold |
| `hand_sets` | `mahjong_core.shanten.shanten()`/`ukeire()` (`hand_sets=` keyword), threaded by `EfficiencyBot` and `FaanBot`; `bots/labels.py`'s `is_tenpai`/`winning_tile_types` | Seven Pairs is only parsed when `NEW_18` is on, so `hk_strict` bots don't chase an illegal shape |
| `faan_overrides` | `bots/valuation.py`'s `route_faan_for(faan_overrides)`, computed once per `FaanBot` decision and passed to `estimate_best_faan`/`pattern_optionality` | route values follow per-pattern overrides. Empty overrides return `ROUTE_FAAN` itself (`is`), so default behaviour is byte-identical. Not memoised on `RuleSet`: it isn't hashable (`faan_overrides` is a dict) |
| `wall_reserve`, `flowers_enabled` | `bots/faanbot.py`'s `_turn_breakpoints(ruleset)`, via `mahjong_core.wall.max_turns_per_seat(ruleset)` | weight-schedule and fold breakpoints scale with the real per-seat turn budget |
| `kong_rob_enabled`, `concealed_kong_robbable` | `bots/safety.py`'s `kong_rob_risk` (`ORACLE` only, §9) | mirrors the engine's kong-rob gating |

**Breakpoint calibration.** `max_turns_per_seat(ruleset)` = (144, or 136 without flowers) − 53
dealt − `wall_reserve`, `// 4` — front draws only, a deliberate upper bound ignoring per-hand
kong/flower replacements. At the default ruleset that is `91 // 4 = 22 = _REFERENCE_MAX_TURN`, so
`_turn_breakpoints` returns exactly `(6, 12)`, the constants the weights were tuned against, for
every shipped preset. `RuleSet(wall_reserve=40)` gives 12 turns → `(3, 7)`.

`score_table` (faan → points) and `game_length` (hands per match) have no bot readers and need
none: bots rank discards by faan within a hand.

## 9. `ORACLE` tier

A plain `FaanBot()` (`bots/worker.py`'s `_make_bot`) driven by a `SeatView` with `.hands` (every
seat's concealed tiles) populated. No dedicated class, no search, no rollout
([ADR 0013](decisions/0013-oracle-full-information.md), improvements in
[ADR 0019](decisions/0019-oracle-improvements-plan.md)). Six helpers branch on `view.hands`, and
each is byte-identical to its probabilistic form when `view.hands is None`; `FaanBot` itself reads
it only to gate the `ORACLE`-only rules below (certain deal-ins, exact tenpai valuation, claims). `tests/test_faanbot_trajectory_pin.py` pins whole-bot behaviour on a plain
`seat_view` (4 × `FaanBot`, every preset, hashed action ids), so any `ORACLE`-only change that
leaks into `FaanBot` fails it:

| Helper (`bots/`) | `view.hands is None` | `view.hands` populated |
| --- | --- | --- |
| `safety.tile_risk` | Σ `deal_in_probability × expected_cost` (§5) | exact: per opponent, `_exact_deal_in_faan` checks whether this tile completes their real hand and returns its real faan |
| `safety.opponent_threat_level` | meld/tempo proxy | real shanten from `_opponent_real_shanten`, mapped onto the proxy's scale |
| `features.seen34` | own hand + visible melds + discards | also every opponent's real concealed tiles and concealed kongs |
| `safety.kong_rob_risk` | not called | exact rob check before declaring a self-kong |
| `valuation.exact_wait_value` | not called | a tenpai candidate's `(acceptance, value)` from the real scorer: live wall copies in the self-draw context plus `ron_credit` copies in the discard context, each wait counted only where it clears `min_faan` |
| `safety.ron_credit` | not called | expected ron copies per tenpai wait: 0.5 per copy an opponent holds but doesn't need (removing it doesn't raise their shanten), 0 per needed copy |

**Exact danger** (`_exact_deal_in_faan`), per opponent, for candidate tile `t`:

1. `mahjong_core.actions.hand_is_winning_shape(SeatState(concealed=(*view.hands[opp], t),
   melds=opp_melds))` — structural completeness.
2. If complete: build a `ScoringContext` (seat/prevailing wind, `self_drawn=False`, their real
   flowers, `ruleset.flowers_score`) and call `mahjong_core.scoring.faan.score_winning_hand`.
3. Return `total_faan` if `clears_min_faan`, else `0.0` — a sub-minimum hand can't win (§4).

The synthetic tile's physical id doesn't matter except that `Meld.__post_init__` rejects duplicate
ids, so `synthetic_tile_id` picks an id of that type not in the opponent's hand, or returns `None`
(risk `0.0`) when all four copies are already there — a fifth can't exist.

**Threat level.** `max(0.0, (_SHANTEN_THREAT_BASE - real_shanten) * _SHANTEN_THREAT_STEP)`, with
`_SHANTEN_THREAT_BASE = 3` (equal to `faanbot.py`'s `_FOLD_SHANTEN`, duplicated because importing
it would cycle) and `_SHANTEN_THREAT_STEP = 0.3` (the proxy's per-meld weight). Tenpai scores 0.9,
1-shanten 0.6, 3+ 0.0. Shanten-only on purpose: this gate decides *whether* to defend; `tile_risk`
already prices each tile's real faan, including sub-minimum hands.

**`seen34` and concealed kongs.** `mahjong_core.engine._apply_self_kong` removes a concealed kong's
tiles from `SeatState.concealed`, and `_omniscient_seat_view` builds `.hands` from `concealed`, so
those tiles are in neither `.hands` nor (if skipped) the meld loop. Under `view.hands`, concealed
melds are counted like any other (`_add_meld`, 3 per kong).

**Kong-rob avoidance.** `FaanBot._act_on_turn`'s kong loop skips any kong that
`kong_rob_risk(view, t, concealed=...)` proves would be robbed (`if view.hands is not None and
kong_rob_risk(...) > 0.0: continue`). Hard-avoid, not weighted — discarding is always available,
matching `_should_claim`'s "never do what provably backfires" precedent. Gating mirrors
`_kong_rob_offers`: `kong_rob_enabled` for both kinds; a concealed kong only when
`concealed_kong_robbable` and the robbing hand is 十三么.

**Certain deal-ins.** Under `view.hands`, `tile_risk > 0` is not a likelihood: every tier always
takes `_WIN`, so it is a certain deal-in. `_best_discard` therefore drops every discard with
`tile_risk > 0` from its candidates while any zero-risk legal discard exists, in fold and non-fold
mode alike. Same "never do what provably backfires" precedent as kong-rob avoidance. When every
legal discard deals in, the usual `w_safety * risk` trade-off ranks them. Before this, a certain
deal-in was priced like a soft risk (0.15–0.9 × its faan against `_SHANTEN_UNIT = 5` per shanten
step), and 66 of 67 `ORACLE` deal-ins in 200 sets were avoidable.

**Exact tenpai valuation.** For a candidate discard that leaves `ORACLE` tenpai, `_best_discard`
replaces both structural proxies with `exact_wait_value` over the real waits
(`labels.winning_tile_types`): the speed term's tile count becomes the acceptance (live wall
copies, plus `ron_credit` copies in opponents' hands), and `estimate_best_faan` becomes the
copy-weighted real faan. Wall copies are scored self-drawn, ron copies as a discard win; a wait
that can't clear `min_faan` in a context counts nothing there, so a sub-minimum or dead tenpai
stops looking fast. Ron credit is 0.5 per surplus copy, 0 per needed copy (`safety.py`'s
`_RON_CREDIT_SURPLUS`/`_RON_CREDIT_NEEDED`); calibrated against `FaanBot` opponents, whose
real discard rates were 26% / 7.6% (ADR 0019 §3). Non-tenpai candidates keep the proxies. A
decision costs about the same as before (~12 ms on the arena machine).

**Claims into a clearing tenpai.** When `_act_on_claim`'s default would pass and the hand is
≥ 1-shanten, `ORACLE` tries each offered pung/chow (`view.claim_options`): for every post-claim
discard with `tile_risk == 0` that reaches tenpai, `exact_wait_value` (with the new meld) gives
acceptance and value. It claims the option with the largest acceptance × value among those with
acceptance ≥ 1 copy and value ≥ `min_faan + 1` (`_CLAIM_VALUE_MARGIN`); otherwise it passes. The
margin matters: an exposed meld loses 門前清 and the self-draw bonus, and claiming into any
clearing tenpai won more but cheaper hands with no points gain.

**Containment** ([architecture.md §5](architecture.md)):

- `app/views.py`'s `_omniscient_seat_view(state, seat)` is the only builder of a real seat's
  omniscient view; `seat_view()`'s `_check_reveal` still forbids it. Exactly two callers:
  `app/table.py`'s `_submit_bot_job`, when the seat's effective tier is `ORACLE`, and the
  offline arena's `bots/arena.py` `_view_for` (§7). `tests/test_oracle_containment.py` AST-scans
  production code for any other call site, and for any `app/` module importing `bots.arena`.
- A `SeatView` never carries `game_seed`/`hand_seed`, so it may cross the process-pool boundary.
  No `GameState` crosses; `compute_action` is unchanged.
- **Disconnect handover always uses `T2`.** `Table._effective_bot_tier(seat)` pins an
  `autoplay`-status seat (a human's, gone) to `_DISCONNECT_HANDOVER_BOT_TIER = "T2"`; only
  `bot`-status seats (practice / all-bot tables, never human) use the configured tier. The risk is
  the omniscient *view*, not the bot class.
  `tests/test_table.py::test_disconnect_handover_always_uses_t2_even_when_table_bot_tier_is_oracle`
  pins it; `tests/test_redaction.py` pins that `Table.state_sync_wire` never carries `.hands` for a
  real seat.
- `ORACLE` jobs use the shared pool; a decision costs the same single-digit milliseconds as `T2`.

**Measured** (`python -m bots.arena --a ORACLE --b FaanBot --games 200 --seed 1000000`, 200
duplicate sets): paired difference **+35.153 points/game, 95% CI [32.255, 38.052]**; win rate
0.364 vs 0.143; deal-in rate 0.000 vs 0.178; avg winning faan 4.29. Against the previous `ORACLE`
on the same seeds: Δ **+2.293 points/game [+1.142, +3.445]**, Δ win rate +2.53pp [+1.87, +3.19]
([ADR 0019](decisions/0019-oracle-improvements-plan.md) has each change's gate run).

## 10. Known issues

| Issue | Where | Status |
| --- | --- | --- |
| **`no_chance` counts the observer's own tiles.** `deal_in_probability` returns 0 when `seen34(view)[t] >= 4`, and `seen34` includes the candidate tile itself, so when the other three copies are visible the opponent can still win on this discard yet it scores 0 (3.4% of 32,080 sampled candidate discards). Fix: count `seen34` minus the candidate copy | `bots/safety.py` | unfixed: `FaanBot` is the RL evaluation baseline ([ml.md §12](ml.md)), so change it between gate runs, not during one |
| `FaanBot` vs `EfficiencyBot` points CI includes zero | §7 | open tuning work |
| `_act_on_turn`'s kong loop never fires. Shanten is monotonic in a tile type's count, so removing one copy from a complete group can never lower it, and `s < best_kong_shanten` is never true — no tier voluntarily declares a self-kong. Kong-rob avoidance (§9) guards a branch that is currently unreachable | `bots/faanbot.py` | known; harmless today |
| `kong_rob_risk` reuses `_exact_deal_in_faan`, which hardcodes `is_robbing_kong=False`, so a hand one faan short that 搶槓's +1 would lift over `min_faan` reads as safe | `bots/safety.py` | accepted; narrow and rare |
| No load test of 200 concurrent tables × 3 bot seats against the shared pool | §3 | not run |

## 11. References

- [MahjongRepository/mahjong](https://github.com/MahjongRepository/mahjong) — shanten reference implementation
- [A Fast Algorithm for Computing the Deficiency Number of a Mahjong Hand — arXiv:2108.06832](https://arxiv.org/pdf/2108.06832)
- [Constructing AI Players with MDP Abstraction in Mahjong — arXiv:1904.07491](https://arxiv.org/pdf/1904.07491)
