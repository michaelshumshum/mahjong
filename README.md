# 雀 — Browser Hong Kong Mahjong

[![server coverage](../../raw/badges/coverage-server.svg)](docs/infra.md#9-ci)
[![web coverage](../../raw/badges/coverage-web.svg)](docs/infra.md#9-ci)
[![Python 3.13](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Svelte 5](https://img.shields.io/badge/Svelte-5-FF3E00?logo=svelte&logoColor=white)](https://svelte.dev/)
[![PostgreSQL 17](https://img.shields.io/badge/PostgreSQL-17-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Hong Kong mahjong, browser-native and server-authoritative — full faan scoring, zero client trust.
Play solo against bots from Easy to a full-information "Impossible", or with friends by sharing a
table link.

**Stack:** Python 3.13 / FastAPI (REST + native WebSocket) · SvelteKit 2 + Svelte 5 (runes), DOM + SCSS · Postgres

## Features

- **Full HK ruleset** — faan table, claim priority, payouts, configurable `RuleSet` presets ([rules](docs/rules.md))
- **Bots from Easy to Impossible** — heuristic tiers, a self-play RL agent ("Expert") and a full-information `ORACLE` ([bots](docs/bots.md), [ml](docs/ml.md))
- **Structural anti-cheat** — per-seat redaction; clients never see what they shouldn't ([architecture §5, §9](docs/architecture.md))
- **Deterministic** — any hand reproduces from `(ruleset, seed, actions)` ([architecture §3](docs/architecture.md))

## Quick start

The toolchain (node 24, python 3.13, uv, pnpm) is pinned in [`mise.toml`](mise.toml). Docker runs
Postgres, and optionally the whole stack.

**Containers** (Docker only):

```bash
cp .env.example .env
make up            # postgres + api + web — web http://localhost:5173, api http://localhost:8000/docs
make migrate       # once per fresh database
make help          # everything else
```

**Native** (Postgres in Docker, everything else on the host):

```bash
mise install                          # pinned toolchain
cp .env.example .env
(cd server && uv sync --locked)       # add --extra ml for torch; a plain sync removes it
pnpm install --frozen-lockfile        # also installs git hooks (lefthook)

docker compose up -d postgres
export DATABASE_URL=postgresql+asyncpg://mahjong:mahjong@localhost:5432/mahjong
export CORS_ORIGINS=http://localhost:5173
(cd server && uv run alembic upgrade head && uv run uvicorn app.main:app --reload --workers 1)
pnpm --dir web dev                    # in a second shell
```

Native test and codegen equivalents of the `make` targets: [docs/infra.md §2](docs/infra.md).

## Screenshots

Captured from `/table/[id]`'s frozen mock-scenario fixture (`?mock=`) or its no-socket pre-game
preview (`?pregame=`) — both repeatable without a backend ([docs/frontend.md §7](docs/frontend.md)
"`/table/[id]` wiring"). Regenerate with `pnpm --dir web run screenshots` after any visible
frontend change (see `.claude/skills/frontend-screenshots/SKILL.md`).

| | |
| --- | --- |
| ![Lobby](docs/screenshots/lobby.png) Lobby (`/`) — create a table, practice vs bots, or open the faan guide, over a scrolling tile-mural canvas background | ![Lobby, create-table dialog](docs/screenshots/lobby-create-dialog.png) Lobby — create-table dialog: described rules presets or a custom ruleset (`POST /tables`, `docs/protocol.md §10`) |
| ![Lobby, practice dialog](docs/screenshots/lobby-practice-dialog.png) Lobby — practice setup: tap-to-cycle bot difficulty per seat | ![Tables](docs/screenshots/tables.png) Tables (`/tables`) — join by code, or sit down / watch from cards with a seat compass |
| ![Table, your turn](docs/screenshots/table-your-turn.png) Table — your turn to discard | ![Table, claim window](docs/screenshots/table-claim-window.png) Table — claim window open |
| ![Table, hand ended](docs/screenshots/table-hand-ended.png) Table — hand ended: result stamp, winning hand, faan rows, payments | ![Table, hand ended in a draw](docs/screenshots/table-hand-ended-draw.png) Table — hand ended, exhaustive draw |
| ![Table, game ended](docs/screenshots/table-game-ended.png) Table — game ended: placement, final standings with ties, play again | ![Table, settings](docs/screenshots/table-settings.png) Table — settings: calls, gameplay and display tabs |
| ![Table, connecting](docs/screenshots/table-pregame-connecting.png) Table — connecting | ![Table, take a seat](docs/screenshots/table-pregame-join.png) Table — take a seat |
| ![Table, waiting for players](docs/screenshots/table-pregame-waiting.png) Table — seated, waiting for players | |

Phone (390×844, one screen — the hand stays pinned to the bottom):

| | | |
| --- | --- | --- |
| ![Lobby, phone](docs/screenshots/lobby-phone.png) Lobby | ![Table, your turn, phone](docs/screenshots/table-your-turn-phone.png) Table — your turn | ![Table, claim window, phone](docs/screenshots/table-claim-window-phone.png) Table — claim window |
| ![Table, hand ended, phone](docs/screenshots/table-hand-ended-phone.png) Table — hand ended | ![Table, game ended, phone](docs/screenshots/table-game-ended-phone.png) Table — game ended | ![Table, late hand, phone](docs/screenshots/table-late-hand-phone.png) Table — late hand, crowded |

Phone held sideways (844×390 — opponents stacked beside the centre, no page scroll):

![Table, your turn, phone landscape](docs/screenshots/table-your-turn-phone-landscape.png)

![Table, late hand, phone landscape](docs/screenshots/table-late-hand-phone-landscape.png)

## Documentation

| Doc | Covers |
| --- | --- |
| [architecture.md](docs/architecture.md) | process model, table actor, claim window, redaction, failure handling, anti-cheat |
| [rules.md](docs/rules.md) | tiles, state machine, claim priority, faan table, payments, `RuleSet` |
| [protocol.md](docs/protocol.md) | WebSocket envelope, message catalog, reconnect/resync, codegen, HTTP |
| [frontend.md](docs/frontend.md) | rendering, layout, interaction, client state, routes, assets, a11y/i18n |
| [bots.md](docs/bots.md) | bot tiers, shanten/ukeire, the HK 3-faan trap, safety, arena, `ORACLE` |
| [ml.md](docs/ml.md) | self-play RL agent — in progress, plan and status |
| [infra.md](docs/infra.md) | repo layout, toolchain, local dev, Docker, database, deployment, CI |
| [testing.md](docs/testing.md) | test strategy, Vitest and pytest gotchas |
| [decisions/](docs/decisions/README.md) | ADR log: history, removed designs, deferred work |

## Layout

```
server/   Python. mahjong_core/ (pure rules, stdlib-only) + app/ (FastAPI, tables, WS) + bots/ + ml/
web/      SvelteKit 2 + Svelte 5. Lobby and table, DOM throughout, styled with SCSS.
shared/   Generated protocol JSON schema (make proto)
docs/     Reference docs + decisions/ (ADR log)
```

`uv` owns Python, `pnpm` owns JS, the `Makefile` is the Docker-based seam. Full tree:
[docs/infra.md §1](docs/infra.md).

## Compose profiles

| Command | Adds |
| --- | --- |
| `make up` | postgres, api, web |
| `make arena A=FaanBot B=EfficiencyBot N=20000` | one-shot bot evaluation (`tools`) |
| `docker compose --profile ml up trainer` | torch-enabled training container (`ml`) |

> `--workers 1` on the API is load-bearing: tables are in-memory objects owned by one process.
> [docs/infra.md §3](docs/infra.md)

## Testing

```bash
make test              # everything (server + web)
make test-server       # pytest, fast suite only
make test-server-slow  # pytest, slow suite: soaks, real-bot e2e, hypothesis runs
make test-web          # vitest + Playwright
```

`mahjong_core` is pure and tested directly, no mocks. CI runs the fast and slow suites in parallel
on every push ([docs/infra.md §9](docs/infra.md)); strategy and gotchas in
[docs/testing.md](docs/testing.md).

## Development

```bash
make fmt        # ruff format + oxfmt
make lint       # ruff check + pnpm lint
make typecheck  # svelte-check
make proto      # regenerate shared/protocol.schema.json + web TS types
```

`server/app/protocol.py` is the source of truth for the wire protocol; generated files
(`shared/`, `web/src/lib/net/protocol.d.ts`) are never hand-edited — `make proto-check` (CI)
fails the build if they drift.

## License

MIT — see [LICENSE](LICENSE). Bundled third-party assets (tile art) are credited in `NOTICE`; see
[docs/infra.md §10](docs/infra.md).
