# 05 — Roadmap, testing, risks

## 1. Repository layout

```
mahjong/
├── server/
│   ├── mahjong_core/           # PURE. no asyncio, no I/O, no deps beyond stdlib
│   │   ├── tiles.py            # TileType/TileId, 34-array helpers, parsing ("5s", "1m")
│   │   ├── wall.py             # seeded shuffle, dice, draw front/back, flower replacement
│   │   ├── melds.py            # meld types, legality, decomposition
│   │   ├── shanten.py          # standard / seven pairs / thirteen orphans + ukeire
│   │   ├── state.py            # GameState, SeatState, Phase (all frozen dataclasses)
│   │   ├── actions.py          # Action union, legal_actions(state, seat)
│   │   ├── engine.py           # reduce(state, action) -> (state, events)
│   │   ├── claims.py           # claim priority resolution (pure part)
│   │   ├── config.py           # RuleSet
│   │   ├── ml.py               # action_id / decode_action / legal_mask (ML-ready, day-1 cheap)
│   │   └── scoring/
│   │       ├── patterns.py     # faan pattern detectors
│   │       ├── faan.py         # maximize over all valid decompositions
│   │       └── payout.py       # faan -> points -> per-seat payments
│   ├── app/
│   │   ├── main.py             # FastAPI app, lifespan, uvicorn entry, /healthz
│   │   ├── ws.py               # WebSocket endpoint, Session
│   │   ├── table.py             # Table actor: task loop, timers, claim windows, seq/ring
│   │   ├── registry.py         # TableRegistry, matchmaking, graceful-shutdown drain
│   │   ├── views.py            # seat_view() + redact_event() — redaction
│   │   ├── protocol.py         # pydantic message models (SOURCE OF TRUTH)
│   │   ├── idempotency.py      # per-seat intent id cache (02-protocol.md §1)
│   │   ├── outbox.py           # BoundedOutbox, per-connection backpressure
│   │   └── db/                 # SQLAlchemy models, migrations
│   │       # no REST router yet beyond /healthz — table list, replays, leaderboard
│   │       # (02-protocol.md's REST mention) are not built; matchmaking/presence/rate-
│   │       # limiting are the in-process dicts 00-architecture.md §6 describes, not a
│   │       # separate app/infra/ module
│   ├── tools/gen_protocol.py   # pydantic → TS directly (+ informational JSON Schema), 02-protocol §6
│   ├── bots/
│   │   ├── base.py  random.py  efficiency.py  faanbot.py  safety.py  valuation.py
│   │   └── arena.py            # self-play evaluation harness
│   └── tests/
│       ├── test_engine.py  test_scoring.py  test_faan.py  test_payout.py  test_claims.py
│       ├── test_redaction.py  test_protocol.py  test_selfplay.py  test_full_game_e2e.py
│       └── replays/            # NOT YET BUILT — golden (seed, actions, expected_result)
│                                # fixtures called for by server/AGENTS.md; today's scoring
│                                # suite is hand-authored parametrized cases in test_faan.py/
│                                # test_payout.py instead
├── web/
│   └── src/
│       ├── routes/             # / (lobby), /demo, /table/[id], /replay/[id], /profile
│       └── lib/
│           ├── net/            # socket.ts, reducer.ts, protocol.d.ts (GENERATED)
│           ├── game/           # store.svelte.ts
│           ├── table/          # DOM/CSS table scene: layout, tile positioning, transitions, hit-test
│           ├── ui/             # Svelte components
│           └── styles/         # SCSS: tokens, tile geometry, layout mixins
├── shared/protocol.schema.json # GENERATED from pydantic
├── docker-compose.yml          # postgres + api + web; profiles: ml, tools
├── docker-compose.prod.yml     # prod overlay
├── pnpm-workspace.yaml
└── Makefile                    # make up / test / proto / arena — see `make help`
```

## 2. Milestones

Each milestone ends in something demonstrable. Don't move on until the previous one's tests pass.
Timelines below are honest, not aspirational — see the timeline note after the table.

