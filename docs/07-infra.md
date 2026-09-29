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

`trainer`'s `python -m ml.train --config ml/configs/bc.yaml` and `arena`'s `python -m bots.arena`
both point at real code as of 2026-09-26 — `server/ml/` exists (an empty, import-guarded skeleton
package; `docs/06-ml.md §3`, `docs/99-deferred.md`), so `trainer` no longer names a module that
doesn't exist. `ml.train` is still a stub: `--help` works, a real `--config` run raises
`NotImplementedError`.

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

Every stage that runs `pnpm` (`deps`, `dev`, `build`) copies root `package.json` in and strips its
`scripts` before installing — found and fixed 2026-09-27 via `docker-build.yml` (§9). `corepack`
resolves the pinned pnpm version (`packageManager` in that file) from whatever's at the *stage's*
own `/app`, not inherited across stages, so a stage that skips the copy silently installs with
latest pnpm instead of the pin (this broke `allowBuilds`, which the resolved-latest pnpm didn't
honor the same way, surfacing as `ERR_PNPM_IGNORED_BUILDS` on `@parcel/watcher`). `scripts` is
stripped because the un-copied root manifest's `prepare` (`lefthook install`) hard-fails without a
real `.git` directory, which the build context never has. A new stage that runs `pnpm` needs both.

`ml` mirrors `prod`'s non-root setup — it just installs from the `ml` extra instead of base
deps. `trainer`/`arena` don't bind-mount source over the image: doing so would shadow the
image's baked venv with an empty one and force a ~3GB torch reinstall on first run. Rebuild
(`make train` / `make arena`) to pick up source changes.

The `ml` stage's `CMD ["python", "-m", "ml.train", "--help"]` resolves against a real package
(`server/ml/`) now, not an aspirational path — see §3.

Dependency install is a separate layer keyed on the lockfile. `uv` and `pnpm` caches are
BuildKit cache mounts.

## 5. Deployment

Not yet decided: hosting target, domain, and TLS termination. Minimum shape once it is:

- A reverse proxy (Caddy or nginx) in front of `api` and `web`, terminating TLS and forwarding
  `X-Forwarded-*`. `docker-compose.prod.yml` already requires `TRUSTED_PROXY_IPS` to be set to
  that proxy's address — never `*` (see §9.3 in `00-architecture.md`: wildcard-trusting
  `X-Forwarded-For` defeats per-session rate limiting).
- `docker-compose.prod.yml` uses the `!override`/`!reset` YAML tags on `ports:`, not plain
  values — Compose concatenates `ports:` lists across `-f` files rather than replacing them, so
  a bare `ports: []` for `postgres` would leave the dev file's `5432:5432` mapping in place and
  republish postgres to the host.
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

Third-party assets bundled with the client — notably the samoheen/mahjong-tiles Hong Kong set
(`03-frontend.md`, public-domain-licensed) — need a `NOTICE` file crediting the source even
though the license doesn't require it. Add `NOTICE` at the repo root alongside `LICENSE` when
the asset is actually vendored in.

## 9. CI

`.github/workflows/ci.yml` triggers on push and PR to `main` and calls three **reusable
workflows** (`workflow_call`), one per concern:

| File | Calls into | Runs |
| --- | --- | --- |
| `.github/workflows/server.yml` | `server` + `server-slow` jobs | `server`: `uv sync --locked`, then `ruff check`, `ruff format --check`, `pytest -q -m fast -n auto`. `server-slow`: `uv sync --locked`, then `pytest -q -m slow -n auto --games=1000` — soaks, the real-bot/`ProcessPoolExecutor` practice-mode e2e, hypothesis runs. Never skipped: this is the whole suite, not just the fast gate. |
| `.github/workflows/web.yml` | one `web` job | `pnpm install --frozen-lockfile`, then `pnpm lint`, `pnpm check`, `playwright install --with-deps chromium`, `pnpm test` (vitest + Playwright e2e) |
| `.github/workflows/proto-check.yml` | one `proto-check` job | regenerates protocol types natively (the same two commands `make proto` runs, without the compose wrapper), then `git diff --exit-code` — fails if committed output is stale |

