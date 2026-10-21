# Infrastructure

Repository layout, toolchain, local development, containers, database, deployment and CI.

## 1. Layout

```
mahjong/
├── mise.toml                   # pinned toolchain: node, python, uv, pnpm (§2)
├── Makefile                    # day-to-day interface (Docker-based); `make help`
├── docker-compose.yml          # dev: postgres, api, web; profiles: ml, tools
├── docker-compose.prod.yml     # overlay: prod targets, no mounts, no reload
├── .env.example
├── package.json                # root: lefthook + commitlint only; pins pnpm via packageManager
├── pnpm-workspace.yaml         # web only — shared/ isn't an npm package
├── lefthook.yml                # git hooks (§9)
├── commitlint.config.js        # `action(scope): description`
├── scripts/                    # repo tooling (check_comment_length.py, a pre-commit hook)
├── server/
│   ├── pyproject.toml, uv.lock, Dockerfile, alembic/
│   ├── mahjong_core/           # PURE. no asyncio, no I/O, no deps beyond stdlib
│   │   ├── tiles.py            # TileType/TileId, geometry constants, 34-array helpers, parsing
│   │   ├── wall.py             # seeded shuffle, dice, draw front/back, flower replacement
│   │   ├── melds.py            # meld types, legality, decomposition
│   │   ├── shanten.py          # standard / seven pairs / thirteen orphans + ukeire
│   │   ├── state.py            # GameState, SeatState, Phase (frozen dataclasses)
│   │   ├── actions.py          # Action union, legal_actions(state, seat)
│   │   ├── engine.py           # reduce(state, action) -> (state, events)
│   │   ├── events.py           # Event union (engine output), EventKind
│   │   ├── claims.py           # claim priority resolution (pure part)
│   │   ├── config.py           # RuleSet
│   │   ├── presets.py          # RULESET_PRESETS, resolve_ruleset
│   │   ├── ml.py               # action-id layout constants, action_id / decode_action / legal_mask
│   │   └── scoring/            # patterns.py (faan detectors), faan.py (maximise over
│   │                           # decompositions), payout.py (faan -> points -> payments)
│   ├── app/
│   │   ├── main.py             # FastAPI app, lifespan, /healthz, GET/POST /tables
│   │   ├── api_models.py       # REST request/response models for main.py
│   │   ├── ws.py               # WebSocket endpoint, Session
│   │   ├── table.py            # Table actor: task loop, timers, claim windows, seq/ring
│   │   ├── table_types.py      # SeatBinding, Command, BotJobTag/BotResult, TableSettings
│   │   ├── errors.py           # Table exceptions (one per wire error code), TABLE_CLOSED_ERROR
│   │   ├── clock.py            # now_ms(): server epoch ms for every wire ts/deadline_ts
│   │   ├── registry.py         # TableRegistry, showcase table, graceful-shutdown drain
│   │   ├── views.py            # seat_view() + redact_event()
│   │   ├── protocol.py         # pydantic message models (SOURCE OF TRUTH)
│   │   ├── idempotency.py      # per-seat intent id cache (protocol.md §1)
│   │   ├── outbox.py           # BoundedOutbox, per-connection backpressure
│   │   └── db/                 # SQLAlchemy models, session, save_game_record
│   ├── bots/                   # tiers, safety/valuation/features/labels, worker, arena, selfplay;
│   │                           # base.py (Bot protocol, harness constants), tiers.py (BotTier ids)
│   │   └── weights/learned.npz # T4's exported policy, committed (bots.md §2)
│   ├── ml/                     # RL + supervised training (ml.md); stop_signal.py (SIGINT/SIGTERM flag)
│   ├── tools/gen_protocol.py   # pydantic → TS (+ informational JSON Schema), protocol.md §6
│   └── tests/                  # pytest; pins/ holds pinned fixtures; shared helper modules
│                               # (game_state, hands, decisions, ws_frames, game_records; testing.md §3)
├── web/
│   ├── package.json, Dockerfile, vite.config.ts, playwright.config.ts
│   ├── messages/               # i18n sources (frontend.md §9)
│   └── src/
│       ├── routes/             # /, /tables, /demo, /table/[id], /replay/[id], /profile
│       └── lib/                # net/ game/ table/ ui/ i18n/ styles/ (frontend.md §1)
├── shared/protocol.schema.json # GENERATED, informational
└── docs/
```

