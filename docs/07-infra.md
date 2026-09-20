# 07 — Monorepo and Docker

## 1. Layout

```
mahjong/
├── Makefile                    # day-to-day interface; `make help`
├── docker-compose.yml          # dev: postgres, api, web; profiles: ml, tools
├── docker-compose.prod.yml     # overlay: prod targets, no mounts, no reload
├── .env.example
├── pnpm-workspace.yaml         # web only — shared/ isn't an npm package
├── server/                     # Python package, own pyproject + Dockerfile
├── web/                        # SvelteKit, own package.json + Dockerfile
├── shared/                     # generated protocol JSON schema (make proto)
└── docs/
```

`uv` owns Python, `pnpm` owns JS, the `Makefile` is the seam.

`shared/` holds one generated artifact: `protocol.schema.json`. `make proto` regenerates it
from `server/app/protocol.py` and, in the same step, generates the TS types straight into
`web/src/lib/net/protocol.d.ts` ([02-protocol §6](02-protocol.md)). Neither file is hand-edited.
CI enforces that — see §9.

Matchmaking, presence, rate limiting and session state are in-process structures for now.
Deferred — see [99-deferred.md](99-deferred.md).

## 2. Process model

The API container runs uvicorn with **one worker**.

> Tables are in-memory objects owned by one process. Two workers mean two disjoint sets of tables
> with no routing between them — players 1 and 2 land in worker A's table #7 while players 3 and
> 4 land in worker B's *different* table #7.

`--workers` is pinned by a comment in the Compose file and a startup assertion in `main.py`.
Multi-node scaling is out of scope at this stage. Deferred — see [99-deferred.md](99-deferred.md).

**Graceful shutdown is implemented at the app level, not yet matched at the Compose level.**
`TableRegistry.begin_shutdown` (`app/registry.py`) runs the real drain on SIGTERM — stop new
joins, warn connected seats, let a mid-hand table finish that hand within `SHUTDOWN_GRACE_SECONDS`
(default 90s) — see `00-architecture.md §8.1`. Neither `docker-compose.yml` nor
`docker-compose.prod.yml` sets a `stop_grace_period` yet, so Compose's own default (10s before
SIGKILL) can still cut the drain off well before its 90s window closes — needs sizing to match
once this goes past a personal deploy.

## 3. Compose profiles

| Command | Brings up |
| --- | --- |
| `make up` | postgres, api, web |
| `docker compose --profile ml up trainer` | + torch-enabled container for training |
| `make arena A=FaanBot B=EfficiencyBot N=20000` | one-shot bot evaluation container |

Only `ml` and `tools` profiles exist. There is no `scale` profile and no router service —
multi-node routing is deferred (§2).

The base `server` image has no torch or numpy; the `ml` extra adds both (~180MB vs ~3GB). The
API never imports either.

## 4. Image layering

Both Dockerfiles are multi-stage with a shared `base`:

```
base ──┬── deps    (lockfile only; cached across source edits)
       ├── dev     (+ dev deps, source mounted at runtime, hot reload)
       ├── prod    (venv copied from deps, non-root user, no build tools)
       └── ml      (venv copied from deps+ml extra, non-root user, for trainer and arena)
```

`web`'s `dev` stage is the one exception to the shared `base`: it sits on `node:24-bookworm-slim`
with chromium baked in (`playwright install --with-deps chromium`), because `pnpm test` runs
vitest's browser-mode `client` project and the Playwright e2e suite, and Playwright ships no musl
build — on alpine that browser cannot be installed at all. `deps`/`build`/`prod` stay alpine, so
the shipped image is untouched. Two consequences worth knowing:

- Changing that stage's base invalidates the `web-modules` volume (native deps are built against
  the image's libc) — `docker volume rm mahjong_web-modules` once after pulling such a change,
  or `make test-web` runs against the old base's binaries.
- `make test-web` passes `CI=true`: vitest browser mode and Playwright both default to *headed*
  off-CI, and the container has no X server.
- The browsers also live in a `playwright-browsers` volume mounted at `/root/.cache/ms-playwright`,
  seeded from the image on first use. Baking alone already means no per-run download; the volume
  covers the rebuild case, where a lockfile change invalidates the install layer and would
  otherwise re-fetch ~170MB of chromium.

`ml` mirrors `prod`'s non-root setup — it just installs from the `ml` extra instead of base
deps. `trainer`/`arena` don't bind-mount source over the image: doing so would shadow the
image's baked venv with an empty one and force a ~3GB torch reinstall on first run. Rebuild
(`make train` / `make arena`) to pick up source changes.

Dependency install is a separate layer keyed on the lockfile. `uv` and `pnpm` caches are
BuildKit cache mounts.

## 5. Deployment

Not yet decided: hosting target, domain, and TLS termination. Minimum shape once it is:

- A reverse proxy (Caddy or nginx) in front of `api` and `web`, terminating TLS and forwarding
  `X-Forwarded-*`. `docker-compose.prod.yml` already requires `TRUSTED_PROXY_IPS` to be set to
  that proxy's address — never `*` (see §9.3 in `00-architecture.md`: wildcard-trusting
  `X-Forwarded-For` defeats per-session rate limiting).
- Postgres: no backup story exists. Finished games (`ruleset`, `seed`, `action_log`) are the
  only durable asset the server produces and currently have zero redundancy — a lost volume is a
  lost history. At minimum: scheduled `pg_dump` to off-box storage before this goes past a
  personal deploy.
- No WAL archiving / PITR is specified; not needed until game history has real users depending
  on it.

## 6. Database schema and migrations