### M0 — Skeleton (≈2 days)
Monorepo, Docker Compose, FastAPI hello, SvelteKit hello, WS echo with the `{v,t,seq,id,ts,d}`
envelope, pydantic→JSON Schema→TS codegen wired into `make proto`. Also: `git init`, a remote,
and a minimal CI workflow (even just `pytest` + the protocol-diff check) — see §3.
**Done when:** a Svelte button sends a typed message and renders a typed reply, and a push to the
remote runs the CI workflow. **Met** — `.github/workflows/ci.yml`, see [07-infra.md §9](07-infra.md).

### M1 — Pure engine (3–4 weeks, critical path)
Tiles, seeded wall, deal, flower replacement, melds, full turn state machine, claim priority
resolution, `legal_actions`, `reduce`. This is the milestone most underestimated by an earlier
draft of this doc — see the timeline note below for why 3–4 weeks, not 1.
`legal_actions`' win-declaration legality is win-*shape* only (standard melds+pair, Seven
Pairs, Thirteen Orphans) — the `min_faan` gate below is a real M2 dependency, not an
oversight; see [01-rules-spec.md §11.8](01-rules-spec.md). Closed in M2 sub-task 8, below.
**Done when:** `pytest -k selfplay` runs 10,000 complete games with four `RandomBot`s — no
illegal states, no deadlocks, every game terminates. Run under `hypothesis` too. **Met.**
Also: persist `GameRecord` (`engine_version`, full `ruleset` body, `seed`, `actions`, `outcome`)
for every game, bot-only included (~2h; full definition and the replay-invalidation policy in
[06-ml §2](06-ml.md)). **Met** — `server/app/db/models.py` (`games` table), `server/app/db/records.py`
(`save_game_record`, `is_replayable`), `server/bots/selfplay.py` (`play_and_record_game`, the
bot-only integration point). M1 is now fully complete.

### M2 — Scoring (2–3 weeks)
All faan patterns for `CLASSIC + NEW_6 + NEW_18` (~43 patterns), decomposition maximisation,
limit hands, caps, the `min_faan` gate, points tables, payment splits.
**Done when:** a golden-fixture suite of ~120 hands (hand, context, ruleset → expected faan and
payments) passes, including every edge case in [01-rules-spec §11](01-rules-spec.md). Hand-authoring
those 120 fixtures is itself days of work, not an afternoon — budget for it explicitly.
**Met** — `server/tests/{test_scoring,test_faan,test_payout}.py` carry 145 hand-authored test
functions, well past the ~120-fixture bar. Every one of the 34 registered patterns is positively
exercised, and every [01-rules-spec.md §11](01-rules-spec.md) edge case is either closed with a
named fixture or tracked there as a scope gap (`four_kong_abort`/`nine_terminals_abort`,
`thirteen_orphans_wait_bonus`, and the initial-deal flower-instant-win check — unbuilt features,
not fixture gaps).
Also: the fixed 109-action space + `legal_mask` + type-level round-trip property test
([06-ml §1](06-ml.md)) — ~1 day, painful to retrofit; the bots share the mask.

### M3 — Server (≈1 week)
Table actor + task loop, sessions, claim windows with early exit, per-seat redaction, timers with
deadline broadcast, seq + ring buffer, reconnect/resync, disconnect→bot handover, Postgres
persistence of finished games.
**Done when:** four scripted WS clients play a full game; killing one mid-hand and reconnecting
resumes correctly from `last_seq`; `test_redaction` proves no seat ever receives a tile identity
it isn't entitled to. **Met.**

Postgres persistence of finished `Table`-driven games and the graceful-shutdown drain
([00-architecture.md §6](00-architecture.md)/[§8.1](00-architecture.md)) are both implemented —
see those sections. `server/tests/test_full_game_e2e.py` drives four real WS clients through a
complete `EAST_ONLY` game (4 hands, dealer rotating 0→1→2→3) covering a real claim exchange, a
self-draw win, and a mid-claim-window disconnect/reconnect, checking every frame against
`app/views.py`'s `Entitlement` rules live. Turn timeout is also closed: `app/table.py`'s
`_arm_turn_timer`/`_handle_turn_timeout` enforce `RuleSet.turn_seconds`/`turn_timeout_strikes`
for both human and bot-driven seats identically (00-architecture.md §8 "Turn timeout"). M3 is
fully complete; no gaps remain beyond what's tracked elsewhere in this doc set (§4, §7, §8, §9).

