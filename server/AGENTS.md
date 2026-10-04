# server/AGENTS.md

Python 3.13, FastAPI, asyncio. Architecture: `docs/architecture.md`; rules: `docs/rules.md`;
bots: `docs/bots.md`; ML: `docs/ml.md`.

## Layout

```
mahjong_core/   pure rules engine — no asyncio, no I/O, no unseeded randomness
app/            FastAPI, table actors, WebSocket, redaction, protocol models, db/
bots/           bot tiers + arena harness
ml/             RL + supervised training (torch via the `ml` extra)
tools/          gen_protocol.py (make proto)
tests/          pytest
```

Full file map: `docs/infra.md §1`.

## Rules

- `mahjong_core` stays pure: `reduce(state, action) -> (state, events)`. Needing a clock,
  socket or random value there means the code belongs in `app/`.
- One table = one `asyncio.Task` = one writer. Never mutate `GameState` from outside it.
- `seat_view(state, seat)` and `redact_event(state, seat, event)` are the only paths to seat-visible state. Bots included.
- The server computes the legal-action set. Never trust a client-supplied one.
- `--workers 1` (`docs/infra.md §3`).

## Commands

```
make test-server       pytest fast suite (parallelized across all cores)
make test-server-slow  pytest slow suite — soaks, real-bot e2e, hypothesis runs; CI runs this too
make selfplay          engine soak — N complete games, random bots
make arena             bot evaluation
make migrate           alembic upgrade head
make fmt lint typecheck
```

Native (toolchain from root `mise.toml`, run from `server/`):

```
uv sync --locked                       # add --extra ml for torch; a plain sync removes it
uv run pytest -q -m fast -n auto
uv run pytest -q -m slow -n auto --games=1000
uv run ruff check . && uv run ruff format --check .
uv run alembic upgrade head            # needs DATABASE_URL
uv run uvicorn app.main:app --reload --workers 1   # needs CORS_ORIGINS for the web dev server
```

Env vars and the full native/Docker split: `docs/infra.md §2`.

## Style

- `ruff` over `mahjong_core`, `app`, `bots`.
- Frozen dataclasses for state. Fully typed.
- `async def` only where there is real I/O or concurrency.
