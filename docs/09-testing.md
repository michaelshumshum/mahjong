# 09 — Testing

General policy — commands, `mahjong_core` purity, golden fixtures, seeded determinism — lives in
root `AGENTS.md`'s Testing section. This doc is the implementation-level follow-up: the
hard-won "why this specific spec needs that specific setup" gotchas that don't belong inline in
`web/AGENTS.md` or `server/AGENTS.md`.

## 1. Web (Vitest)

### 1.1 `client` vs `server` project — runes need a real browser

A `*.svelte.ts` file's runes (`$state`/`$effect`) must run under `vite.config.ts`'s vitest
`client` project, not `server`. Vitest's default `node` environment still loads modules through
Vite's SSR compile target even with `environment: 'jsdom'` set, and Svelte's server runtime never
runs `$effect` — there's no DOM to react into, so it silently no-ops instead of erroring. That
reads like "nothing subscribed yet," not "this never ran," which makes it easy to miss.

The `client` project uses real browser mode (`@vitest/browser-playwright`, reusing the
`playwright` install this repo already has for e2e/screenshots) so effects actually execute.
Name the spec `*.svelte.spec.ts` to route it there automatically — a plain `.spec.ts` importing a
`.svelte.ts` module still runs under `server`, and any `$effect` inside it never fires.

### 1.2 Mounting a `.svelte` component — `test-render.ts` vs inline mount

Mounting a `.svelte` component directly (not just its logic) in a `*.svelte.spec.ts` spec:
`lib/table/test-render.ts` (`render`/`cleanup`/`cleanupAll`, wrapping Svelte's own
`mount`/`unmount`) is the shared helper for table-surface specs — `afterEach(cleanupAll)` covers
specs that don't hold on to each `render()` result individually.

Rendering a route's top-level `+page.svelte` needs SvelteKit context the table-surface components
don't (`$app/navigation`, `$lib/net/lobby`'s `$env/dynamic/public` — see §1.4), so
`routes-tests/*.svelte.spec.ts` mount inline with plain `mount`/`unmount` instead of this helper.
`test/mocks.ts` (`createMessagesProxy`) covers what those routes need mocked.

### 1.3 `vi.mock`/`vi.hoisted` under the `client` project's real browser mode

Vite's import-analysis transform rewrites every static `import` into an awaited dynamic
`import()`, so any code that runs *synchronously* before those imports resolve — a
`vi.hoisted()` callback's body, in particular — can't reference an imported binding. Referencing
one throws `[vitest] There was an error when mocking a module` at hoist time, not at the call
site, which reads like the mock itself is broken rather than a timing issue.

`vi.mock(...)`'s own factory is fine referencing an import, since factories run lazily (after the
mocked module is actually requested, i.e. after imports have resolved) — confirmed by
`routes-tests/tables/TableCard.svelte.spec.ts`'s working
`vi.mock('$lib/paraglide/messages.js', () => ({ m: createMessagesProxy() }))` with no
`vi.hoisted` involved.

When a factory needs data from module scope (a fixture array, a prior `vi.fn()`), the safe
pattern is a **dynamic `import()` inside the factory itself** (see
`routes-tests/lobby/page.svelte.spec.ts`), not a reference to any outer-scope variable — even one
declared via `vi.hoisted()`.

To assert against or configure a mocked function afterwards, import the real binding
(`import { goto } from '$app/navigation'` after
`vi.mock('$app/navigation', () => ({ goto: vi.fn() }))`) rather than threading a separately-held
mock reference through the file.

### 1.4 `$env/dynamic/public` must be mocked for anything touching `$lib/net/lobby`

A route pulling in `$lib/net/lobby` (directly, or transitively through a child component like
`TableCard`) needs `$env/dynamic/public` mocked too:

```ts
vi.mock('$env/dynamic/public', () => ({ env: {} }))
```

That module is only populated by SvelteKit's own dev/build server at request time, so under
Vitest it's `undefined` — `lobby.ts`'s `apiBaseUrl()` reading `env.PUBLIC_API_URL` throws before
the component even renders.

## 2. Server (pytest)

No implementation-level gotchas beyond root `AGENTS.md`'s Testing section (slow-marker split,
golden fixtures, determinism) and `server/AGENTS.md`'s Commands table. Add them here, not inline,
as they turn up.