**`.github/workflows/server-ml.yml` (added 2026-09-26) is deliberately not one of the three above.**
It smoke-tests the `ml` extra — `uv sync --locked --extra ml`, `import ml`/`import ml.train`,
`python -m ml.train --help` (must exit 0), and a real `--config` run (must raise, not exit 0) —
plus the ml unit tests (`tests/test_ml_*.py`, `tests/test_generate_dataset.py`), which skip
silently under `server`'s no-extra environment and only run for real here —
but `workflow_call` (what `ci.yml` uses for the three reusable workflows) has no path-filter
mechanism, and the `ml` extra's torch/numpy install is too heavy (§3) to pay on every push the way
`server`/`web`/`proto-check` do. So it's a standalone workflow with its own `on.push.paths`/
`on.pull_request.paths` (GitHub's native path filter, since none of the other workflows use one) —
`server/ml/**`, `server/pyproject.toml`, `server/uv.lock`, or the workflow file itself — instead of
being called from `ci.yml`. `server`/`server-slow` are untouched: neither installs the `ml` extra.

`ci.yml` also has one job of its own, not a reusable-workflow call: `coverage-badge`, gated
`if: push to main` (never a PR — a fork PR has no write access, and shouldn't mutate main anyway)
and `needs: [server, web]`. It downloads the `coverage-server`/`coverage-web` artifacts those two
jobs upload and renders each into a standalone shields.io-flat-style SVG badge
(`.github/scripts/coverage_badge.py`), committing `.github/badges/coverage-server.svg`/
`coverage-web.svg` if they changed — alongside the generator script rather than at the repo root,
keeping root to what `§1`'s layout actually lists. README's two coverage badges reference those
files by **relative path**, not shields.io's own hosted badge — this repo is private, and shields.io's anonymous
server-side fetch of `raw.githubusercontent.com` 401s on a private repo, so an externally-hosted
badge would never resolve; GitHub renders a repo-relative image straight from the repo for any
authenticated viewer, no external fetch involved. No external service (Codecov etc.) either —
self-hosted so it needs no account/token, at the cost of no PR-diff coverage comments or trend
graphs. `GITHUB_TOKEN`-authored pushes don't retrigger workflow runs, so this can't loop into
itself.

Coverage collection is a **second, non-blocking pytest rerun** in `server.yml`'s `server` job
(`pytest (coverage, informational)`, `continue-on-error: true`), not folded into the hard-gate
`pytest` step above it — `coverage.py`'s line tracing adds enough overhead to trip
`test_frontier_cache_warms_and_stays_fast`'s wall-clock ceiling (`tests/test_shanten.py`, a real
cache-performance assertion, not a flaky test), and that test is deselected from the coverage
rerun since the hard gate already exercised it for correctness. `web.yml`'s `web` job instead runs
the new `pnpm run test:coverage` script (`vitest --run --coverage`, `@vitest/coverage-v8`,
`json-summary` reporter, both vitest projects) as one step ahead of the existing Playwright e2e
step — no wall-clock-timing tests there to trip, so no rerun needed.

**Local dev vs. CI split.** `make test` / `make test-server` / `make test-web` run the fast
suite only — the loop a change actually blocks on. The slow suite (soaks, real-bot e2e,
hypothesis property runs, `@pytest.mark.slow`) is real, correctness-relevant coverage, not a
"nice to have when there's time" tier — it caught a genuine tile-conservation bug in
`mahjong_core.engine`'s claimed-win path that the fast suite structurally can't reach (needs
thousands of randomized games to hit). It's deliberately excluded from the everyday local loop
because of its cost (~15 min for the full 10,000-game soak), not skipped: `make
test-server-slow` runs it locally (`N=` overrides the game count, same as `make selfplay`), and
`server-slow` above runs it on every push/PR in CI, capped at 1,000 games so it doesn't blow up
per-push latency. CI is the backstop that guarantees this suite always actually runs somewhere,
since nothing about `@pytest.mark.slow` runs it by default.

All native tooling (`uv`, `pnpm`) rather than `docker compose run` — nothing here touches
Postgres, so the containers buy nothing but slower cold starts. `docker compose`-based
`make test` / `make proto-check` stay the local dev path; CI reimplements their commands
directly against the toolchain instead of shelling through Compose. Revisit if a job ever needs
Postgres.

Native tooling means none of the above ever builds the Dockerfiles themselves — a broken stage
(bad `COPY`, stale build arg, a torch/musl mismatch) would only surface at `make up` or deploy
time. **`.github/workflows/docker-build.yml`** (added 2026-09-27) closes that gap: a matrix job
builds `server`'s `dev`/`prod` and `web`'s `dev`/`prod`, plus a separate `build-server-ml` job
for `server`'s `ml` target (below) — all `push: false` (build-only, nothing published). Same
path-filter reasoning as `server-ml.yml` above: `workflow_call` can't filter by path, and a
Docker layer build is too heavy to pay on every unrelated push, so it's standalone with its own
`on.push.paths`/`on.pull_request.paths` — `server/Dockerfile`, `web/Dockerfile`, either
lockfile, either Compose file, or the workflow file itself.

`ml` needed its own job, not a 5th matrix entry: the first run that included it as a plain
matrix entry (2026-09-27, run `36332754927`) exhausted a standard `ubuntu-latest` runner's disk
building torch and exporting that layer via `cache-to: type=gha,mode=max`, killing the runner
process outright mid-step rather than failing the build cleanly. The `ml` target image is
**18.6GB** — torch's default PyPI wheel bundles full CUDA (`nvidia-cublas`, `cudnn`, `nccl`,
`triton`, ...) even though GPU passthrough is commented out in `docker-compose.yml`'s `trainer`
service and `docs/99-deferred.md` defers GPU training entirely for now (no compute budget
defined). Switching to a CPU-only torch wheel would shrink this dramatically, but GPU training
is still the eventual plan, so `build-server-ml` instead works around the size:

- **Frees disk first**: removes the preinstalled dotnet/Android SDK/GHC/CodeQL toolchains this
  job never uses, ~25-30GB back on a runner that otherwise starts with ~14GB free.
- **Caches via GHCR, not `type=gha`**: `cache-from`/`cache-to` point at
  `ghcr.io/<repo>/cache:server-ml` (`type=registry`, needs `permissions.packages: write` and a
  `docker/login-action` step). A registry push streams large blobs as a normal OCI transfer;
  `type=gha`'s cache-blob API buffering that same 18GB layer is what's suspected to have crashed
  the runner above.

`server-ml.yml` (§3) still separately smoke-tests the actual torch install/import/train-CLI path
natively via `uv sync --extra ml` — `build-server-ml` only proves the Dockerfile stage itself
builds, not that the code inside it runs correctly.

**Job graph**: GitHub Actions can't `needs:` across independent top-level workflow files, only
within one workflow's own jobs — reusable workflows are the way to get real separate files while
keeping the option to chain a job that has a genuine dependency. Here, none do: `server`,
`server-slow`, `web`, and `proto-check` are independent domains with no shared artifact, so root
`ci.yml` calls all three files with no `needs:`, and `server.yml` itself declares `server` and
`server-slow` as two separate jobs (also no `needs:` between them) rather than sequential steps —
unlike lint/test below, which do share a venv and gain nothing from splitting, `server-slow`
would otherwise sit on the fast job's own critical path for no reason, defeating the point of
having a separate fast loop at all. All four jobs run in parallel. Within `server.yml`'s `server`
job and `web.yml`, lint and test (plus typecheck, for `web`) also don't depend on each other's
*output*, but are sequential steps inside one job rather than separate jobs, so the dependency
install (`uv sync` / `pnpm install`) happens once per job instead of 2-3x or needing an artifact
handoff.

**Gates**:

| Check | Tolerance |
| --- | --- |
| `ruff check`, `ruff format --check` | hard — any finding fails the job |
| `pytest -q -m fast -n auto` | hard |
| `pytest -q -m slow -n auto --games=1000` (`server-slow`) | hard |
| `pnpm lint` (oxlint + oxfmt) | hard |
| `pnpm check` (svelte-check) | hard |
| `pnpm test` (vitest + Playwright) | hard |

**Pre-commit** (`lefthook.yml`): `web-lint`/`web-format` (oxlint/oxfmt on staged files),
`server-format`/`server-check` (ruff on staged `.py` files), and `web-typecheck` (pnpm check,
whole project) — svelte-check inherently checks the whole graph, not just staged files, so it's
slower and there's no meaningful way to scope it down without producing wrong (missing-context)
results.