`alembic` is wired into the `Makefile` (`make migrate`, `make revision`). A fresh dev database
needs `make migrate` once: Compose gives `api` a real `DATABASE_URL`, so `make test-server`
exercises the real `GAME_OVER` persist rather than the no-session-factory no-op, and against an
unmigrated database every finished game logs a lost record (`app/table.py`'s `process_one`).
`games` is the first table, migrated in `server/alembic/versions/95b97823dd97_create_games_table.py`, model at
`server/app/db/models.py`. `leaderboard` below is still just the target shape — not built yet, no
migration. There is no `users` table planned: `docs/00-architecture.md §2.1` cuts real accounts
entirely (guest-only, a client-chosen name in `localStorage`, no server-side identity to give a
table to) — this isn't a "not built yet" line item, it's out of scope by design.

| Table | Holds | Status |
| --- | --- | --- |
| `games` | `id`, `engine_version`, `ruleset` (JSONB), `seed`, `action_log` (JSONB), `players` (JSONB — each seat's chosen guest name, wired through from `join.name` via `SeatBinding.name`, M5), `result` (JSONB), `created_at` — the durable record of a finished game (`docs/06-ml.md §2`) | **built** |
| `leaderboard` | derived/aggregated from `games.players`/`games.result` by name, not by account — a guest who reuses the same name resumes the same leaderboard row, no login needed; may be a materialized view instead of a table | not built |

`ruleset`/`action_log`/`players`/`result` use `JSON().with_variant(JSONB(), "postgresql")` —
JSONB on Postgres, generic `JSON` everywhere else, so the same model works against SQLite in
tests (CI has no Postgres service, §9) and JSONB in production. `save_game_record`
(`server/app/db/records.py`) is the only write path; `bots/selfplay.py`'s `play_and_record_game`
is the self-play integration point (`docs/05-roadmap.md §2`'s M1 gate: bot-only games recorded
end to end).

Table state itself is never persisted — it's in-memory only until stage-3 durability
(`00-architecture.md §7`) is built, which is out of scope now.

## 7. Observability

Nothing exists here yet. For a stateful single-process server where one wedged table silently
kills a game in progress, this is a gap, not a nice-to-have. Minimum bar before real users:

- **Logging:** structured (JSON) to stdout, one line per request/event, `LOG_LEVEL` already
  wired via env. Docker captures stdout; no log shipping decided yet.
- **Health:** `/healthz` already exists (used by the `api` container healthcheck). No readiness
  vs. liveness distinction yet — fine at one instance.
- **Metrics:** none. At minimum, table count, active connections, and per-table hand duration
  would surface a wedged table before a player reports it.
- **Error tracking:** none. Uncaught exceptions in a table's `asyncio.Task` currently have
  nowhere to go but the log.
- **Tracing:** not needed at this scale; skip until stage 2.

## 8. Licensing and attribution

Project code: MIT (`LICENSE`).

Third-party assets bundled with the client — notably the FluffyStuff riichi tile set
(`03-frontend.md`, public-domain-licensed) — need a `NOTICE` file crediting the source even
though the license doesn't require it. Add `NOTICE` at the repo root alongside `LICENSE` when
the asset is actually vendored in.

## 9. CI

`.github/workflows/ci.yml` triggers on push and PR to `main` and calls three **reusable
workflows** (`workflow_call`), one per concern:

| File | Calls into | Runs |
| --- | --- | --- |
| `.github/workflows/server.yml` | one `server` job | `uv sync --locked`, then `ruff check`, `ruff format --check`, `pytest -q -m "not slow"` |
| `.github/workflows/web.yml` | one `web` job | `pnpm install --frozen-lockfile`, then `pnpm lint`, `pnpm check`, `playwright install --with-deps chromium`, `pnpm test` (vitest + Playwright e2e) |
| `.github/workflows/proto-check.yml` | one `proto-check` job | regenerates protocol types natively (the same two commands `make proto` runs, without the compose wrapper), then `git diff --exit-code` — fails if committed output is stale |

All native tooling (`uv`, `pnpm`) rather than `docker compose run` — nothing here touches
Postgres, so the containers buy nothing but slower cold starts. `docker compose`-based
`make test` / `make proto-check` stay the local dev path; CI reimplements their commands
directly against the toolchain instead of shelling through Compose. Revisit if a job ever needs
Postgres.

**Job graph**: GitHub Actions can't `needs:` across independent top-level workflow files, only
within one workflow's own jobs — reusable workflows are the way to get real separate files while
keeping the option to chain a job that has a genuine dependency. Here, none do: `server`, `web`,
and `proto-check` are independent domains with no shared artifact, so root `ci.yml` calls all
three with no `needs:` — they run in parallel. Within `server.yml`/`web.yml`, lint and test (plus
typecheck, for `web`) also don't depend on each other's *output*, but are sequential steps inside
one job rather than separate jobs, so the dependency install (`uv sync` / `pnpm install`) happens
once per pipeline instead of 2-3x or needing an artifact handoff between jobs.

**Gates**:

| Check | Tolerance |
| --- | --- |
| `ruff check`, `ruff format --check` | hard — any finding fails the job |
| `pytest -q -m "not slow"` | hard |
| `pnpm lint` (oxlint + oxfmt) | hard |
| `pnpm check` (svelte-check) | hard |
| `pnpm test` (vitest + Playwright) | hard |

**Pre-commit** (`lefthook.yml`): alongside the existing `web-lint`/`web-format` (oxlint/oxfmt on
staged files) and `server` (ruff via `.pre-commit-config.yaml`) jobs, `web-typecheck` runs `pnpm
check` (svelte-check) — it inherently checks the whole project graph, not just staged files,
unlike oxlint/oxfmt's `{staged_files}`, so it's slower and there's no meaningful way to scope it
down without producing wrong (missing-context) results.