### M4 — Playable client + bots (6–10 weeks)
Lobby, table route, DOM/CSS table scene, inline-SVG tile faces, hand/pool/meld rendering,
draw-discard-claim animations, claim buttons, timer ring, hand-end faan breakdown, score sheet.
T1 `EfficiencyBot` **and T2 `FaanBot`** in the opponent seats — `FaanBot` is pulled forward from
M6 here, not left until later, because it's load-bearing for M4.5's done gate (next section):
three `EfficiencyBot`s under `min_faan=3` reach tenpai constantly and then can never legally
declare ([04-bots §4](04-bots.md)), so an all-`EfficiencyBot` table produces endless exhaustive
draws, not finished games. `EfficiencyBot` alone is not sufficient to make M4.5 playable.
**Done when:** the client renders a full hand correctly end to end, and `FaanBot` beats
`EfficiencyBot` over an arena run ([04-bots §8](04-bots.md)). The player-facing "does this feel
like a game" gate lives in M4.5, not here.

**Bots half: built, not yet fully cleared.** `T1`/`T2`/the arena harness are all built and
merged; `tenpai_rate_on_sub_minimum_hand` — the HK-only failure this milestone exists to fix —
is well down relative to T1, but the paired-difference CI on raw points still includes zero, not
yet a clean "`FaanBot` beats `EfficiencyBot`" per this gate's literal wording. Current numbers
and tuning status: [04-bots.md §8](04-bots.md). Client work (the rest of this milestone's list)
is untouched by this note.

### M4.5 — Single-player is shippable
No new engine work — this is a checkpoint milestone, not a build phase. Play the M4 client
against a table of three `FaanBot`s end to end (not `EfficiencyBot`s — see M4), fix whatever that
reveals (pacing, animation edge cases, mobile layout per §4 risks), and cut a build.
**Done when:** you can play a full game solo against three bots in a browser, hands end in real
wins at a normal rate rather than perpetual exhaustive draws, and it feels good. This is the last
point at which shipping single-player-only is a live, cheap option — given the M5 cost below,
treat it as a real decision point, not a formality.

**Backend mechanism: built.** The live table path (disconnect-handover's `autoplay` seats) runs
the real bot tiers ([04-bots.md §1](04-bots.md)), and a table can also be started with bots
filling the other three seats from creation (`?practice=true` on the WS endpoint →
`Table.__init__(practice=True)`), defaulting to `T2`/`FaanBot`. Proven end to end: one human
client, three real `FaanBot`s, unscripted play to `Phase.GAME_OVER`
(`server/tests/test_practice_mode_e2e.py`). **What's left for this milestone is entirely
frontend** — a lobby entry point for practice mode and bot-seat visual treatment.

### M5 — Real multiplayer (1–2 weeks)
Guest identity only, by design — no accounts, no password, no email, no JWT, no REST auth
endpoint. A player picks a display name client-side; it's persisted in `localStorage` (or a
cookie) so it survives a reload, and sent once at `join` (docs/02-protocol.md §2's existing
`JoinPayload` grows a sibling `name` field alongside `seat` — no new wire concept, just one more
client-asserted field on the message that actually claims a seat for the first time; a later
`hello{seat}` reconnect never resends it — see docs/00-architecture.md §2.1's note on why `join`,
not `hello`, is the right message). Matchmaking, private tables with invite codes, mid-game bot
takeover for disconnects, spectating (spectating backend built — see below; frontend wiring
still open, matchmaking/invite codes not started).

This is a deliberate rescope, not a placeholder for auth done later: `docs/00-architecture.md
§2.1`'s earlier ticket/JWT design (guest-first, with an *optional* account upgrade layered on
top) is cut, not deferred — cutting it removes the one M5 line item that pulled in
infrastructure (email deliverability, SPF/DKIM, a transactional provider) unlike anything else in
this project. A consequence worth stating plainly: seat identity stays permanently
client-asserted (a `join{seat: 2, name: "..."}` claiming seat 2, or a later `hello{seat: 2}`
reclaiming it, is trusted at face value, same as the stand-in `hello.seat` mechanism already
ships today) — there's no ticket to bind a seat to a verified identity, so nothing stops a
malicious client from claiming a seat it didn't join. Accepted for a guest-only, no-real-stakes
game; revisit only if real accounts ever become an actual goal, which is explicitly not scoped
anywhere in this document.
**Done when:** four browsers on four devices finish a game with one deliberate disconnect, each
seeing the other three players' chosen names throughout.

