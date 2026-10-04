# i18n Phase 10 (tests & QA) — done, 2026-09-28

Full plan: `mem:web/core`, `docs/frontend.md` §9.

## What changed
- Converted fragile English-text e2e selectors to `data-testid`/stable classes for core flows only
  (lobby create-table/practice-vs-bots, tables list join/watch/rejoin, claim win/pung, hand-end
  close, settings/score-sheet toggles, seat-join in `live.e2e.ts`). New testids added to:
  `CloseButton.svelte` (`close-button`), `TableToolbar`/`MockTableToolbar` (`toggle-settings`,
  `toggle-score-sheet`), lobby `+page.svelte` (`lobby-create-table`, `lobby-practice-bots`,
  `lobby-join-game-link`), `TableCard.svelte` (`table-card-action`, same id on all 3 branches —
  scope queries to a specific card), `JoinByCodePanel.svelte` (`join-by-code-input`/`-submit`),
  `CreateTableDialog.svelte` (`create-table-dialog`/`-submit`), `PracticeSetupDialog.svelte`
  (`practice-setup-dialog`/`-start-submit`), `PracticeDifficultySlot.svelte` (new required prop
  `testId`, all 3 call sites in `PracticeSetupDialog` pass `practice-difficulty-{left,right,across}`).
  Claim Win/Pung assertions switched to the pre-existing `.claim-btn--{kind}` classes instead —
  zero component change needed there.
- Deliberately left alone: `MOCK_SCENARIOS`/`MockTableToolbar` scenario-picker labels and
  `AnimationDemoPanel` controls (e2e fixture data, not real copy — `web/AGENTS.md`),
  `ApiConnectGate` copy in `page.e2e.ts` (still byte-identical post-migration), form `getByLabel`
  selectors (real semantic interactions, not presence checks), and the "route renders" h1 sanity
  checks on replay/profile/table (generic smoke tests, not core flow).
- New `web/src/lib/i18n/locale-switch.e2e.ts`: switches locale via the UI on `/demo` (no backend
  needed — `ApiConnectGate` skips `/demo`), asserts `PARAGLIDE_LOCALE` cookie + zh-Hant lobby copy
  on next nav + survives reload, plus an English-default case.
- New `web/src/hooks.server.e2e.ts`: fetches `/` via Playwright's `request` fixture (no browser)
  with/without the locale cookie, asserts raw SSR `<html lang="en" dir="ltr">` /
  `<html lang="zh-Hant" dir="ltr">`. Nothing client-side ever touches `<html lang>` post-hydration.
- Screenshots regenerated and diffed: all 12 changed but only in `TileMuralBackground`'s randomized
  tiles (confirmed by extracting the pre-change PNGs via `git show HEAD:...` and eyeballing) —
  reverted via `git checkout -- docs/screenshots`, not a real diff.

## Known gap found in this phase — since fixed
`PracticeSetupDialog.svelte` + `PracticeDifficultySlot.svelte` had hardcoded English outside their
`aria-label`/title (Phase 8 only covered those): hint text, Cancel/Start/Starting… buttons,
Across/Left/Right-opponent/You captions, the create-error message, Easy/Normal/Impossible labels.
Migrated to `m.*` and translated into `zh-Hant.json` in a follow-up change, which also added
`web/AGENTS.md`'s "No literal user-facing strings" rule so new components don't repeat this.

## Verified green (post `pnpm run format` too)
`pnpm run paraglide:compile && pnpm run test:unit -- --run && pnpm run check && npx playwright test`
— 210 unit passed/1 skipped, svelte-check 0 errors, e2e 36 passed/4 skipped (the opt-in
`RUN_LIVE_BACKEND_TESTS=1` `live.e2e.ts` suite, expected). `pnpm run lint` also clean.
