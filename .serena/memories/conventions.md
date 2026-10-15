# Conventions

- Commits: `action(scope): description` (commitlint). Small, single-purpose; no refactor+behaviour mix.
- Comments: only non-inferable decisions; terse, lowercase; no banners/section dividers.
- New behaviour ships with a test; bugs get a failing regression test first.
- `mahjong_core` tested directly — no mocks, no I/O. Golden fixtures (`tests/replays/`, scoring hand suite) are data and required.
- New deps need a reason beyond convenience.
- Docs (`docs/`) are outlines: tables/lists over prose; rationale only where non-obvious.
- Python: ruff (line 100), frozen dataclasses for state, fully typed, `async def` only for real I/O.
- Svelte: runes not stores; SCSS `@use` never `@import`, max 2 nesting levels; runtime values as CSS custom properties; motion via CSS, never JS ticker.

- Types/constants: define once in the concept-owning module, import everywhere; no catch-all constants/types file; wire enums via `make proto`; named constants over bare 34/27/9. Keep-local exceptions + ownership tables: root `AGENTS.md` "Types and constants", `server/AGENTS.md` / `web/AGENTS.md` "Where things live".

Module-specific rules: `mem:server/core`, `mem:web/core`.
