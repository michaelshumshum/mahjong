# Phone table layout pass (2026-10-11)

- New `layout.phone-portrait` mixin (max-width 767 AND min-height 501) = phone-only minus phone-landscape.
- Portrait: hand wraps to 2 rows of 7 (flex-wrap, `.hand-tile-slot:nth-child(7n+1)` margin reset), row-gap = lift (0.4w); gutters trimmed in +page.svelte. Tile ~46px at 390.
- Opponent chips on phone: `.seat-hand-strip { display: contents }` so plate/backs/melds are one wrapping flex line; grid is one column `left/across/right/center/self` in portrait.
- Landscape: self region is grid 'plate melds' / 'hand hand'; tile w clamp(44, min(fit, 16dvh*3/4), 56).
- Double-tap zoom: `html { touch-action: manipulation }`; NOT touchend preventDefault (kills synthesized click on iOS -> breaks two-step discard).
- Gotchas: `web/test-results/` may be root-owned (docker) -> run playwright with `--output /tmp/...`. Screenshot script re-renders desktop/lobby PNGs with pixel noise; revert unrelated ones before committing.
