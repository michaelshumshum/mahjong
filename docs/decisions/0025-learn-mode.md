# 0025. Learn mode (學): engine-generated puzzles and a guided tutorial

- **Status:** Accepted (in progress)
- **Date:** 2026-10-28

## Context

Solo play is a complete product on its own ([ADR 0003](0003-product-scope.md)), but nothing in the app
teaches the game: the faan guide and hand checker explain scoring, and practice mode drops a
beginner straight into a full game against bots. Learn mode adds short, deterministic puzzles and a
guided tutorial.

[ADR 0010](0010-client-scope-cuts.md) set the constraint that shapes this: no TypeScript
reimplementation of the engine. Every answer must come from `mahjong_core`.

## Decision

Puzzle content is written once in Python under `server/app/lessons/`. The engine computes each
answer key, and `make proto` emits the result as committed static JSON. The web plays a puzzle
through the existing client reducer and table components on `/learn`, and grades it by looking the
answer up in the precomputed key. Curated puzzles need no new HTTP or WebSocket endpoint. Random
endless puzzles (phase 4) come from a committed pool graded the same way, served by
`GET /lessons/random` in the curated files' shape.

| Option | Verdict |
| --- | --- |
| **A. Generated static lessons** | **chosen**: answers come from the real engine; works offline with no `ApiConnectGate` dependency; proto-check fails CI if an engine change moves an answer |
| B. Server endpoints for every lesson and answer | only for random puzzles (phase 4); hiding answers isn't worth new API surface while stakes are cosmetic |
| C. Tutorial as a real `Table` with a stacked wall | rejected: puts tutorial logic in the table actor and needs a client-chosen seed, which `69c1a9f` removed from `/ws` |
| D. Lessons and answers hand-written in TypeScript | rejected: answers drift from the engine; a second copy of the rules |

### Settled choices

| Question | Answer |
| --- | --- |
| Lobby entry | The third lobby card becomes **學** (Learn). The faan guide moves to a secondary-tier button, next to the language toggle and Settings. |
| Ruleset | Every puzzle uses `hk_classic`. |
| Tutorial and coach marks | Finishing the tutorial sets `coachMarksDone`. Practice mode points first-timers to the tutorial. |
| Package home | `server/app/lessons/` |
| Order | Puzzles (phases 0–2), then the tutorial (phase 3), then random puzzles (phase 4) |
| Random endless puzzles | Wanted, so `lessons/grade.py` is built for runtime from the start: pure, no import-time catalog work, cheap per call |

## Reusable building blocks

### Server

| Building block | Where | Use |
| --- | --- | --- |
| `GameState`/`SeatState`/`Wall` are frozen dataclasses | `mahjong_core/state.py`, `wall.py` | build any position directly (`tests/game_state.py` already does) |
| `new_game` + `reduce` | `state.py`, `engine.py` | positions from `(ruleset, seed, actions)` |
| `legal_actions` | `actions.py` | check scripted and expected actions |
| `shanten`, `ukeire` | `shanten.py` | grade best discard |
| `winning_tile_types` | `bots/labels.py` | find waits (shape only; ignores `min_faan`) |
| `can_win_on` | `engine.py` | exact shape + `min_faan` check for a claimed win |
| `build_scoring_context` + `score_winning_hand` | `actions.py`, `scoring/faan.py` | count faan, melds included |
| `check_hand` / `POST /score` | `hand_check.py`, `app/main.py` | precedent for a stateless evaluator; too narrow for melded hands |
| `seat_view` → `seat_view_wire` | `app/views.py` | a `state_sync` payload redacted for seat 0 |
| `redact_event` | `app/views.py` | wire frames for tutorial steps |
| `turn_frame`/`claim_offer_frame`/`deal_frame`/`event_frame`/`state_sync_frame`, `to_envelope` | `app/frames.py` (pulled out of `Table` in phase 3; also unblocks [ADR 0011](0011-replay-viewer.md)) | the generated `state_sync` snapshots; tutorial frame streams |
| `seen34`, `provably_safe`, `walls_every_run` | `bots/features.py`, `bots/safety.py` | decide which discards are deducibly safe ("Safe-discard deductions"). `tile_risk` is a heuristic and never grades |
| `make proto` generator + proto-check | `tools/gen_protocol.py`, `Makefile`, `.github/workflows/proto-check.yml` | precedent for server-owned data emitted to the web |

### Web

| Building block | Where | Use |
| --- | --- | --- |
| Pure `reduce(state, event)` | `lib/net/reducer.ts` | feed it puzzle snapshots, no socket |
| `viewFromClientState` | `lib/table/live-view.ts` | same view model as `/table` |
| Prop-driven table components | `lib/table/*`, `lib/ui/*` (`YourSeatRegion`, `ClaimDialog`, `FaanBreakdown`, …) | render puzzles with the real table |
| `CoachMarks` + `data-coach` highlight | `lib/ui/CoachMarks.svelte` | tutorial tips |
| Table scene + legal-action derivations | `lib/table/TableScene.svelte`, `lib/table/legal-actions.ts` | render a puzzle position with the real table |
| Tile palette | `lib/ui/TilePalette.svelte` | answer input |
| localStorage conventions | `lib/ui/settings-storage.ts` | progress |
| Paraglide area files + parity spec | `messages/{en,zh-Hant}/`, `lib/i18n/messages.spec.ts` | lesson text |

