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
endless puzzles (phase 4) use the same grading module behind `GET /lessons/random`.

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
| `turn`/`claim_offer`/`deal` frame builders | `app/table.py` (methods on `Table`) | not reusable until pulled out (phase 3; also unblocks [ADR 0011](0011-replay-viewer.md)) |
| `seen34`, `no_chance`, `is_genbutsu` | `bots/features.py`, `bots/safety.py` | explain why a discard is safe. `tile_risk` is a heuristic and never grades |
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
below), and the generated lesson bundle ([protocol.md §6](../protocol.md)). Still open:

1. Frame builders exist only on `Table`.
2. No curated content (`catalog/`).

## Design

### Server: `server/app/lessons/`

| Module | Holds |
| --- | --- |
| `model.py` | frozen `Position`, `SeatSetup`, `Puzzle` (`TutorialStep`, `Lesson` in phase 3); `PuzzleKind(StrEnum)`, `LessonKind`, `SafeReason`, `Band`, `Track`. Wire vocabulary, emitted to TS by `gen_lessons` |
| `position.py` | `build_position(spec) -> GameState`, `from_seed(ruleset, seed, actions)`, `discard_on(state, tile)` (claim positions), `position_from_state(state, seed=, seat=)` (a live `AWAIT_ACTION` state as an explicit spec, rotated so `seat` is seat 0), `position_to_dict`/`position_from_dict` |
| `grade.py` | one key function per kind, `answer_key(puzzle) -> AnswerKey` dispatching over them, `stated_answer_holds`; runtime-safe |
| `catalog/*.py` | content, one module per track: `basics`, `efficiency`, `defence`, `faan` |
| `frames.py` | (phase 3) tutorial frame stream |
| `tools/gen_lessons.py` | emits `web/src/lib/learn/generated/index.json`, `<id>.json` per lesson, `lessons.d.ts` |

**Position spec:** tile-code strings, the same codes as `parse_tile`. Fields:

- `hand="123m456p789s1122z"`
- `melds=[("pung", "555s", from_seat=2)]`
- `discards`, `flowers`
- `dealer`, `prevailing`, `turn`
- optional `wall_front`, the stacked next draws

A position can instead be `FromSeed(seed, actions)`, pinned to `ENGINE_VERSION`.

**`build_position` must:**

- assign physical tile ids across all seats, sharing `hand_check`'s logic; a fifth copy fails;
- fill the rest of the wall: `wall_front` first, then the remaining tiles shuffled by the lesson seed;
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
as `learn_*` and `lesson_<id>_title|prompt|explain` keys, with numbers from the key interpolated.
A spec asserts every generated id has its keys.

### Puzzle kinds

| Kind | Engine truth | Graded |
| --- | --- | --- |
| `winning_tiles` | for each of the 34 types: does it complete the hand, its faan, does it clear `min_faan` (`can_win_on`); both discard and self-draw | multi-select must equal the waits that clear the minimum. Feedback names waits that complete the hand but score too low |
| `best_discard` | per discard: shanten after, then `ukeire` over what seat 0 can see only | lowest shanten, then most tiles accepted; ties all count |
| `count_faan` | `score_winning_hand` + `points()` | number entry; feedback shows `FaanBreakdown` |
| `safe_discard` | `can_win_on` against the real hidden hands, plus the author's accepted set and reason | in the accepted set. A tile that is safe but can't be deduced gets "safe this time, but you couldn't know" |
| `claim` (later) | shanten/ukeire after the best follow-up discard, plus value vs `min_faan` | author-stated, engine-checked |

### Guided tutorial vs one-shot puzzle

| | Puzzle | Tutorial |
| --- | --- | --- |
| Source | one position | position + stacked wall + a full script for all four seats |
| Steps | one question | `narrate` (tip + highlight target), `expect` (seat 0 must take a given action), `auto` (opponents play) |
| Payload | `state_sync` + answer key | seat-0 redacted frames per step, with a `state_sync` at each `expect` |
| Client | `PuzzleBoard` + `AnswerPanel` | `LessonPlayer`: a `$state<ClientGameState>` stepped by `reduce`, no socket |

Basics tutorial: draw/discard → pung → chow → kong → self-draw win. Flowers are off, or kept out of
every scripted draw. The script runs through `reduce()` at generation time, so an illegal script
fails `make proto`.

### Web

| Item | Detail |
| --- | --- |
| Lobby | 3rd card becomes **學** (Learn) and links to `/learn`. The faan guide becomes a `btn-secondary` beside the language toggle and Settings |
| Refactors | `lib/table/TableScene.svelte` and `lib/table/legal-actions.ts` out of the table page; `lib/ui/TilePalette.svelte` out of `HandChecker` |
| Routes | `/learn` (tracks, lesson cards, solved state) and `/learn/[id]`. Both skip `ApiConnectGate` |
| Modules (`lib/learn/`) | `lessons.ts` (index, lazy import per lesson), `grade.ts` (lookup only), `lesson-player.svelte.ts`, `PuzzleBoard.svelte`, `AnswerPanel.svelte`, `TutorialCoach.svelte`, `types.ts` |
| Persistence | `mahjong:learnProgress:v1`: `{ [id]: { solved, attempts, solvedAt?, step? } }`, local only ([ADR 0001](0001-guest-only-identity.md)); unknown ids dropped |
| Other entry points | faan guide links to a faan puzzle; practice points first-timers to the tutorial; the tutorial ends with "Practice vs Easy bots" |

### Random endless puzzles (phase 4)

