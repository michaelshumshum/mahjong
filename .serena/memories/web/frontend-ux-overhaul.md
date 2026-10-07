# Frontend UX overhaul

**COMPLETE (2026-10-08).** P0–P4 all shipped. Remaining follow-ups listed at the bottom.

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
  P1-era regression the old comment already warned about). Self-pool direction: P3 believed
  it inverted at tablet-up; P4.8 measured it and it is NOT (each tile's own scaleY(-1) cancels the
  pool flip before the face's translate). Now pinned in screen space by CenterDiscardPool.svelte.spec.ts.
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

## P4 shipped (2026-10-07/08)
Commits (subjects): native dialog modals (P4.1), roving-tabindex hand (P4.2), live announcements
(P4.3), phone opponent chips + viewport-fit=cover (P4.4), contrast audit fixes + accent-on-dark
follow-up (P4.5), mock scenario disclosure (P4.7), short-landscape/desktop breakpoints + cqi
(P4.6), discard settle direction pin (P4.8), chip plate wrap fix, screenshots.

- **ModalDialog.svelte** (lib/ui): every overlay is a native `<dialog>` + showModal(). The
  dialog box itself is the full-viewport scrim (placement center/sheet/scroll). `cancel` is
  always preventDefault'ed and routed to `onCancel` (owner's `{#if}` unmounts it); no onCancel =
  not dismissable. Chrome force-closes a dialog after a second prevented cancel without user
  activation -> `close` handler reopens / treats as cancel. Focuses `[data-autofocus]` on open,
  restores focus to opener on unmount. ClaimDialog: no onCancel, its own window keydown does
  Escape=Pass (single path).
- **Top layer gotcha:** a `popover="manual"` toast stack DOES paint above the modal but is inert
  (no clicks, dropped from a11y tree -> role=alert not announced). Fix: `followTopmostDialog`
  attachment moves the element into the topmost open dialog and back. Element must be the ONLY
  child of a `display: contents` wrapper — svelte removes component DOM by walking sibling ranges,
  a moved range-end node would make it delete unrelated siblings. Used by ToastStack + Announcer.
- vitest browser mode supports showModal fine; dialog `close` event is async (await it).
- **Hand keyboard:** `.hand-row` role=toolbar (role=group + keydown trips svelte a11y warning),
  roving tabindex, default stop = last discardable (drawn tile), H shortcut with typing guard.
  `userEvent` from 'vitest/browser' for real Enter/Space -> click.
- **Announcer:** pure `announcementsBetween(prev,next,everyDiscard)` in announcements.ts (unit
  tested), handKey re-baselines; 300ms debounce, max 4 lines, zero-width-space toggle for repeats.
  New pref `announceAllDiscards` (default false) migrated in loadClientPrefs like haptics.
- **Breakpoints:** phone-only now = `max-width 767 OR max-height 500`; tablet-up = min-width 768
  AND min-height 501; phone-landscape layered on top; desktop-up 1180. `.table-surface` is
  `container: table / inline-size`, table sizes in cqi.
- **app.html had no viewport-fit=cover** -> every env(safe-area-inset-*) was 0 on iOS until P4.4.
- **Contrast:** `web/scripts/contrast-audit.mjs` parses _tokens.scss, composites layers, exits 1
  on failure. New token `--color-accent-on-dark` for accent text/icons on dark surfaces.
- **comment-length hook** checks the working tree, not just staged files — an unrelated unstaged
  over-long comment blocks a commit. Also: commit hook output hides failures if piped; check
  `git log -1` after.
- Partial-file commits without `git add -p`: `git hash-object -w --stdin` +
  `git update-index --cacheinfo` to stage an intermediate version.
- GitHub push returned 500 for ~10 min once; fetch worked. Just retry later.
- Final counts: vitest 418 passed/1 skipped; playwright 59 passed/4 skipped; live (practice
  mode|four real seats|game_end) 3 passed; check/lint clean. 18 screenshots (+phone-landscape).

## Follow-ups after the overhaul
- Live TableToolbar was not checked at 844x390 with a real game (mock toolbar was); it is one row
  but worth a look in the live landscape view.
- Opponent chips in landscape scroll their melds inside a third of the column; a seat with 3-4
  melds needs scrolling to see all of them.
- Game-end phone: score-sheet table clips horizontally inside its card (pre-existing).
- added_kong isn't announced (meld count doesn't grow, only kind changes).
- zh-Hant announcer/settings strings are machine-written, not reviewed by a fluent speaker.
- Sound (deferred), AUTOPLAY-handover banner, resync crossfade still "planned" in frontend.md.
