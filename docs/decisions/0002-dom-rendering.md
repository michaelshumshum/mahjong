# 0002. DOM/CSS rendering, no PixiJS

- **Status:** Accepted
- **Date:** 2026-09-14

## Context

The first frontend plan rendered the table with PixiJS on a `<canvas>` under a Svelte overlay,
with a 1600×1000 letterboxed logical scene, @1x/@2x tile atlases, golden-PNG screenshot tests, and
an open question about a genuinely 3D table.

## Decision

The whole client, table surface included, is DOM/CSS ([frontend.md §2](../frontend.md)).

- ~150 static, axis-aligned tiles with no tick loop don't need a canvas renderer.
  Absolutely-positioned, `transform`-animated elements are GPU-composited anyway.
- DOM gives hit-testing, focus, tab order, live regions, CJK text and devtools for free; a canvas
  needs a parallel accessible representation.
- A letterboxed scene and a responsive phone layout are mutually exclusive — 16:10 on a 390×844
  phone leaves the table at ~35% of the screen.

Cut along with it:

| Item | Why |
| --- | --- |
| Pixi golden-PNG screenshot tests | no canvas scene to test. If a canvas renderer ever returns, golden-PNG tests are flaky across GPU/driver/font differences and need a flakiness budget |
| @1x/@2x tile atlas | SVG tiles are resolution-independent; there is no atlas or build step at all |
| 3D/2.5D table, Blender pre-rendered tiles | out of scope entirely. Reference asset pack if ever revisited: [libreriichi-assets](https://codeberg.org/davidgomez/libreriichi-assets) (CC0 textures + Blender sources) |

## Consequences

- The one canvas is the decorative background mural ([frontend.md §2](../frontend.md)).
- Keyboard play has one implementation shared with pointer and touch.
- Animated paths must stay `transform`/`opacity`-only.
