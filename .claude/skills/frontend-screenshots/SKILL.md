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
   what a page shows. Keep the embedded set curated (the 5 entries below), not exhaustive —
   don't add a screenshot for every mock scenario or dev-toolbar state, only for genuinely
   distinct, notable pages.

## Editing the notable-pages list

Add/remove entries in the `PAGES` array in `web/scripts/screenshot-pages.mjs` — each entry is
`{ name, url, before? }`, where `before(page)` is an optional Playwright action (click a
scenario button, open a panel) run after navigation and before the screenshot. Keep names
stable once they're referenced from `README.md`.

## Current notable pages

`home`, `lobby`, `table-your-turn`, `table-claim-window`, `table-hand-ended` — see
`README.md`'s Screenshots section for the embedded images.

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
