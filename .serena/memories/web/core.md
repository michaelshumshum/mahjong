# web/

Full rules: `web/AGENTS.md`, `docs/03-frontend.md`.

## Layout
- `src/routes/` — lobby (root), tables, demo, table/[id], replay/[id], profile
- `src/lib/net/` — ws client, per-seat seq tracking, pure reducer, generated `protocol.d.ts`
- `src/lib/game/` — client `$state` store
- `src/lib/table/` — table-surface components (DOM); `src/lib/ui/` — app chrome
- `src/lib/styles/` — SCSS tokens, tile geometry, mixins

## Invariants
- One-way flow: server event → reducer → store → components; no optimistic mutation of game truth (only exception: pending visual on just-discarded tile).
- Seq numbers per-seat, gapless; gap → resync.
- Reducer exhaustive over event union.
- `/table/[id]`, `/replay/[id]` have `ssr = false`.
- `/table/[id]?mock=<scenario>` uses frozen `MOCK_SCENARIOS` (e2e + screenshots rely on it).
- Runes in `*.svelte.ts` must be tested in `*.svelte.spec.ts` (browser project) — `$effect` silently never runs under the server project.
- Out-of-component subscriptions need `$effect.root(...)` with disposer; pass `$state.snapshot(...)` + `version` to non-reactive consumers.
