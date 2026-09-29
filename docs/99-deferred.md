# 99 — Deferred

Ideas cut from the v1 plan during the 2026-09-14 design audit. Nothing here is rejected on
merit; it is out of scope for v1 and parked so the intent survives without the false precision
of a live spec. Each entry names the doc and section it came from.

Before reviving anything here, re-read the source section — the surrounding design has changed.

## From 00-architecture.md

### Client-contributed entropy for provable fairness

Provenance: `00-architecture.md` §9 (anti-cheat, item 4) and §3/§5 (D2) — deferred per doc-audit
finding 5: the server-only commit/reveal scheme proves the wall wasn't edited *after* commitment,
not that the deal was unbiased, since the server alone picks `hand_seed` and `nonce` and already
knows the resulting wall before it commits.

**Scheme (post-v1):** each seat contributes entropy the server cannot see in advance.

1. Before the deal, each of the four seats independently generates a private nonce `nᵢ` and
   sends a commitment `Cᵢ = SHA256(nᵢ)` to the server. The server does not yet know any `nᵢ`.
2. Once all four commitments are in, the server combines them:
   `hand_seed = SHA256(n₀ ‖ n₁ ‖ n₂ ‖ n₃)` — but it can only compute this *after* every seat has
   locked in its commitment, so no seat (including the server) can choose its own nonce in
   response to seeing another party's contribution or the resulting deal.
3. Deal proceeds as in v1: `hand_seed` shuffles the wall (§3), and it — not `game_seed` — is what
   gets revealed at hand end.
4. At hand end, each seat reveals its `nᵢ`; everyone checks `SHA256(nᵢ) == Cᵢ` and recomputes
   `hand_seed` independently. If it matches what was used to deal, no party (server included)
   could have picked their contribution knowing the outcome.

**Needs before un-deferring:**
- A commit round adds a network round-trip before every hand can start; needs a bounded timeout
  and a defined fallback (server-only entropy for that hand? seat forfeits and a bot substitutes
  its nonce?) for a seat that never sends `Cᵢ` or never reveals `nᵢ`.
- Bots need a nonce-generation story — a bot seat still needs to contribute unpredictable
  entropy, not a fixed or server-supplied value, or it reduces to the server picking its share.
- Decide whether this applies to every hand or only rated/ranked play, given the added latency.
- Protocol messages for the commit/reveal round don't exist yet (`02-protocol.md`).

---

### Multi-node scaling detail (stages 2–3) and mid-game durability

