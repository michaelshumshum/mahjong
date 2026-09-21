# server/AGENTS.md

Python 3.13, FastAPI, asyncio. Architecture: `docs/00-architecture.md`.

## Layout

```
mahjong_core/   pure rules engine — no asyncio, no I/O, no unseeded randomness
app/            FastAPI, table actors, WebSocket, redaction, protocol models
bots/           bot tiers + arena harness
```

## Rules

- `mahjong_core` stays pure: `reduce(state, action) -> (state, events)`. Needing a clock,
  socket or random value there means the code belongs in `app/`.
- One table = one `asyncio.Task` = one writer. Never mutate `GameState` from outside it.
- `seat_view(state, seat)` and `redact_event(state, seat, event)` are the only paths to seat-visible state. Bots included.
- The server computes the legal-action set. Never trust a client-supplied one.
- `--workers 1` (`docs/07-infra.md §2`).

## Commands

```
make test         pytest, slow tests excluded
make selfplay     engine soak — N complete games, random bots
make arena        bot evaluation
make fmt lint typecheck
```

## Style

- `ruff` over `mahjong_core`, `app`, `bots`.
- Frozen dataclasses for state. Fully typed.
- `async def` only where there is real I/O or concurrency.
