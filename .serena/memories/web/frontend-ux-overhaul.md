# Frontend UX overhaul

P0 done (2026-10-06). P1 done (2026-10-06/07). **P2 done (2026-10-07): all 7 items shipped.**
All committed directly to `main` (no branch). Next: P3 (gameplay motion), P4 (a11y/responsive).

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

## P2 shipped (2026-10-07), all 7 items
63df80a P2.1 lobby (seal + visible display h1, tagline, 3 equal cards, quiet join/language links,
radial scrim); 1c6bf9f P2.2 OptionRow `description` + preset copy + practice tier legend;
6652387 P2.3 invite (`lib/ui/share-invite.ts` shareOrCopy, big code chip, 2s reset, hidden in
practice); cf65477 P2.4 hand-end reveal (stamp, timer in header, staggered tiles/rows, payment
plates) + `haloTurn` halo fix; 1291d4e P2.5 game-end (rank.ts `placements` competition ranking,
"Game over", you-placed line, Play again); e129f3b sticky-hand fix; 18f3902 P2.6 coach marks +
toolbar Guide; a4f314e P2.7 tables compass/empty state/refresh stamp; 1ff8ce0 screenshots.

## P2 gotchas
- **`.table-surface` must be `overflow: clip`, never `hidden`**: `hidden` makes it a scroll
  container and the phone self row's `position: sticky` sticks inside the surface, not the
  viewport -- the hand scrolled off-screen once the page outgrew the screen. Masked until the mock
  toolbar grew a row; `table.e2e.ts` now pins 390x700.
- **Pre-commit typechecks the working tree, not the index.** To commit a split hunk while other
  WIP is unstaged: `git stash push --keep-index --include-untracked`, commit, `stash pop`. Also
  `rm -rf web/.svelte-kit/.svelte-check` if a stashed new .svelte file leaves stale errors.
- comment-length counts a run of adjacent `//` lines as one block (max 2) -- appending a line
  under an existing 2-line comment fails the hook.
- `toHaveText('Create a table')` on the lobby testid is a full match: the card's `<button>` holds
  only the title; description sits outside, wired by `aria-describedby`, `::after` stretches the hit
  area. Same trick if a labelled card ever needs a sub-line.
- Play again uses `window.location.assign`, not `goto`: SvelteKit reuses the `/table/[id]`
  component and its local flags (game-started heuristic, dismissals) would leak into the new table.
- Last practice tiers live in `mahjong:practiceSetup:v1` (also prefills the dialog); coach marks
  in `mahjong:onboarding:v1`. Coach marks gate on `handNo === 1`, so no mock scenario shows them
  (all mocks are hand 3+); verified visually with a temporary override, not committed.
- `HandEndOverlay` renders no `DialogTimer` when `handEndHoldMs` is null -- a 0ms timer would
  auto-close instantly. Neither mocks nor the reducer clear `turn` at hand/game end; `+page`
  passes `haloTurn = -1` while a result overlay is up.
- Mocking `GET /tables` in ad-hoc scripts: response is `{ tables: [...] }`, and a `**/tables`
  glob also matches the page navigation -- filter on `resourceType() === 'fetch'`.
- `lib/net/lobby` mocks in `routes-tests` must list every export a child imports
  (`CreateTableDialog` needs `createTable`), or the suite fails at import time.

## Full-suite status at end of P2
`npx vitest --run`: 378 passed, 1 skipped. `npx playwright test`: 48 passed, 4 skipped (opt-in
live suite, still not run here). `pnpm check`/`pnpm lint` clean. 17 screenshots reviewed.

## Notes for P3/P4
- P3 motion: discard/draw/claim still have no `animate:flip`; staggered reveals use `--i` custom
  property delays (FaanBreakdown/GameEndScreen) -- reuse that pattern. Mural is still bright on
  the felt-less pages; scrim tuned only by radial gradient + brightness(0.5).
- P4: overlays are divs with role=dialog, no focus trap / native `<dialog>`; hand has no roving
  tabindex; no live announcements for discards; phone opponents' strips are cramped and the mock
  toolbar eats ~400px on phone; contrast of `--color-text-muted` over the mural not audited.
