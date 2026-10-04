# 0018. Milestone plan and timeline

- **Status:** Historical
- **Date:** 2026-09-14 (plan), retired 2026-10-04

## Context

The project was planned as milestones, each ending in something demonstrable, with "don't move on
until the previous one's tests pass." The plan lived in `docs/05-roadmap.md` until the docs were
reorganized into reference documentation; this record keeps it.

## Milestones

| Milestone | Scope | Done gate | Outcome |
| --- | --- | --- | --- |
| M0 Skeleton | monorepo, Compose, FastAPI/SvelteKit hello, WS echo with the `{v,t,seq,id,ts,d}` envelope, protocol codegen in `make proto`, a remote + minimal CI | a Svelte button sends a typed message and renders a typed reply; a push runs CI | met |
| M1 Pure engine | tiles, seeded wall, deal, flowers, melds, turn state machine, claim resolution, `legal_actions`, `reduce`; `GameRecord` persisted for every game, bot-only included | 10,000 `RandomBot` games, no illegal states or deadlocks, under `hypothesis` too | met |
| M2 Scoring | all `CLASSIC + NEW_6 + NEW_18` patterns, decomposition maximisation, limits, caps, `min_faan` gate, points, payments; the fixed 109-action space + `legal_mask` | ~120 golden hands incl. every rules edge case | met: 145 hand-authored tests; remaining edge cases are unbuilt features (aborts, wait bonus, initial-deal flower instant win) |
| M3 Server | table actor, sessions, early-exit claim windows, redaction, timers, seq + ring buffer, reconnect, disconnect→bot handover, persistence | four scripted WS clients finish a game; a killed client resumes from `last_seq`; `test_redaction` proves entitlement | met, plus turn timeouts and the shutdown drain |
| M4 Playable client + bots | lobby, table route, DOM table, tile faces, animations, claim buttons, timer ring, faan breakdown, score sheet; T1 **and T2** (pulled forward from M6: three `EfficiencyBot`s under `min_faan=3` draw forever) | full hand renders end to end; `FaanBot` beats `EfficiencyBot` in the arena | client met; bots: `FaanBot` cuts sub-minimum tenpai ~31% but the points CI still includes zero |
| M4.5 Single-player shippable | play three `FaanBot`s end to end, fix what that reveals, cut a build | a full solo game with real wins at a normal rate, and it feels good | built (`?practice=true`, lobby button, bot badges); the "feels good" judgment is qualitative |
| M5 Real multiplayer | guest identity, matchmaking, private tables, bot takeover, spectating | four browsers on four devices finish a game with one disconnect, names visible throughout | identity, takeover, spectating, `/tables` browser, host start-with-bots built; matchmaking not started |
| M6 Depth (open-ended) | arena deepening, T3 search, replay viewer, sound, ruleset presets, ML "Expert", stats, rating, i18n, mobile pass | none by design | presets, ruleset-aware bots, i18n, `ORACLE` built; T3 built and removed ([ADR 0012](0012-searchbot-removed.md)); ML in progress ([ml.md](../ml.md)) |

## Timeline lesson

The first draft estimated "6–7 weeks of focused work" to real multiplayer. The revised estimate was
4.5–5.5 months full-time (11–17 months at 8–10 hours/week) — off by ~4×, the kind of miss that
kills a solo project around month three. Per milestone:

- **M1 engine — 3–4 weeks, not 1.** Flower chains, kong robbing inside claim windows,
  concealed-kong re-waits, frozen dataclasses under `mypy --strict`, then the 10k-game soak and
  `hypothesis` properties — each multi-day.
- **M2 scoring — 2–3 weeks, not 4 days.** Hand-authoring ~120 correct fixtures is days on its own.
- **M4 client — 6–10 weeks, not 2.** A real turn-based UI with animation timing and claim windows.
- **M5 multiplayer — 1–2 weeks, not 3–4**, after cutting magic-link auth
  ([ADR 0001](0001-guest-only-identity.md)).

## Risk register (as last maintained)

| Risk | Likelihood | Resolution |
| --- | --- | --- |
| Claim-window races | High | single-writer table loop, `window_id`, deterministic arrival tests, never first-arrival |
| Scoring disputes across house rules | High | `RuleSet`, per-pattern breakdown at hand end, named presets |
| Efficiency bots can't win under 3-faan minimum | — | partially mitigated by `FaanBot` ([bots.md §7](../bots.md)) |
| Bots blind to non-default rulesets | — | closed ([ADR 0014](0014-ruleset-aware-bots.md)) |
| Rules scope creep | High | defaults only; everything else behind a flag |
| Mobile ergonomics (13 tiles at 390px) | Medium | mobile layout designed into M4 |
| Message timing leak | Low | accepted ([architecture.md §4](../architecture.md)) |
| Python perf — bots at 200 tables × 3 seats | Medium–High | per-suit shanten cache; load test not run |
| Someone raises `--workers` | Medium | pinned with comments ([infra.md §3](../infra.md)) |
| ML retrofit becomes an engine rewrite | Low | action encoding and `GameRecord` built early |
| Cold start | High | bots + private links ([ADR 0003](0003-product-scope.md)) |
| Silent table failure | Unrated | no detection exists ([infra.md §8](../infra.md)) |