**Backend wire slice: built.** `join.name` is stored on `SeatBinding.name` for the seat's entire
game and surfaced via `state_sync.names`, `seat_state.name`, and `GameRecord.players`
([00-architecture.md §5](00-architecture.md)). What's left for this milestone is everything
client-side (name-entry UI, `localStorage`, rendering) plus matchmaking and invite codes.

**Spectating: backend built.** `?spectate=true` on the WS URL gets a spectator-redacted
`state_sync` and every subsequent broadcast, minus anything naming a seat's own concealed tiles
([00-architecture.md §3](00-architecture.md)). Proven end to end
(`server/tests/test_spectator.py`). What's left is entirely frontend (a "watch" entry point, a
spectator-mode table render with no own-hand section). Showing hands to spectators after a delay
remains a real, un-built future enhancement — not required for a correct v1.

### M6 — Depth (ongoing)
Arena harness deepening (`FaanBot` itself now ships in M4 — see above, not here). Replay viewer
(reusing the client reducer). Sound. Ruleset presets. Stats, rating, hand history. i18n
(zh-Hant/en). Mobile layout pass. M6 has no done gate by design — see §7 for what actually has to
ship before that's okay.

### Timeline, honestly

**Total to M5 (real multiplayer): roughly 4.5–5.5 months full-time, or 11–17 months on evenings
and weekends.** An earlier draft of this doc estimated "6–7 weeks of focused work" to the same
milestone — that was off by roughly 4×, and 4× is exactly the kind of miss that kills a solo
project around month three, when the actual pace becomes undeniable and there's no plan B. (This
total already reflects cutting magic-link auth from M5 — see that section's own note — which is
the one change to this estimate since the figure below was first written; every other
per-milestone number here has held up in practice.)
Per-milestone reality:

- **M1 engine — 3–4 weeks, not 1.** Flower chains, kong-robbing interleaved with claim windows,
  concealed-kong re-wait, frozen dataclasses kept honest under `mypy --strict`, and *then* the
  10,000-game self-play clean run plus `hypothesis` properties on top — each of those is a
  multi-day task on its own, not a subtask that fits inside a single week alongside the rest.
- **M2 scoring — 2–3 weeks, not 4 days.** Maximizing over all valid decompositions across ~35
  patterns is the tractable part; hand-authoring 120 golden fixtures — correct faan, correct
  payments, per documented edge case — is by itself days of work.
- **M4 client — 6–10 weeks, not 2.** This is a full turn-based UI with animation timing, claim
  windows, and a faan breakdown at hand end — a real client application, not a rendering demo.
- **M5 multiplayer — 1–2 weeks, not 3–4.** The earlier estimate priced in magic-link auth (email
  infrastructure and deliverability — a different kind of work than anything in M0–M4). Guest-only
  identity (a client-chosen name in `localStorage`, no server-side account) cuts that out
  entirely; what's left — matchmaking, invite codes, bot takeover, spectating — is all in
  the same shape as work already done in M0–M4.

If this is evenings-and-weekends work rather than full-time, the 12–18 month figure already
accounts for that at roughly 8–10 hours/week — don't also apply a separate part-time discount on
top of it.

## 3. Testing strategy

