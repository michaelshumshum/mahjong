# 00 — Architecture

## 1. Constraints

Mahjong is **turn-based, four-player, hidden-information, low-tick-rate**.

- **No tick loop, no physics, no interpolation.** State changes are discrete events (draw,
  discard, claim, win). No client prediction, rollback, lag compensation or snapshot
  interpolation.
- **Hidden information is the entire game.** Requires server-authoritative state *and* per-seat
  redaction on every outbound message.
- **Throughput is trivial; concurrency is not.** A table peaks at 2–5 messages/second, but four
  players can act *simultaneously* during a claim window (§4) — the hardest part of the system.
- **The rules are contested.** HK house rules vary: minimum faan, faan cap, scoring table, which
  hand sets count, flower handling, payment split. The engine is config-driven from day one.

## 2. Component map

```
                     ┌──────────────────────────────────────────────┐
   Browser           │  SvelteKit 5 app                             │
                     │  ┌────────────┐        ┌──────────────────┐  │
                     │  │ Svelte DOM │        │ PixiJS v8 canvas │  │
                     │  │ lobby, HUD │        │ table surface    │  │
                     │  │ modals,    │◄──────►│ tiles, melds,    │  │
                     │  │ scores     │ runes  │ discard pool     │  │
                     │  └────────────┘        └──────────────────┘  │
                     │          ▲  client game store (runes)        │
                     └──────────┼───────────────────────────────────┘
                                │  WebSocket (JSON envelope, seq'd)
                                │  HTTPS (auth, lobby, history)
    ────────────────────────────┼────────────────────────────────────
                                ▼
                     ┌──────────────────────────────────────────────┐
   Python process    │  FastAPI / Starlette (uvicorn + uvloop)      │
                     │                                              │
                     │  REST router ──── auth, profile, room list,  │
                     │                   replays, leaderboard       │
                     │                                              │
                     │  WS endpoint ──► Session (thin)              │
                     │                    · authenticate            │
                     │                    · parse + validate envelope│
                     │                    · push Command to room    │
                     │                    · pump outbound queue     │
                     │                         │                    │
                     │                         ▼                    │
                     │  RoomRegistry ──► Room (one asyncio.Task)    │
                     │                    · owns GameState          │
                     │                    · inbox: asyncio.Queue    │
                     │                    · timers, claim windows   │
                     │                    · event seq + ring buffer │
                     │                    · calls view_for(seat)    │
                     │                         │                    │
                     │                         ▼                    │
                     │  mahjong_core  (PURE — no asyncio, no I/O)   │
                     │    reduce(state, action) -> (state', events) │
                     │                         ▲                    │
                     │  bots/ ─────────────────┘ (same redacted view│
                     │                            as a human gets)  │
                     └──────────────────────────────────────────────┘
                                │
                           Postgres
                       users, finished games,
                       action logs (replays)
```

## 3. Core model

### Pure engine

```python
def reduce(state: GameState, action: Action) -> tuple[GameState, list[Event]]:
    ...
```

No `async`, clock, sockets, logging, or randomness except a seeded PRNG carried inside
`GameState`. Same seed + same action sequence → byte-identical output, forever.

This gives 100k-game test runs in CI, replays as `(seed, actions)` through the same code path as
live play, crash recovery by replaying a room's action log, and search bots that call `reduce` on
a determinized copy rather than needing a second rules implementation.

### Room actor

Each table is a single `asyncio.Task` owning its `GameState` exclusively. All mutation happens
inside that task's loop, fed by an `asyncio.Queue` of commands:

```python
class Room:
    def __init__(self, room_id: str, ruleset: RuleSet, seed: int):
        self.inbox: asyncio.Queue[Command] = asyncio.Queue()
        self.state = new_game(ruleset, seed)
        self.seq = 0
        self.history: deque[Envelope] = deque(maxlen=512)   # reconnect replay
        self.seats: list[SeatBinding | None] = [None] * 4   # human session or bot

    async def run(self):
        while True:
            cmd = await self._next()          # inbox.get() raced against timer deadlines
            actions = self._authorize(cmd)
            for action in actions:
                self.state, events = reduce(self.state, action)
                self._publish(events)         # redacts per seat
            self._arm_timers()
            self._poke_bots()
```

No locks. No `await` between read and write of shared state. Four simultaneous clicks are four
items in a queue.

> In-room messages never leave the owning task. A room lives on exactly one node and its
> members are routed there (§7); room state is never distributed.

## 4. Claim window

After a discard, up to three players may claim it. They race, and **first-to-arrive must not
win** — a chow claim landing in 80ms loses to a win claim landing in 3s.

Priority (configurable; common HK ordering):

```
Win (食糊)  >  Kong (槓) / Pung (碰)  >  Chow (上)
```
- Chow is only available to the player immediately downstream of the discarder.
- Ties between two Wins: nearest player counter-clockwise from the discarder, *or* multi-win
  payouts (一炮多響) — a ruleset flag.

The algorithm:

```
on DISCARD(seat, tile):
  legal = {s: legal_claims(state, s, tile) for s in others if legal_claims(...) non-empty}
  if legal is empty:            -> advance to next player's draw immediately
  window_id = next_window_id()
  for s in legal:  send CLAIM_OFFER(window_id, options, deadline_ts)
  open window:
    collect CLAIM(window_id, choice) from legal seats only
    close when  (all legal seats responded)  OR  (deadline reached -> absentees = PASS)
    EARLY EXIT: close as soon as the best outstanding possible claim cannot beat
                the best claim already received.
  resolve by priority -> emit exactly one CLAIM_RESOLVED event
```