Provenance: `00-architecture.md` §7 (scaling path) — deferred per doc-audit findings 7 and 8.
v1 (this doc's actual scope) is single-process with no mid-game durability: a process death
abandons every live table in it. Everything below is the deferred design space for surviving that,
compressed to intent in §7 itself.

**Stage 2 — N nodes, sticky tables.** A table is pinned to exactly one node for its lifetime; a
lightweight router in front holds only a table→node directory, the matchmaking queue, and lobby
presence, and redirects `GET /tables/{id}/route` to the right node's WebSocket URL. Table state
itself is never distributed — `shard by table, never split a table` (the single-writer invariant
in §3 depends on this).

**Stage 3 — durability.** The originally-drafted plan was "append each action to Postgres as it's
applied," with a parenthetical alternative of "or batch per hand." These are not interchangeable
and the doc previously left both standing at once, which is the bug this entry replaces:

- **Per-action append** conflicts directly with §3's own invariant — "no `await` between read and
  write of shared state" — since a Postgres write is real I/O and awaiting it inside the table's
  synchronous reduce-and-publish step reintroduces exactly the race the single-task-per-table
  design exists to avoid. Making it safe requires moving the write off the hot path (e.g. a
  separate writer task fed by a queue the table enqueues into without awaiting), which changes the
  durability guarantee: a write can now be lost between "table applied it" and "writer persisted
  it," narrowing but not eliminating the crash window.
- **Batch per hand** has a larger, differently-shaped crash window: it loses exactly the
  in-progress hand on a crash — the one hand a durability feature exists to protect — while
  being cheaper and easier to keep off the table's hot path.
- Whichever is chosen, **exact replay is the hard unsolved part**, independent of write
  granularity: `reduce` is pure only over its explicit inputs, and two categories of
  non-determinism currently happen *outside* `reduce` and are not logged as actions at all:
  - **Bot decisions** are ε-random ([04-bots.md](04-bots.md)) — replaying "what the bot decided"
    requires logging the decision itself as a first-class action, not just re-running bot logic
    against replayed state, since re-running would pick a different ε-random branch.
  - **Timer expiries** (tsumogiri-on-timeout, auto-pass-on-timeout, bot-deadline defaults,
    §8) are server-clock-driven, not derived from `GameState`; an exact replay needs each expiry
    logged as the action it produced, with enough info to know *why* it fired, not just recompute
    a new deadline against a possibly-different wall-clock on the replaying node.

None of this — write granularity, the async-invariant fix, or the non-determinism log format —
has a chosen design yet. It needs one before Stage 3 is buildable; §7 states the v1 fallback
(process dies → games abandoned, softened only by the planned-shutdown drain in §8.1) rather than
committing to an unresolved durability story.

## From 01-rules-spec.md

### Multi-win (一炮多響)

Provenance: `01-rules-spec.md` §6 (claim priority), §10 (`RuleSet.multi_win`), §11 (edge case
7) — deferred per canonical decision D7: v1 is single-winner; 一炮多響 is deferred past v1.

**Full behavior (post-v1):** when two or more players can declare a win off the same
discard, instead of resolving to a single winner by seat-order tiebreak
(`(claimer_seat - discarder_seat) % 4`, smallest wins — the v1 rule, see
`01-rules-spec.md` §6), all claimants win simultaneously. The discarder pays each winner in
full (i.e. the discarder's total liability is the sum of `P` for every winning hand, not
split). Each winning hand is scored independently — no `1.5×` self-draw-style adjustment,
since this is still a discard win for each claimant. Dealer continuity (連莊) follows
whichever house rule the table has configured for multi-winner hands (commonly: dealer
repeats only if the dealer is among the winners).

Needs before un-deferring:
- Decide whether all winners are required to reveal their full hand simultaneously or in
  seat order (affects information leakage in the reveal sequence).
- Decide interaction with `pao_rules` (包) if a discarder is liable under a responsibility
  rule for one hand but not another among the multiple winners.
- Client/protocol support for a multi-winner `SCORING` payload (currently single-winner
  shaped, see `02-protocol.md`).

`RuleSet.multi_win: bool` field stays in the dataclass as a reserved flag (`False` in v1) so
the shape doesn't need to change when this is implemented.

## From 02-protocol.md

### Deferred material cut from docs/02-protocol.md

### Chess-clock bonus bank

From `02-protocol.md` §4 (Timers).

Each player gets `bonus_seconds` (default 20) for the whole game, drawn down only after the
per-turn budget is spent — like a chess byoyomi/bank.

Cut per D16: a bank means the deadline for a prompt can extend mid-flight (spend some of the
bank, get more time), but the rest of §4 is built entirely around a single immutable
`deadline_ts` per prompt with no message that pushes a *revised* deadline to the client. Adding
the bank properly requires:

- A new server→client event (or a mutable field on the existing prompt) that updates
  `deadline_ts` when a player draws on their bank, plus client handling to extend an
  already-rendered countdown instead of just reading the deadline once.
- A decision on what the client is even allowed to see before the bank is spent — does the
  timer bar show "you may extend" as an affordance, or is spending the bank an explicit action
  (e.g. a `use_bonus` intent) rather than automatic?
- Interaction with §9 (turn timeout auto-action) and §8/backpressure — a revised-deadline event
  arriving late or getting dropped under backpressure must not leave the client counting down
  against a stale deadline.

None of that is designed yet. Keep the absolute-`deadline_ts` + measured-clock-offset model
as-is (it's correct) and revisit the bank as a follow-up feature with its own event type once
the extension-message design is worked out.

Related: the `bonus_seconds: int = 20` field this feature needed has been removed from the
`RuleSet` in `01-rules-spec.md` §10. Reviving the bank means adding it back alongside the
deadline-extension message described above.

## From 03-frontend.md

### Deferred — 03-frontend.md

Cut during the docs audit (2026-09) that resolved the Pixi → DOM rendering decision. Content here
was removed from `docs/03-frontend.md` for scope, not because it's wrong; nothing here is
designed, just parked. Main-doc pointers read "Deferred — see [99-deferred.md](99-deferred.md)."

### Faan preview on hover

Provenance: was `03-frontend.md §4` (Interaction model), cut — no protocol message carries
shanten/ukeire, and a client-side TypeScript reimplementation duplicates the one deliberately-pure
Python engine (`00-architecture.md §3`).

Original: "Faan preview on a hovered discard candidate: shanten, wait count, and whether the hand
can reach the 3-faan minimum. Gated behind a training-mode setting for rated play."

Revisit as: a rate-limited server `hint` request/response reusing `mahjong_core.shanten`/
`ukeire`, not a client-side reimplementation. Needs a new protocol message — out of scope here,
flagged for whoever owns `02-protocol.md`.

### Recorded Cantonese call-out audio

Provenance: was `03-frontend.md §5` (Asset pipeline), cut — nobody has recorded it; unbudgeted
content task, not a code task.

Original: "Sound: draw click, discard clack, claim call (recorded Cantonese 「碰」「上」「槓」
「食糊」), shuffle."

v1 ships draw/discard/shuffle UI SFX only, mute default-on.

### High-contrast tile theme system

Provenance: was `03-frontend.md §7`, cut — a switchable theme engine is more surface area than v1
needs. The colourblind-safe glyph is a fixed asset, not a theme, and ships regardless
(`03-frontend.md §8`).

Original: "Colourblind-safe: dragons distinguished by glyph, not just red/green. High-contrast
tile theme."

### Drag-to-reorder hand, sticky per session

Provenance: was `03-frontend.md §4`, cut — extra interaction + persistence surface for v1;
auto-sort covers the actual need (finding tiles fast).

Original: "Sort hand: auto by default; drag to reorder, sticky per session [desktop] / drag
[touch]."

### Chess-clock bonus-bank meter

Provenance: `02-protocol.md` §4 (Timers), where the bank was cut along with the `bonus_seconds`
config field; no dedicated client UI was specified for v1 either.

v1 behaviour: bonus seconds are enforced server-side and folded into `deadline_ts` like any other
deadline; no separate meter/visualization. Revisit once the base countdown ring (`03-frontend.md
§5`) ships and there's a UX reason to distinguish "spending bonus time" from "spending turn time."

### @1x tile atlas

Provenance: was `03-frontend.md §5` (Asset pipeline: two atlases, @1x/@2x, picked by DPR) — moot,
not really deferred. SVG tile art is resolution-independent, so there's no atlas, DPR split, or
build pipeline at all. Noted for history only.

### 2.5D Blender pre-render

Provenance: was `03-frontend.md §5`, cut — the DOM approach gets the 2.5D look from `perspective`
+ `rotateX` on the table container (`03-frontend.md §2`) at zero asset cost.

Original: "2.5D look: pre-render tiles in Blender at the table's fixed camera angle, ship as
sprites — real lighting and bevels at zero runtime cost."

Source asset pack for a future higher-fidelity pass:
[libreriichi-assets](https://codeberg.org/davidgomez/libreriichi-assets) (CC0 3D textures +
Blender sources), kept for reference.

## From 04-bots.md

### Deferred from 04-bots.md

Cut per audit decision D16. Original source: `docs/04-bots.md`, pre-audit versions of §2 (T3
row), §6 ("T3 — search"), and §7 (bot personas paragraph, Expert row detail).

### T3 `SearchBot` — CLOSED (built, M6; removed 2026-09-27)

Provenance: `04-bots.md` §2, tier table row for T3 (pre-audit). **Built in M6, removed
2026-09-27** — `server/bots/search.py` is deleted; `04-bots.md §6` carries the compact
built-then-removed writeup (what happened, why removed, revival requirements). Kept below as the
historical record of the original ask and the full shipped design, per this doc's own header
rule — nothing here is rejected on merit, this is exactly the kind of decision this file exists
to keep a trail for.

| Tier | What it is | Effort | Use |
| --- | --- | --- | --- |
| **T3** `SearchBot` | determinized rollouts / MCTS over the pure engine | large | "Expert", post-launch |

(the row above is the original, pre-audit ask, kept verbatim for the historical record — the
shipped tier table is `04-bots.md §2`.)

### T3 — search — CLOSED (built, M6; removed 2026-09-27)

Provenance: `04-bots.md` §6, "T3 — search" (pre-audit; cut because T1/T2 alone satisfy the M4
done-gate per the D9/§4 fix, and the 300–800ms budget below is incompatible with the
single-worker, single-event-loop process described in `07-infra.md` — it would block every table,
every socket, and every heartbeat on that process if run inline, and even off-loop it competes
for the same `ProcessPoolExecutor` capacity flagged as a real constraint in §3). **Built, M6, once
the execution-model finding below stopped being a blocker** — `04-bots.md §6` has the shipped
algorithm, the determinization design, every scope cut actually made (bounded-depth rollout
instead of full hand-to-`HAND_OVER`, `AWAIT_ACTION`-only search, strategy fusion accepted not
solved), the pool-isolation fix, and a real (small) arena comparison against `FaanBot`. This entry
stays as the historical record of the original ask and the finding that gated it.

With a pure engine, determinized MCTS is straightforward:

1. Sample N worlds consistent with the redacted view (unseen tiles distributed among opponents
   and wall, respecting counts and light discard-based inference).
2. Run rollouts with T2 policies as the default policy.
3. Average action values across worlds; pick the best.

Budget 300–800ms per decision, inside human think time. The known weakness is **strategy
fusion** (the search assumes it can act differently per world when it can't); information-set
MCTS mitigates it. Read [arXiv:1904.07491](https://arxiv.org/pdf/1904.07491) on MDP abstraction
for mahjong before building this.

~~Before reviving this: re-derive the per-decision CPU budget against whatever the
`ProcessPoolExecutor` sizing turns out to be (see `04-bots.md` §3) — 300–800ms per decision at
200 concurrent tables × 3 bot seats is a much larger capacity ask than the T1/T2 shanten-table
path and needs its own worker-pool sizing pass, not a shared one.~~ **Done, at a starting-point,
not final-capacity, level of rigor:** the CPU-budget arithmetic actually done for the shipped
version lives in `04-bots.md §6` ("Bounded-depth rollout" bullet — a direct benchmark, not a
guess); the pool is now per-tier (`app/table.py`'s `_shared_search_bot_pool`,
`max_workers=2`), but that worker count is still explicitly flagged as unvalidated against real
per-core throughput, exactly the open item this paragraph originally named — 200-concurrent-table
capacity sizing is still not done.

**Execution-model finding (2026-09-26, ml-readiness scoping pass):** `app/table.py`'s
`_shared_bot_pool()` is one `ProcessPoolExecutor` shared by every tier and every table
(`00-architecture.md §3`, `04-bots.md §1`). A T3 job at the 300–800ms budget above would
head-of-line-block T1/T2 jobs from unrelated tables sharing that same pool — one slow `SearchBot`
decision stalls every other table's bot turn queued behind it in the pool's worker processes.
**Deliberately not fixed at the time, for two reasons, not an oversight:** (1) the fix — routing
by tier to a tier-appropriate pool instead of one shared pool — needs real per-core throughput
measurement on target hardware to size correctly; guessing pool sizes then would have just been
another unvalidated constant, no better than the reference numbers `04-bots.md §3` already flags
as needing calibration. (2) there was no real consumer yet: `SearchBot` didn't exist, so building
a tier-routing abstraction then would have been exactly the premature-abstraction pattern this
project's conventions warn against (see the KV/Queue/Bus precedent above — "written for a Redis
that doesn't exist yet"). **What actually un-deferred T3:** (a) per-tier `ProcessPoolExecutor`
routing landed in `app/table.py` (`_shared_search_bot_pool`, routed by `Table._bot_tier` in
`_submit_bot_job`) alongside `SearchBot` itself in the same change, so the pool finally had a real
consumer to size a starting point against; (b) the CPU-budget re-derivation is the direct
`FaanBot.act` benchmark cited in `04-bots.md §6`, which is *why* the shipped rollout is
bounded-depth rather than full-hand — the literal 300–800ms full-rollout budget this section
described turned out not to be arithmetically achievable at all, benchmark or no benchmark, and
that finding (not a capacity number) is what actually shaped the shipped design.

**Removal (2026-09-27).** The shipped design, archived in full since `server/bots/search.py` no
longer exists:

- **Algorithm.** Per decision (`Phase.AWAIT_ACTION` only): sample N worlds consistent with the
  redacted `SeatView` (`determinize()`), for each legal root action roll forward up to
  `rollout_depth` further decisions with `FaanBot` acting for every seat, value a rollout by its
  real point delta at `HAND_OVER` or a shanten/reachable-faan/ukeire proxy (`value_estimate`) at
  the depth cap, average each action's value across the worlds it was evaluated in, return the
  best. Default `time_budget=0.5s`, `max_worlds=8`, `rollout_depth=4`.
- **`determinize(view, rng)`.** Every `TileId` not accounted for by (own hand + all melds + all
  discards) is unseen, shuffled once, and handed out — `concealed_counts[s]` tiles to each
  opponent seat, the remainder to the wall; flowers need no identity sampling (only 8 exist, so
  whichever aren't revealed must be in the wall — only their wall position was randomized). Tile
  conservation (every physical tile accounted for exactly once) was verified directly, not
  eyeballed. Only supported `AWAIT_ACTION`-shaped views — a `SeatView` never carries another
  seat's live claim offers/`window_id`/discarding seat, so a legal `ClaimWindow` couldn't be
  reconstructed for a sampled world; claim-window decisions delegated straight to `FaanBot`.
- **Scope cuts (deliberate, not oversights):** only `AWAIT_ACTION` ran real search; bounded-depth
  rollout with a value-estimate cutoff instead of full hand-to-`HAND_OVER` (a direct benchmark of
  `FaanBot.act` measured ~4.7ms/decision, ~83 decisions/hand, so one full-hand rollout for a
  single (world, candidate) pair alone cost ~390ms — already the entire per-decision budget);
  strategy fusion accepted, not solved; time-boxing checked between worlds, between candidates,
  and inside a rollout's own step loop.
- **Pool isolation (`app/table.py`).** A dedicated `_shared_search_bot_pool()`
  (`ProcessPoolExecutor(max_workers=2)`) existed so a 300–800ms `T3` job never head-of-line-blocked
  `T1`/`T2` jobs from unrelated tables sharing the default pool. Removed along with `SearchBot`;
  every tier now shares `_shared_bot_pool()` again.

**Why removed, not re-tuned.** Two real debugging rounds in this same pass (2026-09-27, alongside
the `ORACLE` redesign, see `04-bots.md §10`) found and fixed three genuine bugs — a fixed
candidate-iteration order that, combined with deadline pressure, systematically biased search
toward low action ids; a `max()` tie-break that silently always picked the lowest action id among
ties (confirmed common: 20/40 sampled real decisions had tied candidates); and a `value_estimate`
with no ukeire term at all, giving ties nothing to break on meaningfully. All three real, all
three fixed, all three correctly diagnosed. The final arena validation after all three fixes (15
duplicate sets, paired-duplicate methodology, `04-bots.md §8`) still showed `SearchBot`
decisively worse than `FaanBot` — paired difference −13.156 pts/game, 95% CI [−25.581, −0.730]
(excludes zero, in `FaanBot`'s favor), `tenpai_at_draw_rate` 6.35% vs `FaanBot`'s 51.85% — the
core symptom essentially unmoved from the pre-fix run.

That result, plus the domain literature, points at a structural ceiling rather than an
implementation gap: `SearchBot` and the original rollout-based `OracleBot` (`04-bots.md §10`)
shared the identical rollout machinery — every candidate root action evaluated by rolling forward
with the same static `FaanBot` heuristic as both the acting policy and the implicit leaf
evaluator. A noisy, few-sample value estimate built entirely out of a fixed heuristic's own
judgment can't reliably beat that same heuristic acting directly; it can only add variance around
it. This is a known, named failure mode for determinized/"perfect information Monte Carlo" (PIMC)
search in hidden-information games — *strategy fusion* (planning a different continuation per
sampled world, which a real player can't do across their own single hidden hand) and
*non-locality* (a subtree's true value depending on the opponent's real strategy, not just what a
rollout policy does in it) are severe enough in comparable games that dedicated algorithms exist
specifically to fix them (e.g. Cazenave & Ventos's αμ search for Bridge,
[arXiv:1911.07960](https://arxiv.org/abs/1911.07960)) rather than a better heuristic bolted onto
the same PIMC loop. The mahjong paper this project already cites for strategy fusion,
[arXiv:1904.07491](https://arxiv.org/abs/1904.07491) (Kurita & Hoki), doesn't use naive
determinized-rollout MCTS either — it builds an MDP abstraction specifically to make search
tractable under imperfect information. And the two strongest published mahjong AIs this project's
own `06-ml.md` references — Suphx ([arXiv:2003.13590](https://arxiv.org/abs/2003.13590)) and
Mortal — are both learned value/policy-function approaches, not heuristic-rollout search, which is
consistent with PIMC's known dependence on rollout/evaluation quality rather than coincidental.

**Needs before reviving this**, in rough order of realism:

1. **A rollout leaf evaluator meaningfully better than a shallow rollout of the same heuristic
   used as the policy** — realistically a learned value function, i.e. T4 (see "Self-play PPO"
   below), which is itself blocked on a compute budget, a training corpus, and a success metric,
   none of which exist yet. This is the load-bearing requirement; the other two items are
   secondary without it.
2. **Real information-set MCTS instead of the determinized simplification** — solves strategy
   fusion/non-locality properly rather than accepting them. Real, undone design work: needs a way
   to search over claim-window decisions too (reconstructing a legal `ClaimWindow` from
   information a `SeatView` doesn't carry), not a parameter change to the existing algorithm.
3. **Materially more rollout budget** — arithmetically incompatible with the measured
   ~4.7ms/decision × ~83 decisions/hand economics at this project's target concurrency (200
   concurrent tables × 3 bot seats, `04-bots.md §3`) unless that concurrency target or the
   deploy hardware budget changes; this alone doesn't fix the ceiling above even if it were
   affordable, since more samples of the same noisy heuristic-driven estimate narrows variance,
   not bias.

Re-read `04-bots.md §6` in full before reviving — it has the compact version of this same
argument plus pointers to what changed around it since.

### Bot personas

Provenance: `04-bots.md` §7, paragraph following the difficulty table (pre-audit); the Expert row
that referenced this tier is also cut, see above.

Give each bot a **persona** — a name, an avatar, a play-style bias (aggressive / defensive /
flush-lover) and a think-time distribution. A bot that reliably chases full flushes is more
memorable than one that's marginally more optimal.

The play-style bias is the same `FaanBot` weight-profile mechanism `06-ml.md` §6.6 wants for
training-opponent variety — build it once, serve both.

**Play-style bias half: built (2026-09-28), for the training-variety use case.**
`bots/faanbot.py`'s `WeightProfile`/`BASELINE`/`AGGRESSIVE`/`DEFENSIVE`/`FLUSH_CHASING`, registered
in `bots/arena.py`'s `BOT_REGISTRY` as `FaanBotAggressive`/`FaanBotDefensive`/
`FaanBotFlushChasing` — exactly the "build it once, serve both" mechanism this paragraph
anticipated. What's still not done, and still genuinely this section's own scope, not §6.6's: a
**name** for a persona (vs. a bare bot-tier string), an **avatar**, and a **think-time
distribution** per persona (docs/04-bots.md §1's humanising delay is currently uniform per
decision regardless of tier or profile) — none of that matters for a training-data generator, all
of it matters for a difficulty-picker-facing persona. Also still open: no live-table selection
path (`PracticeSetupDialog.svelte`/`POST /tables`'s `bot_tiers`) offers these profiles the way
`04-bots.md §7`'s Easy/Normal/Impossible picker offers `T1`/`T2`/`ORACLE` — a weight profile isn't
a difficulty level, so it isn't obvious it belongs in that picker at all without a real product
decision, not just wiring.

| Level | How |
| --- | --- |
| Expert | T3 with search budget |

### Tier 2: full ruleset-aware bots — CLOSED

Provenance: `04-bots.md` §9 (added 2026-09-25). Tier 1 (`min_faan` reaching `FaanBot` via a new
`SeatView.ruleset` field) and all of Tier 2 below — `hand_sets`, `faan_overrides`, and
`wall_reserve` (the last item, closed 2026-09-26) — are done. `score_table` and `game_length`
turned out not to be bot gaps at all — see their rows below. This section is kept as the
historical record of what was deferred and why, per this doc's own header note ("nothing here is
rejected on merit... parked so the intent survives"); it is not live work.

| Setting | Needs | Why it's Tier 2, not Tier 1 |
| --- | --- | --- |
| ~~`hand_sets` (e.g. NEW_18 off under `hk_strict`)~~ **closed** | `mahjong_core/shanten.py`'s `shanten()`/`ukeire()` gated on `HandSet.NEW_18 in hand_sets`, threaded from `view.ruleset.hand_sets` through both `EfficiencyBot` and `FaanBot` — see `04-bots.md` §9 for the full writeup | Reached into the pure, `MahjongRepository`-oracle-validated engine core (§3) — the highest blast radius of anything in this list, and a regression here would have been a correctness bug (illegal-pattern chasing), not a tuning miss. No re-tuning needed: the new `hand_sets` param defaults to every hand_set, so oracle comparisons and every pre-existing caller are unaffected |
| ~~`faan_overrides`~~ **closed** | `bots/valuation.py`'s fixed `ROUTE_FAAN` dict now goes through `route_faan_for(view.ruleset.faan_overrides)`, a route-name → `scoring/patterns.py` Chinese-pattern-name lookup, threaded through `FaanBot`'s three `estimate_best_faan`/`pattern_optionality` call sites — see `04-bots.md` §9 for the full writeup and the arena regression numbers | Needed the route-name → pattern-name mapping this row anticipated; every changed override value would invalidate T2's shipped weights the same way, but the *default* case (empty `faan_overrides`, every shipped preset) is required to stay byte-identical, so no re-tune was needed to close this row — only a regression check (§9's arena run) that the threading itself didn't perturb anything |
| ~~`score_table`~~ **not a bot gap** | N/A | Investigated during the `faan_overrides` item: `mahjong_core/scoring/payout.py`'s `points()` already takes `ruleset` directly and reads `ruleset.score_table`, and has zero references anywhere in `bots/`. It's a faan→**points** payout conversion, never consulted for T2's faan-based discard ranking — this row was only ever combined with `faan_overrides` because both are `RuleSet` scoring fields, not because any bot logic hardcoded it |
| ~~`wall_reserve`~~ **closed** | `bots/faanbot.py`'s fixed `_LATE_TURN=12`/turn-6 constants replaced by `_turn_breakpoints(ruleset)`, scaling `(6, 12)` off the new `mahjong_core.wall.max_turns_per_seat(ruleset)` relative to its value at the default ruleset (`_REFERENCE_MAX_TURN = 22`) — see `04-bots.md` §9 for the calibration arithmetic and the arena regression numbers | Re-deriving the breakpoints as a fraction of the ruleset's actual turn budget would invalidate the shipped `_weights_for_turn` tuning (§4/§8) the same way `faan_overrides` could have, *unless* the fractions are calibrated to reproduce the old fixed `(6, 12)` exactly at the default ruleset — which they are, by construction, so (like `faan_overrides`) closing this needed only a regression check, not a re-tune |
| ~~`game_length`~~ **not a bot gap** | N/A | Checked via `find_referencing_symbols` during the `wall_reserve` item: `GameLength`/`game_length` has zero references anywhere in `bots/` — it's read only by `mahjong_core/engine.py`'s `start_next_hand` (`_ALLOWED_ROUNDS`), which decides how many *hands* make up a match (4/8/16 for EAST_ONLY/EAST_SOUTH/FULL). `bots/faanbot.py`'s turn-based weights key off discard count *within the current hand*, a different axis entirely — this row was only ever combined with `wall_reserve` because both are `RuleSet` "flow" fields, not because any bot logic hardcoded it |

## From 05-roadmap.md and 06-ml.md

### Deferred from 05-roadmap.md and 06-ml.md

Cut during the post-audit fix pass (D10, D11, and the doc-8/12 directive to trim `06-ml.md` down
to the two things worth doing now). Original sources noted per item.

### Pixi golden-PNG screenshot tests

Provenance: `05-roadmap.md` §3, Client testing row (pre-audit).

Cut because D10 removed PixiJS entirely — the table is DOM/CSS, so there is no `<canvas>` scene
to screenshot-test. Also worth remembering if a canvas renderer ever comes back: golden-PNG scene
tests are notoriously flaky across GPU/driver/font differences regardless of which renderer
produced the canvas, so re-adopting this pattern later needs a flakiness budget, not just a
revived test file.

### 3D / 2.5D table rendering

Provenance: `05-roadmap.md` §5, open question #6 (pre-audit): "A genuinely 3D table changes the
asset pipeline; decide now."

Cut, not merely deferred as a live "decide later" question — D10 settled rendering as DOM/CSS.
A 3D/2.5D asset pipeline is out of scope for this project, full stop. Recorded here only because
the question and its framing existed in the doc and the audit wants cuts to leave a trail.

### Early bot-vs-bot game recording as training data

Provenance: `06-ml.md` §1 (pre-audit): "Start recording now — every bot-vs-bot game from M1
onward is training data later."

Cut as pointless rather than merely early: M1's only bots are `RandomBot`s, the
behaviour-cloning prior needs to be `FaanBot` (`06-ml.md` §4/§5), and the engine's pure +
seeded design means regenerating self-play data on demand is free. `GameRecord` persistence
itself is *not* cut — it still happens from M1 (`06-ml.md` §2) — only the "this is training data,
starting now" framing is.

### Human game records as training data

Provenance: `06-ml.md` §6.6 (2026-09-28 training-plan pass).

Persisted `GameRecord`s from live human tables replay through the pure engine to the full
`GameState`, so every hidden hand is recoverable — each human game is **exactly labelled phase-1
data** (opponent tenpai/waits) drawn from the real target distribution, which bot variants only
approximate. The strongest available fix for phase 1's opponent-distribution shift.

Deferred because:

- no live human traffic yet — the corpus would be too small to matter
- only records matching the current `ENGINE_VERSION` replay (`06-ml.md` §2's policy); a corpus
  accumulated across engine bumps is mostly unusable unless replay is pinned to old engine builds
- using players' games for training needs a disclosure/consent line in the product first

Revive when live play has produced a meaningful volume of same-`engine_version` records. Mix into
phase 1 training alongside bot self-play, and keep a human-only held-out split as the evaluation
set for §6.6's generalisation check.

### `SeatView` input-boundary writeup

Provenance: `06-ml.md` §2 (pre-audit), "Input boundary."

```
GameState ──seat_view(state,seat)──► SeatView ──► bot ──► Intent
                                 │
                                 └──► (day 2) encode() ──► tensor ──► policy
```

The encoder takes `SeatView`, never `GameState`, so a network trained this way is structurally
un-cheatable. The rule to hold in M3: `seat_view()` is the only path to seat-visible state — no
shortcuts for bots, ever. Cut from the trimmed `06-ml.md` because it mostly restates
`04-bots.md` §1's existing plan rather than adding new ML-specific work; revive alongside the
day-2 encoder.

**Update (2026-09-26):** `SeatView` already carries `ruleset: RuleSet` (`app/views.py`, added for
`04-bots.md` §9's bot ruleset-awareness work) — a day-2 encoder built on this diagram gets it for
free. See "Feature-plane encoding" below for why that field needs to actually reach the tensor,
not just ride along on the struct.

### Shared feature functions (shanten / ukeire / safety as pure `SeatView` functions) — done, not deferred

Provenance: `06-ml.md` §4 (pre-audit), "Shared feature functions." **Correction (2026-09-26,
ml-readiness scoping pass):** this entry was stale. The work it describes is already built, not
open — kept here per this doc's own header rule ("nothing here is rejected on merit... parked so
the intent survives"), not because it's still pending.

T1/T2 need shanten, ukeire, safe-tile inference, and faan-reachability regardless (`04-bots.md`).
The ask was to put them in `mahjong_core`/`bots` as pure functions of a `SeatView`, not buried
inside bot classes, so a day-2 encoder can call the same functions — and that's what exists:
`server/bots/features.py` exports `own_hand34`/`seen34`/`is_closed`/`is_terminal_or_honor`,
`server/bots/safety.py` exports `no_chance`/`is_genbutsu`/`wall_pressure_multiplier`/
`deal_in_probability`/`expected_cost`/`tile_risk`/`opponent_threat_level`, and
`server/bots/valuation.py` exports `route_faan_for`/`reachable_routes`/`estimate_best_faan`/
`pattern_optionality` — all pure functions of a `SeatView` (or the 34-count arrays derived from
one), confirmed directly against each module's symbols. A day-2 feature-plane encoder can call all
of this today. What's still actually deferred is the encoder itself — see "Feature-plane
encoding" below, and its ruleset-as-input requirement.

### `server/ml/` package skeleton (2026-09-26)

`server/ml/` now exists (`__init__.py`, `train.py`, `configs/bc.yaml`) as an empty,
import-guarded skeleton — enough that the `ml` extra (`pyproject.toml`), the Dockerfile's `ml`
stage, and `docker-compose.yml`'s `trainer`/`arena` services resolve to a real package instead of
a nonexistent module (see `docs/06-ml.md §3`, `docs/07-infra.md §3`/§4). `python -m ml.train
--help` works; running it with a real `--config` raises `NotImplementedError` pointing back here.
Nothing below this note — encoding, the PettingZoo AEC wrapper, behaviour cloning, self-play PPO —
is any less deferred because the skeleton exists; none of it does real work yet.

### Feature-plane encoding — built, not deferred

Provenance: `06-ml.md` §4 (pre-audit), closing paragraph.

**Correction (2026-09-28):** this entry was stale. The encoder itself is now built — kept here
per this doc's own header rule ("nothing here is rejected on merit... parked so the intent
survives"), not because it's still pending. What's still actually deferred is everything *around*
the encoder: the network, the PettingZoo AEC wrapper, behaviour cloning, self-play PPO — see those
entries below.

Feature planes over the 34 tile types, thermometer-encoded counts, players in relative seat
order. Day-2 work in the pre-audit doc, unchanged by this pass — still day 2.

**Ruleset must be an explicit input, not assumed fixed (added 2026-09-26, per `04-bots.md` §9).**
This paragraph predates `FaanBot`/`EfficiencyBot` becoming ruleset-aware (`min_faan`, `hand_sets`,
`faan_overrides`, `wall_reserve` all now read from `view.ruleset`) and a table's ruleset being
player-choosable at all (`05-roadmap.md` M6's presets/custom-ruleset feature). The consequence for
this section specifically: the *correct* discard for an identical 13-tile hand now genuinely
depends on the active ruleset — e.g. chasing Seven Pairs is correct under `hk_classic` and wrong
under `hk_strict` for the same shape (`04-bots.md` §9's `hand_sets` fix exists precisely because
this wasn't true of the heuristic bots either, until now). A feature-plane design that encodes
only tile/seat state and omits the ruleset would train a network that either overfits to whichever
ruleset generated its data or, worse, gets self-contradictory labels if training data ever mixes
rulesets (see "Behaviour cloning from `FaanBot`" below). `RuleSet`'s fields split unevenly for
this purpose: `min_faan`/`hand_sets`/`faan_overrides`/`wall_reserve` change what a *correct*
action is and need encoding (e.g. `min_faan`/`wall_reserve` as scalars or thermometer-coded like
the tile counts above, `hand_sets` as a small bitmask, `faan_overrides` is the awkward one —
unbounded `dict[str, int]`, needs a fixed-size encoding scheme, e.g. one slot per registered
pattern in `scoring/patterns.py`'s registry). Fields governing timing/connection/fairness
(`turn_seconds`, `provable_fairness`, etc.) have no bearing on hand-value decisions and shouldn't
be encoded at all — don't pad the input with the whole `RuleSet.to_dict()` uncritically.

**Built (2026-09-28):** `server/ml/encode.py` (`ml`-extra only — numpy isn't a base dependency,
`server/AGENTS.md`). `encode_seat_view(view) -> EncodedSeatView` reads only entitled `SeatView`
fields — `own_hand`, `melds`, `discard_pools`, `concealed_counts` — never `view.hands` (the
`"ORACLE"` tier's omniscient extra, `04-bots.md` §10): a network trained on oracle-only input
wouldn't generalize to the redacted view it's actually served at inference. `hand`/`melds`/
`discards` are `(..., 4, 34)` thermometer planes exactly as specified above (plane `k` lit where a
tile type's count is `> k`, a kong contributing 3 tiles per `mahjong_core.shanten`'s own
convention); every per-seat axis is reordered to relative seats (`_relative_seats`: self, next,
across, previous) so the same absolute seat never has to be looked up twice. `context` adds
turn/dealer/prevailing-wind/own-seat-wind/phase as one-hot blocks — not in the original spec text,
but the tile planes alone can't express whose turn it is or a seat's yakuhai exposure, and both
are already load-bearing for the heuristic bots (`04-bots.md` §5 item 4, §9's `hand_sets`/
`wall_reserve` closure) this encoder exists to eventually replace signals inside.

`encode_ruleset(ruleset) -> np.ndarray` implements the exact scheme this paragraph specifies:
`[min_faan, wall_reserve, *hand_sets bitmask, *effective faan per `PATTERNS` entry]` — the last
block is `ruleset.faan_overrides.get(pattern.name, pattern.faan)` for all 36 registered patterns
in registry order, so the network sees each pattern's real, currently-active faan value rather
than needing to separately learn the override-lookup semantics. Timing/connection/fairness fields
are not encoded, per this paragraph's own instruction. `tests/test_ml_encode.py` pins the
thermometer boundary (0/1/2/3/4 copies), the kong-counts-as-3 convention, relative-seat reordering
under a non-zero seat, the context one-hots, and both ruleset cases (default vs. narrowed
`hand_sets` + a `faan_overrides` entry) — guarded with `pytest.importorskip("numpy")` so it skips
cleanly (not a collection failure) under `make test-server`'s no-`ml`-extra environment, the same
gap `server-ml.yml`'s separate smoke-test workflow already works around (`07-infra.md` §9).

**Fixed (2026-09-29): concealed-kong leak.** `SeatView.melds` carries the full `Meld` for every
seat (only the wire path redacts), so reading it directly encoded the tile type of other seats'
concealed kongs. `server/ml/raw.py` (numpy-free) now owns `visible_meld_counts34` — another
seat's concealed kong is skipped, the observer's own is kept, same rule as `bots/features.py`
`seen34` — and both `encode.py` and `generate_dataset.py` read through it. Datasets generated
before this fix (schema v2) carry the leak and shouldn't be trained on.

Not built: anything that consumes `EncodedSeatView` — the opponent-danger model itself (`06-ml.md`
§6.2), so this is still a pure input-shaping function with no trained weights behind it anywhere.

### PettingZoo AEC environment wrapper

Provenance: `06-ml.md` §6 (pre-audit), "Day-2 work" list.

[PettingZoo AEC](https://pettingzoo.farama.org/api/aec/) wrapper around the pure engine, for
training-loop compatibility with standard RL tooling.

### Behaviour cloning from `FaanBot`

Provenance: `06-ml.md` §6 (pre-audit), "Day-2 work" list.

Blocked on two things beyond just "day 2": `FaanBot` existing (now M4 per D11, not M6), and a
compute budget / target metric being defined somewhere — neither exists in the doc set yet. See
`06-ml.md` §3 for the honest version of this constraint.

**Third thing, added 2026-09-26:** `FaanBot` is now ruleset-conditioned (`04-bots.md` §9), so
"clone `FaanBot`" is underspecified until someone decides which ruleset(s) generate the training
corpus. Cloning from single-ruleset self-play (e.g. `hk_classic` only) is straightforward and
matches this section's original framing. Cloning from a *mix* of rulesets to get a network that
generalizes across tables additionally requires the "Feature-plane encoding" entry above's
ruleset-as-input point — without it, the same hand shape carries contradictory labels across
examples and behaviour cloning has nothing consistent to fit.

**Superseded teacher (2026-09-28):** `06-ml.md` §6.4 now plans to clone `ORACLE`, not `FaanBot` —
`ORACLE` is measurably stronger (+12.1 points/game vs `FaanBot`, `04-bots.md` §10), so cloning it
raises the ceiling instead of capping at `FaanBot`. Cloning from a *mix* of similar-strength
teachers is rejected for the contradictory-labels reason in `06-ml.md` §6.6.

### Self-play PPO + batched inference serving

Provenance: `06-ml.md` §6 (pre-audit), "Day-2 work" list.

Was listed as a casual day-2 bullet alongside behaviour cloning. Realistically thousands of
GPU-hours (see Suphx, arXiv:2003.13590) with no compute budget or success metric defined
anywhere in this doc set — do not schedule this against a milestone until both exist.
**Update (2026-09-28):** `06-ml.md` §6.5 now defines the success metric; the compute budget is
still open, and §7 there measures why local CPU-only RL is marginal. A ≤5 ms single-sample CPU
model (§7 "Serving") would avoid the batched-serving requirement below entirely.

**Execution-model finding (2026-09-26, ml-readiness scoping pass):** batched inference is
architecturally incompatible with `bots/worker.py`'s per-decision `ProcessPoolExecutor` job model
(`00-architecture.md §3`, `04-bots.md §1`) — each worker is an isolated process handling one bot's
decision at a time, with no channel to batch several seats'/tables' forward passes into a single
GPU call. A learned policy fast enough to serve real tables needs a separate long-lived
inference-serving process (model loaded once, requests batched across callers) that `Table`/the
worker pool talk to over IPC or a socket, instead of a `ProcessPoolExecutor` job. **Not designed
or built now** — no model exists yet to serve, and designing a serving protocol before there's a
policy to put behind it would be speculative. **Un-deferring T4 concretely requires:** (a) a
trained policy worth serving (blocked on the compute-budget/target-metric gap above); (b) an
inference-serving process design (batching strategy, IPC/socket shape, how `Table`/`worker.py`
call it instead of submitting a `ProcessPoolExecutor` job) — neither is scoped yet.

## From 07-infra.md

### Deferred from 07-infra.md

Material cut from `docs/07-infra.md` during the D16 audit pass. Feed into
`docs/99-deferred.md` when that file exists.

### KV / Queue / Bus ports

Cut from §1. A Redis-shaped `Protocol` abstraction (`app/infra/ports.py`) for matchmaking,
presence and rate limiting, backed by in-process implementations — written for a Redis that
doesn't exist yet, fronting a single process that doesn't need the indirection. Revisit if/when
stage 2 (multi-node) actually happens; until then this is over-engineering for a one-process
server.

```python
class KV(Protocol):
    async def get(self, k: str) -> bytes | None: ...
    async def set(self, k: str, v: bytes, ttl: int | None = None) -> None: ...

class Queue(Protocol):                       # matchmaking
    async def push(self, q: str, item: bytes) -> None: ...
    async def pop_n(self, q: str, n: int) -> list[bytes]: ...   # atomic

class Bus(Protocol):                         # lobby presence fan-out, never in-table
    async def publish(self, ch: str, msg: bytes) -> None: ...
    def subscribe(self, ch: str) -> AsyncIterator[bytes]: ...
```

In-process matchmaking/presence/rate-limiting can live as plain module-level state or a small
non-`Protocol` class until a second node is actually on the roadmap.

### Multi-node scaling infrastructure

Cut from §2. The router, table→node directory, and `ws://node-N/ws?table=...` routing scheme
described as "stage 2" in `00-architecture.md §7`. There is one process and no `scale` compose
profile; this is a stage-2+ concern and shouldn't be designed against until stage 1 (one
process, hundreds of tables) is actually load-bearing.

## From web/AGENTS.md

### TypeScript 7 as the primary compiler (svelte-check)

Provenance: `web/AGENTS.md` "Commands" section. `typescript` is pinned to `^6.0.3` as the
primary dependency; TS7 is installed only as a secondary aliased package (`@typescript/native`,
`npm:typescript@^7.0.2`) and used exclusively via `svelte-check --tsgo`
(`web/package.json`'s `check`/`check:watch` scripts).

Not a v1 scope cut — a genuine upstream blocker, not a project decision. `svelte-check`'s own
CLI does an unconditional `require('typescript')` at its top level and hard-requires that to
resolve to TS5/6 even in `--tsgo` mode (confirmed against `sveltejs/language-tools#3063`);
TypeScript 7 doesn't yet expose a stable programmatic API for embedding tools — Volar,
svelte-check, Vue, and Astro all hit the same wall. From Microsoft's own TS7 announcement,
quoted in that issue: "tools which embed TypeScript into their own compilers and language
services can only currently rely on TypeScript 6.0 ... We expect this to be a point-in-time
issue." No date attached as of 2026-09. The `svelte-check` maintainer's own stated plan
(2026-08-31): even TS 7.1's "content mapper" support — the next incremental step — "will
currently still require both TypeScript 6 and 7."

**Needs before un-deferring:**
- TypeScript ships a stable programmatic API `svelte-check` (and the rest of the Volar-based
  tooling ecosystem) can embed directly — the actual blocker, owned upstream by the TypeScript
  team, not by us or by Svelte's maintainers.
- `svelte-check` drops the TS6-primary requirement once that API exists.
- Before then, if still relying on `--tsgo` in the meantime: re-check its own open bugs —
  `sveltejs/language-tools#3120` (includes more files than expected under `--tsgo`) and `#3095`
  (crashes on Linux/arm64 CI, not repro'd on macOS — our CI runs `ubuntu-latest`/x86_64, so
  likely not hit, but worth reconfirming before depending on it further). Also found in practice
  (not filed upstream): `$state<T>(...)`/`$derived<T>(...)`'s explicit generic-argument syntax
  type-checks fine under plain `tsc` but errors under `--tsgo` in this project — worked around
  by using `let x: T = $state(...)` annotation style instead of `$state<T>(...)`. Re-check
  whether this is still needed once revisiting this entry.

**When it lands:** drop the `@typescript/native` alias, bump `typescript` straight to whatever
TS7.x is current, remove `--tsgo` from `web/package.json`'s `check`/`check:watch` scripts, and
delete the rationale note in `web/AGENTS.md`.