### Gaps

Closed so far: the position builder and answer keys (`app/lessons/`), public `can_win_on`,
`TableScene`/`legal-actions.ts` and `TilePalette` out of their pages, mined positions (phase 4
below), the generated lesson bundle ([protocol.md §6](../protocol.md)) and the first catalog
(`catalog/basics.py`, eight hand-written puzzles; `catalog/mined.py`, the 60-puzzle shortlist as
the `waits`/`efficiency`/`defence`/`faan` tracks), and the frame builders, pulled out of `Table`
into `app/frames.py` ([architecture.md §5](../architecture.md) "Frame building").

## Design

### Server: `server/app/lessons/`

| Module | Holds |
| --- | --- |
| `model.py` | frozen `Position`, `SeatSetup`, `Puzzle`; `Tutorial` with its steps (`Narrate`, `Expect`, `Auto`, each move a `Move(ActionKind, tiles)`); `PuzzleKind(StrEnum)`, `LessonKind`, `SafeReason`, `Band`, `Track`, `StepKind`, `Highlight`. Wire vocabulary, emitted to TS by `gen_lessons` |
| `position.py` | `build_position(spec) -> GameState`, `from_seed(ruleset, seed, actions)`, `discard_on(state, tile)` (claim positions), `position_from_state(state, seed=, seat=)` (a live `AWAIT_ACTION` state as an explicit spec, rotated so `seat` is seat 0), `position_to_dict`/`position_from_dict` |
| `grade.py` | one key function per kind, `answer_key(puzzle) -> AnswerKey` dispatching over them, `stated_answer_holds`, `key_from_dict` (a key back from the shortlist's JSON); runtime-safe |
| `themes.py` | `puzzle_theme(key, hand) -> PuzzleTheme`, what a puzzle teaches ("Themes" below); pure |
| `catalog/*.py` | content: `basics` (hand-written, one teaching point each), `mined` (the shortlist, one `Track` per kind: `waits`, `efficiency`, `defence`, `faan`) and `tutorials` (`TUTORIALS`); `CATALOG` is `/learn`'s puzzle order |
| `tutorial.py` | `run_tutorial(tutorial) -> TutorialRun`: plays and validates a script, and builds seat 0's frame stream with `app/frames.py` (protocol.md §6 "Tutorials") |
| `payload.py` | one puzzle's lesson JSON (`puzzle_entry`, `snapshot`, `puzzle_payload`), shared by the generator and `GET /lessons/random` |
| `pool.py` | the endless pool (`puzzle_pool.json`): `load_pool`, `pick`, `lesson_payload` |
| `tools/gen_lessons.py` | emits `web/src/lib/learn/generated/index.json`, `<id>.json` per lesson, `lessons.d.ts` |

**Position spec:** tile-code strings, the same codes as `parse_tile`. Fields:

- `hand="123m456p789s1122z"`
- `melds=[("pung", "555s", from_seat=2)]`
- `discards`, `flowers`
- `dealer`, `prevailing`, `turn`
- optional `wall_front`, the stacked next draws, and `wall_back`, the stacked next back draws
  (kong and flower replacements come off the back of the same wall)

A position can instead be `FromSeed(seed, actions)`, pinned to `ENGINE_VERSION`.

**`build_position` must:**

- assign physical tile ids across all seats, sharing `hand_check`'s logic; a fifth copy fails;
- fill the rest of the wall: `wall_front` first, then the remaining tiles shuffled by the lesson
  seed, then `wall_back` reversed, so its first tile is the first back draw;
- set `total_discards`;
- set `hand_seed = derive_hand_seed(lesson_seed, 1)`;
- validate hand sizes: 13 − 3·melds, +1 for the seat that has just drawn.

**Claim positions:** never build a `ClaimWindow` by hand. Reduce a `Discard` from the state just
before it, so the engine opens the window.

**Generated puzzle payload:**

```json
{"id": "eff-01", "kind": "best_discard", "engine_version": "…",
 "snapshot": { "t": "state_sync", "…": "seat_view_wire(seat_view(state, 0))" },
 "key": { "correct": ["…"], "options": { "<choice>": { "…": "numbers for feedback" } } }}
```

### Text

The server holds structure and answers only. All prose lives in `messages/{en,zh-Hant}/learn.json`
as `learn_*` and `lesson_<text>_title|prompt|explain` keys, with numbers from the key interpolated.
`text` is a stem per hand-written lesson, and per kind for mined ones, which share templated prose
([frontend.md §9](../frontend.md) "Lesson text"). A tutorial has `lesson_<text>_title` and one
`lesson_<text>_<step>` per `narrate` tip and `expect` hint. A spec asserts every generated lesson
has its keys.

### Puzzle kinds

| Kind | Engine truth | Graded |
| --- | --- | --- |
| `winning_tiles` | for each of the 34 types: does it complete the hand, its faan, does it clear `min_faan` (`can_win_on`); both discard and self-draw | multi-select must equal the waits that clear the minimum. Feedback names waits that complete the hand but score too low |
| `best_discard` | per discard: shanten after, then `ukeire` over what seat 0 can see only | lowest shanten, then most tiles accepted; ties all count |
| `count_faan` | `score_winning_hand` + `points()` | number entry; feedback shows `FaanBreakdown` |
| `safe_discard` | `can_win_on` against the real hidden hands, plus which tiles are deducible from seat 0's view ("Safe-discard deductions"); the author states the accepted set and a reason, and both are checked | in the accepted set, which is every deducible tile. A tile that is safe but can't be deduced gets "safe this time, but you couldn't know" |

#### Safe-discard deductions

`grade._reasons` separates what seat 0 can see from what counts as a deduction. Only these do:

| Reason | Holds when | Rules out |
| --- | --- | --- |
| `all_copies_visible` | every copy visible, and `bots.safety.provably_safe` against every opponent: a suited tile also needs every run walled, an orphan (honour or 1/9) needs every opponent melded or another orphan type dead | every wait: nobody can win on it |
| `no_chance` | suited, every run through it walled by a tile with every copy visible (`walls_every_run`) | run waits only; a pair or pung wait can still take it, and the explanation says so |

| Not a deduction | Why |
| --- | --- |
| every copy of a suited tile visible, a run still open | rules out only waits that hold a copy; 45m waits on 3m/6m holding neither. The first mined defence shortlist accepted such tiles, and several dealt in |
| a dead honour or terminal with Thirteen Orphans still open | the single wait holds no copy of its tile |
| genbutsu (in every opponent's pool) | HK has no furiten: a player can win on a tile they discarded ([bots.md §5](../bots.md) item 1). Removed from `SafeReason` |

`safe_discard` (the key) requires the stated `accepted` set to be exactly the hand tiles with a
deduction, none dealing in, all sharing the stated `reason`. Grading a deducible tile as "you
couldn't know" would contradict the lesson, and one stated reason keeps the explanation (one
stem per reason) true for every accepted tile. A suited tile with every copy visible always has
both reasons, so `all_copies_visible` is the stronger statement and is stated when every accepted
tile has it. The answer panel still lists each tile's own reasons.
| `claim` (later) | shanten/ukeire after the best follow-up discard, plus value vs `min_faan` | author-stated, engine-checked |

### Guided tutorial vs one-shot puzzle

| | Puzzle | Tutorial |
| --- | --- | --- |
| Source | one position | position + stacked wall + a full script for all four seats |
| Steps | one question | `narrate` (tip + highlight target), `expect` (seat 0 must take a given action), `auto` (opponents play) |
| Payload | `state_sync` + answer key | seat-0 redacted frames per step, with a `state_sync` at each `expect` |
| Client | `PuzzleBoard` + `AnswerPanel` | `LessonPlayer`: a `$state<ClientGameState>` stepped by `reduce`, no socket |

Basics tutorial (`basics-tutorial`): draw/discard → pung → chow → kong → self-draw win and the
hand-end result, 8 `expect` steps. The script runs through `reduce()` at generation time, so an
illegal script fails `make proto`.

| Question | Answer |
| --- | --- |
| Flowers | kept out of every scripted draw, not turned off: `LESSON_RULESET` is pinned with flowers on. Every draw must come off the stacked `wall_front`/`wall_back`, and any flower drawn fails generation |
| A script's moves | `Move(ActionKind, tiles)` by tile codes, resolved against `legal_actions` (a claim's own tiles, as `claim_offer` lists them); tile and window ids would tie content to id assignment |
| Who `expect`s | always seat 0, so an `Expect` has no seat; one where seat 0 has no decision fails, as does an `Auto` for seat 0 |
| Other seats' claim offers | none unplanned: an offer the script doesn't answer leaves its window open, so the next scripted move is illegal and generation fails. Opponents hold scattered suited tiles and throw honours nobody pairs |
| Deadlines | 0 where a frame type needs one (`turn`, `claim_offer`, `hand_end`): the player keeps no clock |
| Where it lists | the index carries the tutorial (`lesson_kind: "tutorial"`, first); `/learn` shows it as the basics track's "Start here" card |

