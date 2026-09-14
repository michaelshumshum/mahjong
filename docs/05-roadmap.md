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
│   │   ├── main.py             # FastAPI app, lifespan, uvicorn entry
│   │   ├── api/                # REST: auth, rooms, replays, leaderboard
│   │   ├── ws.py               # WebSocket endpoint, Session
│   │   ├── room.py             # Room actor: task loop, timers, claim windows, seq/ring
│   │   ├── registry.py         # RoomRegistry, matchmaking
│   │   ├── views.py            # view_for(seat, state, event) — redaction
│   │   ├── protocol.py         # pydantic message models (SOURCE OF TRUTH)
│   │   ├── infra/              # ports.py + memory.py (KV / Queue / Bus)
│   │   └── db/                 # SQLAlchemy models, migrations
│   ├── bots/
│   │   ├── base.py  random.py  efficiency.py  faan.py  safety.py
│   │   └── arena.py            # self-play evaluation harness
│   └── tests/
│       ├── test_engine.py  test_scoring.py  test_claims.py  test_redaction.py
│       ├── test_protocol.py  test_selfplay.py
│       └── replays/            # golden (seed, actions, expected_result) fixtures
├── web/
│   └── src/
│       ├── routes/             # /, /lobby, /table/[id], /replay/[id], /profile
│       └── lib/
│           ├── net/            # socket.ts, reducer.ts, protocol.d.ts (GENERATED)
│           ├── game/           # store.svelte.ts
│           ├── table/          # pixi/ scene, layout, sprites, tweens, hit-test
│           └── ui/             # Svelte components
├── shared/protocol.schema.json # GENERATED from pydantic
├── server/tools/gen_protocol.py
├── docker-compose.yml          # postgres + api + web; profiles: scale, ml, tools
├── docker-compose.prod.yml     # prod overlay
├── pnpm-workspace.yaml
└── Makefile                    # make up / test / proto / arena — see `make help`
```

## 2. Milestones

Each milestone ends in something demonstrable. Don't move on until the previous one's tests pass.

### M0 — Skeleton (≈2 days)
Monorepo, Docker Compose, FastAPI hello, SvelteKit hello, WS echo with the `{v,t,seq,id,ts,d}`
envelope, pydantic→JSON Schema→TS codegen wired into `make proto` and enforced in CI.
**Done when:** a Svelte button sends a typed message and renders a typed reply.

### M1 — Pure engine (≈1 week, critical path)
Tiles, seeded wall, deal, flower replacement, melds, full turn state machine, claim priority
resolution, `legal_actions`, `reduce`.
**Done when:** `pytest -k selfplay` runs 10,000 complete games with four `RandomBot`s — no
illegal states, no deadlocks, every game terminates. Run under `hypothesis` too.
Also: persist `GameRecord = (ruleset_hash, seed, action_log)` for every game, bot-only included
(~2h; future training set — [06-ml §1](06-ml.md)).

### M2 — Scoring (≈4 days)
All faan patterns for `CLASSIC + NEW_6`, decomposition maximisation, limit hands, caps, the
`min_faan` gate, points tables, payment splits.
**Done when:** a golden-fixture suite of ~120 hands (hand, context, ruleset → expected faan and
payments) passes, including every edge case in [01-rules-spec §11](01-rules-spec.md).
Also: the fixed 109-action space + `legal_mask` + round-trip property test
([06-ml §3](06-ml.md)) — ~1 day, painful to retrofit; the bots share the mask.

### M3 — Server (≈1 week)
Room actor + task loop, sessions, claim windows with early exit, per-seat redaction, timers with
deadline broadcast, seq + ring buffer, reconnect/resync, disconnect→bot handover, Postgres
persistence of finished games.
**Done when:** four scripted WS clients play a full game; killing one mid-hand and reconnecting
resumes correctly from `last_seq`; `test_redaction` proves no seat ever receives a tile identity
it isn't entitled to.

### M4 — Playable client (≈2 weeks)
Lobby, table route, Pixi scene, tile atlas, hand/pool/meld rendering, draw-discard-claim
animations, claim buttons, timer ring, hand-end faan breakdown, score sheet. T1 `EfficiencyBot`
in all three opponent seats.
**Done when:** you can play a full game against three bots in a browser and it feels good.

### M5 — Real multiplayer (≈1 week)
Auth (magic-link or OAuth; no passwords), matchmaking, private rooms with invite codes, mid-game
bot takeover for disconnects, spectating, chat with canned phrases.
**Done when:** four browsers on four devices finish a game with one deliberate disconnect.

### M6 — Depth (ongoing)
T2 `FaanBot` + arena harness. Replay viewer (reusing the client reducer). Sound. Ruleset presets.
Stats, rating, hand history. i18n (zh-Hant/en). Mobile layout pass.

**Rough total to M5: 6–7 weeks of focused work.** M1+M2 are ~40% of it.

## 3. Testing strategy

| Layer | Approach |
| --- | --- |
| `mahjong_core` | Table-driven unit tests + `hypothesis` property tests. **Invariants:** tile conservation (all 144 accounted for in hands+melds+pool+wall+flowers at every step); hand sizes always in `{1,4,7,10,13}` mod melds; `legal_actions` never empty in an active phase; every game terminates. |
| Scoring | Golden fixtures, one per faan pattern plus combinations. Cross-check shanten against `MahjongRepository/mahjong`. |
| Claim windows | Deterministic tests with injected arrival ordering — assert a slow high-priority win beats a fast chow, stale `window_id`s are dropped, and early exit fires when it should. |
| Redaction | Schema-walking test: render every event type for every seat and assert no unauthorised `tile_id`/`tile` ever appears. Fails loudly on new message fields. |
| Server | `httpx` + WS test client, four scripted clients, scripted disconnect/reconnect. |
| Protocol | CI fails if generated TS differs from committed TS. |
| Client | Vitest on the reducer (pure, so this is easy). Pixi screenshot tests against golden PNGs for scene layout. Playwright for a full game vs. bots. |
| Bots | Arena: candidate must beat incumbent over 20k seeded games to merge. |
| Load | Replay bot sessions as real WS clients; target 200 concurrent tables on one node. |

Build the self-play harness in M1. It finds deadlocks, illegal states, and rules gaps, and
becomes the bot evaluation harness later.

## 4. Risks

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| **Claim-window races** produce wrong or inconsistent resolutions | High | Single-writer room loop; `window_id` on every claim; deterministic arrival-order tests; never resolve on first-arrival |
| **Scoring disputes** — HK house rules differ from what you implemented | High | `RuleSet` from day one; show a per-pattern faan breakdown at hand end so players can see *why*; ship named presets |
| **Efficiency bots can't win under 3-faan minimum** | Certain if unaddressed | [04-bots §4](04-bots.md); track "tenpai on sub-minimum hand" as an explicit arena metric |
| Rules scope creep (pao, aborts, regional variants) | High | Ship `CLASSIC + NEW_6` + `min_faan=3` only. Everything else is a config flag behind a flag. |
| Canvas rewrite because the rendering choice was wrong | Medium | Keep the Pixi layer a pure function of the game store with a narrow interface; swapping renderers then touches `lib/table/` only |
| Mobile ergonomics (13 tiles on a 390px screen) | Medium | Design the mobile layout in M4, not M6. Test on a real phone early. |
| Information leak via message size/timing | Low | Redact server-side (already); pad `claim_offer` timing so "no offer" and "offer" are indistinguishable to a network observer if you care |
| Python perf | Low | Turn-based, ~5 msg/s/room. Profile before optimising. |
| Someone "uses all the cores" by raising `--workers`, silently splitting rooms across processes | Medium | Comment in Compose + Dockerfile, and a startup assertion in `main.py` ([07-infra §2](07-infra.md)) |
| ML retrofit turns into an engine rewrite | Low, if M1/M2 items land | [06-ml §6](06-ml.md) checklist — ~1.5 days total, all of it useful for heuristic bots anyway |

## 5. Open questions

Defaults in use; confirm or override each.

1. **Rendering.** Default Pixi ([03-frontend §2](03-frontend.md)).
2. **Scale target.** Default single node; thousands of tables moves stage-2 routing into M3.
3. **Ruleset defaults.** `min_faan=3`, `faan_cap=10`, `half_spicy`, `discarder_pays_all`, `CLASSIC+NEW_6`, `EAST_SOUTH`.
4. **Money/stakes.** Cosmetic points, or real stakes (pulls in commit scheme, audit logs, tighter bug tolerance)?
5. **Accounts.** Guest-only, or persistent accounts with rating? Affects M5 scope.
6. **3D.** A genuinely 3D table changes the asset pipeline; decide now.

## 6. Sources

- [Hong Kong mahjong scoring rules — Wikipedia](https://en.wikipedia.org/wiki/Hong_Kong_mahjong_scoring_rules) — faan tables, spicy conversion, payments, penalties
- [Complete Faan Guide — TileBuddy](https://tilebuddy.app/blog/complete-faan-guide/) — Classic / New 6 / New 18 hand sets
- [HK Mahjong Scoring Chart — mahjonggame.hk](https://www.mahjonggame.hk/learn/hk-mahjong/scoring) — faan cross-reference
- [Hong Kong Mahjong Rules — Table Mahjong](https://tablemahjong.com/mahjong-rules/) — gameplay flow
- [MahjongRepository/mahjong](https://github.com/MahjongRepository/mahjong) — shanten reference implementation
- [A Fast Algorithm for Computing the Deficiency Number of a Mahjong Hand — arXiv:2108.06832](https://arxiv.org/pdf/2108.06832)
- [Constructing AI Players with MDP Abstraction in Mahjong — arXiv:1904.07491](https://arxiv.org/pdf/1904.07491)
- [Phaser vs PixiJS (2026)](https://generalistprogrammer.com/comparisons/phaser-vs-pixijs) — bundle/perf comparison
- [FluffyStuff/riichi-mahjong-tiles](https://github.com/FluffyStuff/riichi-mahjong-tiles) — public-domain tile vectors
- [libreriichi-assets](https://codeberg.org/davidgomez/libreriichi-assets) — CC0 3D tile textures
- [Networking of a turn-based game — Longwelwind](https://longwelwind.net/blog/networking-turn-based-game/) — reducer/event pattern, seq resync
- [Server-Authoritative Game Logic — AccelByte](https://accelbyte.io/blog/server-authoritative-logic-to-prevent-cheating)
