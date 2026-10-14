# Abandoned-table early termination (2026-10, ADR 0024, architecture.md §8.2)

- `Table.abandon_grace_seconds` (None = never) comes from env `ABANDONED_TABLE_GRACE_SECONDS` (120) via `lifespan` -> `ws.reset_registry` -> `TableRegistry`. Showcase gets none. Bare `Table(...)`/`TableRegistry()` in tests default to None, so existing tests are unaffected.
- Armed in `process_one()` tail (`_update_abandon_timer`), not in `mark_disconnected`: the off-loop disconnect enqueues `_WakeUp` + `SeatDisconnected`, and the tail check catches strike-autoplay too. `reconnect()` disarms directly so a second departure gets a full fresh grace; `_handle_abandon_timeout` re-checks anyway.
- "abandoned" = started + >=1 non-bot binding + none `connected`. A strike-autoplayed human with an open socket counts as gone (spec choice).
- On close: `closed=True`, bot tasks cancelled, `_poke_bots`/`_handle_bot_result` refuse, inbox getter cancelled (only place the never-cancel rule is broken; nothing reads the inbox after), `error{code:table_closed}` broadcast, spectators closed. `run()` returns before the GAME_OVER persist path.
- Registry evicts closed tables and tombstones the id in `_closed`; `ws_endpoint` refuses closed ids before `get_or_create`, `_generate_table_id` skips them, `Session.handle` covers the race of a connection grabbed just before close.
- Client: `socket.ts` closes itself + stops reconnecting on `table_closed` after ingesting the frame (closing inside `#ingest` got overwritten by the seq path's `setStatus('open')`).
- Test driving: a manual `process_one()` loop needs 3 ticks after `mark_disconnected` (`_WakeUp`, `SeatDisconnected`, then the deadline pop).