`uv` owns Python, `pnpm` owns JS, the `Makefile` is the Docker-based seam. Generated files
(`shared/protocol.schema.json`, `web/src/lib/net/protocol.d.ts`,
`web/src/lib/net/protocol.assertNever.ts`) are never hand-edited — `make proto`
([protocol.md §6](protocol.md)); CI enforces it (§9).

## 2. Toolchain and local development

### Pinned versions

| Tool | Version | Pinned in |
| --- | --- | --- |
| Python | 3.13 | `mise.toml`, `server/.python-version` (what `uv` and so CI resolve), `server/Dockerfile` (`python:3.13-slim`), `pyproject.toml` (`requires-python >=3.13`, floor only) |
| Node | 24 | `mise.toml`, `web/Dockerfile` (`node:24-*`) |
| pnpm | 12.4.2 | `mise.toml`, root `package.json` `packageManager` (corepack, used inside images) |
| uv | 0.12 | `mise.toml` |
| Postgres | 17 | `docker-compose.yml` (`postgres:17-alpine`) |

Keep these in sync when bumping. CI does not read `mise.toml`: `web.yml`/`proto-check.yml` use
`node-version: lts/*`. Python is pinned for CI only through `server/.python-version`: with the
floor alone, `uv` picked the newest CPython (3.15), for which torch has no wheels, and
`server-ml.yml`'s `uv sync --extra ml` failed (§9).

### Two ways to run

**Containers** — no host toolchain needed beyond Docker:

```bash
cp .env.example .env
make up            # postgres + api + web; web :5173, api :8000/docs
make migrate       # once per fresh database
make help          # everything else
```

**Native** — host toolchain from `mise`, Postgres still in Docker:

```bash
mise install                          # node, python, uv, pnpm per mise.toml
cp .env.example .env
(cd server && uv sync --locked)       # add --extra ml for torch; a plain sync removes it
pnpm install --frozen-lockfile        # root + web; root `prepare` installs lefthook hooks

docker compose up -d postgres
export DATABASE_URL=postgresql+asyncpg://mahjong:mahjong@localhost:5432/mahjong
export CORS_ORIGINS=http://localhost:5173
(cd server && uv run alembic upgrade head)
(cd server && uv run uvicorn app.main:app --reload --workers 1 \
  --ws-max-size 65536 --ws-per-message-deflate false)   # protocol.md §1
pnpm --dir web dev
```

| Variable | Native default | Notes |
| --- | --- | --- |
| `DATABASE_URL` | unset → no persistence | Compose sets it for `api` |
| `CORS_ORIGINS` | unset → **no cross-origin requests**, so the web dev server can't reach the API | comma-separated; Compose sets `http://localhost:${WEB_PORT}` |
| `PUBLIC_API_URL` / `PUBLIC_WS_URL` | `http://localhost:8000` / `ws://localhost:8000/ws` (`lib/net/lobby.ts`, `lib/net/socket.ts`) | web, read at runtime via `$env/dynamic/public` |
| `SHUTDOWN_GRACE_SECONDS` | 90 | [architecture.md §8.1](architecture.md) |
| `ABANDONED_TABLE_GRACE_SECONDS` | 120 | seconds a started table may run with no human connected before it's ended; keep well above the 20s disconnect grace ([architecture.md §8.2](architecture.md)) |
| `SHOWCASE_TABLE_ID` | `BOTS`; empty disables | [architecture.md §3](architecture.md) |
| `CLAIM_HOLD_SECONDS` | `BOT_THINK_MAX_SECONDS` + 0.2 (1.6) | the pause after every discard and robbable kong that hides whether a claim window opened; `0` disables ([architecture.md §4](architecture.md) "Claim hold") |
| `LOG_LEVEL` | `info` | |
| `API_DOCS` | on; `0` disables | `/docs`, `/redoc`, `/openapi.json`; the prod overlay sets `0` |
| `TRUSTED_PROXY_IPS` | — | prod overlay only, required there (§7) |
| `JWT_SECRET` | — | passed by both Compose files but read by nothing — vestigial from the cut auth design ([ADR 0001](decisions/0001-guest-only-identity.md)) |

