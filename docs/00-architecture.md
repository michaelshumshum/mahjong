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
   Browser           │  SvelteKit 2 app (Svelte 5, runes)           │
                     │  ┌────────────────────────────────────────┐  │
                     │  │ Svelte DOM/CSS — lobby, HUD, modals,    │  │
                     │  │ scores, AND the table surface itself:   │  │
                     │  │ tiles, melds, discard pool. No canvas.  │  │
                     │  └────────────────────────────────────────┘  │
                     │          ▲  client game store (runes)        │
                     └──────────┼───────────────────────────────────┘
                                │  WebSocket (JSON envelope, per-seat seq'd)
                                │  HTTPS (lobby, replays)
    ────────────────────────────┼────────────────────────────────────
                                ▼
                     ┌──────────────────────────────────────────────┐
   Python process    │  FastAPI / Starlette (uvicorn + uvloop)      │
                     │                                              │
                     │  REST router ──── table list, replays,        │
                     │                   leaderboard (no auth       │
                     │                   endpoint — see §2.1)       │
                     │                                              │
                     │  WS endpoint ──► Session (thin)              │
                     │                    · bind seat from          │
                     │                      join{seat, name} /      │
                     │                      reclaim via hello{seat} │
                     │                    · parse + validate envelope│
                     │                    · push Command to table    │
                     │                    · pump BOUNDED outbound   │
                     │                      queue (drop→state_sync) │
                     │                         │                    │
                     │                         ▼                    │
                     │  TableRegistry ──► Table (one asyncio.Task)    │
                     │                    · owns GameState          │
                     │                    · inbox: asyncio.Queue    │
                     │                    · timer heap (§3)         │
                     │                    · per-seat seq + per-seat │
                     │                      ring buffers (redacted) │
                     │                    · calls seat_view() /     │
                     │                      redact_event() (§5)     │
                     │                         │                    │
                     │                         ▼                    │
                     │  mahjong_core  (PURE — stdlib only, no       │
                     │    asyncio, no I/O, no numpy)                │
                     │    reduce(state, action) -> (state', events) │
                     │                         ▲                    │
                     │  bots/ ─────────────────┘ (same seat_view,   │
                     │                       worker pool, §3)       │
                     └──────────────────────────────────────────────┘
                                │
                           Postgres
                       users, finished games,
                       action logs (replays)
```

### 2.1 Auth

Guest-only, by design — not guest-first with an account upgrade path. There is no account, no
password, no email, no JWT, and no REST auth endpoint. A player picks a display name
client-side; it persists in `localStorage` so it survives a reload, and travels with the
connection as a plain field on `join` (not `hello` — `hello.seat` only ever reclaims an
already-bound seat on reconnect, and the server already has the name from that seat's original
`join`; `SeatBinding.name` holds it for the game).

```
client ──ws://…/ws?table=…────────────────────────────────────────────► WS endpoint
client ──join{seat?, name?}────────────────────────────────────────────► Session binds this seat,
                                                                          ack carries a fresh
                                                                          reconnect_secret
client ──hello{seat, secret}──(a later reconnect, same seat)──────────► Session reclaims it iff
                                                                          secret matches
```

**Seat identity (which seat, whose name) is client-asserted; seat *possession* is not.** `join`
mints a random per-seat credential — `SeatBinding.reconnect_secret`, `secrets.token_urlsafe(16)`
— and hands it back exactly once, in that `join`'s own `ack` (`AckPayload.reconnect_secret`;
`ack` is sender-only, never broadcast, `docs/02-protocol.md §3`). The client persists it in
`localStorage` alongside the seat number (`web/src/lib/ui/settings-storage.ts`'s
`saveSecretForTable`/`loadSecretForTable`) and presents it on every later `hello{seat, secret}`;
`Table.reconnect` compares it against the binding with `secrets.compare_digest` (constant-time)
and refuses the reclaim — `error{code:'bad_secret'}` — on any mismatch, including a missing
secret. This closes a real seat-hijack gap an earlier version of this design accepted: previously
any `hello{seat}` reclaimed that seat outright, so a second browser — or a malicious client that
simply guessed a live seat number, 0-3 — could silently steal a live seat mid-game, same
display name or not, with the original connection never notified. Still no account behind any of
this: the secret authenticates "the browser `join` handed this seat to," not a person, so a
player who loses their `localStorage` (new device, cleared storage, a private-browsing tab) loses
the seat exactly as before this change — the guest-only, no-real-stakes tradeoff is unchanged,
only the hijack path is closed instead of open.

## 3. Core model

### Pure engine

```python
def reduce(state: GameState, action: Action) -> tuple[GameState, list[Event]]:
    ...
```

No `async`, clock, sockets, logging, or randomness except tile shuffling, which is fully
determined by `game_seed`. `game_seed` is fixed once at game start and **never leaves this
process** — not even redacted, not ever, during play. Each hand derives its own subseed,

```
hand_seed = SHA256(game_seed || hand_no)
```

and shuffles that hand's wall from `hand_seed` alone. Only `hand_seed` is ever revealed, and only
at that hand's end (§5, §9). Same `game_seed` + same action sequence → byte-identical output,
forever, but no single reveal exposes a future hand's wall (revealing `game_seed` itself would
hand every later wall in the game to every player).

This gives 100k-game test runs in CI, replays as `(game_seed, actions)` through the same code
path as live play, and search bots that call `reduce` on a determinized copy rather than needing
a second rules implementation. Crash recovery by replaying a table's action log is **not** a v1
property — see §7.

**Two pure entry points.** `reduce()` takes exactly one `Action` and returns once a real decision
is needed from some seat, or the hand ends (`Phase.HAND_OVER`). Advancing from `HAND_OVER` to the
next deal (or `GAME_OVER`) is a second function, `engine.start_next_hand(state) -> (state,
events)` — there's no `Action` for "deal the next hand" since it isn't a seat's decision
(`legal_actions` is `()` in that phase). The Table loop calls it right after a `reduce()` call
lands on `HAND_OVER`, once the hand-end hold (below) closes.

### Table actor

Each table is a single `asyncio.Task` owning its `GameState` exclusively. All mutation happens
inside that task's loop, fed by an `asyncio.Queue` of commands:

```python
class Table:
    def __init__(self, table_id: str, ruleset: RuleSet, game_seed: int):
        self.inbox: asyncio.Queue[Command] = asyncio.Queue()
        self.state = new_game(ruleset, game_seed)
        self.event_id = 0                     # internal monotonic id: logging/replay only, NEVER on the wire
        self.seat_seq: list[int] = [0, 0, 0, 0]        # per-seat outbound seq: dense, gapless, per stream
        self.spectator_seq: dict[str, int] = {}        # per spectator-session, same discipline
        self.spectators: dict[str, Callable] = {}      # session_id -> push callback
        self.ring: dict[int | str, deque[Envelope]] = {  # per-seat/spectator, holds ALREADY-REDACTED frames
            seat: deque(maxlen=512) for seat in range(4)
        }
        self.seats: list[SeatBinding | None] = [None] * 4   # human session or bot
        self.deadlines = TimerHeap()          # claim window + per-seat clocks + bot budgets

    async def run(self):
        getter = asyncio.create_task(self._inbox_getter())    # long-lived; NEVER cancelled
        while True:
            cmd = await self._next(getter)     # races getter against self.deadlines.peek(); never cancels getter
            action = self._authorize(cmd)      # None if illegal for cmd.seat right now -- drop it
            if action is not None:
                self.state, events = reduce(self.state, action)
                self.event_id += 1
                self._publish(events)          # redact_event() per recipient; stamps that stream's own seq (§5)
                if self.state.phase == Phase.HAND_OVER:
                    self._open_hand_end_window() # hold the round open -- see "Hand-end hold" below
            self._arm_timers()
            self._poke_bots()                  # submits to a worker pool; never runs bot logic in this loop
```

No locks. No `await` between read and write of shared state. Four simultaneous clicks are four
items in a queue.

> In-table messages never leave the owning task. A table lives on exactly one node and its members
> are routed there (§7); table state is never distributed.

**Sequencing.** `seq` is per-seat (and per-spectator-session): dense and gapless *within that
stream*, never per-table. Two seats' `seq` counters have no relationship to each other. `event_id`
is a separate, internal, table-global monotonic counter for server-side logging only — never
serialized to a client. The ring buffer is per-seat and stores frames *after* `redact_event()`
has run, never raw `Event` objects, so a reconnect replay ([02-protocol.md
§5](02-protocol.md)) can never hand a redacted-out tile back to a seat.

**Spectating.** An explicit `?spectate=true` connect-time flag (`app/ws.py`), not a passive
"never sent `join`" default — a passive default would race the `hello{client_version}` every
real client sends immediately after connecting, before `join`. `join`/`reconnect` promote a
spectating connection away the moment it claims a seat. A spectator has no `SeatBinding` and no
reconnect/reclaim: `unregister_spectator` drops its ring/seq entry the moment its connection
closes, and reconnecting is always a brand-new spectator session with a fresh `state_sync`. A
spectator gets `seat_view(state, None)`, every broadcast, and every `redact_event(state, None,
event)` output — except `claim_offer`, which is never sent to spectators since it would name the
offered seat's own concealed tiles.

**Table settings.** `TableSettings` (`app/table.py`) holds per-table options that aren't game rules
(those are `RuleSet`). `spectators_see_hands` switches every spectator to the open-hands view (§5);
`Table.update_settings` swaps it mid-game and resyncs spectators. No wire message sets it yet.

**Ruleset selection.** Unlike `TableSettings`, `RuleSet` is fixed once at table construction —
`mahjong_core` has no path to change it mid-game — so it's chosen at connect time instead of over
the envelope: `?ruleset=<preset_id>` (`mahjong_core.presets.RULESET_PRESETS`, default
`hk_classic`) or `?ruleset=custom&rules=<RuleSet.to_dict() JSON>` on the WS URL, resolved by
`app/ws.py`'s `_resolve_ruleset` and threaded into `TableRegistry.get_or_create` the same way
`?practice=`/`?seed=` already are — only meaningful the first time a given table id is created.
`state_sync.ruleset`/`ruleset_preset` (`docs/02-protocol.md` "Ruleset selection") surface the
resolved value so a client can render it. No table-creation UI reads/writes these yet — see
`docs/05-roadmap.md`.

**Showcase table.** `TableRegistry.start_showcase` (`app/registry.py`, started from `lifespan` for
`SHOWCASE_TABLE_ID`, default `BOTS`, empty disables) keeps one all-bot, open-hands table running
forever. `Table(all_bots=True)` binds all four seats and deals when `run()` starts; its hand-end
hold runs the full `hand_end_seconds` (no human to ack, and it's the spectators' only time to read
the result). After `GAME_OVER` the finished table stays up for 30s, then a fresh game replaces it
under the same id and the old table's spectator sockets are closed so their reconnect lands on
the new one. Not persisted, not waited on by the shutdown drain (§8.1).

**Timer race.** `asyncio.wait_for(inbox.get(), timeout)` is wrong here: when the timer wins, the
cancelled `get()` can silently drop an item that arrived in the same scheduler tick. `_next()`
holds one long-lived `_inbox_getter()` task for the table's entire lifetime and only ever awaits
`asyncio.wait({getter, sleep_until_next_deadline})`, never cancelling `getter`. A table has several
concurrent deadlines live at once — the current claim window, each connected human's per-turn
clock, each pending bot's budget — so `self.deadlines` is a heap keyed by `(deadline_ts, id)`, not
a single scalar.

**Bots off the loop.** `_poke_bots()` never runs bot search inline. It submits
`(table_id, window_id, state_version, seat_view)` to a `ProcessPoolExecutor` — the GIL makes a
thread pool useless for CPU-bound pure-Python search — with a hard deadline (`bots/worker.py`'s
`compute_action`, 10s, `_BOT_JOB_TIMEOUT_SECONDS`), and returns immediately. The worker builds the
requested tier (`T0`/`T1`/`T2`, default `T2`/`FaanBot`, [04-bots.md](04-bots.md)) and drives
`Bot.act(view, mask, deadline)` against a `SeatView`/`legal_mask`, returning a bare action id — a
worker process never receives `GameState`; `Table._handle_bot_result` decodes the id against the
real state once it lands back. The result re-enters through `inbox`, tagged with the
`(window_id, state_version)` it was computed against, and is dropped if either has moved on by
the time it arrives — the same staleness protection a laggy human click gets (§4). On a worker
crash or hard timeout, `Table` applies no synthesized action itself; it just clears the pending job
tag so the next tick retries. What actually bounds a stalled turn is the independent per-seat
`ruleset.turn_seconds` timer (§8), not this path.

### Hand-end hold

A hand ending — win or exhaustive draw — holds the table at `Phase.HAND_OVER` instead of chaining
straight into `start_next_hand()`, so a client has a chance to show the just-finished hand before
the board resets:

```
on HAND_OVER:
  acked = {seat for seat in bound_seats if seat.status in (bot, autoplay)}
  if len(acked) == 4:      -> advance immediately (e.g. an all-bot practice table)
  arm deadline_ts = now + ruleset.hand_end_seconds   # default 10s
  wait:
    seat ack (hand_end_ack)  -> acked.add(seat); all 4 acked -> advance
    OR deadline reached      -> advance regardless of who hasn't acked
```

`mahjong_core` is untouched by this — `Phase.HAND_OVER`/`start_next_hand()` are pure engine
facts; the ack tracking and timer are `app/table.py`-only (`_open_hand_end_window`,
`mark_hand_end_ack`, one `TimerHeap` entry per hold, not per seat — there's no priority/tiebreak
here, just "wait for N of 4"). A stray or late ack (wrong hand, already resolved) is a no-op.

### Outbound backpressure

Session pumps a **bounded** outbound queue per connection (`app/outbox.py`'s `BoundedOutbox`,
default 64 frames), not an unbounded one — an unbounded queue behind a stalled TCP socket is a
slow memory leak that grows until the process OOMs under real traffic.

Overflow policy: drop the oldest non-`ack`/`error` frame first, and the instant anything is
dropped, clear every remaining non-critical frame and publish a fresh `state_sync` in its place
(a real `seq`, allocated normally). Because `seq` is per-seat and gapless, a drop is self-healing:
the client's next `last_seq` is behind, and the resume protocol ([02-protocol.md
§5](02-protocol.md)) notices the gap and requests exactly the `state_sync` this policy already
forces. If the queue is still over capacity after collapsing to `state_sync` (everything queued
was `ack`/`error`), the connection is dead, not just slow, and `Session` closes it.

`Table.publish_to_seat` only ever does a synchronous, non-blocking `push()` onto the queue — never
awaits the socket write. A separate `Session.writer()` task owns `websocket.send_text()`, so a
stalled TCP connection blocks only that task, never the Table task.

## 4. Claim window

After a discard, up to three players may claim it. They race, and **first-to-arrive must not
win** — a chow claim landing in 80ms loses to a win claim landing in 3s.

Priority, tiebreaks, and the kong-vs-pung edge case are **canonical in
[01-rules-spec.md §6](01-rules-spec.md)** — this section covers only the window mechanics below.
Don't restate the ordering here; if the two docs ever disagree, 01-rules-spec.md §6 wins.

```
Win (食糊)  >  Kong (槓) / Pung (碰)  >  Chow (上)
```

- Chow is only legal for `claimer_seat == (discarder_seat + 1) % 4` — the seat immediately after
  the discarder in turn order (01-rules-spec.md §2). No other seat may claim a chow on this
  discard, regardless of priority.
- v1 is single-winner: a Win-vs-Win tie resolves by seat order and the algorithm below emits
  exactly one `CLAIM_RESOLVED`. Multi-win payouts (一炮多響) are a ruleset flag that exists but
  does nothing yet — deferred past v1; see [99-deferred.md](99-deferred.md).

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

`claims.can_close_early`/`resolve_claims` are pure and reason only over responses already
collected — early exit is invoked from `mahjong_core.engine._apply_claim_response` itself, the
moment a real response makes the window ready. `Table` owns what the pure engine can't: arming
`deadline_ts` (`TimerHeap`, keyed `(deadline_ts, window_id)`) when a window opens, and — on timer
expiry, staleness-checked against the live `window_id` — synthesizing `Pass` for every seat that
never responded, fed through the same `reduce()`/`resolve_claims` path. Window duration is
`RuleSet.claim_seconds` (`mahjong_core/config.py`, default 5s).

Gotchas:

- **Only offer claims to players who actually have one.** Broadcasting "someone may claim" leaks
  information and trusts the client.
- **`window_id` on every claim.** Claims tagged with a stale window are dropped silently;
  without it a laggy click from the previous discard fires on the current one.
- **Early exit is a UX feature, not an optimisation — kept deliberately.** If the only eligible
  chow passes, the game must continue instantly; waiting out a 5s timer every discard feels dead.
  **Accepted information leak:** this trades a UX necessity for two signals an attentive opponent
  can read — (1) how long the window stays open at all tells non-claimants that *someone* had a
  claim; (2) a player who passes immediately, before the window closes, learns from the window
  staying open afterward that another seat still holds a live claim. Accepted, not mitigated —
  timing-obfuscation (padding `claim_offer` delivery) was considered and rejected: it's
  incompatible with instant early exit, which is the whole point of this bullet.
- **Pre-declared intent.** Clients pre-arm "auto-pass on chow" / "no calls" toggles; the server
  treats a pre-arm as an instant PASS. Keeps strong players from being prompted 40 times a hand.
- **Robbing the kong (搶槓)** opens a claim window on a *kong declaration*, not a discard. Same
  machinery, different trigger.

## 5. Redaction

The table never serializes `GameState`. Redaction is **two named functions**, not one overloaded
one — they answer different questions:

```python
def seat_view(state: GameState, seat: int | None) -> SeatView:
    """Full redacted snapshot for one recipient. seat=None -> spectator view.
    Used by anything that needs 'the whole table as seat X may see it right now'
    rather than one wire event: bots (§3), state_sync, ML encoders (06-ml.md)."""

def redact_event(state: GameState, seat: int | None, event: Event) -> dict:
    """Per-event wire redaction: the JSON actually sent for one logical Event,
    to one recipient. Concealed tiles become counts, never identities."""
```

### `SeatView`

**This subsection is the canonical definition** — `server/app/views.py` — depended on by
[04-bots.md](04-bots.md) (bot `act()` input) and [06-ml.md](06-ml.md) (encoder input), neither of
which may change its shape unilaterally. Lives in `app/`, not `mahjong_core/`: `server/AGENTS.md`
reserves `mahjong_core` for pure rules, and "what may this specific recipient see" is a
wire-recipient concern, not a rule.

```python
@dataclass(frozen=True)
class SeatView:
    seat: int | None                              # None for a spectator view
    hand_no: int
    prevailing: Wind
    dealer: int
    turn: int                                     # seat currently acting
    phase: Phase                                  # AWAIT_DRAW | AWAIT_ACTION | AWAIT_CLAIMS | ...
    own_hand: tuple[int, ...]                     # tile_ids — populated ONLY when seat is this view's own seat
    concealed_counts: tuple[int, int, int, int]   # per seat, including own (uniform, redundant with own_hand)
    melds: tuple[tuple[Meld, ...], ...]           # per seat, fully public
    discard_pools: tuple[tuple[int, ...], ...]    # per seat, fully public tile_ids
    flowers: tuple[tuple[Flower, ...], ...]       # per seat, fully public
    wall_remaining: int                            # count only — see wall bullet below
    seat_status: tuple[str, ...]                   # connected | disconnected | autoplay | bot | empty, per seat
    names: tuple[str | None, ...]                  # chosen guest display name, per seat — None if unjoined
    scores: tuple[int, int, int, int]
    legal_actions: tuple[Action, ...]              # non-empty whenever actions.legal_actions(state, seat) is
    claim_options: tuple[ClaimOffer, ...]          # this seat's own live claim offer (§4), if any
    deadline_ts: int | None                        # the deadline relevant to this seat, if any
```

`legal_actions`/`claim_options` reuse `mahjong_core.actions.Action` / `mahjong_core.state.
ClaimOffer` directly rather than a separate wire type — both already carry only this seat's own
tiles or already-public tiles, so a parallel type would add translation with no redaction
benefit. `legal_actions` is non-empty whenever `actions.legal_actions(state, seat)` is — "seat's
own `AWAIT_ACTION` turn" *or* "seat holds a live claim/kong-rob offer", not just `seat == turn`.

There is no field on `SeatView` capable of holding another seat's concealed tile identity —
`own_hand` is the only tile-id field, and it's populated only for the view's own seat.

`seat_status` (`connected`/`disconnected`/`autoplay`/`bot`/`empty`) comes from
`SeatBinding.status`; `bot` seats are bound at table construction for practice mode
([05-roadmap.md](05-roadmap.md)) and driven through the identical `_poke_bots`/`BotJobTag` path
as `autoplay` seats. `names` comes from `SeatBinding.name`, set once at `join`
(`_normalize_name`), synthesized from the table's `bot_tier` for a `bot` seat. `deadline_ts`
surfaces `ClaimWindow.deadline_ts` for a claim offer, or the per-turn deadline when `seat ==
state.turn` and `phase == AWAIT_ACTION`.

### Redaction test

Invariants are enforced by a **schema walker**, not a substring scan of serialized bytes.
Scanning JSON text for tile-shaped integers is a false-positive machine — `"tile_id": 5` and
`"pool_index": 5` are indistinguishable as raw digits — so entitlement is an explicit, per-field
annotation the walker checks structurally:

```python
class Entitlement(Enum):
    PUBLIC = "public"          # any recipient, any time — melds, discards, scores, flowers
    OWN_SEAT = "own_seat"      # tile identity allowed only when recipient seat == field's owning seat
    COUNT_ONLY = "count_only"  # non-owners get a count in this field, never an identity
    HAND_END = "hand_end"      # tile identity allowed only once that hand has reached HAND_END

tile_id: int | None = Field(json_schema_extra={"entitlement": Entitlement.OWN_SEAT})
```

The test enumerates every wire message type × every recipient (seats 0–3, plus `None` for
spectator), builds one instance via `redact_event`/`seat_view`, and asserts: any field annotated
`OWN_SEAT`, `COUNT_ONLY`, or `HAND_END` whose predicate is false for that (seat, state) pair is
either absent from the payload or holds a count/placeholder — never a real tile id.

Invariants this enforces:

- Another player's concealed hand → `{"count": 13}`. Never a tile list.
- The wall → `{"remaining": 42}`. Never contents, never `game_seed`. Only that hand's
  `hand_seed = SHA256(game_seed || hand_no)` is revealed, and only at that hand's end (§3, §9) —
  `game_seed` itself is never on the wire during play.
- A concealed kong (暗槓) → `{"kind": "concealed_kong", "count": 4}` to others; the tile
  identity is revealed only at hand end.
- Flowers, melds, discard pool, scores: fully public — send them.
- A spectator sees the union of what all four players show publicly, **not** their private
  hands — unless the table sets `spectators_see_hands` (§3), in which case `seat_view(state,
  None, reveal_hands=True)` adds `hands` (every seat's concealed tiles) and `redact_event(...,
  reveal_hands=True)` hands the spectator every `OWN_SEAT` field (draw/kong-replace tile ids,
  concealed-kong tiles). `reveal_hands` raises for a real seat, so no player can ever be handed
  another seat's tiles through it; the schema walker checks it under its own `OPEN_HANDS`
  entitlement. There is no delay: an open-hands table is for watching bots (or a table that
  opted in), where a spectator relaying hands to a player isn't a concern.

**Bots consume the identical `seat_view` output a human's client would render from** — proof they
can't cheat, and any bot is runnable as a client against a real server for integration testing.

## 6. Stack

### Backend: FastAPI + native WebSockets

ASGI-native, WebSockets through Starlette, and pydantic models double as the protocol schema,
codegen'd into TypeScript (see [02-protocol.md](02-protocol.md)). Run on uvicorn with uvloop.

### Serialization: JSON

Payloads are tiny: ~2KB for a full state snapshot, ~150 bytes for a typical event.

### Frontend: SvelteKit 2 (Svelte 5, runes) — DOM/CSS, no canvas

SvelteKit and Svelte version independently: the stack is SvelteKit 2.x on Svelte 5.x. The table
is DOM/CSS like everything else in the client — this is a turn-based, low-tick-rate game (§1);
there's no draw-call budget worth a second rendering system to protect, and DOM/CSS gets text
layout, hit-testing, and accessibility for free instead of fighting a canvas for them. Svelte owns
the whole client: lobby, HUD, claim buttons, score sheet, settings, and the table surface (tiles,
melds, discard pool). Details in [03-frontend.md](03-frontend.md).

### Storage

**Postgres** — users, table metadata, finished games as `(ruleset, game_seed, action_log)` with
`action_log` as JSONB, leaderboards. Matchmaking, presence, rate limiting and session state are
v1 **module-level dicts in the API process** — no `KV`/`Queue`/`Bus` abstraction layer. A
Protocol-per-backend split earns its keep once there's a second real backend to swap in (Redis,
say); v1 has exactly one backend (in-process memory), so the abstraction has no job yet, and it
would invite `async def` on a plain dict lookup with no I/O behind it, violating `server/AGENTS.md`'s
"`async def` only where there is real I/O or concurrency" rule. Deferred — see
[99-deferred.md](99-deferred.md).

`TableRegistry` (`server/app/registry.py`) is exactly this: an in-process `dict[str, Table]` plus
the bookkeeping to run each table's `asyncio.Task`. `Table.run()` returns on `GAME_OVER`, and
`TableRegistry` drops its task-bookkeeping entry then; the `Table` object itself is **not**
evicted — reconnecting after the game ends is still a supported, synchronous path
(`Table.reconnect`/`resume`). Full table eviction (freeing a long-dead finished game's memory) is
an open gap — no session-expiry/TTL policy exists.

`Table` persists a real game's full action log (`self.actions`, every `Action` that ran through
`reduce()` — never a `start_next_hand()` transition, which isn't an `Action`; replay reconstructs
those off `Phase.HAND_OVER`) via an optional `session_factory: async_sessionmaker[AsyncSession] |
None` threaded through `Table.__init__`/`TableRegistry`. `app/main.py`'s `lifespan` builds the real
engine from a `DATABASE_URL` env var (unset → no persistence) and installs it into a fresh
`TableRegistry` on every ASGI startup. On `Phase.GAME_OVER`, `Table` calls `save_game_record` at
most once with `self.actions` and each seat's `SeatBinding.name` — there's no account id in this
design to record instead; guest names are the permanent identity model.

## 7. Scaling path

**Stage 1 — one process (v1, this doc's scope).** In-memory tables, Postgres for durable records
(users, finished games, leaderboards). Handles hundreds of concurrent tables. **No mid-game
durability:** a table's live `GameState` exists only in that process's memory. If the process
dies, every table in it dies too — **games in progress are abandoned**, full stop. This is a
deliberate v1 answer; see the shutdown story in §8 for the one case (a planned deploy, not a
crash) where we do better than that.

Everything past Stage 1 is deferred intent, sketched here only so the single-writer-per-table
invariant (§3) isn't accidentally violated later: **Stage 2** would shard tables across N nodes,
each table pinned to exactly one node for its lifetime via a router holding nothing but a
table→node directory, the matchmaking queue, and lobby presence (`shard by table, never split a
table`). **Stage 3** would add durability — surviving a node loss without abandoning the table —
which needs *every* source of non-determinism logged as a first-class action, including bot
decisions (ε-random, [04-bots.md](04-bots.md)) and every timer expiry (tsumogiri-on-timeout,
auto-pass-on-timeout, bot-deadline defaults). No log format or write-granularity tradeoff has been
picked. Deferred — see [99-deferred.md](99-deferred.md).

## 8. Failure handling

| Event | Behaviour |
| --- | --- |
| Player disconnects | Seat marked `DISCONNECTED` (only on the WS connection actually closing — no heartbeat/dead-socket timeout exists). Table continues. Grace period (`ruleset.disconnect_grace_seconds`, default 20s) before the seat flips to `AUTOPLAY` and the bot takes over. Uses the same `TimerHeap` claim-window deadlines use. **Mid-claim-window:** if this seat holds a live, unresolved claim offer at the instant it disconnects, that offer is forfeited immediately (`Pass`, the same path a claim-window timeout uses) rather than left open — see below for why. **Pre-start** (table still filling seats, not yet dealt into play): the same `DISCONNECTED` + grace period applies (so a reload or blip while joining still reconnects normally), but if the grace period elapses with no reconnect, the seat frees back to empty instead of going `AUTOPLAY` — there's no hand for a bot to play pre-start, and an `AUTOPLAY` seat that never gets touched again would keep the lobby (`GET /tables`) listing the table as taken with nobody actually there. |
| Player reconnects | Rejoin table, send `last_seq`. Server replays from that seat's ring buffer or sends a fresh `state_sync` (§3). Bot relinquishes the seat. There is never a claim offer waiting to be handed back: a disconnect already forfeited any offer this seat held (row above), so a reconnect mid-claim-window is ordinary replay/`state_sync`, nothing claim-specific. **Superseded design:** an earlier version re-armed the seat's `TimerHeap` entry to a fresh full window on reconnect instead of forfeiting on disconnect. Dropped because it was never actually reachable through a full-`state_sync` reconnect (the common case once a page reload persists its own seat, docs/03-frontend.md) — `state_sync`'s `claim_options` carries no `window_id` (docs/02-protocol.md §3), so the client had nothing to render a dialog against or submit a `claim` with, even though the server was still nominally waiting on it: the seat would reconnect into a table that looked paused with no way to act on the thing pausing it. |
| Player never returns | Bot plays out the game. Result recorded against the human. |
| Turn timeout | `ruleset.turn_seconds` (default 15s), armed from every `AWAIT_ACTION` landing (`_arm_turn_timer`). **After a draw:** tsumogiri — discard the drawn tile. **After a claimed pung or chow:** no drawn tile to reflexively discard, so the fallback discards the concealed tile with the lowest `tile_id` (kong is unaffected — it always draws a replacement first). The drawn-vs-claimed distinction reads the real `Drawn`/`KongReplacementDrawn` events from that tick, not hand size. The synthesized discard is sourced from `legal_actions`, so it can never name an illegal tile. Strikes live on `SeatBinding.turn_timeout_strikes`, incremented on every timeout, never reset — three strikes flips the seat to `AUTOPLAY` for the rest of the game. |
| Bot raises / hangs | Runs in a worker pool with a hard deadline (§3), outside the table loop. A *claim* offer resolves via its own `TimerHeap` entry (default-to-`Pass`) regardless of whether the bot answers. A bot's *turn* gets the identical `turn_seconds` fallback a human timeout does — it races the wall clock, not the worker job, so a hung/crashed worker can't outlast `turn_seconds` regardless of the job's own 10s deadline. |
| Planned shutdown / deploy | See §8.1 — different from a crash; the process gets to say goodbye. |
| Node dies (deferred, stage 3) | Not a v1 behavior — see §7. Sketch: router reassigns; new owner replays the action log; clients reconnect and `state_sync`. |

### 8.1 Graceful shutdown

Nothing in v1 (§7) survives a crash — a killed process abandons every table in it. Acceptable for
a crash, which is rare and unplanned. Not acceptable for a routine deploy, which is frequent and
planned: `restart: unless-stopped` with a single in-memory process otherwise means every deploy
kills every live table, silently, mid-hand.

v1's answer is a drain, not durability — it buys the process time to reach a safe stopping point:

1. On `SIGTERM`, the process stops accepting new WebSocket connections and stops matchmaking new
   tables; the health check starts failing so a load balancer drains inbound traffic.
2. Every table still holding players gets a `server_shutdown{deadline_ts}` event so clients can
   show a "reconnect shortly" banner instead of reading a dropped socket as an error.
3. A table that is mid-hand is allowed to *finish that hand* — but no further — within a bounded
   grace window (`SHUTDOWN_GRACE_SECONDS` env var, default 90s). Reaching a hand boundary before
   the window elapses is a clean stop.
4. If the grace window elapses first, the table is torn down anyway and that hand is abandoned,
   same as a crash — but the players were warned.
5. The process exits once every table has reached a hand boundary or its grace window has expired,
   whichever comes first for that table — not a single global sleep.

`TableRegistry.begin_shutdown` implements steps 2–5: sets `.draining` (new connections get closed
with code 1013; `/healthz` serves `503`), broadcasts `server_shutdown` to every table with a seat
ever bound, then waits on each table's `Table.wait_for_shutdown_boundary` concurrently
(`asyncio.gather`, so total wall-clock cost is the grace window once, not per table). A table that
never reaches a boundary is logged as abandoned; the process exiting is what ends it. `app/main.py`'s
`lifespan` runs the drain after `yield`, where uvicorn's SIGTERM handling resumes; a
`TestClient(app)` context exit runs the identical drain, which is why `server/tests/conftest.py`
pins `SHUTDOWN_GRACE_SECONDS=0` for the test session. A table whose `GAME_OVER` persist is already
in flight is the drain's one unbounded wait — `process_one` catches a persist that raises, logs
the lost record, and still marks the attempt finished, so this wait can always be exited.

## 9. Anti-cheat

1. **Server-authoritative + per-seat redaction** (§5) closes information cheating, the dominant
   threat. If the client never receives a tile it shouldn't see, memory inspection is useless.
2. **Validate every intent against the server-computed legal-action set.** Never trust a
   client-declared meld, claim legality, faan count, or score.
3. **Rate-limit intents per session** and reject malformed envelopes hard.
4. **Provable fairness — commitment only, not proof of an unbiased deal.** Commit
   `SHA256(hand_seed || nonce)` at hand start, reveal `hand_seed, nonce` at hand end (§3, §5).
   This proves the server didn't change the wall *after* committing. It does **not** prove the
   wall was fair: the server alone picks `hand_seed` and `nonce`, and dealing is a pure function
   of `hand_seed`, so it already knows the resulting wall before committing to anything. Nothing
   stops a malicious server from grinding `(hand_seed, nonce)` pairs off-protocol until one deals
   a wall it likes, then publishing that commitment — the reveal still verifies. Closing the real
   gap needs client-contributed entropy so the server can no longer see the outcome before it's
   locked in. Deferred — see [99-deferred.md](99-deferred.md).
5. **Collusion** (two humans sharing a screen) is unsolvable technically. Mitigate socially:
   random matchmaking for rated play, statistical review of suspicious deal-in patterns.
6. **Claim-window timing leak (accepted, not mitigated) — see §4.** Early exit means both the
   window's duration and a fast-passer's view of whether it stays open afterward leak partial
   claim information to an attentive opponent. Deliberate trade of a small leak against a UX
   regression worse than the leak — don't "fix" it locally without re-reading §4.