### Web

| Item | Detail |
| --- | --- |
| Lobby | 3rd card becomes **學** (Learn) and links to `/learn`. The faan guide becomes a `btn-secondary` beside the language toggle and Settings |
| Refactors | `lib/table/TableScene.svelte` and `lib/table/legal-actions.ts` out of the table page; `lib/ui/TilePalette.svelte` out of `HandChecker` |
| Routes | `/learn` (tracks, lesson cards, solved state) and `/learn/[id]`. Both skip `ApiConnectGate`. Phase 4 adds `/learn/endless`, which doesn't |
| Modules (`lib/learn/`) | `lessons.ts` (index, lazy import per lesson), `grade.ts` (lookup only), `lesson-player.svelte.ts`, `PuzzleBoard.svelte`, `AnswerPanel.svelte`, `TutorialCoach.svelte`, `types.ts` |
| Persistence | `mahjong:learnProgress:v1`: `{ [id]: { solved, attempts, solvedAt?, step? } }`, local only ([ADR 0001](0001-guest-only-identity.md)); unknown ids dropped |
| Other entry points | faan guide links to a faan puzzle; practice points first-timers to the tutorial; the tutorial ends with "Practice vs Easy bots" |

### Random endless puzzles (phase 4)

| Piece | Detail |
| --- | --- |
| `tools/mine_puzzles.py` | mines candidates of all four kinds from seeded Expert (`T4`) self-play and rates each one's difficulty with the bot tiers (below) |
| `app/lessons/mined_puzzles.json` | the committed shortlist the miner curates: up to 15 per kind, spread across difficulty bands |
| `app/lessons/puzzle_pool.json` | the committed endless pool the miner writes (`--pool`): 100 per kind and band, 1,200 puzzles, keys stored |
| `GET /lessons/random?kind=&band=&exclude=` | a random pooled puzzle as a curated lesson file, rate-limited per IP ([protocol.md §10](../protocol.md)) |
| Grading | the answer key is returned with the puzzle; the client grades it the same way as curated ones |
| Shared with | the ADR 0010 `hint` request can reuse `grade.py` |

