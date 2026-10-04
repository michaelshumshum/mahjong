# ORACLE tier redesign (rollout OracleBot -> hands-aware FaanBot)

Done: replaced `bots/oracle.py`'s rollout-based `OracleBot` with a plain `FaanBot()` fed an
omniscient view. No dedicated bot class, no search, no dedicated process pool.

## Mechanism
- `bots/safety.py`'s `tile_risk(view, tile_type)` now branches on `view.hands`:
  - `None` (every tier but ORACLE): byte-identical to the old probabilistic formula.
  - populated (ORACLE only): `_exact_deal_in_faan` per opponent builds a candidate `SeatState`
    (`(*view.hands[opp], synthetic_tile)`), checks `mahjong_core.actions.hand_is_winning_shape`,
    then `score_winning_hand` with a `ScoringContext` built directly from `SeatView` fields
    (mirrors `engine._can_win_with`'s pattern, no live GameState needed). Returns real
    `total_faan` if `clears_min_faan`, else 0.0.
- `_synthetic_tile_id(tile_type, hand)`: **must** pick an id not already in `hand` — a naive
  `tile_type*4` can collide with a real physical id already in the opponent's hand once
  `decompose()` materializes a `Meld`, and `Meld.__post_init__` rejects duplicate physical ids
  in one meld. Returns `None` (read as 0.0 risk) if all 4 real copies are already in hand (5th
  physical tile can't exist). This bug was NOT caught by unit tests — only by the ad hoc 60-game
  arena verification script, first run. Lesson: exact-info code touching `decompose`/`Meld`
  needs either property-style fuzzing or a real self-play run before trusting hand-picked fixtures.
- FaanBot's `_best_discard` already called `tile_risk`; zero changes needed to `faanbot.py`.

## Dispatch (bots/worker.py, app/table.py)
- `_make_bot("ORACLE", seed)` just returns `FaanBot()`.
- `app/table.py`: `_shared_oracle_bot_pool`/`_default_oracle_bot_pool`/`oracle_bot_pool` param
  all deleted. ORACLE jobs route to the same default pool as T0-T2 (only T3 keeps its own pool).
  `_submit_bot_job` still special-cases `tier == "ORACLE"` to build the view via
  `_omniscient_seat_view` — that's the one thing still ORACLE-specific.
- `_omniscient_seat_view` (app/views.py) kept as-is, single call site still
  `Table._submit_bot_job` (tests/test_oracle_containment.py still pins this, docstrings only
  reworded).
- Disconnect-handover carve-out (`_effective_bot_tier` pins autoplay seats to T2) still matters
  post-redesign: the risk is the omniscient *view*, not the bot class, since ORACLE and T2 are
  both FaanBot now.

## Verification (arena, 15 duplicate sets / 60 games, scratch script deleted after use)
Paired diff (ORACLE - FaanBot): **+11.644 pts/game, 95% CI [6.220, 17.069]**. deal_in_rate
0.0083 vs 0.1542 baseline (~18x drop). Full numbers in docs/bots.md §9.

## Tests
- `tests/test_safety.py`: hands-aware tile_risk unit tests (exact deal-in, probabilistic-looks-
  dangerous-but-safe, sub-min-faan not flagged, hands=None regression, concealed-kong synthetic-id
  collision regression).
- `tests/test_oracle.py`: fully rewritten — dispatch wiring test (`_make_bot("ORACLE")` returns
  plain `FaanBot`), scripted behavioral proof (omniscient view avoids a real deal-in that
  genbutsu — weak in HK, no furiten — fools the probabilistic view into), self-play smoke test.
- `tests/test_table.py`: deleted 2 pool-isolation tests (no pool to isolate anymore), kept/
  rewrote hands-populated + disconnect-handover tests (now check the default pool, not a
  separate oracle pool).

docs/bots.md §9 fully rewritten with design history + mechanism + verification numbers.
docs/architecture.md §5 and §3 references reworded (not rewritten).

## Follow-up 1: `opponent_threat_level` made hands-aware too (fold-timing gap)

`tile_risk` being exact only changes *which* tile `_best_discard` picks once already in
`fold_mode` — it says nothing about *when* `fold_mode` engages. That gate's `threatening` flag
was still the old meld-count/discard-tempo proxy, blind to `view.hands`. Fixed the same way:

- `bots/safety.py`'s `opponent_threat_level(view, opponent_seat)` branches on `view.hands`:
  - `None`: byte-identical to `melds * 0.3 + tempo_bump` (pinned,
    `test_opponent_threat_level_hands_none_matches_the_original_probabilistic_formula`).
  - populated: `_opponent_real_shanten` (new helper, `_opponent_hand34` + `mahjong_core.shanten.
    shanten`) maps real shanten onto the proxy's own scale:
    `max(0.0, (_SHANTEN_THREAT_BASE - real_shanten) * _SHANTEN_THREAT_STEP)`,
    `_SHANTEN_THREAT_BASE=3` (== `faanbot.py`'s `_FOLD_SHANTEN`, not imported — would cycle),
    `_SHANTEN_THREAT_STEP=0.3` (== proxy's per-meld weight). Tenpai (shanten 0) -> 0.9, shanten 1
    -> 0.6, both decisively past `_THREAT_THRESHOLD=0.3`; shanten 3+ clamps to 0.0.
  - Deliberately shanten-only, not faan-weighted — `tile_risk` (already hands-aware) prices the
    real faan once fold_mode is active, including the sub-`min_faan` zero case; duplicating that
    here would just re-run the same check one level up.
- Zero changes to `faanbot.py` needed (same pattern as `tile_risk`).

### Tests
- `tests/test_safety.py`: regression pin (hands=None), plus two "proxy would get this wrong"
  pairs on the identical position — near-tenpai opponent the proxy reads as safe (no melds, no
  tempo) but hands-aware correctly flags; meld+tempo-heavy opponent the proxy reads as dangerous
  but whose real hand (shanten 4) hands-aware correctly clears.
- `tests/test_oracle.py::test_omniscient_view_folds_against_a_tenpai_opponent_the_proxy_reads_as_safe`:
  bot-level proof. Opponent has zero melds/empty discard pool, real hand tenpai tanki-waiting on
  exactly the tile `_best_discard`'s ordinary value-weighted scoring would pick anyway (a middle
  tile, best ukeire). Ordinary view: fold gate never opens (proxy threat 0 < 0.3), `FaanBot`
  walks into the deal-in. Omniscient view: real-shanten threat opens the gate, and — combined
  with `tile_risk`'s own exact per-tile danger — `FaanBot` avoids that exact tile. Both fixes
  have to fire together for this outcome (isolates the threat-timing fix from the earlier
  `tile_risk` fix, whose own test already had fold_mode open under *both* views via a meld).

### Empirical re-verification — the win-rate gap did NOT close at the standard 15-set/60-game
sample size, and this took real investigation, not just re-running the script:

- 15 duplicate sets (60 games), same seed as the original check: win_rate/deal_in_rate/
  avg_points_per_hand/paired-diff-CI came out **bit-for-bit identical** to the pre-fix numbers
  (0.1750/0.1472, 0.0083/0.1542, +11.644 [6.220, 17.069]) — only avg_winning_faan/
  tenpai_at_draw_rate/tenpai_rate_on_sub_minimum_hand moved slightly, proving some hands *did*
  play out differently without flipping any win/loss/deal-in outcome in this particular sample.
- Direct instrumentation (compare pre-fix-proxy vs current `_best_discard` pick on the identical
  `SeatView`, every own-turn oracle-seat decision, 20 games/seeds 1-5): fold_mode's `threatening`
  flag flipped 39/1399 decisions (2.8%), and the flip changed the actual discard chosen on only
  22/1399 (1.6%). Real effect, but thin per-decision — not enough to reliably flip a binary
  per-hand win/loss outcome inside 60 games.
- 200 duplicate sets (800 games), same seed: win_rate moved to **0.2047 vs 0.1671** (up from
  0.1750/0.1472), paired diff **+12.100 pts/game, 95% CI [10.247, 13.953]** (tighter than the
  15-set CI, same ballpark point estimate). Confirms the fix is real; it just needs a bigger
  sample than this tier's existing 15-set convention to see in win_rate specifically.
- Lesson for next time: this tier's ~1.6%-per-decision-class of fix is invisible at 15
  duplicate sets. If a future change to this tier looks like a no-op in the standard-size check,
  don't stop there — instrument decision-level divergence directly before concluding "no effect."

Full mechanism + both verification tables are in docs/bots.md §9 ("The fold-timing gap" /
"Re-verification after the fold-timing fix" subsections).

## Follow-up 2: `seen34` made hands-aware too (offense-side ukeire gap) -- biggest effect of the three

`tile_risk`/`opponent_threat_level` are both defense-side. Neither touches `_best_discard`'s
speed term, which reads `ukeire`'s live-tile count `4 - seen34[t]`. `bots/features.seen34` never
read `view.hands` at all -- an opponent's real concealed tiles (genuinely known under the
omniscient view) still read as "maybe still in the wall," so ukeire overstated live tiles and
`FaanBot`'s speed term was systematically inflated for ORACLE.

- `bots/features.py`'s `seen34(view)` branches on `view.hands`:
  - `None`: byte-identical (own hand, every seat's non-concealed melds, discards; concealed kong
    still skipped -- genuinely invisible to a normal bot).
  - populated: also counts every opponent's real concealed tiles (`view.hands[opponent]`), AND
    stops skipping a concealed meld -- adds it via the existing `_add_meld` (kong contributes 3,
    unchanged convention).
- **Concealed-kong subtlety (had to get this right, not assume):** traced
  `mahjong_core.engine._apply_self_kong` -- a concealed kong's 4 tiles are REMOVED from
  `SeatState.concealed` the instant it's declared, live only in `SeatState.melds` from then on.
  `_omniscient_seat_view` builds `.hands` straight from `state.seats[s].concealed`, so a concealed
  kong's tiles are absent from `view.hands[opponent]` too -- NOT double-counted if also added from
  `view.melds`. Confirmed by mirroring `bots/safety.py`'s own `_opponent_hand34`, which already
  does exactly this (unconditionally adds every meld including concealed ones on top of
  `view.hands`) -- this task's fix makes `seen34` consistent with that existing pattern rather
  than inventing a new one. Getting the direction backwards (still skipping concealed melds under
  `view.hands`) would have silently dropped those 4 tiles from the count entirely -- neither loop
  would add them -- the opposite of what an omniscient view should do.
- Zero changes to `faanbot.py`/`mahjong_core.shanten` needed (same pattern as the other two).

### Tests
- `tests/test_features.py` (new file): `view.hands is None` regression pin; a scripted position
  (opponent holds 3/4 real copies of a tile a discard is kanchan-waiting on) showing seen34
  undercounts under `hands=None` (0) vs correctly counts under `hands` (3), and `ukeire`'s live
  count for that discard drops 4->1 accordingly; concealed-kong regression mirroring
  `test_tile_risk_hands_aware_handles_a_concealed_kong_of_the_candidate_type`'s convention.
- `tests/test_oracle.py::test_omniscient_view_prefers_a_discard_with_more_real_live_tiles`:
  bot-level proof, scripted position **found by direct programmatic search over `FaanBot.act`**
  (not hand-derived -- brute-forced random 13-tile hands + a hidden opponent tile type until a
  real discard flip appeared, then verified/pinned). Probabilistic view picks PIN_9 (16 kinds/58
  tiles ukeire, inflated by 3 hidden WIND_EAST copies reading as live); omniscient view correctly
  shrinks it to 14/51 and picks WIND_NORTH instead. `tile_risk` checked directly in-test to read
  identically for both candidates in both views, proving the flip is seen34's doing alone.

### Empirical verification (200 duplicate sets / 800 games, same script/seed as the
fold-timing re-verification -- reran the *unmodified* baseline first via `git stash` to confirm
the script reproduces the documented pre-fix numbers bit-for-bit before trusting the post-fix run):

| Metric | pre-fix A/B | post-fix A/B |
| --- | --- | --- |
| win_rate | 0.2047 / 0.1671 | **0.3181** / 0.1517 |
| deal_in_rate | 0.0106 / 0.1523 | 0.0209 / 0.1628 |
| avg_points_per_hand | 2.2687 / -0.7562 | 5.1925 / -1.7308 |

Paired diff: pre-fix +12.100 [10.247, 13.953] -> post-fix **+27.693 [25.098, 30.288]** -- more
than double, and visible directly at the existing 200-set size (unlike the fold-timing fix, which
needed the larger sample to show up in win_rate at all). Biggest single effect of the three
hands-aware fixes -- makes sense: seen34 touches the speed term on *every* turn's discard
decision, not just a comparatively rare fold-timing gate (~1.6% of decisions) or a single-target
deal-in check. deal_in_rate ticked up slightly (0.0106->0.0209, still ~8x below FaanBot's own
0.1628) -- ORACLE now pushes hands further/discards more before hands end, giving the residual
real-deal-in mechanism marginally more chances to fire; net effect still decisively positive.

Full mechanism + tables in docs/bots.md §9 ("The offense-side gap: `seen34` needed the same
treatment" / "Re-verification after the `seen34` fix" subsections).
