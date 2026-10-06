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
