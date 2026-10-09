# Table header rail (2026-10-10)

- `TableToolbar` is the walnut rim's top edge; `.table-surface` has `border-top-width: 4px` and bottom-only radius to join it. `.table-page` has no flex gap for the same reason. Phone-landscape border is `4px 6px 6px`.
- Mock mode renders the same `TableToolbar` (no MockTableToolbar). Scenario = `?mock=<id>` only; `scenarioId` is `$derived` from the url.
- `/demo` lists scenario + `?pregame=` links and hosts `AnimationDemoPanel` (moved to `routes/demo/_components/`).
- e2e/screenshot scripts navigate to `?mock=<id>` instead of clicking scenario buttons.
- Gotcha: after deleting a .svelte file, `pnpm check` can report errors from stale `.svelte-kit/.svelte-check/` — `rm -rf` it.