| Layer | Approach |
| --- | --- |
| `mahjong_core` | Table-driven unit tests + `hypothesis` property tests. **Invariants:** tile conservation (all 144 accounted for in hands+melds+pool+wall+flowers at every step); hand sizes always in `{1,4,7,10,13}` mod melds; `legal_actions` never empty in an active phase; every game terminates. |
| Scoring | Golden fixtures, one per faan pattern plus combinations. Cross-check shanten against `MahjongRepository/mahjong`. |
| Claim windows | Deterministic tests with injected arrival ordering — assert a slow high-priority win beats a fast chow, stale `window_id`s are dropped, and early exit fires when it should. |
| Redaction | Schema-walking test: render every event type for every seat and assert no unauthorised `tile_id`/`tile` ever appears. Fails loudly on new message fields. |
| Server | `httpx` + WS test client, four scripted clients, scripted disconnect/reconnect. |
| Protocol | Intended: CI fails if generated TS differs from committed TS. See the reality check below. |
| Client | Vitest on the reducer (pure, so this is easy). Playwright for a full game vs. bots. (Pixi golden-PNG screenshot tests are cut along with Pixi itself — deferred, see [99-deferred.md](99-deferred.md).) |
| Bots | Arena: candidate must beat incumbent over 20k seeded games to merge. |
| Load | Replay bot sessions as real WS clients; target 200 concurrent tables on one node. |

`.github/workflows/ci.yml` runs on push/PR to `main`: `pytest -m "not slow"`, the web test suite
(vitest + Playwright), and `proto-check` (`git diff --exit-code` after regenerating) — see
[07-infra.md §9](07-infra.md). The "CI fails if stale" promise here and in
[02-protocol.md](02-protocol.md) is now enforced, not aspirational.

