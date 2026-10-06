# Frontend UX overhaul (branch feat/frontend-ux-overhaul)

P0 done (2026-10-06). Gotchas learned:
- `_a11y.scss` is MIXINS ONLY; app.scss does `@include a11y.globals`. A component `@use`-ing a partial with top-level rules would re-emit them into its scoped CSS.
- `motion-ok`/`motion-reduced` mixins use `:global(html[...]) &` -> only valid inside a Svelte component selector, not in global SCSS. They raise specificity: a later `.x--variant { animation: none }` no longer overrides; exclude variants with `:not()` in the motion selector instead.
- html[data-motion] = clientPrefs.motion ('system'|'reduced'|'full'), set in root +layout.svelte (before children mount) and on Settings change (lib/ui/motion.ts).
- TileFace emits `data-tile="<code>"`; specs match on it since alt is now a localized name (tile-name.ts). Never assert on `alt="z5 tile"`.
- Hand sizing: `.seat-region--self` is `container-type: inline-size`; `.hand-row` derives tile width from 100cqi (44px floor -> negative-margin overlap, 63px cap). Grid side columns are `minmax(88px, auto)`.
- Phone self region is `position: sticky` in its own grid row (rows `auto 1fr auto`), page scrolls on phone; no padding reservation.
- web/test-results is root-owned (from Docker): run playwright with `--output <scratch>`. Browsers live in ~/.cache/ms-playwright (no /opt/pw-browsers). Run `node scripts/screenshot-pages.mjs` directly to avoid `playwright install`.
- Commit hook comment-length: comment blocks max 2 lines.
- Phone 390 hand overlap leaves ~58% of each 44px tile visible: legibility is weak; P1 lift/two-step discard should show the lifted tile fully.

P1 (2026-10-06/07, committed directly to `main` per that phase's instructions, not a branch --
despite this memory's title). Shipped: P1.1 (felt/rim table surface, box-shadow tile thickness,
CSS-jade backs, `--color-felt-muted` contrast override), P1.5 (lastDiscard marker), P1.6 (bigger
discard clamp + felt-line zone guide), P1.9 (away/autoplay seat chips), P1.11 (toast severity +
`--z-toast` fix), P1.12 (tab title), P1.8 (connection pill + ConnectionBanner). Commits: 50d6d59,
b402bde, 49a178b, d5cfe7b, 12d2918.

**Not built this session** (scope too large for one pass; do these next, in roughly this order
since P1.3/P1.2 touch files P1.7/P1.4 also need): P1.3 (seat plates, turn glow), P1.2 (CenterHub),
P1.4 (discard modes/pending state), P1.7 (claim dialog upgrade), P1.10 (self-drawn win hero
button). None of these have any scaffolding yet beyond what P1.1/P1.5/P1.8/P1.9/P1.11 touched in
passing (e.g. `.seat-region--turn`'s outline still exists, untouched, on `OpponentRegion`).

Gotchas from this pass:
- **`--color-text-muted` fails contrast on the new felt background** (3.65:1, need 4.5). Fixed by
  setting `--color-text-muted: var(--color-felt-muted)` as a local custom-property override on
  `.table-surface` -- every descendant mixin that reads the token (seat-wind, seat-score, …) picks
  up the felt-safe value for free, no per-component edit needed. Reuse this pattern for any other
  token/background pairing that turns out to clash once the felt is actually painted.
- `lastDiscard` already existed in the reducer/state before P1 (built for `ClaimDialog`'s
  `sourceSeat`/`tile`) but wasn't cleared on `meld` and wasn't surfaced to the view layer for a
  pool marker -- don't assume a field's existing behavior covers a new feature just because the
  name matches; check what clears it and what reads it.
- `state_sync`'s `lastDiscard` derivation is scoped to "there's an embedded claim window" --
  outside an active claim window a resync loses the last-discard marker until the next real
  discard. Accepted/documented tradeoff, not a bug, but worth fixing properly if P1.7's claim
  dialog work touches this same code.
- **lefthook's comment-length check scans literal path-like strings in commit messages too**, not
  just staged file diffs -- a commit message mentioning `server/app/ws.py` or `docs/frontend.md`
  by path triggers "AGENTS.md context-triggers table: reference X before writing to Y" even though
  nothing under `server/` is being touched. Avoid literal repo paths in commit message prose;
  describe the file by name without the directory, or read the flagged docs preemptively.
- `git commit ... | tail -N` swallows the real exit code (tail's, not git's) -- a commit that
  actually failed (hook rejection) can look like it succeeded if you only read the printed output.
  Always check `git log`/`git status` after a commit, or avoid piping to `tail` at all.
- `pnpm run screenshots` (the package.json script) runs `playwright install chromium` as a side
  effect -- contradicts the "never run playwright install" env gotcha above. Use
  `node scripts/screenshot-pages.mjs` directly for regens within a session where chromium is
  already installed, to avoid the redundant download.
- `live.e2e.ts` (RUN_LIVE_BACKEND_TESTS=1) timed out waiting for the real uvicorn backend to
  become reachable in this sandbox (ApiConnectGate showed "Can't reach the server" after the 60s
  test timeout) -- untriaged; could be `uv run uvicorn` startup being slow with the `ml` extra
  installed (torch import cost) or a port/networking quirk. Not part of `make test`/`pnpm test`,
  so it didn't block this session, but the P1.12 tab-title assertion added to that file's first
  test is unverified end-to-end -- only typechecked and read-reviewed.
