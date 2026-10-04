# server/

Full rules: `server/AGENTS.md`, `docs/architecture.md`.

## Layout
- `mahjong_core/` — pure rules engine: `reduce(state, action) -> (state, events)`. No asyncio, I/O, clock, or unseeded randomness; stdlib-only. Modules: tiles, wall, melds, claims, actions, state, engine, shanten, scoring/, config, ml (feature encoding).
- `app/` — FastAPI (`main.py`), per-table actor (`table.py`), registry, ws, `views.py` (redaction), `protocol.py` (source of generated TS types), outbox, idempotency, db/.
- `bots/` — random, efficiency, faanbot, safety, valuation, features, arena, selfplay, worker.
- `tools/gen_protocol.py` — `make proto` generator.
- `tests/` — flat `test_*.py`; markers `fast`/`slow`.

## Invariants
- One table = one asyncio.Task = sole writer of its `GameState`.
- `seat_view(state, seat)` / `redact_event(state, seat, event)` are the only paths to seat-visible state — bots included.
- Server computes legal-action set; never trust the client's.
- uvicorn `--workers 1` (`docs/infra.md §3`).