Native equivalents of the Docker targets:

| Make target | Native |
| --- | --- |
| `make test-server` | `cd server && uv run pytest -q -m fast -n auto` |
| `make test-server-slow` | `cd server && uv run pytest -q -m slow -n auto --games=10000` |
| `make bench-latency` | `cd server && LATENCY_BUDGET_MS=5 uv run pytest -q -s -m latency -p no:xdist` |
| `make test-web` | `pnpm --dir web test` |
| `make migrate` | `cd server && uv run alembic upgrade head` (with `DATABASE_URL`) |
| `make proto` | `cd server && uv run python -m tools.gen_protocol --ts-out ../web/src/lib/net/protocol.d.ts --schema-out ../shared/protocol.schema.json`, then `pnpm --dir web exec oxfmt src/lib/net/protocol.d.ts src/lib/net/protocol.assertNever.ts` |

## 3. Process model

The API runs uvicorn with **one worker**.

> Tables are in-memory objects owned by one process. Two workers mean two disjoint sets of tables
> with no routing between them — players 1 and 2 land in worker A's table #7 while players 3 and
> 4 land in worker B's *different* table #7.

`--workers 1` is pinned, with a comment, in both Compose files, the server Dockerfile, and
`main.py`'s `uvicorn.run` entry point. Nothing asserts it at startup. Multi-node is out of scope
([ADR 0006](decisions/0006-multi-node-and-durability.md)).

**Shutdown.** `TableRegistry.begin_shutdown` drains on SIGTERM, letting a mid-hand table finish
within `SHUTDOWN_GRACE_SECONDS` (default 90s) ([architecture.md §8.1](architecture.md)). The prod
overlay sets `api` `stop_grace_period: 100s`; the dev file doesn't, so Compose's default (10s before
SIGKILL) cuts the drain short there.

## 4. Compose profiles

| Command | Brings up |
| --- | --- |
| `make up` | postgres, api, web |
| `docker compose --profile ml up trainer` | torch-enabled training container |
| `make arena A=FaanBot B=EfficiencyBot N=20000` | one-shot bot evaluation (`tools` profile) |

Only `ml` and `tools` profiles exist.

The base `server` image has numpy but no torch; the `ml` extra adds torch. The API process never
imports either; numpy loads only in a bot-pool worker serving a `T4` seat (`bots/learned.py`,
[bots.md §2](bots.md)), and the `.npz` weights ship inside the image via `COPY . .`. `trainer` runs `python -m ml.train --config ml/configs/danger.yaml` by default
([ml.md](ml.md)); RL configs (`ml/configs/rl_*.yaml`) run in the same service. GPU passthrough is
commented out in `trainer`; GPU training runs natively ([ml.md §13](ml.md)).

## 5. Image layering

Both Dockerfiles are multi-stage with a shared `base`:

```
base ──┬── deps    (lockfile only; cached across source edits)
       ├── dev     (+ dev deps, source mounted at runtime, hot reload)
       ├── prod    (venv copied from deps, non-root user, no build tools)
       └── ml      (venv copied from deps+ml extra, non-root user, for trainer and arena)
```

Dependency install is a separate layer keyed on the lockfile; `uv` and `pnpm` caches are BuildKit
cache mounts.

