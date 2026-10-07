# Frontend UX overhaul

P0 done (2026-10-06). P1 done (2026-10-06/07), committed directly to `main` throughout (no
branch, per that phase's instructions). **Phase complete: all 12 P1 items shipped.**

## P0 gotchas
- `_a11y.scss` is MIXINS ONLY; app.scss does `@include a11y.globals`. A component `@use`-ing a
  partial with top-level rules would re-emit them into its scoped CSS.
- `motion-ok`/`motion-reduced` mixins use `:global(html[...]) &` -> only valid inside a Svelte
  component selector, not in global SCSS. They raise specificity: a later `.x--variant { animation:
  none }` no longer overrides; exclude variants with `:not()` in the motion selector instead.
- html[data-motion] = clientPrefs.motion ('system'|'reduced'|'full'), set in root +layout.svelte
  (before children mount) and on Settings change (lib/ui/motion.ts).
- TileFace emits `data-tile="<code>"`; specs match on it since alt is a localized name.
- `.seat-region--self` is `container-type: inline-size`; `.hand-row` derives tile width from
  100cqi (44px floor -> negative-margin overlap, 63px cap). Grid side columns `minmax(88px, auto)`.
- Phone self region is `position: sticky` in its own grid row (`auto 1fr auto`), page scrolls.
- web/test-results is root-owned: run playwright with `--output <scratch>`. Browsers live in
  ~/.cache/ms-playwright. Run `node scripts/screenshot-pages.mjs` directly to avoid
  `playwright install` (`pnpm run screenshots` triggers it as a side effect).
- Commit hook comment-length: comment blocks max 2 lines, including inside commit messages
  themselves if they contain path-like strings (see below).

## P1 shipped, all 12 items
P1.1 felt/rim surface + tile thickness + CSS-jade backs + `--color-felt-muted`; P1.5 lastDiscard
marker; P1.6 bigger discard clamp + zone guide; P1.9 away/autoplay chips; P1.11 toast severity +
`--z-toast`; P1.12 tab title; P1.8 connection pill + ConnectionBanner; **P1.3** SeatPlate + turn
halo (replaces the old whole-region outline, which stays class-only on `.seat-region--turn` for
e2e compat) + "Your turn" prompt; **P1.2** CenterHub (wind/hand/wall/min-faan + 4 wind markers,
acting one glowing, carrying the turn ring only when `turnDurationMs` is non-null -- i.e. only
ever your own turn, since the protocol never gives this client an opponent's deadline); **P1.7**
ClaimDialog big buttons (CJK glyph + sub-label + 1-N/Esc key hint, initial focus on Pass, Win
hero-sized, bottom sheet below 768px) -- skipped the CSS-only `@property`/`counter()` seconds
readout (ring's aria-label already states it; deferred, not risking cross-browser quirks);
**P1.4** discardMode client pref (`'two-step'` default/`'one-tap'`), two-step lift (translateY +
z-index, hover preview on fine pointers) + pending/stalled spinner on the sent tile; **P1.10**
self-drawn win declare button is now a `.declare-btn--hero` (accent, bigger) vs secondary kongs.

Commits (chronological): 50d6d59, b402bde, 49a178b, d5cfe7b, 12d2918 (P0+early P1), then
(post-rebase onto f6a187f/bc50b83) 1caeebe (P1.3+P1.2+P1.10 bundled -- hero-win landed in the
same YourSeatRegion edit pass as the turn prompt, not worth re-deriving a split diff), fdfed0b
(P1.7), 09ffb56 (P1.4), 8ebd045 (fix: table.e2e.ts's motion test pointed at the ring's old
location), a87e69a (screenshots).

## P1 gotchas
- **`--color-text-muted` fails contrast on felt** (3.65:1, need 4.5). Fixed via a local
  `--color-text-muted: var(--color-felt-muted)` override on `.table-surface` -- every descendant
  mixin reading the token picks it up for free. Reuse this pattern for other token/bg clashes.
- `lastDiscard` existed pre-P1 (for `ClaimDialog`) but wasn't cleared on `meld` or surfaced to the
  pool marker -- a field's existing behavior doesn't cover a new feature just because the name
  matches; check what actually clears/reads it.
- **lefthook's comment-length check scans commit message prose too**, not just staged diffs -- a
  message mentioning a `server/...`/`docs/...` path by name can trip the routing-table hook
  message even when nothing under that dir changed. Avoid literal repo paths in commit prose.
- `git commit ... | tail -N` swallows git's real exit code -- always check `git log`/`git status`
  after, never rely on piped/truncated output alone.
- Opponent's turn deadline is genuinely not on the wire: `ClientGameState.deadlineTs` /
  `turnDurationMs` are this-seat-only (`live-view.ts`'s `turnDurationMsFromState`). CenterHub's
  non-self wind markers glow with no ring for this reason -- not a bug, a protocol limit noted in
  frontend.md §3. A real opponent countdown would need a wire field first.
- Svelte 5 test gotcha: a real `.click()`/`dispatchEvent()` in a `*.svelte.spec.ts` (client
  project, real browser mode) needs `flushSync()` (from `'svelte'`) right after, or the next
  assertion reads stale classList/DOM state -- state updates aren't synchronously flushed to the
  DOM by a raw DOM event the way Svelte's own event bindings are in this test harness.
  `bind:this` only accepts a plain identifier, not a per-iteration conditional in an `{#each}` --
  use a small `use:action` to capture one specific element's node instead (`ClaimDialog`'s Pass
  button ref, for `$effect`-driven initial focus).
- `isClientPrefs`-style storage validators: when adding a new required field to a persisted type,
  keep the validator checking only the *original* fields and migrate/default the new one inside
  the `load*` function, not inside the validator -- otherwise an old stored object is discarded
  wholesale instead of upgraded (`settings-storage.ts`'s `discardMode` migration).
- `live.e2e.ts` (opt-in, `RUN_LIVE_BACKEND_TESTS=1`, still untriaged/unrun in this sandbox per the
  P0 note) needed `addInitScript` on every context/page to force `discardMode: 'one-tap'` before
  navigation, since its discard-driving loops click `.hand-tile-btn` once and expect an immediate
  discard -- the new default (`two-step`) would just lift the tile instead. Not exercised this
  session (opt-in + real backend needed); typechecked and read-reviewed only, same caveat as
  before. `scripts/live-declare-click.mjs` needed no change -- it only clicks `.declare-actions`
  buttons, never `.hand-tile-btn`.
- Screenshot regen: lobby/tables/pregame pages always diff on the canvas mural's random tile
  placement even with zero code change behind them -- `git checkout` those back when they're not
  the page you actually touched, so the commit's screenshot diff matches its code diff.
- A pre-existing cosmetic quirk (not introduced this session, confirmed against the pre-P1.3
  screenshot): the hand-ended/game-ended mock scenarios leave `turn` pointing at a seat after
  `HAND_OVER`/`GAME_OVER`, so that seat's `SeatPlate` still shows the turn halo behind the
  overlay. Pre-existing on the old whole-region outline too (and worse there -- taller). Not
  fixed; would need the mock fixtures (or the reducer) to clear `turn` on hand/game end.

## Full-suite status at end of P1
`npx vitest --run`: 359 passed, 1 skipped. `npx playwright test` (non-live): 43 passed, 4 skipped
(the opt-in `live.e2e.ts` suite). `pnpm check` / `pnpm lint`: clean. Screenshots regenerated and
reviewed (`docs/screenshots/table-*`); `README.md` captions still accurate, left unchanged.

P1 is done -- no more deferred items from the original plan. Next phase (P2) scope isn't written
yet; candidates surfaced in passing but not acted on: per-discard announcements (frontend.md §9
"Designed, not implemented"), swipe-to-discard, the CSS-only claim-dialog countdown this session
skipped, `state_sync`'s lastDiscard gap outside an active claim window (§6 tradeoff).