| Question | Decision | Why |
| --- | --- | --- |
| What the server serves from | a committed pool, `app/lessons/puzzle_pool.json` (~1.5 MB), cut from the full mined corpus by `tools.mine_puzzles --from <corpus.jsonl> --pool …` | the corpus is 256 MB of JSONL and isn't in the repo. Mining on demand means an Expert game per puzzle, and a T4 seat loads numpy and the policy into the API process. 1,200 puzzles is a few hundred per kind, enough that a recent-id skip rarely runs dry, at ~1.1 kB each |
| Pool size | 100 per kind and band (`POOL_PER_BAND`) | even bands, so the band picker always finds puzzles; `winning_tiles` has only 380 advanced candidates in the corpus. Load is ~0.4 s and ~18 MB on first request, well inside the 1.9 GiB prod box |
| Which puzzles | per band, the shortlist's own order: round-robin over best shanten / reason / wait count / faan total, `best_discard` only where `T4` agreed; one puzzle per source game per kind (`varied`, as the shortlist) | one rule for both cuts (`_by_band`), so the pool is the shortlist continued; many of the curated tracks' picks reappear, which is harmless. No cap across kinds: endless plays one kind at a time, so a game recurring in another kind is never met back to back, and a cross-kind cap would only thin `winning_tiles` advanced (380 candidates) |
| Grading cost | keys stored in the pool and served as is; `tests/test_lessons_pool.py` regrades all 1,200 against `answer_key()` (~1.5 s) | a `best_discard` key is ~470 shanten evaluations (bots.md §3), ~1.5 ms warm, and safe-discard keys reduce one discard per hand tile. Stored keys make a request ~1 ms whatever the kind, and the regrade test turns any engine change that moves a key into a failing test, as the shortlist's does |
| Reproducibility | a pool record keeps its explicit `Position`, its `source` (`game_seed`, `decision`, `seat`) as its id, and the pool file the corpus's `engine_version`, `miner_tier` and seed range. `pool()` is deterministic for a corpus, and the corpus for its seeds | an engine change that fails the regrade test means re-mining (~1 h on the laptop) and rewriting both files |
| Response shape | exactly a generated `<id>.json` puzzle, built by the generator's own `app/lessons/payload.py` | the web plays it through the same page and types it with the generated `Lesson`, so no new wire type and no second builder |
| Text and title | each record becomes its `Puzzle` through `catalog/mined.py`'s `mined_puzzles`, so `text` is the mined track's stem and `theme` is `puzzle_theme` on its key, titled by `THEME_LABEL` like a mined lesson. The pool stores each `theme` too, and `test_lessons_pool.py` checks it against the one read at load | endless prose and titles follow the mined catalog, with no second copy; a stored theme makes a change in theme rules show up as a pool diff |
| Don't repeat | `exclude=` with the client's last 20 ids (server cap 50); when every candidate is excluded, any is returned | stateless on the server; the alternative, a client re-request on a repeat, spends the rate limit |
| Rate limit | 60 per 60 s per IP (`LESSON_RATE_LIMIT`), the `POST /tables` limiter | a puzzle takes seconds; a sustained one a second is a script |
| Web | `/learn/endless?kind=&band=` plays the fetched lesson through the curated puzzle page (`routes/learn/_components/PuzzlePage.svelte`, moved up from `[id]/`), with snippets for the streak, Skip and "Next puzzle", and an `onGraded` hook in place of learn progress | one page for both; endless ids are positional per pool and must never land in `learnProgress` |
| Gate | `/learn/endless` stays behind `ApiConnectGate`; the rest of `/learn` still skips it | it can't render anything without the API, unlike the bundled lessons |
| Score | per kind, local only: streak of no-miss solves (a wrong or partial answer or a skip ends it), best streak, solves | honour-system like the curated progress; per kind, since a defence streak and a faan streak aren't comparable |

### Mined puzzles

`uv run python -m tools.mine_puzzles --games N --seed S --workers W --out all.jsonl --shortlist
app/lessons/mined_puzzles.json`, from `server/`. `--from all.jsonl` reads an earlier run's
candidates instead of mining, and `--pool app/lessons/puzzle_pool.json` writes the endless pool;
both cuts are deterministic for a corpus.