**`web`'s `dev` stage** sits on `node:24-bookworm-slim` with chromium baked in (`playwright install
--with-deps chromium`), not alpine: `pnpm test` runs vitest browser mode and Playwright, and
Playwright ships no musl build. `deps`/`build`/`prod` stay alpine.

- `web/` is bind-mounted, but the root `package.json`/`pnpm-lock.yaml` and `node_modules` are
  baked into the image. A dependency change therefore needs a rebuilt image, or pnpm's pre-run
  check fails with `ERR_PNPM_OUTDATED_LOCKFILE`. `make test-web` runs `docker compose build web`
  first (a no-op when cached), and `make up` passes `--build --renew-anon-volumes`.
- `/app/web/node_modules` is an **anonymous** volume, so every new container reseeds it from the
  current image. A named volume is seeded only once and would keep masking a rebuilt image's
  dependencies (and its libc-specific native builds) indefinitely.
- `make test-web` passes `CI=true`: vitest browser mode and Playwright default to *headed* off-CI,
  and the container has no X server.
- Browsers live in a `playwright-browsers` volume at `/root/.cache/ms-playwright`, seeded from the
  image, so a lockfile-triggered rebuild doesn't re-fetch ~170MB of chromium.

**Every stage that runs `pnpm`** (`deps`, `dev`, `build`) copies the root `package.json` in and
strips its `scripts`:

- corepack resolves the pinned pnpm (`packageManager`) from the *stage's own* `/app`; a stage that
  skips the copy silently installs with latest pnpm (which broke `allowBuilds`, surfacing as
  `ERR_PNPM_IGNORED_BUILDS` on `@parcel/watcher`).
- `scripts` is stripped because the root `prepare` (`lefthook install`) hard-fails without a real
  `.git`, which the build context never has.

**`ml`** mirrors `prod`'s non-root setup with the `ml` extra. `trainer`/`arena` don't bind-mount
source: that would shadow the baked venv and force a ~3GB torch reinstall. Rebuild (`make train` /
`make arena`) to pick up source changes. The image is ~18.6GB because torch's default wheel bundles
CUDA ([ml.md §13](ml.md)). `deps-ml` installs the torch/CUDA wheels in their own layer first, from a
`torch-pins` stage that filters `uv export` down to `torch`/`triton`/`nvidia-*`/`cuda-*`. `COPY` is
keyed on content, so a `uv.lock` change that leaves those pins alone reuses the multi-GB layer and
only reruns the following `uv sync`.

## 6. Database and migrations

Alembic, wired into the `Makefile` (`make migrate`, `make revision M="…"`). A fresh database needs
migrating once; against an unmigrated database every finished game logs a lost record
(`app/table.py`'s `process_one`).

| Table | Holds | Status |
| --- | --- | --- |
| `games` | `id`, `engine_version`, `ruleset` (JSONB), `seed`, `action_log` (JSONB), `players` (JSONB — each seat's guest name), `result` (JSONB), `created_at` — a finished game ([ml.md §2](ml.md)) | built |
| `hand_records` | `id`, `engine_version`, `ruleset`, `seed`, `dealer`, `prevailing`, `action_log`, `players`, `result`, `created_at` — a standalone hand from `engine.new_hand`, e.g. an RL eval episode ([ml.md §2](ml.md)) | built |
| `leaderboard` | aggregated from `games.players`/`games.result` by name — a guest reusing a name resumes the same row; may be a materialized view | not built |

There is no `users` table — identity is guest-only by design
([ADR 0001](decisions/0001-guest-only-identity.md)).

- Models: `server/app/db/models.py`; migrations: `server/alembic/versions/`.
- JSON columns use `JSON().with_variant(JSONB(), "postgresql")` — JSONB on Postgres, generic `JSON`
  elsewhere, so tests run against SQLite (CI has no Postgres service, §9).
- `save_game_record` (`server/app/db/records.py`) is the only write path; `bots/selfplay.py`'s
  `play_and_record_game` records bot-only games through it.
- Live table state is never persisted ([architecture.md §7](architecture.md)).

## 7. Deployment

No hosting target, domain or TLS termination is chosen. Single-node by design
([ADR 0003](decisions/0003-product-scope.md)): a single VM fits the one-process model; nothing that
implies horizontally scaling the table registry.

**Production overlay.** `make prod-build` / `make prod-up` run
`docker compose -f docker-compose.yml -f docker-compose.prod.yml`: prod targets, no mounts, no
reload.

- A reverse proxy (Caddy or nginx) in front of `api` and `web` terminates TLS and forwards
  `X-Forwarded-*`. The overlay requires `TRUSTED_PROXY_IPS` (passed to uvicorn's
  `--forwarded-allow-ips`) to be that proxy's address — never `*`, which lets any client spoof
  `X-Forwarded-For`.
- The overlay uses `!override`/`!reset` YAML tags on `ports:` — Compose concatenates `ports:` lists
  across `-f` files, so a bare `ports: []` for `postgres` would leave the dev file's `5432:5432`
  mapping in place.
- `JWT_SECRET` is required by the overlay but unused (§2).
- `API_DOCS=0`: no `/docs`, `/redoc` or `/openapi.json` on the public API host (§2).
- The overlay publishes `api` and `web` on `127.0.0.1` only, so a host-side proxy or tunnel
  connector is the sole way in.
- `make prod-migrate` applies migrations inside the prod `api` container (`make migrate` targets the
  dev stack).

**Required before real users, not yet in place:**

| Item | Minimum |
| --- | --- |
| TLS + domain | a real certificate for `wss://`, domain decided up front |
| Postgres backups | finished games are the only durable asset, currently with zero redundancy: scheduled `pg_dump` to off-box storage with a tested restore. WAL archiving / PITR not needed until history has real users depending on it |
| Grace period | `stop_grace_period` sized to `SHUTDOWN_GRACE_SECONDS` (§3) |
| Cost | a rough monthly figure (VM + Postgres + domain) |

