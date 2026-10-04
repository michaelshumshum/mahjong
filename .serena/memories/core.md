# mahjong — core

Browser multiplayer Hong Kong mahjong. Monorepo; Docker Compose runs everything (postgres + api + web).

## Source map
- `server/` — Python/FastAPI api, rules engine, bots. Module rules: `mem:server/core`
- `web/` — SvelteKit client (DOM + SCSS, no canvas). Module rules: `mem:web/core`
- `shared/protocol.schema.json` — generated from `server/app/protocol.py`, informational only
- `docs/` — reference docs (architecture, rules, protocol, frontend, bots, ml, infra, testing; index `docs/README.md`) + `docs/decisions/` ADR log (history, deferred designs)
- `.claude/hooks/enforce-routing-table.sh` — blocks edits to server/web/shared/infra until the matching doc (per root `CLAUDE.md` table) was read this session
- `Makefile` — the only seam between uv (python) and pnpm (js); all targets run inside compose containers

## Invariants
- Protocol types flow one way: `server/app/protocol.py` → `make proto` → `web/src/lib/net/protocol.d.ts` + `shared/`. Never hand-edit generated files; CI `proto-check` fails on drift.
- Games reproducible from `(ruleset, seed, actions)`.
- Docs updated in the same change as code.

Stack/versions: `mem:tech_stack`. Commands: `mem:suggested_commands`. Style/commit rules: `mem:conventions`. Done-checklist: `mem:task_completion`.
