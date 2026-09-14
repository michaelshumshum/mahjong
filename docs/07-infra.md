# 07 — Monorepo and Docker

## 1. Layout

```
mahjong/
├── Makefile                    # day-to-day interface; `make help`
├── docker-compose.yml          # dev: postgres, api, web; profiles: ml, tools
├── docker-compose.prod.yml     # overlay: prod targets, no mounts, no reload
├── .env.example
├── pnpm-workspace.yaml         # web + shared
├── server/                     # Python package, own pyproject + Dockerfile
├── web/                        # SvelteKit, own package.json + Dockerfile
├── shared/                     # generated protocol schema + TS types
└── docs/
```

`uv` owns Python, `pnpm` owns JS, the `Makefile` is the seam.

`shared/` holds generated artifacts only. `make proto` regenerates them from
`server/app/protocol.py`; CI fails if the committed output is stale
([02-protocol §6](02-protocol.md)).

Cross-process state (matchmaking, presence, rate limiting, sessions) sits behind
`app/infra/ports.py` with in-process implementations:

```python
class KV(Protocol):
    async def get(self, k: str) -> bytes | None: ...
    async def set(self, k: str, v: bytes, ttl: int | None = None) -> None: ...

class Queue(Protocol):                       # matchmaking
    async def push(self, q: str, item: bytes) -> None: ...
    async def pop_n(self, q: str, n: int) -> list[bytes]: ...   # atomic

class Bus(Protocol):                         # lobby presence fan-out, never in-room
    async def publish(self, ch: str, msg: bytes) -> None: ...
    def subscribe(self, ch: str) -> AsyncIterator[bytes]: ...
```

## 2. Process model

The API container runs uvicorn with **one worker**.

> Rooms are in-memory objects owned by one process. Two workers mean two disjoint sets of rooms
> with no routing between them — players 1 and 2 land in worker A's room #7 while players 3 and
> 4 land in worker B's *different* room #7.

Scale by adding nodes with room-aware routing (stage 2 in
[00-architecture §7](00-architecture.md)), never workers. For more CPU on one box, run N
containers on N ports behind the router, each with its own room shard. `--workers` is pinned by
a comment in the Compose file and a startup assertion in `main.py`.

## 3. Compose profiles

| Command | Brings up |
| --- | --- |
| `make up` | postgres, api, web |
| `docker compose --profile ml up trainer` | + torch-enabled container for training |
| `make arena A=FaanBot B=EfficiencyBot N=20000` | one-shot bot evaluation container |

The base `server` image has no torch; the `ml` target adds it (~180MB vs ~3GB). The API never
imports torch.

## 4. Image layering

Both Dockerfiles are multi-stage with a shared `base`:

```
base ──┬── deps    (lockfile only; cached across source edits)
       ├── dev     (+ dev deps, source mounted at runtime, hot reload)
       ├── prod    (venv copied from deps, non-root user, no build tools)
       └── ml      (prod + torch/numpy, for trainer and arena)
```

Dependency install is a separate layer keyed on the lockfile. `uv` and `pnpm` caches are
BuildKit cache mounts.
