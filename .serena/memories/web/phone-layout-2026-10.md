# Phone table layout pass (2026-10-11)

- New `layout.phone-portrait` mixin (max-width 767 AND min-height 501) = phone-only minus phone-landscape.
- Portrait: hand wraps to 2 rows of 7 (flex-wrap, `.hand-tile-slot:nth-child(7n+1)` margin reset), row-gap = lift (0.4w); gutters trimmed in +page.svelte. Tile ~46px at 390.
- Opponent chips on phone: `.seat-hand-strip { display: contents }` so plate/backs/melds are one wrapping flex line; grid is one column `left/across/right/center/self` in portrait.
- Landscape (reworked 2026-10-13): box grid (across full width, left|right, pool-self on hand), CenterHub rendered in TableToolbar via `hub` snippet chosen by `MediaQuery(PHONE_LANDSCAPE_QUERY)` (lib/ui/breakpoints.ts — keep in sync with _layout.scss). Self bar: melds beside hand when ≤11 slots (`:has(.hand-tile-slot:nth-child(12))`), declare buttons on plate row. Claim = top sheet; hand-end/game-end two-column. late-hand fits 667x375/740x360/844x390 with ~0px spare at 360 — any added vertical chrome in landscape will break `a crowded late hand fits ...` e2e.
- Pre-commit hook `comment-length`: comment blocks max 2 lines.
- `pkill -f "<pattern>"` in Bash kills the Bash tool's own shell (pattern is in its cmdline) -> exit 144.
- Double-tap zoom: `html { touch-action: manipulation }`; NOT touchend preventDefault (kills synthesized click on iOS -> breaks two-step discard).
- Gotchas: `web/test-results/` may be root-owned (docker) -> run playwright with `--output /tmp/...`. Screenshot script re-renders desktop/lobby PNGs with pixel noise; revert unrelated ones before committing.
