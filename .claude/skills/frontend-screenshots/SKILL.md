---
description: Regenerate and commit screenshots of the app's notable pages after a frontend UI change, and keep README.md's Screenshots section in sync. Trigger phrases - "take screenshots", "show me the frontend", "update the screenshots", or any frontend sub-task that changes what a notable page looks like.
---

# Frontend screenshots

This project commits a small set of PNG screenshots (`docs/screenshots/*.png`) so anyone
reading the repo — human or agent — can see what the app actually looks like without running
it. `web/AGENTS.md` requires this after any frontend change that's visible on one of the
notable pages; this skill is the mechanics.

## When to run this

After any frontend sub-task that changes what a **notable page** (see the list in
`web/scripts/screenshot-pages.mjs`) looks like — new component wired into a page, layout
change, new mock scenario worth showing, a visual bug fix. Not needed for changes with no
visible surface (a pure logic module, a test-only change, a refactor with identical output).

## Run it

```sh
pnpm --dir web run screenshots
```

(`node web/scripts/screenshot-pages.mjs` skips the script's `playwright install chromium`
step when the browser is already installed.)

This is fully self-contained: it starts its own dev server on a scratch port (5199, distinct
from the normal dev port so it can run alongside `pnpm dev` without colliding), waits for it to
actually respond (polls, never a fixed sleep), captures every page in the list, and shuts the
server down again — safe to run repeatedly with no manual setup and no leftover processes.

Output lands in `docs/screenshots/<name>.png`, one file per entry in the `PAGES` list at the
top of `web/scripts/screenshot-pages.mjs`.

## After running it

1. **Look at the screenshots.** Not just "did the script exit 0" — actually view them. This is
   what caught a real bug: the rotated opponent hand-strip CSS (`transform: rotate(90deg)` on
   `.seat-hand-strip--left/--right`) visually escaping its grid column, invisible from reading
   the code or from `pnpm test` but obvious in a screenshot.
2. **Commit the changed files** under `docs/screenshots/` alongside the code change that caused
   them to change — same commit, not a separate one, so the screenshot always matches the code
   it documents.
3. **Update `README.md`'s Screenshots section** if you added, removed, or meaningfully changed
   what a page shows. Keep the embedded set curated (the entries listed below), not exhaustive —
   don't add a screenshot for every mock scenario, only for genuinely
   distinct, notable pages.

## Editing the notable-pages list

Add/remove entries in the `PAGES` array in `web/scripts/screenshot-pages.mjs` — each entry is
`{ name, url, before?, viewport? }`, where `before(page)` is an optional Playwright action
(open a panel, wait out a reveal; pick a mock scenario via `?mock=<scenarioId>` in the url) run after navigation and before the screenshot, and
`viewport` is `DESKTOP` (default, 1400×900, full-page capture) or `PHONE` (390×844, viewport-only
capture — one phone screen, sticky hand footer included). Keep names stable once they're
referenced from `README.md`; phone variants use a `-phone` suffix.

## Current notable pages

Desktop: `lobby`, `lobby-create-dialog`, `tables`, `table-your-turn`, `table-claim-window`,
`table-hand-ended`, `table-hand-ended-draw`, `table-game-ended`, `table-settings`,
`table-pregame-connecting`, `table-pregame-join`, `table-pregame-waiting`.

Phone (390×844): `lobby-phone`, `table-your-turn-phone`, `table-claim-window-phone`,
`table-hand-ended-phone`, `table-game-ended-phone`, `table-late-hand-phone` (full pools, heavy
melds); landscape (844×390): `table-your-turn-phone-landscape`, `table-late-hand-phone-landscape` — the
phone layout (docs/frontend.md §3) differs enough that a desktop capture says nothing about it.
Look at these after any layout change too.

See `README.md`'s Screenshots section for the embedded images.

## Live pre-game states: `?pregame=`, not a real backend

The `/table/[id]` connecting / sit-down / waiting-for-players states (docs/frontend.md's
"`/table/[id]` wiring") only ever occur on the real `liveStore`-driven path — `?mock=` always
renders a fully-seated, already-dealt table (`tableReady` is unconditionally true when
`isMock`), so there's no `MOCK_SCENARIOS` entry that could stand in for "not seated yet" or
"seated, waiting for others" the way the other three table screenshots reuse existing mock
scenarios.

Rather than have this script spawn a second real process (`uv run uvicorn`, matching
`live.e2e.ts`'s heavier opt-in setup) just for three static captures, `+page.svelte` accepts
`?pregame=connecting|join|waiting` — same "repeatable, no backend running" posture `?mock=`
already gives this script. It freezes the page on one of the three pre-game states without ever
constructing a real `MahjongSocket`: the socket-opening `$effect` early-returns when
`pregamePreview !== null`, and `effectiveConnection`/`effectiveSeat` (computed alongside it) feed
the same template branches a real `liveStore` would drive. The `waiting` variant reuses whatever
`MOCK_SCENARIOS[0]`'s dealer happens to be (via the existing `gameState` fallback) to compute a
real-looking seat wind — illustrative, not tied to any particular scenario's content.

If you need to see the _real_ sequence (not the frozen preview) — e.g. after touching the
`$effect` that opens the socket, or `GameStore`/`MahjongSocket` themselves — that still needs a
real backend: `uv run uvicorn app.main:app` from `server/`, `PUBLIC_WS_URL` pointed at it, and
`/table/<id>` opened in 1-4 browser contexts (`live.e2e.ts` already does exactly this, opt-in
via `RUN_LIVE_BACKEND_TESTS=1`). Not part of this script — too slow and too flaky (two extra
real processes) to run on every screenshot regen.

## Troubleshooting

- **`sudo: a terminal is required...` during `playwright install`**: don't use `--with-deps` —
  it tries to `apt-get install` system libraries via `sudo`, which fails in this sandboxed
  environment (no TTY, no askpass configured). Plain `playwright install chromium` (browser
  binary only, no system deps) works fine here and is what the `screenshots` script actually
  runs — the missing system libs it warns about aren't needed for chromium to launch and render
  correctly on this host.
- **Script hangs after printing the last "captured" line**: this bit us once — `pnpm exec vite
dev` is a wrapper that doesn't forward `SIGTERM` to the real vite process it spawns, so
  killing just the wrapper's PID leaves vite (and the event loop it holds open via its stdio
  pipes) running forever. The script spawns the dev server `detached: true` and kills the whole
  process group (`process.kill(-pid, 'SIGTERM')`) plus calls `process.exit()` explicitly at the
  end for exactly this reason — if you modify the spawn/cleanup logic, keep both of those.
