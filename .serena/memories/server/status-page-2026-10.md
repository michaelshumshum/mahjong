# Public status page (2026-10-22)

`GET /status` (app/main.py) + web `/status` route, linked from lobby corner beside Source Code.

- `app/status.py` ServerStats singleton, reset per lifespan (`reset_stats()` starts `run_sampler` task, cancelled before drain). Table records bot latency in `_await_bot_job` via `server_stats()` (submit->answer, think delay excluded).
- Counts from `TableRegistry.load()` (aggregates only, private tables counted, never named). Showcase counts for spectators only, but its bot decisions DO feed bot latency (real load).
- loop lag floor ~1.0ms locally: asyncio sleep timer resolution, not real lag.
- games_finished_24h: `count_games_since` on `games.created_at`, cached 60s in main.py; None without DATABASE_URL. Showcase games aren't persisted so never counted.
- /status skips ApiConnectGate (it must show "unreachable" itself).
- History is in-memory, 5-min points, 24h ring: empty after every deploy -> "Not enough history yet" for ~10 min.
- Screenshot regen rewrites table-*.png with pixel noise even with no table change; only keep the ones the change affects.
- Not done: per-table liveness / stuck-table count, external uptime probe, alerting (docs/infra.md §8).