## 8. Observability

| Area | Current state |
| --- | --- |
| Logging | stdout, `LOG_LEVEL` via env, captured by Docker. Not structured, no shipping |
| Health | process-level `/healthz` (the `api` healthcheck): `503` while draining; `200` with `"status": "degraded"` when the learned weights failed the startup check ([bots.md §2](bots.md)), which the Compose healthcheck treats as unhealthy (it requires `"ok"`). No per-table liveness |
| Metrics | none |
| Error tracking | none — an uncaught exception in a table's task goes only to the log |
| Tracing | not needed at one process |

A wedged table silently destroys a game in progress, and nothing would tell anyone. Minimum bar
before real users:

- Structured (JSON) logs per table (`table_id`, `seq`, phase transitions), shipped off-box.
- A per-table liveness check — a process can be up while one table's task loop is stuck.
- An alert on "table hasn't advanced `seq` in N minutes while players are connected."
- Metrics: table count, active connections, per-table hand duration.

## 9. CI

`.github/workflows/ci.yml` triggers on push and PR to `main` and calls three **reusable workflows**
(`workflow_call`):

| File | Jobs | Runs |
| --- | --- | --- |
| `server.yml` | `server`, `server-slow` | `server`: `uv sync --locked`, `ruff check`, `ruff format --check`, `pytest -q -m fast -n auto`. `server-slow`: `pytest -q -m slow -n auto --games=1000` — soaks, real-bot e2e, hypothesis runs, and the latency tests, which gate on ratios and write absolute p50/p99 to the job summary ([testing.md §1](testing.md)) |
| `web.yml` | `web` | `pnpm install --frozen-lockfile`, `pnpm lint`, `pnpm check`, `playwright install --with-deps chromium`, `pnpm run test:coverage` (vitest, both projects), `pnpm run test:e2e` |
| `proto-check.yml` | `proto-check` | regenerates protocol types natively (§2's `make proto` equivalent), then `git diff --exit-code` |

All jobs run in parallel with no `needs:` — they share no artifacts. `server-slow` is its own job
so it stays off the fast job's critical path. Within a job, lint/typecheck/test are sequential
steps so dependencies install once.

**Native tooling, not Compose.** CI runs `uv`/`pnpm` directly; nothing needs Postgres, so
containers would only add cold-start time.

**Standalone, path-filtered workflows.** `workflow_call` can't filter by path, so heavy checks are
separate workflows with their own `on.push.paths`/`on.pull_request.paths`:

| File | Triggers on | Runs |
| --- | --- | --- |
| `server-ml.yml` | `server/ml/**`, `server/pyproject.toml`, `server/uv.lock`, itself | `uv sync --locked --extra ml`, `import ml`/`ml.train`, `python -m ml.train --help`, and the ml unit tests (`tests/test_ml_*.py`, `tests/test_generate_dataset.py`), which skip without the extra |
| `docker-build.yml` | either Dockerfile, either lockfile, either Compose file, itself | build-only (`push: false`) matrix of `server` `dev`/`prod` and `web` `dev`/`prod`, `type=gha` cache per entry |
| `docker-build-ml.yml` | `server/Dockerfile`, `server/pyproject.toml`, `server/uv.lock`, itself | build-only `server` `ml` target, uncached |

The `ml` image (~18.6GB, §5) is its own workflow so web-only changes don't rebuild it. It first
removes unused preinstalled toolchains (dotnet, Android SDK, GHC, CodeQL — ~25-30GB), since a
standard runner has ~14GB free. It builds without a layer cache:

- `type=gha` crashed the runner exporting the torch layer.
- `type=registry` on GHCR worked, but publishes a package that shows on the repo page.
- The job only runs on server dependency changes, which miss the cache anyway unless the torch
  pins are unchanged.

**Concurrency.** Every top-level workflow (`ci.yml` and the three standalone ones) sets
`concurrency.group: ${{ github.workflow }}-${{ github.ref }}`, so each runs at most once per ref. On a
PR a newer push cancels the in-progress run (`cancel-in-progress` only for `pull_request`); on
`main` runs queue rather than cancel, so every pushed commit is still checked and the
`coverage-badge` job isn't killed mid-push. GitHub keeps only the newest pending run per group, so a
burst of `main` pushes skips the middle ones. The reusable workflows don't set it: called from
`ci.yml`, `github.workflow` resolves to the caller, so a nested group would deadlock against it.

**Coverage.** `server.yml` reruns pytest with coverage as a separate, non-blocking step
(`continue-on-error: true`) — line tracing trips `test_frontier_cache_warms_and_stays_fast`'s
wall-clock ceiling, so that test is deselected from the rerun. `web.yml`'s `test:coverage` is
`vitest --run --coverage` (v8, `json-summary`). `ci.yml`'s own `coverage-badge` job (push to
`main` only, `needs: [server, web]`, one run at a time) renders both summaries into SVGs
(`.github/scripts/coverage_badge.py`) and, if either changed, force-pushes them as the single
commit of the orphan `badges` branch. The README references them as `../../raw/badges/*.svg`: the
repo is private, so shields.io can't fetch them, but GitHub serves `raw/` to signed-in viewers.
Committing them to `main` instead put a bot commit on top of nearly every push, so local `main`
kept diverging. A missing coverage report keeps that badge's previous SVG rather than failing the
run.

