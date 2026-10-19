# Hoi Toi — Hong Kong Mahjong

*開枱 · "open a table"*

[![server coverage](../../raw/badges/coverage-server.svg)](docs/infra.md#9-ci)
[![web coverage](../../raw/badges/coverage-web.svg)](docs/infra.md#9-ci)
[![Python 3.13](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Svelte 5](https://img.shields.io/badge/Svelte-5-FF3E00?logo=svelte&logoColor=white)](https://svelte.dev/)
[![PostgreSQL 17](https://img.shields.io/badge/PostgreSQL-17-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Hoi Toi is an open-source, browser-based implementation of Hong Kong mahjong. The server is
authoritative: it runs the complete ruleset, including faan scoring and payouts, and sends each
player only the information their seat is entitled to see. Players can practise solo against
computer opponents ranging from Easy to a full-information "Impossible" tier, or play with
friends by sharing a table link.

## Contents

- [Features](#features)
- [Screenshots](#screenshots)
- [Architecture](#architecture)
- [Getting started](#getting-started)
- [Development](#development)
- [Testing](#testing)
- [Project structure](#project-structure)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)

## Features

- **Complete Hong Kong ruleset.** Faan table, claim priority and payouts are implemented in full,
  with configurable `RuleSet` presets and per-table custom rules ([rules](docs/rules.md)).
- **Computer opponents at four levels.** Easy and Normal are heuristic bots, Expert is a
  self-play reinforcement-learning agent, and Impossible (`ORACLE`) adds full-information play on
  top of it ([bots](docs/bots.md), [ml](docs/ml.md)).
- **Server-side anti-cheat.** Game state is redacted per seat before it leaves the server, so a
  client never receives hidden tiles ([architecture §5, §9](docs/architecture.md)).
- **Deterministic replay.** Every hand can be reproduced exactly from `(ruleset, seed, actions)`
  ([architecture §3](docs/architecture.md)).
- **Responsive interface.** The table layout adapts to desktop, phone portrait and phone landscape
  without page scrolling ([frontend](docs/frontend.md)).

## Screenshots

| | |
| --- | --- |
| ![Lobby](docs/screenshots/lobby.png) Lobby (`/`) — play online, practice vs bots, or open the faan guide, over a scrolling tile-mural canvas background | ![Table, your turn](docs/screenshots/table-your-turn.png) Table — your turn to discard |
| ![Table, hand ended](docs/screenshots/table-hand-ended.png) Table — hand ended: result stamp, winning hand, faan rows, payments | ![Table, your turn, phone](docs/screenshots/table-your-turn-phone.png) Table — your turn, phone |

<details>
<summary><strong>Desktop gallery</strong></summary>

| | |
| --- | --- |
| ![Create-table dialog](docs/screenshots/lobby-create-dialog.png) Tables — create-table dialog: described rules presets (`POST /tables`, `docs/protocol.md §10`) | ![Custom rules](docs/screenshots/lobby-create-custom.png) Tables — custom rules: tabbed editor seeded from a preset, with a change count, dependent switches and faan overrides |
| ![Lobby, practice dialog](docs/screenshots/lobby-practice-dialog.png) Lobby — practice setup: tap-to-cycle bot difficulty per seat | ![Tables](docs/screenshots/tables.png) Tables (`/tables`) — join by code, or sit down / watch from cards with a seat compass |
| ![Table, claim window](docs/screenshots/table-claim-window.png) Table — claim window open | ![Table, hand ended in a draw](docs/screenshots/table-hand-ended-draw.png) Table — hand ended, exhaustive draw, with the provable-fairness check |
| ![Table, game ended](docs/screenshots/table-game-ended.png) Table — game ended: placement, final standings with ties, play again | ![Table, settings](docs/screenshots/table-settings.png) Table — settings: calls, gameplay and display tabs |
| ![Table, connecting](docs/screenshots/table-pregame-connecting.png) Table — connecting | ![Table, take a seat](docs/screenshots/table-pregame-join.png) Table — take a seat |
| ![Table, waiting for players](docs/screenshots/table-pregame-waiting.png) Table — seated, waiting for players | |

</details>

<details>
<summary><strong>Phone gallery</strong> (390×844 portrait; 844×390 landscape)</summary>

| | | |
| --- | --- | --- |
| ![Lobby, phone](docs/screenshots/lobby-phone.png) Lobby | ![Table, claim window, phone](docs/screenshots/table-claim-window-phone.png) Table — claim window | ![Table, hand ended, phone](docs/screenshots/table-hand-ended-phone.png) Table — hand ended |
| ![Table, game ended, phone](docs/screenshots/table-game-ended-phone.png) Table — game ended | ![Table, late hand, phone](docs/screenshots/table-late-hand-phone.png) Table — late hand, crowded | |

In landscape, opponents are stacked beside the centre of the table and the page does not scroll:

![Table, your turn, phone landscape](docs/screenshots/table-your-turn-phone-landscape.png)

![Table, late hand, phone landscape](docs/screenshots/table-late-hand-phone-landscape.png)

</details>

Screenshots are generated from frozen fixtures without a running backend; regenerate them with
`pnpm --dir web run screenshots` ([frontend §7](docs/frontend.md)).

## Architecture

```mermaid
flowchart LR
    B["Browser<br/>SvelteKit 2 · Svelte 5"]
    subgraph API["FastAPI process (single worker)"]
        S["WebSocket session"]
        T["Table actor<br/>one asyncio task per table"]
        C["mahjong_core<br/>pure rules engine"]
        BOT["Bots"]
    end
    DB[("PostgreSQL<br/>finished games")]

    B <-->|"WebSocket + REST"| S
    S --> T
    T -->|"reduce(state, action)"| C
    BOT -->|"per-seat view"| T
    T --> DB
```

Each table is a single asyncio task that owns its game state and applies player and bot actions
through `mahjong_core`, a pure, stdlib-only rules engine with no I/O. Outbound events are redacted
per seat before they are sent. Full component map: [architecture §2](docs/architecture.md).

## Getting started

### Prerequisites

| Tool | Version | Notes |
| --- | --- | --- |
| Docker (with Compose) | — | Required for Postgres; optionally runs the whole stack |
| [mise](https://mise.jdx.dev/) | — | Installs the pinned toolchain below (native setup only) |
| Python | 3.13 | Managed by `uv` |
| Node.js | 24 | |
| pnpm | 12.4.2 | |
| uv | 0.12 | |
| PostgreSQL | 17 | Provided by `docker-compose.yml` |

All versions are pinned in [`mise.toml`](mise.toml) ([infra §2](docs/infra.md)).

### Option A: Docker

```bash
cp .env.example .env
make up            # postgres + api + web
make migrate       # once per fresh database
make help          # list all targets
```

The web client is served at <http://localhost:5173> and the API documentation at
<http://localhost:8000/docs>.

### Option B: Native

Postgres runs in Docker; the server and client run on the host.

```bash
mise install                          # pinned toolchain
cp .env.example .env
(cd server && uv sync --locked)       # add --extra ml to include PyTorch
pnpm install --frozen-lockfile        # also installs git hooks (lefthook)

docker compose up -d postgres
export DATABASE_URL=postgresql+asyncpg://mahjong:mahjong@localhost:5432/mahjong
export CORS_ORIGINS=http://localhost:5173
(cd server && uv run alembic upgrade head && uv run uvicorn app.main:app --reload --workers 1)
pnpm --dir web dev                    # in a second shell
```

> [!IMPORTANT]
> The API must run with a single worker (`--workers 1`). Tables are in-memory objects owned by one
> process, so additional workers would split table state ([infra §3](docs/infra.md)).

Native equivalents of every `make` target are listed in [infra §2](docs/infra.md).

### Compose profiles

| Command | Adds |
| --- | --- |
| `make up` | postgres, api, web |
| `make arena A=FaanBot B=EfficiencyBot N=20000` | one-shot bot evaluation (`tools`) |
| `docker compose --profile ml up trainer` | torch-enabled training container (`ml`) |

## Development

```bash
make fmt        # ruff format + oxfmt
make lint       # ruff check + pnpm lint
make typecheck  # svelte-check
make proto      # regenerate shared/protocol.schema.json + web TS types
```

`server/app/protocol.py` is the single source of truth for the wire protocol. Generated files
(`shared/`, `web/src/lib/net/protocol.d.ts`) must not be edited by hand; `make proto-check` fails
the CI build if they drift.

## Testing

```bash
make test              # server + web
make test-server       # pytest, fast suite
make test-server-slow  # pytest, slow suite: soak tests, real-bot end-to-end, hypothesis
make test-web          # Vitest + Playwright
```

`mahjong_core` is pure and is tested directly, without mocks. CI runs the fast and slow suites in
parallel on every push ([infra §9](docs/infra.md)). Test strategy and known pitfalls are described
in [testing.md](docs/testing.md).

## Project structure

```
server/   Python: mahjong_core/ (pure rules, stdlib-only), app/ (FastAPI, tables, WebSocket), bots/, ml/
web/      SvelteKit 2 + Svelte 5 client: lobby and table, DOM rendering, SCSS styling
shared/   Generated protocol JSON schema (make proto)
docs/     Reference documentation and decisions/ (ADR log)
```

`uv` manages Python dependencies, `pnpm` manages JavaScript dependencies, and the `Makefile`
provides Docker-based entry points. Full tree: [infra §1](docs/infra.md).

## Documentation

| Document | Scope |
| --- | --- |
| [architecture.md](docs/architecture.md) | Process model, table actor, claim window, redaction, failure handling, anti-cheat |
| [rules.md](docs/rules.md) | Tiles, state machine, claim priority, faan table, payments, `RuleSet` |
| [protocol.md](docs/protocol.md) | WebSocket envelope, message catalog, reconnect/resync, codegen, HTTP |
| [frontend.md](docs/frontend.md) | Rendering, layout, interaction, client state, routes, assets, accessibility and i18n |
| [bots.md](docs/bots.md) | Bot tiers, shanten/ukeire, the HK 3-faan minimum trap, safety, arena, `ORACLE` |
| [ml.md](docs/ml.md) | Self-play reinforcement-learning agent: plan and status |
| [infra.md](docs/infra.md) | Repository layout, toolchain, local development, Docker, database, deployment, CI |
| [testing.md](docs/testing.md) | Test strategy, Vitest and pytest pitfalls |
| [decisions/](docs/decisions/README.md) | Architecture decision records: history, removed designs, deferred work |

## Contributing

Contributions are welcome. Before opening a pull request:

1. Run `make fmt lint typecheck test`.
2. Add a test for any new behaviour, and a failing regression test for any bug fix.
3. Update the relevant document in `docs/` in the same change as the code.
4. Write commit messages in [Conventional Commits](https://www.conventionalcommits.org/) form,
   `type(scope): description`. This is enforced by commitlint through the lefthook git hooks.

For the reasoning behind past design choices, and for work that has been deliberately deferred,
see the [decision log](docs/decisions/README.md).

## License

Released under the MIT License. See [LICENSE](LICENSE).

### Acknowledgements

Tile artwork is from [samoheen/mahjong-tiles](https://github.com/samoheen/mahjong-tiles)
(CC0 1.0). Full attribution for bundled third-party assets is in [NOTICE](NOTICE) and
[infra §10](docs/infra.md).