| Piece | Detail |
| --- | --- |
| `tools/mine_puzzles.py` | mines candidates of all four kinds from seeded Expert (`T4`) self-play and rates each one's difficulty with the bot tiers (below) |
| `app/lessons/mined_puzzles.json` | the committed shortlist the miner curates: up to 15 per kind, spread across difficulty bands |
| `GET /lessons/random?kind=` | builds and grades on the server with `lessons/grade.py`, rate-limited like other per-IP endpoints |
| Grading | the answer key is returned with the puzzle; the client grades it the same way as curated ones |
| Shared with | the ADR 0010 `hint` request can reuse `grade.py` |

### Mined puzzles

`uv run python -m tools.mine_puzzles --games N --seed S --workers W --out all.jsonl --shortlist
app/lessons/mined_puzzles.json`, from `server/`.

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
| `safe_discard` | some discard the efficient answer (`best_discard`'s) would make deals in; the first reason of all-copies-visible, no-chance, genbutsu that covers 1–3 hand tiles, every one of them safe; `accepted` = those tiles | a real fold: the natural discard loses; a reason that also covers a tile that deals in would teach a false rule; one that clears half the hand isn't a deduction |
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

**Current run** (laptop, i7-1265U, 8 workers, ~63 min wall, engine 1.3.0): 6,000 games, seeds
20,000,000–20,005,999; 3,655,016 decisions, 2,993,369 turns scanned; 56,413 candidate positions
skipped as unrepresentable; 460,328 duplicates dropped. A first run graded `best_discard` with
exposed meld tiles regroupable (the bots' whole-hand shanten, [bots.md §3](../bots.md)), which
picked wrong answers for melded hands; this run uses `melds=n` and replaced its shortlist.

| Kind | Kept | Beginner | Intermediate | Advanced |
| --- | --- | --- | --- | --- |
| `best_discard` | 56,586 | 10,864 | 16,413 | 29,309 |
| `safe_discard` | 36,856 | 8,611 | 11,721 | 16,524 |
| `winning_tiles` | 57,488 | 44,032 | 13,076 | 380 |
| `count_faan` | 30,029 (17,521 discard wins) | 9,325 | 13,944 | 6,760 |

15,574 of the `best_discard` candidates (28%) are ones where `T4` played something else, nearly
all scored advanced; the shortlist leaves them out. `safe_discard` reasons: all copies visible
30,907, no-chance 5,880, genbutsu 69 (needs the tile in every opponent's pool).

## Tests

### Server (pytest)

| Test file | Covers |
| --- | --- |
| `test_lessons_position.py` | tile conservation; invariants; fifth copy and bad hand sizes rejected; deterministic |
| `test_lessons_grade.py` | per kind: known waits; a wait below the minimum is excluded; tied discards; safe discard against a known hidden hand; `count_faan` agrees with `check_hand` |
| `test_lessons_catalog.py` | parametrized over every lesson (below) |
| `test_gen_lessons.py` | generator output is deterministic |
| `test_mine_puzzles.py` | each filter keeps and rejects a hand-built position; difficulty score and bands; one mined game is deterministic and every record regrades; the committed shortlist regrades |
| `test_lessons_frames.py` | (phase 3) the pulled-out frame builders match what `Table` sends |

For every lesson, `test_lessons_catalog.py` checks:

- the position builds;
- the author's `answer=` equals `answer_key()`;
- for safe discard, the stated reason holds;
- for `FromSeed` positions, `ENGINE_VERSION` matches;
- for tutorials, every scripted action is legal and every `expect` step is seat 0's.

### Web and e2e

| Where | Covers |
| --- | --- |
| Vitest | `grade.spec.ts`; `lesson-player.svelte.spec.ts`; `lessons.spec.ts` (message keys); `settings-storage.spec.ts` (progress); `legal-actions.spec.ts` |
| Playwright | `routes/learn/learn.e2e.ts`: best discard wrong then right, winning-tile multi-select, faan entry, progress survives a reload, and the tutorial in phase 3 |
| Screenshots | `/learn`, one puzzle, and later one tutorial state |

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
8. `feat(server): generate lesson bundle in make proto and proto-check`
9. `feat(server): first puzzle set and catalog validity tests` (about 3 per kind)

### 2. Web puzzles

10. `feat(web): learn progress storage`
11. `feat(web): 學 lobby card, faan guide as a secondary button`
12. `feat(web): /learn index and puzzle page over TableScene`
13. `feat(web): answer panels and feedback per puzzle kind`
14. `test(web): learn e2e and screenshots`

### 3. Guided tutorial

15. `refactor(server): pure turn, claim_offer and deal frame builders shared with Table`
16. `feat(server): tutorial scripts with stacked wall and expect steps`
17. `feat(web): lesson player and tutorial coach`
18. `feat(server): basics tutorial content`
19. `feat(web): tutorial completion sets coach marks and links to easy practice`

### 4. Random endless puzzles

20. `feat(server): mine puzzles from expert self-play with bot difficulty` (done, with `position_from_state` and the first shortlist; "Mined puzzles")
21. `feat(server): GET /lessons/random`
22. `feat(web): endless mode on /learn`

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
| Answers ship in the bundle | fine for cosmetic stakes; revisit if puzzles ever feed a leaderboard |
| Coupling to `ENGINE_VERSION` and the ruleset | a scoring change moves `count_faan` answers. The catalog test and proto-check diff make that loud, but the prose explanations need re-checking by hand |
| `FromSeed` positions | break on any change to dealing; prefer explicit positions |
| `safe_discard` | safe is not the same as deducibly safe; content needs care |
| `TableScene` extraction | touches the most complex page; keep it a pure move, verified by screenshots and the table e2e |
| Translation | every lesson needs en and zh-Hant text, enforced by the parity spec |
