# Frontend UX overhaul

P0/P1/P2 done. **P3 done (2026-10-07): P3.1(a-e), P3.3, P3.4 shipped.** Next: P4
(a11y/responsive — native dialog modals, keyboard hand model, live announcements, phone
opponents, contrast audit, breakpoints).

(See prior memory versions / `git log` for P0-P2 detail; summarized here only where P3 builds on
or changes it.)

## P3 shipped (2026-10-07)
Commits: 1096c39 (P3.1 a-c: hand reflow animate:flip, discard settle, meld slide-in), 069c533
(P3.1 d-e + P3.3: seal stamp, score-delta chips, haptics), 3916e43 (P3.4 mural tuning), 59e47cf
(screenshots).

- **P3.1(a)** `YourSeatRegion`'s hand tiles: `animate:flip` keyed by `tile.key` (tile_id-derived).
  `animate:` directive requires the each-block's sole child — the button/div swapping between
  interactive/static broke that, so a `.hand-tile-slot` wrapper div carries the each-block/
  animate, sized via the vars that used to live on `.hand-tile`; the inner element just fills it
  at 100%/100%. Kept `class:hand-tile--drawn` on the inner element too (not just the slot) since
  `table.e2e.ts` selects `.seat-region--self .hand-tile--drawn` directly — renaming/moving a
  class off a selector a spec already pins silently breaks it with no type error.
- **P3.1(b)** `CenterDiscardPool`'s landing tile: added a `--discard-enter-x/y`-driven `translate`
  (individual CSS property, not `transform`) to the existing scale pulse, `--ease-place`.
  Composes with the side pools' static rotate `transform` instead of overriding it (exactly the
  P1-era regression the old comment already warned about). Self-pool direction is approximate:
  the pool's own `scaleY(-1)` at tablet-up means the translate's visual direction is inverted
  there — cosmetic, not pinned by any test, left as a known minor nit.
- **P3.1(c)** `_tile.scss`'s new `meld-enter` mixin (`@include tile.meld-enter` beside
  `@include tile.meld` in both seat regions) promotes `AnimationDemoPanel`'s pre-existing
  `demo-meld-in` keyframe pattern into the real meld rows — plays automatically on DOM insert.
- **P3.1(d)/(e)** `SeatPlate` gained `sealStamp`/`scoreDelta` props (`{glyph|value, key}`, `key`
  forces the CSS entrance to replay via `{#key}` even on a repeat). `+page.svelte` derives both
  as transient, non-game-truth signals: sealStamp off a seat's `melds.length` growing between
  renders (glyph from meld `kind`: 碰/上/槓; win's 食糊 is *not* covered — that's already the
  existing `HandEndOverlay` stamp, scoping seal stamp to melds only was a deliberate cut), scoreDelta
  off `handResult.payments` appearing once per hand. Both: (1) gated on a `scenarioId:handNo` key
  so switching mock scenarios or starting a new hand resets the baseline instead of misreading a
  jump as "a call just happened", (2) skipped outright under `isMotionReduced()` rather than
  given a reduced-motion CSS variant — the information is redundant with state already visible
  elsewhere (the meld tile itself, the score sheet), so dropping it entirely was simpler and
  correct per "state changes always apply instantly; only motion is dropped" (frontend.md §9) —
  there's no *state change* here to preserve, just decoration. **Neither has a mock-scenario
  trigger** (frozen fixtures never produce the transition) — previewed instead on a real
  `SeatPlate` instance added to `AnimationDemoPanel` with dedicated buttons.
- **P3.3 haptics** `lib/ui/haptics.ts`'s `vibrate(ms)`: feature-detected to `(pointer: coarse)`,
  no-op elsewhere. New `ClientPrefs.haptics` (default `true`), migrated in `loadClientPrefs` the
  same way `discardMode` was (the `isClientPrefs` validator stays checking only the original
  fields, `haptics` is defaulted inside `loadClientPrefs`, not the validator — getting this
  backwards discards the whole stored object instead of upgrading it, per the P1-era gotcha).
  Fired in `+page.svelte` on the rising edge of "your turn" (`discardableTileIds.size > 0`) and
  "claim offer open" (`claimOptions` non-empty), both `!isMock`-gated.
- **P3.4 mural** `TileMuralBackground`'s canvas filter: `blur(4px) brightness(0.42)
  saturate(0.55)` (was `blur(3px) brightness(0.5)`, no saturate), scrim centre opacity raised
  0.6→0.72. Scrim/filter values only, scroll mechanism untouched.

## P3 gotchas
- `animate:` directive placement: Svelte 5 hard-requires the animated element be the each-block's
  *only* child — any `{#if}/{:else}` branching at that position throws
  `animation_invalid_placement` at `svelte-check` time (caught by `pnpm check`, not a runtime-only
  failure). Wrap in a container div and animate that instead; move sizing CSS to the wrapper.
- Renaming/relocating a class used only by an e2e selector (not in web/AGENTS.md's "keep stable"
  list, but still pinned by a spec) breaks silently — `pnpm check`/`vitest` won't catch it, only
  `playwright test` will (`table.e2e.ts`'s viewport-fit test hung 3x30s on
  `.seat-region--self .hand-tile--drawn` after the first wrapper-refactor pass here). Grep every
  class touched in a structural refactor against `*.e2e.ts` before considering it done.
- `check_comment_length.py`'s 2-line cap applies to `/** */` JSDoc blocks too, not just `//` —
  caught post-hoc by the pre-commit hook on `haptics.ts`'s doc comment.
- `git commit | tail -N` (or `| cat`) swallows the real exit code same as before (P1 memory) —
  this session re-learned it once more piping into `cat`; always check for the `[main <hash>]`
  line or a bare, unpiped `$?`.
- Individual CSS transform properties (`translate`/`rotate`/`scale`) compose with a static
  `transform` declaration on the same element without needing to parse/merge transform lists —
  this is the mechanism both the discard-settle and meld-enter animations lean on to coexist with
  the side pools'/rotated strips' own `transform: rotate(...)`. Reach for this instead of
  `transform` directly whenever animating something that shares an element with a rotation.
- Full suite at P3 end: `npx vitest --run` 378 passed/1 skipped; `npx playwright test` 48
  passed/4 skipped; `RUN_LIVE_BACKEND_TESTS=1 npx playwright test live.e2e -g 'practice
  mode|four real seats'` 2 passed; `pnpm check`/`pnpm lint` clean. 17 screenshots regenerated and
  reviewed.

## Notes for P4
- Overlays are still divs with `role=dialog`, no focus trap / native `<dialog>`.
- Hand has no roving tabindex; no live announcements for discards (frontend.md §9 "Designed, not
  implemented").
- Phone opponents' strips are cramped; mock toolbar eats ~400px on phone.
- `--color-text-muted` over the mural not contrast-audited (P3's mural darkening likely helps,
  not re-measured).
- P3.1(b)'s self-pool discard-settle direction is visually inverted at tablet-up (see gotcha
  above) — low priority, cosmetic only, would need a sign-flip on `--discard-enter-y` scoped to
  `.discard-pool--self` at the tablet-up breakpoint specifically.
