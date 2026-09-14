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
There is no CI to enforce that yet — see §9.

Matchmaking, presence, rate limiting and session state are in-process structures for now.
Deferred — see [99-deferred.md](99-deferred.md).

## 2. Process model

The API container runs uvicorn with **one worker**.

> Rooms are in-memory objects owned by one process. Two workers mean two disjoint sets of rooms
> with no routing between them — players 1 and 2 land in worker A's room #7 while players 3 and
> 4 land in worker B's *different* room #7.

`--workers` is pinned by a comment in the Compose file and a startup assertion in `main.py`.
Multi-node scaling is out of scope at this stage. Deferred — see [99-deferred.md](99-deferred.md).

**No graceful shutdown yet.** `restart: unless-stopped` plus in-memory rooms means every deploy
or restart currently kills every live table mid-hand — there's no drain step between "stop
accepting new rooms" and "SIGKILL". The drain sequence (stop new joins, wait for in-flight hands,
persist or reject) is being specified in `00-architecture.md §8`; once it lands, `docker-compose
*.yml` needs a `stop_grace_period` sized to it and the API needs a SIGTERM handler that actually
uses the grace window instead of dying with the default 10s.

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

`alembic` is wired into the `Makefile` (`make migrate`, `make revision`) but no schema exists
beyond the one sentence in `00-architecture.md §6`. Minimum tables to get a first migration
written:

| Table | Holds |
| --- | --- |
| `users` | account identity for upgraded (non-guest) players; guests never get a row |
| `games` | `ruleset`, `seed`, `action_log` (JSONB), players, result — the durable record of a finished game |
| `leaderboard` | derived/aggregated from `games`; may be a materialized view instead of a table |

Room state itself is never persisted — it's in-memory only until stage-3 durability
(`00-architecture.md §7`) is built, which is out of scope now.

## 7. Observability

Nothing exists here yet. For a stateful single-process server where one wedged room silently
kills a game in progress, this is a gap, not a nice-to-have. Minimum bar before real users:

- **Logging:** structured (JSON) to stdout, one line per request/event, `LOG_LEVEL` already
  wired via env. Docker captures stdout; no log shipping decided yet.
- **Health:** `/healthz` already exists (used by the `api` container healthcheck). No readiness
  vs. liveness distinction yet — fine at one instance.
- **Metrics:** none. At minimum, room count, active connections, and per-room hand duration
  would surface a wedged room before a player reports it.
- **Error tracking:** none. Uncaught exceptions in a room's `asyncio.Task` currently have
  nowhere to go but the log.
- **Tracing:** not needed at this scale; skip until stage 2.

## 8. Licensing and attribution

Project code: MIT (`LICENSE`).

Third-party assets bundled with the client — notably the FluffyStuff riichi tile set
(`03-frontend.md`, public-domain-licensed) — need a `NOTICE` file crediting the source even
though the license doesn't require it. Add `NOTICE` at the repo root alongside `LICENSE` when
the asset is actually vendored in.

## 9. CI

There is no CI, and this isn't a git repository yet. `02-protocol.md §6` and `05-roadmap.md §3`
both describe "CI fails if stale" for generated protocol types — that's the intent, not the
current state. `make proto` regenerates; `make proto-check` (same regeneration, plus
`git diff --exit-code`) is the gate to wire into CI once there's a repo and a workflow file to
wire it into. Don't rely on `proto-check` today; it will only pass if `proto` was already run.
