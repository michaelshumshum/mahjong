# Tech stack

- Server: Python >=3.13 (ruff target py313), uv (`package = false`), FastAPI, pydantic v2, SQLAlchemy async + asyncpg, alembic, pyjwt. Tests: pytest + pytest-asyncio (auto mode) + xdist + hypothesis.
- `mahjong` PyPI pkg is a dev-only shanten test oracle, not runtime.
- `ml` optional extra (torch, numpy, pettingzoo, pyarrow) — ml image target only; never import from `mahjong_core` (stdlib-only).
- Web: SvelteKit 2, Svelte 5 runes, Vite 8, SCSS (sass), adapter-node, vitest 5 (browser mode via @vitest/browser-playwright for `*.svelte.spec.ts`), playwright e2e, oxlint + oxfmt (not eslint/prettier).
- `typescript` pinned ^6; TS7 installed as `@typescript/native`, used only via `svelte-check --tsgo`. Don't flip — see `docs/99-deferred.md`.
- pnpm workspace at root; lefthook git hooks; commitlint.
- Postgres via docker compose.
