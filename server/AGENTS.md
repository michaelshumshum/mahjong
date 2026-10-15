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
make bench-latency     latency tests serially against the 5 ms budget; run on the target CPU
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

## Where things live

Rule: root `AGENTS.md` "Types and constants". Anything `bots/` or `ml/` reads lives in
`mahjong_core` (stdlib-only) or `bots/`, never in `app/`.

| Concept | Home |
| --- | --- |
| Tile geometry: `N_TILE_TYPES`, `N_SUITED_TYPES`, `RANKS_PER_SUIT`, `COPIES_PER_TYPE`, `N_FLOWERS`, `TOTAL_PHYSICAL_TILES`, `WIND_TYPES`/`DRAGON_TYPES`/`ORPHAN_TYPES`/`ORPHAN_INDICES` | `mahjong_core/tiles.py` |
| Action-id layout: `N_ACTIONS`, `*_BASE`, `PASS_ID`…`WIN_ID`, `CHOW_IDS` | `mahjong_core/ml.py` |
| Action types / engine event types (`Event`, `EventKind`) | `mahjong_core/actions.py` / `mahjong_core/events.py` |
| Bot tier ids (`BotTier`, `BOT_TIERS`, `DEFAULT_BOT_TIER`, `LEARNED_TIERS`) — wire values, generated to TS | `bots/tiers.py` |
| Harness limits: `NO_DEADLINE`, `GAME_STEP_CAP` | `bots/base.py` |
| ML format: `PAD`, `MAX_DISCARDS`, `PADDED_WIDTH`/`PADDED_POSITIONS`, `PHASE_INDEX`, `N_OPPONENTS` | `ml/encode.py` (torch-free) |
| Dataset splits (`SPLITS`) | `ml/splits.py` |
| Table exceptions + `TABLE_CLOSED_ERROR` / table dataclasses (`Command`, `Envelope`, `SeatBinding`, `TableSettings`, …) | `app/errors.py` / `app/table_types.py` |
| REST request/response models | `app/api_models.py` |
| WS wire models (source of `protocol.d.ts`) | `app/protocol.py` |
| Redacted wire dataclasses (`*Wire`, `SeatView`), `CLAIM_KIND_WIRE` | `app/views.py`. They stay beside the redaction code because their `Entitlement` annotations are what the redaction walker checks |
| Server epoch ms (`now_ms`) | `app/clock.py` |