**Source.** Four `T4` seats play `LESSON_RULESET` games, seeds `S … S+N−1`, one game per pool task.
Expert rather than `FaanBot`, so the positions are ones strong play reaches. Without loadable
`learned.npz` the tool says so and plays `T2`, rating without `T4`. Every seat's decisions are
scanned, each rotated into a seat-0 position by `position_from_state`: seat winds follow the
dealer, so a rotation grades the same, and one game yields puzzles from four hands. States a
`Position` can't carry (a kong-replacement or last-tile draw, a complete hand just claimed into)
are skipped. Each candidate is rebuilt from its spec and graded there, on the position a player
would see. A record keeps its explicit `Position`, never `FromSeed`, so it survives changes to
dealing; `source` (`game_seed`, `decision` = step index, `seat`) replays the live game, and
`engine_version` pins the rules it was graded under.

**Filters.**

| Kind | Kept when | Why |
| --- | --- | --- |
| `best_discard` | best shanten after the discard ≤ 2; 1–2 correct tiles; a naive pick (the most isolated tile: fewest extra copies and same-suit neighbours within two ranks, honours then terminals first, blind to shanten) is not correct; and the answer accepts ≥ 4 more live tiles than the best wrong discard at the same shanten | far from tenpai there is rarely one answer; ties of 3+ stop being about a shape; a pick the naive heuristic finds teaches nothing; a lead under one tile type's four copies is noise |
| `safe_discard` | some discard the efficient answer (`best_discard`'s) would make deals in; 1–3 hand tiles have a deduction ("Safe-discard deductions"), none of them deals in, none is an efficient answer, and they share a reason (all-copies-visible preferred, else no-chance); `accepted` = all of them | a real fold: the natural discard loses; a deducible tile that deals in (a no-chance tile into a pair wait) would teach a false rule; a deducible tile that is also efficient makes folding free, so nothing is taught; one shared reason keeps the explanation true; a deduction that clears half the hand isn't one worth asking for |
| `winning_tiles` | at least one live winning tile, and ≥ 2 of them, or a wait below `min_faan`, or a dead wait | a single clean wait is a lookup |
| `count_faan` | a self-draw, or a discard win (the record's `discard` is reduced on the rebuilt position, "Claim positions"), scoring ≥ 2 patterns | one pattern is a lookup |

Duplicates (same kind, seat-0 hand and melds, and the same visible tiles; for `winning_tiles` the
same waits, for `count_faan` the same breakdown) keep their first sighting in seed order.

**Difficulty, decision kinds** (`best_discard`, `safe_discard`). Each tier that plays on a plain
`seat_view` answers the rebuilt position from seat 0; `ORACLE` sees every hand, so it is not
asked. Rates per tier:

| Rate | Meaning |
| --- | --- |
| `T0` | correct legal ids / legal ids: the exact rate a uniform-random seat scores |
| `T1`, `T2`, `T4` | 1 or 0: these tiers are greedy, so `compute_action` with any seed returns the same action and sampling N seeds would repeat it N times |
| `T4_policy` | the Expert policy's softmax mass on the correct ids: the rate it would score sampled at temperature 1, computed exactly instead of sampled |

`score` = mean miss rate (1 − rate) over the informative rates: argmax `T4` is left out since
`T4_policy` carries it graded, and on `best_discard` `T1` is left out too, because its rule
(min shanten, then ukeire) is the key's own grading rule.

| Kind | Beginner | Intermediate | Advanced | Reading |
| --- | --- | --- | --- | --- |
| `safe_discard` | < 0.55 | < 0.85 | ≥ 0.85 | about: `T2` and `T4` both right / one misses / both miss |
| `best_discard` | < 0.28 | < 0.32 | ≥ 0.32 | terciles of an 80-game calibration run: after the filters `T2` and `T4` solve nearly every kept puzzle, so the spread comes from the option count (`T0`) and the policy's confidence |

**Difficulty, structural kinds.** No decision to ask a bot about, so a proxy:

| Kind | Points | Beginner | Intermediate | Advanced |
| --- | --- | --- | --- | --- |
| `winning_tiles` | one per live winning tile past the first, +2 for a wait below `min_faan`, +2 for a dead wait | < 2 | < 4 | ≥ 4 |
| `count_faan` | patterns in the breakdown | 2 | 3 | ≥ 4 |

**Shortlist.** Per kind up to 15, round-robin across bands, and within a band round-robin across
best shanten (`best_discard`), reason (`safe_discard`), wait count (`winning_tiles`) or faan total
(`count_faan`). The `best_discard` key is pure efficiency, which a value play under `min_faan` can
beat, so the shortlist keeps a `best_discard` only where `T4` also played a correct answer.
`tests/test_mine_puzzles.py` regrades every shortlisted record and fails when an engine change
moves one.

The walk then skips (`varied`, in the band it is taking from, so band and spread balance hold) a
record whose source game already has one puzzle of its kind or `SHORTLIST_GAME_CAP` = 2 across
all tracks, or the same seat within `SAME_HAND_WINDOW` = 60 decisions in any track.

| Rule | Why |
| --- | --- |
| one per game per kind | the walk is in seed order, so uncapped the first games fill every band: before this cut 28 of the 60 came from seeds 20,000,000 and 20,000,001, and one game gave a track 7 puzzles |
| 2 per game across tracks | 60 puzzles from 6,000 games leaves room for one game per puzzle, but a second puzzle from a game's other seat or a later hand is a different hand and costs nothing; the cap keeps it at a pair |
| same seat within 60 decisions | `decision` counts every seat's actions and claim answers, so a hand runs ~70–120 of them; the near-duplicates found (defence 294/298/302/308, waits 208/213, a wait at 80 with a best discard at 79 and a faan at 85) sat ≤ 15 apart, the same hand a few draws on with the same answer |

| Shortlist | Source games | Most from one game | From the top two games | Same seat within 60 |
| --- | --- | --- | --- | --- |
| before (`44d4590`) | 23 | 15 | 28 | 28 pairs |
| now | 48 | 2 | 4 | 0 |
| pool before / now | 449 / 732 | 61 / 4 | 98 / 8 | 563 / 39 pairs (now only across kinds) |

Shortlist ids are positional, so a re-cut moves them and resets saved progress on the mined
tracks; 24 of the 60 records survived this one, 12 under the same id.

**Current run** (laptop, i7-1265U, 8 workers, ~59 min wall, engine 1.3.0): 6,000 games, seeds
20,000,000–20,005,999; 3,655,016 decisions, 2,993,369 turns scanned; 55,735 candidate positions
skipped as unrepresentable; 460,328 duplicates dropped. Earlier runs, each replacing its
shortlist and pool:

| Run | Why it was replaced |
| --- | --- |
| first | graded `best_discard` with exposed meld tiles regroupable (the bots' whole-hand shanten, [bots.md §3](../bots.md)), which picked wrong answers for melded hands; now `melds=n` |
| second | `safe_discard` counted every copy of a suited tile visible and genbutsu as deductions, and accepted only the first reason's tiles: 103 of the pool's 300 defence puzzles rested on a suited all-copies-visible tile, several such tiles dealt in, and 104 had an accepted tile among the efficient answers. Now "Safe-discard deductions" and the tension filter |

`--from` re-cuts a corpus without regrading or re-filtering it, so a filter change means a full
re-mine. Re-mining also re-rates every kind against the current bot tiers, so two `best_discard`
shortlist entries changed with the defence fix.

| Kind | Kept | Beginner | Intermediate | Advanced |
| --- | --- | --- | --- | --- |
| `best_discard` | 56,586 | 11,444 | 16,615 | 28,527 |
| `safe_discard` | 16,551 | 811 | 4,466 | 11,274 |
| `winning_tiles` | 57,488 | 44,032 | 13,076 | 380 |
| `count_faan` | 30,029 (17,521 discard wins) | 9,325 | 13,944 | 6,760 |

15,574 of the `best_discard` candidates (28%) are ones where `T4` played something else, nearly
all scored advanced; the shortlist leaves them out. `safe_discard` stated reasons: no-chance
12,774, all copies visible 3,777 (1,184 of them honours only); accepted tiles per puzzle 1 /
2 / 3: 10,535 / 4,430 / 1,586. The pool's 300 split 194 all copies visible / 106 no-chance; the
shortlist's 15 are 8 / 7.

### Themes

A mined puzzle's title is its theme ("Two-sided wait", "Half flush, all pungs"), not "Waits 7".
`app/lessons/themes.py`'s `puzzle_theme(key, hand)` reads it off the answer key and seat 0's
concealed hand, nothing else, so it is pure and costs nothing at import: `catalog/mined.py` sets
`Puzzle.theme` from the shortlist's stored key (`key_from_dict`), and `gen_lessons` refuses a
puzzle whose `theme` differs from `puzzle_theme` on the freshly graded key, as it does a wrong
`answer`. Basics keep their hand-written titles (`theme=None`).

`PuzzleTheme` is one closed `StrEnum` (wire vocabulary, emitted to `lessons.d.ts`);
`model.THEMES_BY_KIND` lists each kind's themes in priority order. The classifier takes the first
that holds, and each kind's last one always holds, so every key gets a theme. Counts are the
current 60-puzzle shortlist.

| Kind | Theme, in priority order | Holds when | Now |
| --- | --- | --- | --- |
| `winning_tiles` | `too_cheap` | a wait completes the hand but clears `min_faan` neither way | 2 |
| | `dead_wait` | a winning wait has every copy visible | 3 |
| | `many_sided` | 3+ tile types complete the hand | 5 |
| | `two_sided` / `pair_wait` / `single_wait` / `edge_closed` | every completing type plays only that shape, over every standard split of hand + tile (`wait_shapes`: two-sided, edge 12-3 / 89-7, closed, pung of a pair, pair) | 2 / 1 / 1 / 0 |
| | `mixed_wait` | otherwise (66+68 closed or 666+8 single) | 1 |
| `best_discard` | `wider_wait` | the answer reaches ready and so does a wrong discard, with fewer tiles | 1 |
| | `reach_ready` | the answer reaches ready and nothing else does | 2 |
| | `trim_run` | an answer ends four or more held consecutive ranks (1 of 1234) | 1 |
| | `cut_terminal` | an answer is a suited 1 or 9 | 5 |
| | `keep_two_sided` | a lone answer two from a held tile with a neighbour beyond (2 of 245) | 3 |
| | `cut_floater` | a lone honour, or a lone suited tile with nothing held within two ranks | 2 |
| | `break_pair` | an answer is held twice or more | 1 |
| | `most_tiles` | otherwise | 0 |
| `safe_discard` | `walled_runs` | the stated reason is no-chance | 7 |
| | `dead_honour` | all copies visible, every accepted tile an honour | 1 |
| | `all_visible` | otherwise (all copies visible, a suited tile among them) | 7 |
| `count_faan` | `limit_hand` | a limit pattern | 0 |
| | `full_flush` | 清一色 | 4 |
| | `half_flush_pungs` / `half_flush_honours` / `half_flush` | 混一色 with 對對糊 / with 箭刻, 門風 or 圈風 / alone | 4 / 1 / 1 |
| | `all_pungs` / `all_chows` | 對對糊 / 平糊 | 2 / 2 |
| | `flowers` | 正花 or 一台花 | 1 |
| | `small_faan` | otherwise | 0 |

Why this shape:

- **Priority over a scoring model.** A puzzle often fits two themes (a many-sided wait with one
  dead tile; a 9 that is also the outer tile of 79+6). The first match in a fixed order is
  deterministic and testable, and the order puts what makes the puzzle hard first: a too-cheap
  or dead wait is the trap, the shape comes second.
- **Themes with no puzzle today** (`edge_closed`, `most_tiles`, `limit_hand`, `small_faan`) keep the classifier total for a re-mined shortlist or random
  endless puzzles. The mining filters rule some out (a single clean wait is a lookup; a limit hand
  is one pattern).
- **Titles only.** Prompts and explanations stay per kind (`text`); a theme adds one
  `learn_theme*` message per value, never one per puzzle.
- **Ids unchanged.** Progress is keyed by id, so titling by theme moves nothing.

## Tests

### Server (pytest)

| Test file | Covers |
| --- | --- |
| `test_lessons_position.py` | tile conservation; invariants; fifth copy and bad hand sizes rejected; deterministic |
| `test_lessons_grade.py` | per kind: known waits; a wait below the minimum is excluded; tied discards; safe discard against a known hidden hand; `count_faan` agrees with `check_hand` |
| `test_lessons_catalog.py` | parametrized over every lesson (below) |
| `test_gen_lessons.py` | generator output is deterministic |
| `test_lesson_themes.py` | `wait_shapes` per shape; each theme on a hand-built position; priority where several apply; every mined puzzle's theme equals `puzzle_theme` on the engine's key |
| `test_mine_puzzles.py` | each filter keeps and rejects a hand-built position; difficulty score and bands; the shortlist's per-game caps and same-hand window on hand-built records; one mined game is deterministic and every record regrades; the committed shortlist regrades and is varied |
| `test_lessons_pool.py` | every pooled key equals `answer_key()`; even kind × band coverage, unique ids, one per game per kind, the file is the tool's output; `pick` keeps kind and band and honours `exclude`; pooling one mined game is deterministic and takes one per kind |
| `test_lessons_random.py` | `GET /lessons/random` per kind × band returns a lesson payload shaped like a bundle file; `exclude`; `422` on bad params; the per-IP `429` |
| `test_frames.py` | the pulled-out frame builders match what `Table` sends |
| `test_lessons_tutorial.py` | every tutorial runs to its end phase with valid, densely numbered seat-0 frames and each `expect`'s action in its snapshot's `legal_actions`; an illegal move, an `expect` off seat 0's turn, an `auto` for seat 0, a flower or a draw past the stacked wall, and a wrong end phase are rejected; every step's frames equal a live `Table`'s for the same actions |

For every lesson, `test_lessons_catalog.py` checks:

- the position builds;
- the author's `answer=` equals `answer_key()`;
- for safe discard, the stated reason holds;
- for `FromSeed` positions, `ENGINE_VERSION` matches.

Tutorials are checked in `test_lessons_tutorial.py` instead: every scripted action is legal and
every `expect` step is seat 0's.

### Web and e2e

| Where | Covers |
| --- | --- |
| Vitest | `grade.spec.ts`; `feedback.spec.ts` and `AnswerPanel.svelte.spec.ts` (feedback per kind); `lesson-player.svelte.spec.ts`; `lessons.spec.ts` (message keys); `settings-storage.spec.ts` (progress, endless scores); `legal-actions.spec.ts`; `endless.spec.ts` (the fetch, its errors, recent ids, the streak) |
| Playwright | `routes/learn/learn.e2e.ts`: best discard wrong then right, winning-tile multi-select, faan entry, a safe pick that was only lucky, a discard win's breakdown, progress survives a reload, answering at phone width and by keyboard alone, a zh-Hant smoke, and the tutorial in phase 3. `routes/learn/endless/endless.e2e.ts` (`GET /lessons/random` mocked): band picker links, a right answer counting toward the streak, the next puzzle excluding the last, a miss and a skip ending it, a themed title, a failed and a rate-limited fetch |
| Screenshots | `/learn`, one puzzle, best-discard and safe-discard feedback, and later one tutorial state |

## Phases

### 0. Groundwork (refactors only)

1. `refactor(core): public can_win_on for a claimed win check`
2. `refactor(core): move winning_tile_types into mahjong_core.shanten`
3. `refactor(web): extract TableScene and legal-action derivations from the table page`
4. `refactor(web): extract TilePalette from the hand checker`

### 1. Server lessons and generator

5. `feat(server): lessons package with position builder and validation`
6. `feat(server): answer keys for winning_tiles, best_discard, count_faan`
7. `feat(server): exact safe_discard answer key with stated reasons`
8. `feat(server): generate lesson bundle in make proto and proto-check` (done)
9. `feat(server): first puzzle set and catalog validity tests` (done: two hand-written per kind,
   plus the mined shortlist)

### 2. Web puzzles

10. `feat(web): learn progress storage` (done)
11. `feat(web): 學 lobby card, faan guide as a secondary button` (done)
12. `feat(web): /learn index and puzzle page over TableScene` (done: the simplest input per kind
    behind `AnswerPanel`, a result line and the explanation; `PuzzleBoard` stayed inline in the
    route page)
13. `feat(web): answer panels and feedback per puzzle kind` (done: `feedback.ts` and
    `OptionTable` behind `AnswerPanel`; a lucky safe pick is not solved; discard wins hold the
    last-discard marker, [frontend.md §7](../frontend.md) "Learn")
14. `test(web): learn e2e and screenshots` (done: most landed with 12 and 13; this added answering
    at phone width and by keyboard alone, a zh-Hant smoke, and the safe-discard screenshot)

### 3. Guided tutorial

15. `refactor(server): pure turn, claim_offer and deal frame builders shared with Table` (done:
    `app/frames.py`, every outbound payload; `tests/test_frames.py` pins `Table`'s streams)
16. `feat(server): tutorial scripts with stacked wall and expect steps` (done: `Tutorial` in
    `model.py`, `tutorial.py`, `Position.wall_back`, the generated tutorial shape, protocol.md §6
    "Tutorials"; the basics content landed here too, so 18 is folded in. `/learn` skips the
    tutorial entry until 17)
17. `feat(web): lesson player and tutorial coach` (done: `LessonPlayer`, `TutorialCoach` on a
    `CoachCard` shared with the practice coach marks, `TableScene`'s `coach` outline, the
    tutorial leading `/learn`'s basics track; `PuzzleBoard` became the route's
    `_components/PuzzlePage.svelte` beside `TutorialPage.svelte`, [frontend.md §7](../frontend.md)
    "Learn")
18. `feat(server): basics tutorial content` (done with 16)
19. `feat(web): tutorial completion sets coach marks and links to easy practice` (done: the last
    step's "Practice vs Easy bots" goes through `createPracticeTable`, now the practice dialog's
    and "Play again"'s create path too; the practice coach marks link first-timers to the
    tutorial)

Phase 3 is complete.

### 4. Random endless puzzles

20. `feat(server): mine puzzles from expert self-play with bot difficulty` (done, with `position_from_state` and the first shortlist; "Mined puzzles")
21. `feat(server): GET /lessons/random` (done: the pool, `app/lessons/payload.py` shared with the
    generator, the endpoint; "Random endless puzzles")
22. `feat(web): endless mode on /learn` (done: `/learn/endless` over the shared `PuzzlePage`,
    the index's band picker and per-kind cards, a per-kind streak in `mahjong:learnEndless:v1`;
    [frontend.md §7](../frontend.md) "Learn")

Phase 4 is complete.

## Docs to update alongside

| Doc | Change |
| --- | --- |
| `frontend.md §7` | routes, a "Learn" subsection, the lobby (學 card, faan guide button), `TableScene` |
| `frontend.md §6` | persistence row |
| `frontend.md §9` | `learn.json` |
| `infra.md §1, §2, §9` | file map; `make proto`; proto-check |
| `protocol.md §6` | generated lesson bundle; `GET /lessons/random` in phase 4 |
| `architecture.md §2` | `app/lessons/` |
| `testing.md §1` | lessons strategy row |
| `bots.md §5` | puzzles grade safety exactly, never with `tile_risk` |
| ADRs 0010, 0011 | cross-links |

## Consequences and risks

| Risk | Notes |
| --- | --- |
| Answers ship in the bundle | fine for cosmetic stakes; revisit if puzzles ever feed a leaderboard. Endless puzzles return their key the same way, so the endless streak is honour-system too |
| Endless pool goes stale | an engine change that moves a key fails `test_lessons_pool.py`; fixing it means re-mining the corpus (~1 h, not committed) and rewriting the pool and shortlist together |
| Pool cost | ~1.5 MB in the repo and the image, ~18 MB and ~0.4 s on the first request; per request ~1 ms of event-loop time, bounded by the 60/min per-IP limit |
| Endless needs the API | unlike curated lessons, `/learn/endless` sits behind `ApiConnectGate` and says so when a fetch fails or is rate-limited |
| Coupling to `ENGINE_VERSION` and the ruleset | a scoring change moves `count_faan` answers. The catalog test and proto-check diff make that loud, but the prose explanations need re-checking by hand |
| `FromSeed` positions | break on any change to dealing; prefer explicit positions |
| `safe_discard` | safe is not the same as deducibly safe; content needs care |
| `TableScene` extraction | touches the most complex page; keep it a pure move, verified by screenshots and the table e2e |
| Translation | every lesson needs en and zh-Hant text, enforced by the parity spec |