Gotchas:

- **Only offer claims to players who actually have one.** Broadcasting "someone may claim" leaks
  information and trusts the client.
- **`window_id` on every claim.** Claims tagged with a stale window are dropped silently;
  without it a laggy click from the previous discard fires on the current one.
- **Early exit is a UX feature, not an optimisation.** If the only eligible chow passes, the game
  must continue instantly — waiting out a 5s timer every discard feels dead. Conversely, if a
  chow claim arrives while a pung is still possible from another seat, wait.
- **Pre-declared intent.** Clients pre-arm "auto-pass on chow" / "no calls" toggles; the server
  treats a pre-arm as an instant PASS. Keeps strong players from being prompted 40 times a hand.
- **Robbing the kong (搶槓)** opens a claim window on a *kong declaration*, not a discard. Same
  machinery, different trigger.

## 5. Redaction

The room never serializes `GameState`. Every outbound event goes through:

```python
def view_for(seat: int | None, state: GameState, event: Event) -> dict:
    """seat=None -> spectator view. Concealed tiles become counts, never identities."""
```

Invariants, enforced by a test that walks every field of every message type:

- Another player's concealed hand → `{"count": 13}`. Never a tile list.
- The wall → `{"remaining": 42}`. Never contents. Never the seed until the hand ends.
- A concealed kong (暗槓) → `{"kind": "concealed_kong", "count": 4}` to others; the tile
  identity is revealed only at hand end.
- Flowers, melds, discard pool, scores: fully public — send them.
- A spectator sees the union of what all four players show publicly, **not** their private
  hands. Showing hands to spectators requires a 30–60s delay.

**Bots consume the identical `view_for` output** — proof they can't cheat, and any bot is
runnable as a client against a real server for integration testing.

## 6. Stack

### Backend: FastAPI + native WebSockets

ASGI-native, WebSockets through Starlette, and pydantic models double as the protocol schema,
codegen'd into TypeScript (see [02-protocol.md](02-protocol.md)). Run on uvicorn with uvloop.

### Serialization: JSON

Payloads are tiny: ~2KB for a full state snapshot, ~150 bytes for a typical event.

### Frontend: SvelteKit 5 + PixiJS v8

Svelte owns all DOM chrome (lobby, HUD, claim buttons, score sheet, chat, settings); Pixi owns
the felt table and the tiles on it. One texture atlas, ~150 sprites, one draw call. Details in
[03-frontend.md](03-frontend.md).

### Storage

**Postgres** — users, room metadata, finished games as `(ruleset, seed, action_log)` with
`action_log` as JSONB, leaderboards. Matchmaking, presence, rate limiting and session state are
in-process structures behind `app/infra/ports.py`.

## 7. Scaling path

**Stage 1 — one process.** In-memory rooms, Postgres for durable records. Handles hundreds of
concurrent tables.

**Stage 2 — N nodes, sticky rooms.** A room is owned by exactly one node for its lifetime; all
four players and all spectators connect to that node.

```
client ── GET /rooms/{id}/route ──► router (room→node directory) ──► ws://node-3/ws?room=...
```

The router holds only the directory, the matchmaking queue and lobby presence. Room state stays
local and single-writer: **shard by room, never split a room.**

**Stage 3 — durability.** Append each action to Postgres as it's applied (or batch per hand). On
node loss, the router reassigns the room and the new owner replays the log — exact, not
approximate, because the engine is pure.

## 8. Failure handling

| Event | Behaviour |
| --- | --- |
| Player disconnects | Seat marked `DISCONNECTED`. Room continues. Grace period (default 20s) before the bot takes over; the seat keeps playing as `AUTOPLAY`. |
| Player reconnects | Auth, rejoin room, send `last_seq`. Server replays from ring buffer or sends a fresh `state_sync`. Bot relinquishes the seat. |
| Player never returns | Bot plays out the game. Result recorded against the human. |
| Turn timeout | Server acts for them: discard the drawn tile (tsumogiri), auto-pass claims. Three strikes → seat flips to `AUTOPLAY` for the rest of the game. |
| Bot raises / hangs | Bot runs with a deadline outside the room loop. On timeout, the room applies a safe default action. A bot must never be able to wedge a table. |
| Node dies (stage 3) | Router reassigns; new owner replays the action log; clients reconnect and `state_sync`. |

## 9. Anti-cheat

1. **Server-authoritative + per-seat redaction** (§5) closes information cheating, the dominant
   threat. If the client never receives a tile it shouldn't see, memory inspection is useless.
2. **Validate every intent against the server-computed legal-action set.** Never trust a
   client-declared meld, claim legality, faan count, or score.
3. **Rate-limit intents per session** and reject malformed envelopes hard.
4. **Provable fairness (optional):** commit `SHA256(seed || nonce)` at hand start, reveal
   `seed, nonce` at hand end. Players can verify the wall wasn't rigged.
5. **Collusion** (two humans sharing a screen) is unsolvable technically. Mitigate socially:
   random matchmaking for rated play, statistical review of suspicious deal-in patterns.