The `badges` repository ruleset blocks creating, updating and deleting the branch. A personal
repo's ruleset can't list the Actions token as a bypass actor, so the job pushes over SSH with a
write-enabled deploy key (`badges`, private half in the `BADGES_DEPLOY_KEY` secret), and the
ruleset's bypass list holds **Deploy keys**. A missing secret fails the job rather than leaving the
badges silently stale.

**Gates** (all hard): `ruff check`, `ruff format --check`, fast pytest, slow pytest
(`--games=1000`; latency as ratios, the absolute 5 ms budget is `make bench-latency` on the target
CPU, [testing.md §1](testing.md)), `pnpm lint` (oxlint + oxfmt), `pnpm check` (svelte-check), vitest, Playwright,
`proto-check`.

**Local vs. CI.** `make test*` runs the fast suite only; the slow suite (`@pytest.mark.slow`) costs
~15 min at 10,000 games, so it runs locally via `make test-server-slow` and on every push in CI
([testing.md §1](testing.md)).

**Git hooks** (`lefthook.yml`, installed by root `pnpm install`):

| Hook | Job | Runs |
| --- | --- | --- |
| pre-commit | `web-lint`, `web-format` | oxlint / `oxfmt --check` on staged web files |
| pre-commit | `web-typecheck` | `pnpm check` on the whole project — svelte-check can't be scoped to staged files without losing context |
| pre-commit | `server-format`, `server-check` | `ruff format` / `ruff check` on staged `.py` files |
| pre-commit | `comment-length` | `scripts/check_comment_length.py` |
| commit-msg | `commitlint` | `action(scope): description` |

## 10. Licensing and attribution

Project code: MIT (`LICENSE`). Bundled third-party assets are credited in `NOTICE` — notably the
public-domain [samoheen/mahjong-tiles](https://github.com/samoheen/mahjong-tiles) set
([frontend.md §8](frontend.md)).
