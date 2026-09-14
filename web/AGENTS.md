# web/AGENTS.md

SvelteKit 5 (runes), PixiJS v8. Frontend outline: `docs/03-frontend.md`.

## Layout

```
src/routes/     lobby, table, replay, profile
src/lib/net/    WebSocket client, seq tracking, reducer, generated protocol types
src/lib/game/   client state store ($state)
src/lib/table/  Pixi renderer
src/lib/ui/     Svelte components
```

## Rules

- Svelte owns DOM chrome. Pixi owns the table surface and the tiles on it.
- One-way flow: server event → reducer → store → renderer. The renderer never owns game truth.
- No optimistic local mutation. Send an intent, wait for the event.
- `src/lib/net/protocol.d.ts` is generated — edit `server/app/protocol.py`, run `make proto`.
- The reducer is pure and exhaustively switched over the event union.
- A `seq` gap triggers a resync, never a silent patch.

## Commands

```
make test-web
pnpm dev | pnpm build | pnpm lint
```

## Style

- Runes (`$state`, `$derived`, `$effect`), not legacy stores.
- Pixi sprites keyed by `tile_id` so animation identity survives updates.
- Interactive controls live in DOM, not canvas.
