# web/AGENTS.md

SvelteKit 2 + Svelte 5 (runes). No canvas — the table is DOM, styled with SCSS. Frontend outline:
`docs/03-frontend.md`.

## Layout

```
src/routes/     lobby, table, replay, profile
src/lib/net/    WebSocket client, seq tracking, reducer, generated protocol types
src/lib/game/   client state store ($state)
src/lib/table/  table-surface Svelte components (DOM, not canvas)
src/lib/ui/     Svelte components (app chrome)
src/lib/styles/ SCSS tokens, tile geometry, layout mixins (see docs/03-frontend.md §7.1)
```

## Rules

- Svelte/DOM owns everything: chrome and the table surface, including the tiles on it. No canvas.
- One-way flow: server event → reducer → store → components. Components never own game truth.
- No optimistic local mutation of game truth. Send an intent, wait for the event — the one
  exception is a *pending* visual state on the tile you just discarded (`docs/03-frontend.md
  §5`), which is presentation only and reverts to nothing (the discard is never actually
  rejected).
- `/table/[id]` and `/replay/[id]` disable SSR (`export const ssr = false`); other routes keep
  the default SSR that `web/Dockerfile`'s `node build` (adapter-node) turns on.
- `src/lib/net/protocol.d.ts` is generated — edit `server/app/protocol.py`, run `make proto`.
- The reducer is pure and exhaustively switched over the event union.
- **Sequence numbers are per-seat**, gapless within your own stream, not per-room. A gap on your
  own stream triggers a resync, never a silent patch.
- Code that subscribes outside a `.svelte` file (e.g. a `lib/net/` socket manager driving an
  `$effect`) must wrap it in `$effect.root(...)` with an explicit disposer — effects need an
  owner. `$state<T[]>` fields are deep proxies; hand non-reactive consumers a
  `$state.snapshot(...)` plus the store's `version` counter, not the live proxy.

## Commands

```
make test-web
pnpm dev | pnpm build | pnpm lint
pnpm run screenshots   # regenerate docs/screenshots/*.png — see below
```

- **After any change that's visible on a notable page** (new component wired in, layout change,
  a new mock scenario worth showing, a visual bug fix), regenerate screenshots and commit them
  in the same change: `pnpm --dir web run screenshots`, then look at the output — this has
  already caught a real bug (rotated opponent hand-strip CSS escaping its grid column) that
  wasn't visible from the code or from `pnpm test`. Update `README.md`'s Screenshots section too
  if a page's content meaningfully changed. Full workflow, troubleshooting, and the notable-pages
  list: `.claude/skills/frontend-screenshots/SKILL.md`. Skip this for changes with no visible
  surface (pure logic, test-only, refactors with identical output).
- `/table/[id]` opens a real live game by default (`[id]` as a room id) — the screenshot script
  and `table.e2e.ts` explicitly pass `?mock=<scenarioId>` (any value works; a bare `?mock` picks
  the first scenario) to stay on the frozen `MOCK_SCENARIOS` fixture, since neither runs a backend.
  Live wiring detail: `docs/03-frontend.md`'s "`/table/[id]` wiring" (§6).

- **Testing a `*.svelte.ts` file's runes** (`$state`/`$effect`) needs the `vitest.config.ts`
  `client` project, not `server`: Vitest's default `node` environment still loads modules through
  Vite's SSR compile target even with `environment: 'jsdom'` set, and Svelte's server runtime
  never runs `$effect` (there's no DOM to react into) — silently a no-op, not an error, which is
  easy to mistake for "nothing subscribed yet" rather than "this never ran." The `client` project
  uses real browser mode (`@vitest/browser-playwright`, reusing the `playwright` install this repo
  already has for e2e/screenshots) so effects actually execute. Name the spec
  `*.svelte.spec.ts` to route it there automatically; a plain `.spec.ts` importing a `.svelte.ts`
  module still runs under `server` and any `$effect` inside it will silently never fire.
- `typescript` stays pinned to `^6.0.3`; TS7's native/Go compiler is installed alongside as
  `@typescript/native` (`npm:typescript@^7`) and used only via `svelte-check --tsgo` (wired into
  `pnpm check`). svelte-check's own CLI hard-requires the plain `typescript` package to resolve to
  TS6 (`require('typescript')` at its top level, peer range `^5 || ^6`) even in `--tsgo` mode, so
  TS7 can't be the primary dependency yet — flipping it makes svelte-check refuse to start.
  Tracked as a revisit-later item in `docs/99-deferred.md` once upstream TS7 tooling support
  lands — don't re-litigate this from scratch, read that entry first.

## Style

- Runes (`$state`, `$derived`, `$effect`), not legacy stores.
- DOM elements keyed by `tile_id` (own hand, revealed tiles) or by the positional id scheme for
  opponent backs (`docs/03-frontend.md §4`) so animation identity survives updates.
- Interactive controls live in DOM; so does everything else — there's no canvas to keep them out
  of.
- Motion is CSS transitions/animations driven by state changes, never a JS ticker.
- Stylesheets are SCSS (`<style lang="scss">`). `@use`, never `@import`; two levels of nesting
  max. Runtime-varying values are CSS custom properties, not Sass variables — see
  `docs/03-frontend.md §7.1`.
