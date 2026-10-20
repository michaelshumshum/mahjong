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
- [Machine learning](#machine-learning)
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

## Machine learning

The Expert bot is a policy trained from scratch by self-play reinforcement learning. It has no
teacher: no human game records, and no imitation of the heuristic bots, which are kept as held-out
evaluation opponents only ([ml §3, §6](docs/ml.md)).

| Piece | Summary |
| --- | --- |
| Action space | 109 discrete actions (discard, kongs, chow low/middle/high, pung, win, pass); the legal-action mask comes from the rules engine, never from the network ([ml §1](docs/ml.md)) |
| Model | ~0.4M-parameter 1-D residual network over the 34 tile types, with the `RuleSet` as an input, so one policy plays every preset ([ml §8](docs/ml.md)) |
| Training | PPO with an asymmetric critic that sees the full state. Reward is the hand's point delta, not shanten: under the 3-faan minimum, the fastest hand is often one that is not allowed to win ([ml §4, §9](docs/ml.md)) |
| Curriculum | a cold start against passive opponents with oracle information that is annealed away, then self-play, then a league of past and persona snapshots ([ml §10, §11](docs/ml.md)) |
| Serving | exported to numpy (no PyTorch at runtime), with p99 under 5 ms per decision including encoding; weights committed as `server/bots/weights/learned.npz` ([bots §2](docs/bots.md)) |

### Results

Shipped policy (Expert, `LearnedBot`) in one seat against three copies of each opponent,
`hk_classic`, fresh seeds. Points are per hand, with a 95% CI; win rate, deal-in rate and average
winning faan are given as agent / opponent ([ml §14](docs/ml.md),
[rl-learnings §4](docs/rl-learnings.md)):

| Opponent ×3 | Sets | Points/hand [95% CI] | Win rate | Deal-in rate | Avg winning faan |
| --- | --- | --- | --- | --- | --- |
| `FaanBot` (Normal) | 1,000 | **+10.75** [+9.64, +11.86] | 0.267 / 0.160 | 0.076 / 0.105 | 5.26 / 3.37 |
| `EfficiencyBot` (Easy) | 700 | **+15.19** [+13.74, +16.64] | 0.329 / 0.143 | 0.027 / 0.112 | 5.44 / 3.26 |
| `FaanBotAggressive` | 700 | **+11.62** [+10.34, +12.90] | 0.284 / 0.168 | 0.074 / 0.119 | 5.28 / 3.37 |
| `FaanBotDefensive` | 700 | **+10.85** [+9.52, +12.19] | 0.251 / 0.146 | 0.067 / 0.092 | 5.28 / 3.35 |
| `FaanBotFlushChasing` | 700 | **+11.72** [+10.43, +13.01] | 0.285 / 0.154 | 0.072 / 0.109 | 5.22 / 3.37 |

The agent wins more often, deals in less, and wins with larger hands (about 5.3 faan against
about 3.4) than every heuristic bot. Other measurements:

| Measurement | Result |
| --- | --- |
| vs `FaanBot`, other presets | `hk_strict` +25.04, `hk_casual` +18.98 points/hand |
| vs `FaanBot` with perfect information (`OracleFaanBot` ×3) | +2.88 [+1.75, +4.01] points/hand, without seeing hidden tiles |
| Impossible (`ORACLE`) vs Expert ×3 | +3.60 [+3.15, +4.06] points/hand; deals in on 0.3% of hands ([bots §9](docs/bots.md)) |
| Training to ship | 464.3M decisions of curriculum and self-play, then 274.3M in the league, on one RTX 2060 |
| Decision latency | p50 1.8 ms, p99 2.0–3.4 ms per decision including encoding, on CPU |
| Cost compared with Normal | 1.8 ms mean per decision against `FaanBot`'s 3.6 ms |

The Impossible tier runs the same policy and adds vetoes that use full information
([bots §9](docs/bots.md)). Training code lives in `server/ml/` and needs the `ml` extra
(`uv sync --extra ml`).

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
