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
```

- `typescript` stays pinned to `^6.0.3`; TS7's native/Go compiler is installed alongside as
  `@typescript/native` (`npm:typescript@^7`) and used only via `svelte-check --tsgo` (wired into
  `pnpm check`). svelte-check's own CLI hard-requires the plain `typescript` package to resolve to
  TS6 (`require('typescript')` at its top level, peer range `^5 || ^6`) even in `--tsgo` mode, so
  TS7 can't be the primary dependency yet — flipping it makes svelte-check refuse to start.

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