Build the self-play harness in M1. It finds deadlocks, illegal states, and rules gaps, and
becomes the bot evaluation harness later. It runs with `dealer_repeat_on_win`/
`dealer_repeat_on_draw` off, not `DEFAULT_RULESET` — measured empirically while sizing it,
`RandomBot` completes a winning hand rarely enough that repeat-on-draw can chain 150+ hands
before a round rotates, which turns a legitimate slow-converging config into soak-test
flakiness rather than exercising anything new (the repeat paths already have dedicated unit
coverage in `test_engine.py`). With repeats off, a game is bounded at exactly 4/8/16 hands for
EAST_ONLY/EAST_SOUTH/FULL, which is what makes 10,000 games at real bot skill (later
milestones' `EfficiencyBot`/`FaanBot`) worth re-measuring once they exist.

## 4. Risks

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| **Claim-window races** produce wrong or inconsistent resolutions | High | Single-writer table loop; `window_id` on every claim; deterministic arrival-order tests; never resolve on first-arrival |
| **Scoring disputes** — HK house rules differ from what you implemented | High | `RuleSet` from day one; show a per-pattern faan breakdown at hand end so players can see *why*; ship named presets |
| **Efficiency bots can't win under 3-faan minimum** | **Partially mitigated (M4)** | [04-bots §4/§8](04-bots.md); `FaanBot` built and arena-proven to cut `tenpai_rate_on_sub_minimum_hand` well below T1's; raw-points parity not yet fully closed (paired-diff CI still includes zero) — further self-play weight tuning against the same arena harness is the concrete next step |
| Rules scope creep (pao, aborts, regional variants) | High | Ship the default `hand_sets` (`CLASSIC + NEW_6 + NEW_18`) + `min_faan=3` only. NEW_18 is in scope, not creep: Seven Pairs lives there and the bot shanten parser requires it ([01-rules-spec §7](01-rules-spec.md)). Everything else is a config flag behind a flag. |
| Mobile ergonomics (13 tiles on a 390px screen) | Medium | Design the mobile layout in M4, not M6. Test on a real phone early. |
| Information leak via message size/timing | Low | Redact server-side (already). The obvious further mitigation — padding `claim_offer` timing so "no offer" and "offer" are indistinguishable to a network observer — is **not done**: it's incompatible with the early-exit claim window that [00-architecture.md §4](00-architecture.md) requires for UX, since early exit necessarily reveals timing. Accepted as a known, low-severity leak rather than mitigated. |
| **Python perf — server** | Low | Turn-based, ~5 msg/s/table; I/O-bound, not CPU-bound. |
| **Python perf — bots** | Medium–High | Bots run in-process, not gated by network I/O the way the server's message rate is: each decision is roughly 470 pure-Python shanten evaluations, against a stated target of 200 concurrent tables × 3 bot seats. That's a CPU-bound hot loop at real concurrency, not "turn-based so it's fine" — the server row above does not cover it. **Partially mitigated (M4):** `mahjong_core/shanten.py`'s per-suit `functools.cache` turns repeat shapes into O(1) lookups instead of a fresh recursive scan every time — but this is single-process caching, not the 200-concurrent-table load test itself, which still hasn't run. Still worth doing before this becomes a scaling wall for real. |
| Someone "uses all the cores" by raising `--workers`, silently splitting tables across processes | Medium | Comment in Compose + Dockerfile, and a startup assertion in `main.py` ([07-infra §2](07-infra.md)) |
| ML retrofit turns into an engine rewrite | Low, if M1/M2 items land | [06-ml §5](06-ml.md) checklist — ~1 day total, all of it useful for heuristic bots anyway |
| **Cold start — nobody's online at the same time** | High | No current mitigation beyond "bring your own group" via M5's invite-code private tables. See §6; this is the primary product risk for a 4-player realtime game and was missing from this table entirely before this revision. |
| **Silent table failure** — a wedged table destroys a game with no signal to anyone | Unrated — there is currently no way to detect it, which is the problem | See §8; minimum viable fix is per-table structured logs plus a liveness check, not just process-level `/healthz`. |

## 5. Resolved decisions

Previously open questions; now decided. Where the decision's source of truth lives in another
doc, this section just records the answer and points there.

1. **Rendering.** DOM/CSS, not Pixi/canvas. Source of truth: [03-frontend.md](03-frontend.md).
2. **Scale target.** Single node, ~200 concurrent tables ([04. Risks](#4-risks) above,
   [07-infra.md](07-infra.md)). Thousands-of-tables routing is out of scope, not a numbered
   future milestone.
3. **Ruleset defaults.** `min_faan=3`, `faan_cap=10`, `half_spicy`, `discarder_pays_all`,
   `CLASSIC+NEW_6+NEW_18`, `EAST_ONLY` (一圈).
4. **Money/stakes.** Cosmetic points only, never real stakes. Real-stakes mahjong is a licensing
   question in most jurisdictions; deciding this in writing now is free, and revisiting it after
   launch is not.
5. **Accounts.** Guest-only, permanently — not guest-first with an account-upgrade path. No
   account, password, email, JWT, or REST auth endpoint anywhere in this design (cut, not
   deferred: see M5 and [00-architecture.md §2.1](00-architecture.md)).
6. **3D/2.5D rendering.** Cut, not deferred as a live decision — DOM/CSS (see #1) makes a 3D asset
   pipeline out of scope entirely. Deferred — see [99-deferred.md](99-deferred.md).

## 6. Who plays this, and how do they find it

For a 4-player realtime game, the cold-start problem — finding three other humans online at the
same time — is the primary product risk, and an earlier draft of this roadmap didn't mention it
anywhere. Bots cover it partially (M4.5 ships single-player against bots as a real, shippable
artifact), but M5's "real multiplayer" done gate ("four browsers on four devices finish a game")
says nothing about how those four humans found each other or why they were online at once.

Minimum viable answer for v1: private tables with invite codes (already in M5 scope), aimed at
existing friend groups who already coordinate a real-world game time — this sidesteps needing a
public lobby with real matchmaking density. Public-lobby matchmaking (a queue, skill-based
pairing, always-on presence of strangers online at the same time) is a distinct, harder problem
and is explicitly **not** v1 scope. See the cold-start risk row in §4 — it's tracked now instead
of assumed away.

## 7. What "done" means for v1

Every milestone above has a "Done when" gate, but nothing in this doc said what actually ships as
v1 — M6 is explicitly open-ended ("ongoing"), which is fine for a backlog and useless as a launch
target.

**v1 = M0 through M5**, plus whichever M6 items are load-bearing for the M5 done gate to mean
anything in front of real users — at minimum, reconnect/bot-takeover actually holding up under a
real disconnect (already M3/M5 scope) and the ruleset defaults being right, since there's no UI to
change them yet ([04-bots.md](04-bots.md)). Everything else in M6 — replay viewer, sound, stats,
rating, i18n, mobile pass — is post-launch by definition: ship v1 without it, then triage M6
against what real usage actually asks for instead of guessing now.

## 8. Observability

There is none, anywhere in this doc set. The server is a single stateful process where each table
is an in-memory actor ([00-architecture.md](00-architecture.md); `docker-compose.yml` runs the
API with `--workers 1`) — one wedged table silently destroys a game in progress, and nothing
currently described here would tell anyone it happened. Minimum for v1, not something to push to
M6:

- Structured logs per table (`table_id`, `seq`, phase transitions) shipped somewhere off-box.
- A liveness check per table, not just the process-level `/healthz` compose already has — a
  process can be up while one specific table's task loop is stuck.
- An alert, even a crude one, on "table hasn't advanced `seq` in N minutes while players are
  connected."
- Basic visibility into crash recovery: when a table dies, does anyone find out before the players
  do?

See the "Silent table failure" risk row in §4.

## 9. Deployment target and cost

Not specified anywhere in this doc set. Needed before M5, since M5's done gate requires four real
browsers on the open internet, not four local `docker-compose` clients:

- **Host.** Pick one. A single VM is consistent with the `--workers 1` single-process design in
  `docker-compose.yml`; don't reach for anything that implies horizontally scaling the table
  registry, since the architecture doesn't support that ([07-infra.md](07-infra.md)).
- **TLS + domain.** WebSocket over `wss://` needs a real certificate; decide the domain before M5,
  not during it.
- **Postgres backups.** Finished games (`GameRecord`s, per [06-ml §2](06-ml.md)) are the only
  durable asset this system produces, and no backup plan exists anywhere in this doc set. At
  minimum: automated daily snapshots with a tested restore, in place before real users' finished
  games depend on it.
- **Cost.** Even a rough monthly figure (VM + Postgres + domain) belongs in this doc before M5, so
  "ship multiplayer" doesn't also quietly mean "commit to an unbudgeted recurring cost."

## 10. Sources

- [Hong Kong mahjong scoring rules — Wikipedia](https://en.wikipedia.org/wiki/Hong_Kong_mahjong_scoring_rules) — faan tables, spicy conversion, payments, penalties
- [Complete Faan Guide — TileBuddy](https://tilebuddy.app/blog/complete-faan-guide/) — Classic / New 6 / New 18 hand sets
- [HK Mahjong Scoring Chart — mahjonggame.hk](https://www.mahjonggame.hk/learn/hk-mahjong/scoring) — faan cross-reference
- [Hong Kong Mahjong Rules — Table Mahjong](https://tablemahjong.com/mahjong-rules/) — gameplay flow
- [MahjongRepository/mahjong](https://github.com/MahjongRepository/mahjong) — shanten reference implementation
- [A Fast Algorithm for Computing the Deficiency Number of a Mahjong Hand — arXiv:2108.06832](https://arxiv.org/pdf/2108.06832)
- [Constructing AI Players with MDP Abstraction in Mahjong — arXiv:1904.07491](https://arxiv.org/pdf/1904.07491)
- [FluffyStuff/riichi-mahjong-tiles](https://github.com/FluffyStuff/riichi-mahjong-tiles) — public-domain tile vectors
- [Networking of a turn-based game — Longwelwind](https://longwelwind.net/blog/networking-turn-based-game/) — reducer/event pattern, seq resync
- [Server-Authoritative Game Logic — AccelByte](https://accelbyte.io/blog/server-authoritative-logic-to-prevent-cheating)
