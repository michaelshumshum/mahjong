# Architecture

Server-authoritative, browser-native Hong Kong mahjong. One Python process owns every live table;
clients receive only what their seat may see.

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
  hand sets count, flower handling, payment split. The engine is config-driven
  ([rules.md §10](rules.md)).

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
                                │  HTTP (table list/create, /healthz)
    ────────────────────────────┼────────────────────────────────────
                                ▼
                     ┌──────────────────────────────────────────────┐
   Python process    │  FastAPI / Starlette (uvicorn + uvloop)      │
                     │                                              │
                     │  REST ──── GET/POST /tables, /healthz,       │
                     │            GET /lessons/random               │
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
                     │  TableRegistry ──► Table (one asyncio.Task)  │
                     │                    · owns GameState          │
                     │                    · inbox: asyncio.Queue    │
                     │                    · timer heap (§3)         │
                     │                    · per-seat seq + per-seat │
                     │                      ring buffers (redacted) │
                     │                    · builds frames with      │
                     │                      app/frames (pure, over  │
                     │                      seat_view() /           │
                     │                      redact_event(), §5)     │
                     │                         │                    │
                     │                         ▼                    │
                     │  mahjong_core  (PURE — stdlib only, no       │
                     │    asyncio, no I/O, no numpy)                │
                     │    reduce(state, action) -> (state', events) │
                     │                         ▲                    │
                     │  bots/ ─────────────────┘ (same seat_view,   │
                     │                       worker pool, §3)       │
                     │  app/lessons/ ──────────┘ (positions built   │
                     │                       and graded offline;    │
                     │                       the endless pool is    │
                     │                       served with its keys   │
                     │                       stored)                │
                     └──────────────────────────────────────────────┘
                                │
                           Postgres
                    finished games, hand records
```

### 2.1 Auth

Guest-only ([ADR 0001](decisions/0001-guest-only-identity.md)). There is no account, password,
email, JWT or REST auth endpoint. A player picks a display name client-side; it persists in
`localStorage` and travels as a plain field on `join` (`SeatBinding.name` holds it for the game).
`hello.seat` only ever reclaims an already-bound seat, so a reconnect never resends the name.

```
client ──ws://…/ws?table=…────────────────────────────────────────────► WS endpoint
client ──join{seat?, name?}────────────────────────────────────────────► Session binds this seat,
                                                                          ack carries a fresh
                                                                          reconnect_secret
client ──hello{seat, secret}──(a later reconnect, same seat)──────────► Session reclaims it iff
                                                                          secret matches
```

**Seat identity (which seat, whose name) is client-asserted; seat *possession* is not.**

| Step | Mechanism |
| --- | --- |
| Mint | `join` creates `SeatBinding.reconnect_secret` (`secrets.token_urlsafe(16)`) |
| Deliver | once, in that `join`'s own `ack` (`AckPayload.reconnect_secret`); `ack` is sender-only ([protocol.md §3](protocol.md)) |
| Store | client `localStorage` beside the seat number (`web/src/lib/ui/settings-storage.ts`'s `saveSecretForTable`/`loadSecretForTable`) |
| Check | `Table.reconnect` compares against the binding with `secrets.compare_digest`; any mismatch, including a missing secret, gets `error{code:'bad_secret'}` and the seat stays with its current holder |

The secret authenticates "the browser `join` handed this seat to," not a person. A player who
loses their `localStorage` (new device, cleared storage, private tab) loses the seat.

## 3. Core model

### Pure engine

```python
def reduce(state: GameState, action: Action) -> tuple[GameState, list[Event]]:
    ...
```

No `async`, clock, sockets, logging, or randomness except tile shuffling, which is fully
determined by `game_seed`. `game_seed` is fixed once at game start and **never leaves this
process** — not even redacted. Each hand derives its own subseed,

```
hand_seed = SHA256(game_seed || hand_no)
```

and shuffles that hand's wall from `hand_seed` alone. Only `hand_seed` is ever revealed, and only
at that hand's end (§5, §9). Same `game_seed` + same action sequence → byte-identical output,
forever, but no single reveal exposes a future hand's wall.

Consequences:

- 10k-game self-play soaks run in CI ([testing.md §1](testing.md)).
- A finished game replays as `(game_seed, actions)` through the same code path as live play.
- Any analysis that needs "what happens next" calls `reduce` on a copy — there is no second rules
  implementation.
- Crash recovery by replaying a live table's action log is **not** supported (§7).

**Two pure entry points.** `reduce()` takes exactly one `Action` and returns once a real decision
is needed from some seat, or the hand ends (`Phase.HAND_OVER`). Advancing from `HAND_OVER` to the
next deal (or `GAME_OVER`) is `engine.start_next_hand(state) -> (state, events)` — dealing isn't a
seat's decision, so there is no `Action` for it (`legal_actions` is `()` in that phase). The Table
loop calls it once the hand-end hold (below) closes.

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
items in a queue. The queue is bounded for client commands only: `Table.submit` drops one once 64
items are queued, while bot results, disconnects and wake-ups always enqueue
([protocol.md §11](protocol.md)). In-table messages never leave the owning task; table state is never
distributed (§7).

**Sequencing.** `seq` is per-seat (and per-spectator-session): dense and gapless *within that
stream*, never per-table. Two seats' `seq` counters have no relationship to each other. `event_id`
is a separate, internal, table-global counter for server-side logging only — never serialized to
a client. The ring buffer is per-seat and stores frames *after* `redact_event()` has run, never raw
`Event` objects, so a reconnect replay ([protocol.md §5](protocol.md)) can never hand a
redacted-out tile back to a seat.

**Spectating.** An explicit `?spectate=true` connect-time flag (`app/ws.py`). A passive "never sent
`join`" default would race the `hello{client_version}` every real client sends before `join`.
`join`/`reconnect` promote a spectating connection the moment it claims a seat. A spectator has no
`SeatBinding` and no reclaim: `unregister_spectator` drops its ring/seq entry when its connection
closes, and reconnecting is always a brand-new spectator session with a fresh `state_sync`. A
spectator gets `seat_view(state, None)`, every broadcast, and every `redact_event(state, None,
event)` output — except `claim_offer`, which would name the offered seat's own concealed tiles.

**Table settings.** `TableSettings` (`app/table_types.py`) holds per-table options that aren't game rules
(those are `RuleSet`). `spectators_see_hands` switches every spectator to the open-hands view (§5);
`Table.update_settings` swaps it mid-game and resyncs spectators. No wire message sets it.
It is allowed only on an `all_bots` table (`Table._check_settings`: construction and
`update_settings` raise `ValueError` otherwise), and `Table.join` refuses every human on an
`all_bots` table with `table_full`, even on a freed seat. On a table a human can sit at, live open
hands to spectators would be a collusion channel. The check keys on `all_bots`, not current
occupancy, so it holds for the table's whole life without re-checking on each join.

**Ruleset selection.** `RuleSet` is fixed at table construction — `mahjong_core` has no path to
change it mid-game.

`POST /tables` (`app/main.py`'s `create_table`) is the only way to create a table:
`{ruleset, rules?, practice?, bot_tiers?, private?}` → server-generated table id + resolved ruleset
via `mahjong_core.presets.resolve_ruleset` ([protocol.md §10](protocol.md)). `/ws` only attaches
to an existing table (§8.3). `state_sync.ruleset`/`ruleset_preset` surface the resolved value to
late joiners, reconnects and spectators.

**Showcase table.** `TableRegistry.start_showcase` (`app/registry.py`, started from `lifespan` for
`SHOWCASE_TABLE_ID`, default `BOTS`, empty disables) keeps one all-bot, open-hands table running.
Each game draws every seat's tier uniformly from the practice-mode ladder (`bot_tiers`; `main.py`'s
`_available_bot_tiers`, which drops Expert/Impossible while the learned weights fail the startup
check), seeded off that game's seed. `Table(all_bots=True)` binds all four seats and deals when `run()` starts; its hand-end hold runs
the full `hand_end_seconds` (no human to ack; it's the spectators' time to read the result). After
`GAME_OVER` the finished table stays up for 30s, then a fresh game replaces it under the same id
and the old table's spectator sockets are closed so their reconnect lands on the new one. Not
persisted, not waited on by the shutdown drain (§8.1).

**Timer race.** `asyncio.wait_for(inbox.get(), timeout)` is wrong here: when the timer wins, the
cancelled `get()` can silently drop an item that arrived in the same scheduler tick. `_next()`
holds one long-lived `_inbox_getter()` task for the table's lifetime and only ever awaits
`asyncio.wait({getter, sleep_until_next_deadline})`, never cancelling `getter`. A table has several
deadlines live at once — the current claim window, each human's per-turn clock, each pending bot's
budget — so `self.deadlines` is a heap keyed by `(deadline_ts, id)`, not a scalar.

**Bots off the loop.** `_poke_bots()` never runs bot logic inline. It submits
`(table_id, window_id, state_version, seat_view)` to a `ProcessPoolExecutor` — the GIL makes a
thread pool useless for CPU-bound pure-Python work — with a hard deadline (`bots/worker.py`'s
`compute_action`, 10s, `_BOT_JOB_TIMEOUT_SECONDS`), and returns immediately. The worker builds the
requested tier ([bots.md §2](bots.md)) and drives `Bot.act(view, mask, deadline)`, returning a bare
action id — a worker never receives `GameState`; `Table._handle_bot_result` decodes the id against
the real state. The result re-enters through `inbox`, tagged with the `(window_id, state_version)`
it was computed against, and is dropped if either has moved on — the same staleness protection a
laggy human click gets (§4). On a worker crash or timeout, `Table` synthesizes nothing; it clears
the pending job tag so the next tick retries. The per-seat `ruleset.turn_seconds` timer (§8) is
what bounds a stalled turn.

### Hand-end hold

A hand ending — win or exhaustive draw — holds the table at `Phase.HAND_OVER` instead of chaining
straight into `start_next_hand()`, so clients can show the finished hand before the board resets:

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
facts; ack tracking and the timer are `app/table.py`-only (`_open_hand_end_window`,
`mark_hand_end_ack`, one `TimerHeap` entry per hold). A stray or late ack is a no-op.

### Outbound backpressure

Session pumps a **bounded** outbound queue per connection (`app/outbox.py`'s `BoundedOutbox`,
default 64 frames). An unbounded queue behind a stalled TCP socket is a memory leak that grows
until the process OOMs.

Overflow policy: drop the oldest non-`ack`/`error` frame first, and the instant anything is
dropped, clear every remaining non-critical frame and publish a fresh `state_sync` in its place
(a real `seq`, allocated normally). Because `seq` is per-seat and gapless, a drop is self-healing:
the client's next `last_seq` is behind, and the resume protocol ([protocol.md §5](protocol.md))
requests exactly the `state_sync` this policy already forces. If the queue is still over capacity
after collapsing to `state_sync` (everything queued was `ack`/`error`), the connection is dead,
not slow, and `Session` closes it.

`Table.publish_to_seat` only does a synchronous, non-blocking `push()` — it never awaits the
socket. A separate `Session.writer()` task owns `websocket.send_text()`, so a stalled TCP
connection blocks only that task, never the Table task.

## 4. Claim window

After a discard, up to three players may claim it. They race, and **first-to-arrive must not
win** — a chow claim landing in 80ms loses to a win claim landing in 3s.

Priority, tiebreaks and the kong-vs-pung edge case are canonical in
[rules.md §6](rules.md); this section covers only the window mechanics. If the two disagree,
rules.md §6 wins.

```
Win (食糊)  >  Kong (槓) / Pung (碰)  >  Chow (上)
```

- Chow is only legal for `claimer_seat == (discarder_seat + 1) % 4` ([rules.md §2](rules.md)).
- Single-winner: a Win-vs-Win tie resolves by seat order and the algorithm emits exactly one
  `CLAIM_RESOLVED`. `RuleSet.multi_win` exists but does nothing
  ([ADR 0007](decisions/0007-multi-win-and-pao.md)).

```
on DISCARD(seat, tile):
  legal = {s: legal_claims(state, s, tile) for s in others if legal_claims(...) non-empty}
  if legal is empty:            -> advance to next player's draw immediately (engine);
                                   Table still holds it back (claim hold, below)
  window_id = next_window_id()
  for s in legal:  send CLAIM_OFFER(window_id, options, deadline_ts)
  open window:
    collect CLAIM(window_id, choice) from legal seats only, one per seat
    close when  (all legal seats responded)  OR  (deadline reached -> absentees = PASS)
    EARLY EXIT: close as soon as the best outstanding possible claim cannot beat
                the best claim already received.
  resolve by priority -> emit exactly one CLAIM_RESOLVED event
                         (Table: a no-claim one only to the seats offered, below)
```

`claims.can_close_early`/`resolve_claims` are pure and reason only over responses already
collected — early exit is invoked from `mahjong_core.engine._apply_claim_response` the moment a
real response makes the window ready. `Table` owns what the pure engine can't: arming
`deadline_ts` (`TimerHeap`, keyed `(deadline_ts, window_id)`) when a window opens, and — on timer
expiry, staleness-checked against the live `window_id` — synthesizing `Pass` for every seat that
never responded, through the same `reduce()`/`resolve_claims` path. Window duration is
`RuleSet.claim_seconds` (default 5s).

Rules:

- **Only offer claims to players who actually have one.** Broadcasting "someone may claim" leaks
  information and trusts the client.
- **`window_id` on every claim.** Claims tagged with a stale window are dropped silently; without
  it a laggy click from the previous discard fires on the current one.
- **One response per seat per window.** Once a seat's answer is in `ClaimWindow.responses`,
  `legal_actions` returns `()` for it, so a second answer (Pass then Pung) fails authorization
  and is dropped. Otherwise a seat could pass, watch the window stay open, and change its mind.
- **Early exit is a UX requirement, kept deliberately.** If the only eligible chow passes, the game
  must continue instantly; waiting out a 5s timer every discard feels dead.
- **Claim hold.** Without it, a seat with no offer could tell whether a window existed: no window
  meant `discard` → `draw` in the same tick, a window meant a pause (a human's decision, or the
  bot think delay, [bots.md §1](bots.md)) and a `claim_resolved{seat:null}`. Since chow offers go
  only to the next seat, that pointed at that player's tiles. A kong-rob window leaked the same
  way and worse: a `claim_resolved{claim_kind:"kong_rob"}` after an added kong said some opponent
  waits on exactly that tile, even if they passed. So, in `app/table.py` (the engine and its
  trajectories are untouched), for both window kinds:

  | Part | Rule |
  | --- | --- |
  | No-claim resolution | `ClaimResolved` with no winner goes only to the seats the window offered (`_publish_claim_resolved`); it is never broadcast or sent to spectators |
  | Uniform pause | every `Discarded`, and every self-declared kong's `MeldFormed` when the ruleset lets it be robbed (`_kong_may_be_robbed`: added kong under `kong_rob_enabled`, concealed kong only with `concealed_kong_robbable` too), starts a hold (`_begin_hold`): for `claim_hold_seconds` every outbound frame queues per recipient, except `ack`/`error`/`server_shutdown`/`claim_offer` and an offered seat's `claim_resolved`, whether or not a window opened. Release (`_release_hold`, one `TimerHeap` entry) flushes the queues in order |
  | Next turn | held too: `_authorize` drops commands in `AWAIT_ACTION`, `_poke_bots` submits no turn job, and `turn` (with its `turn_seconds` timer) is published only on the release tick |
  | `state_sync` mid-hold | rebuilt at release, so a reconnect or new spectator can't probe the held state |
  | Duration | `CLAIM_HOLD_SECONDS`, default 1s. `0` turns it off: the showcase (open hands, nothing to hide) and the test suite (`tests/conftest.py`) |

  **Residual leak, accepted:** a window still open when the hold ends shows. That covers a human
  thinking longer than the hold, and a bot whose think delay (0.4–1.4s, [bots.md §1](bots.md))
  lands past 1s: the hold sits below `BOT_THINK_MAX_SECONDS` on purpose, trading those slow bot
  windows for a shorter pause after every discard. After passing immediately, a window staying
  open also shows — another seat still holds a live claim. Padding every discard to `claim_seconds` would hide it, at 5s a discard.
  A claim that wins is public anyway.
- **Pre-declared intent.** Clients pre-arm "auto-pass on chow" / "no calls" toggles; the server
  treats a pre-arm as an instant PASS. A win offer is never auto-resolved by a pre-arm
  ([protocol.md §2](protocol.md) "Declining a claim on purpose").
- **Robbing the kong (搶槓)** opens a claim window on a *kong declaration*, not a discard. Same
  machinery, different trigger, same claim hold.

## 5. Redaction

The table never serializes `GameState`. Redaction is **two named functions** answering different
questions:

```python
def seat_view(state: GameState, seat: int | None) -> SeatView:
    """Full redacted snapshot for one recipient. seat=None -> spectator view.
    Used by anything that needs 'the whole table as seat X may see it right now'
    rather than one wire event: bots (§3), state_sync, ML encoders (ml.md)."""

def redact_event(state: GameState, seat: int | None, event: Event) -> dict:
    """Per-event wire redaction: the JSON actually sent for one logical Event,
    to one recipient. Concealed tiles become counts, never identities."""
```

### Frame building

`app/frames.py` turns those two into the payload of every frame a recipient gets, as pure
functions of `(state, recipient, event…)`: `turn_frame` (with `legal` for the acting seat only),
`claim_offer_frame`/`claim_options_wire`, `hand_start_frame`, `deal_frame`, `event_frame`
(`redact_event` plus `discard.tile`/`pool_index` and `hand_end`'s deadline and fairness),
`score_frame`, `state_sync_frame` (its `claim_offer` built by `claim_offer_frame`'s payload
builder), and `to_envelope` for the `{v, t, seq, ts, d}` wrapper.

| Owned by the caller, passed in | Never inside a builder |
| --- | --- |
| deadlines `Table` armed, seat statuses and names, `host_seat`, hand history, bot tiers, the fairness commit/reveal | clocks, sockets, `seq`, timers, the claim hold |

`Table` adds those around the builders; its frames are byte-identical to what it built inline
before the split (`tests/test_frames.py` pins every recipient's stream for seeded games and
rebuilds every frame from its state). A caller with no `Table` builds the same bytes: learn
mode's lesson bundle ([ADR 0025](decisions/0025-learn-mode.md)) and, later, a replay
re-redaction ([ADR 0011](decisions/0011-replay-viewer.md)). It is a separate module from
`views.py` because `views.py` answers what a recipient may see, with its `Entitlement`-annotated
types the redaction walker checks; `frames.py` only assembles wire shapes from that answer.

### `SeatView`

**Canonical definition** — `server/app/views.py`. Depended on by [bots.md](bots.md) (`act()` input)
and [ml.md](ml.md) (encoder input); neither may change its shape unilaterally. Lives in `app/`,
not `mahjong_core/`: "what may this recipient see" is a wire-recipient concern, not a rule.

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
    wall_remaining: int                            # count only
    seat_status: tuple[str, ...]                   # connected | disconnected | autoplay | bot | empty, per seat
    names: tuple[str | None, ...]                  # chosen guest display name, per seat — None if unjoined
    scores: tuple[int, int, int, int]
    legal_actions: tuple[Action, ...]              # non-empty whenever actions.legal_actions(state, seat) is
    claim_options: tuple[ClaimOffer, ...]          # this seat's own live claim offer (§4), if any
    deadline_ts: int | None                        # the deadline relevant to this seat, if any
    host_seat: int | None                          # first seat to join; None with no Table behind the caller
    ruleset: RuleSet                               # public; bots read thresholds off it (bots.md §8)
    hands: tuple[tuple[int, ...], ...] | None      # every seat's concealed tiles; see below
    drawn_tile: int | None                         # the tile held apart on this seat's own turn
    last_discard: tuple[int, int] | None           # (seat, tile_id) of the latest unclaimed discard
```

| Field | Notes |
| --- | --- |
| `legal_actions` / `claim_options` | reuse `mahjong_core.actions.Action` / `mahjong_core.state.ClaimOffer` directly — both carry only this seat's own or already-public tiles, so a parallel wire type adds translation with no redaction benefit. Non-empty on the seat's own `AWAIT_ACTION` turn *or* while it holds a live claim/kong-rob offer |
| `seat_status` | from `SeatBinding.status`; `bot` seats are bound at construction (practice mode, showcase) and driven through the same `_poke_bots`/`BotJobTag` path as `autoplay` seats |
| `names` | `SeatBinding.name`, set once at `join` (`_normalize_name`); bot seats draw a display name at bind time |
| `deadline_ts` | `ClaimWindow.deadline_ts` for a claim offer, or the per-turn deadline when `seat == state.turn` and `phase == AWAIT_ACTION` |
| `hands` | `None` for every real seat. `seat_view(..., reveal_hands=True)` fills it for a spectator only and raises (`_check_reveal`) for a real seat |
| `drawn_tile` / `last_discard` | `mahjong_core.engine.drawn_tile` / `newest_discard`, pure reads of `GameState` (a draw lands last in `concealed`; `self_draw_win_allowed` is false only on a claimed turn; a front draw only follows the previous seat's unclaimed discard). `drawn_tile` is `OWN_SEAT`: set only when `seat == state.turn`, never for a spectator, open-hands included. `last_discard` is public. Both default to `None`, so code building a `SeatView` by hand is unaffected |
| `claim_options` on the wire | not sent as is: `state_sync_frame` turns the seat's unanswered offer into `state_sync.claim_offer` with `claim_offer_frame`'s own payload builder, so the two can't drift ([protocol.md §3](protocol.md)) |

**The one contained exception to "a real seat never gets another seat's tiles":**
`_omniscient_seat_view` (`app/views.py`) deliberately bypasses `_check_reveal` to build a real
seat's view with `.hands` populated. It is a separate, dangerously-named function with exactly two
callers — `app/table.py`'s `_submit_bot_job`, for the `ORACLE` bot tier
([bots.md §9](bots.md)), and the offline arena's `bots/arena.py` `_view_for`, which `app/` never
imports. It is safe because:

- a `SeatView` never carries `game_seed`/`hand_seed` (§3's invariant is about the seed, not tile
  visibility), so it may cross the `ProcessPoolExecutor` boundary;
- it never reaches a client — disconnect-handover always runs `T2`, so a human's seat is never
  driven by it;
- `tests/test_oracle_containment.py` AST-scans production code for any other call site and for
  any `app/` import of `bots.arena`, and
  `tests/test_redaction.py` pins that `Table.state_sync_wire` never populates `.hands` for a real
  seat, for every `bot_tier`.

### Redaction test

Invariants are enforced by a **schema walker**, not a substring scan of serialized bytes. Scanning
JSON text for tile-shaped integers is a false-positive machine — `"tile_id": 5` and
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
`OWN_SEAT`, `COUNT_ONLY` or `HAND_END` whose predicate is false for that (seat, state) pair is
either absent or holds a count/placeholder — never a real tile id.

Invariants this enforces:

- Another player's concealed hand → `{"count": 13}`. Never a tile list.
- The wall → `{"remaining": 42}`. Never contents, never `game_seed`. Only that hand's `hand_seed`
  is revealed, and only at that hand's end (§3, §9).
- Flowers, melds (concealed kongs included, [ADR 0023](decisions/0023-concealed-kong-public.md)),
  discard pool, scores: fully public.
- A spectator sees the union of what all four players show publicly, **not** their private hands —
  unless the table sets `spectators_see_hands` (§3). Then `seat_view(state, None,
  reveal_hands=True)` adds `hands`, and `redact_event(..., reveal_hands=True)` hands the spectator
  every `OWN_SEAT` field (draw/kong-replace tile ids). The walker checks this
  under its own `OPEN_HANDS` entitlement. There is no delay: open-hands tables are for watching
  bots, where a spectator relaying hands to a player isn't a concern.

**Bots consume the identical `seat_view` output a human's client renders from** — proof they can't
cheat, and any bot can run as a client against a real server for integration testing.

## 6. Stack

| Layer | Choice | Notes |
| --- | --- | --- |
| Backend | FastAPI + native WebSockets on uvicorn/uvloop | pydantic models double as the protocol schema, codegen'd into TypeScript ([protocol.md §6](protocol.md)) |
| Serialization | JSON | ~2KB for a full snapshot, ~150 bytes for a typical event |
| Frontend | SvelteKit 2 on Svelte 5 (runes), DOM/CSS, no canvas | the table surface is DOM like everything else ([ADR 0002](decisions/0002-dom-rendering.md), [frontend.md](frontend.md)) |
| Storage | Postgres | finished games and hand records only ([infra.md §6](infra.md)) |

### Storage

**Postgres** holds finished games as `(ruleset, game_seed, action_log)` with `action_log` as JSONB.
Session and table state are **in-process structures in the API process** — no
`KV`/`Queue`/`Bus` abstraction. (Matchmaking doesn't exist; the one rate limit, on `POST /tables`,
is an in-process dict too, §8.3.) A Protocol-per-backend split earns its keep only
once a second backend exists; with one (in-process memory) it would invite `async def` on a plain
dict lookup, violating `server/AGENTS.md`'s "`async def` only where there is real I/O" rule
([ADR 0006](decisions/0006-multi-node-and-durability.md)).

`TableRegistry` (`server/app/registry.py`) is an in-process `dict[str, Table]` plus the bookkeeping
to run each table's `asyncio.Task`. `Table.run()` returns on `GAME_OVER` and `TableRegistry` drops
its task entry; the `Table` object itself stays for `FINISHED_TABLE_TTL_SECONDS`, so reconnecting
after the game ends still works (`Table.reconnect`/`resume`), then is reaped (§8.3). An abandoned
table is evicted at once and its id tombstoned (§8.2).

`Table` records a real game's full action log (`self.actions`, every `Action` that ran through
`reduce()` — never a `start_next_hand()` transition, which replay reconstructs off
`Phase.HAND_OVER`) via an optional `session_factory: async_sessionmaker[AsyncSession] | None`
threaded through `Table.__init__`/`TableRegistry`. `app/main.py`'s `lifespan` builds the engine from
`DATABASE_URL` (unset → no persistence). On `Phase.GAME_OVER`, `Table` calls `save_game_record` at
most once with `self.actions` and each seat's `SeatBinding.name` — guest names are the permanent
identity model.

## 7. Scaling

**One process.** In-memory tables, Postgres for durable records. Sized for hundreds of concurrent
tables ([ADR 0003](decisions/0003-product-scope.md)). **No mid-game durability:** a table's live
`GameState` exists only in that process's memory. If the process dies, every table in it is
abandoned. The one case handled better is a planned deploy (§8.1).

Any future multi-node design must keep the single-writer-per-table invariant (§3): shard by table,
never split a table. The deferred design space — sticky routing, action-log durability, and the
non-determinism (bot decisions, timer expiries) that exact replay would need to log — is in
[ADR 0006](decisions/0006-multi-node-and-durability.md).

## 8. Failure handling

| Event | Behaviour |
| --- | --- |
| Player disconnects | Seat marked `DISCONNECTED` when the WS connection closes (no heartbeat — [protocol.md §8](protocol.md)). Table continues. After `ruleset.disconnect_grace_seconds` (default 20s) the seat flips to `AUTOPLAY` and a bot takes over, via the same `TimerHeap` claim windows use. **Mid-claim-window:** a live claim offer held by this seat stays open on its own deadline; it times out to `Pass` like any silent seat's, or the `AUTOPLAY` bot answers it if grace expires first ([ADR 0004](decisions/0004-claim-forfeit-on-disconnect.md)). **Pre-start** (table still filling): same `DISCONNECTED` + grace, but on expiry the seat frees back to empty instead of `AUTOPLAY` — there's no hand for a bot to play, and an untouched `AUTOPLAY` seat would keep `GET /tables` listing the table as taken. |
| Player reconnects | `hello{last_seq, seat, secret}`. Server replays from that seat's ring buffer or sends a fresh `state_sync` (§3). Bot relinquishes the seat. A live claim offer comes back answerable, its deadline re-armed to a fresh `claim_seconds` once per window ([protocol.md §5](protocol.md)). |
| Player never returns | Bot plays out the game while at least one other human seat is `connected`. Result recorded against the human. |
| Every human gone | Started table, every human-bound seat `disconnected`/`autoplay`: ended after `ABANDONED_TABLE_GRACE_SECONDS` (default 120s), not persisted (§8.2). |
| Turn timeout | `ruleset.turn_seconds` (default 15s), armed on every `AWAIT_ACTION` (`_arm_turn_timer`). **After a draw:** tsumogiri. **After a claimed pung or chow:** discard the concealed tile with the lowest `tile_id` (kong always draws a replacement first). The drawn-vs-claimed distinction reads that tick's real `Drawn`/`KongReplacementDrawn` events, not hand size. The synthesized discard comes from `legal_actions`, so it is always legal. `SeatBinding.turn_timeout_strikes` counts timeouts, never resets; at `ruleset.turn_timeout_strikes` (3) the seat flips to `AUTOPLAY` for the rest of the game. |
| Bot raises / hangs | Runs in a worker pool with a hard deadline (§3). A *claim* offer resolves via its own `TimerHeap` entry (default `Pass`) whether or not the bot answers. A bot's *turn* gets the same `turn_seconds` fallback a human does — it races the wall clock, not the worker job. |
| Planned shutdown / deploy | §8.1. |
| Process dies | Every table in it is abandoned (§7). |

### 8.1 Graceful shutdown

A crash abandons every table. A routine deploy must not, so the process drains instead:

1. On `SIGTERM`, stop accepting new WebSocket connections and new tables; `/healthz` starts
   failing so a load balancer drains inbound traffic.
2. Every table still holding players gets `server_shutdown{deadline_ts}` so clients show
   "reconnect shortly" instead of reading a dropped socket as an error.
3. A table mid-hand may *finish that hand* — no further — within `SHUTDOWN_GRACE_SECONDS`
   (default 90s). Reaching a hand boundary is a clean stop.
4. If the grace window elapses first, the table is torn down and that hand is abandoned — but the
   players were warned.
5. The process exits once every table has reached a boundary or its grace window, per table — not
   one global sleep.

`TableRegistry.begin_shutdown` implements steps 2–5: sets `.draining` (new connections close with
code 1013; `/healthz` serves `503`), broadcasts `server_shutdown` to every table with a seat ever
bound, then awaits every `Table.wait_for_shutdown_boundary` concurrently (`asyncio.gather`, so the
total cost is one grace window). A table that never reaches a boundary is logged as abandoned.
`app/main.py`'s `lifespan` runs the drain after `yield`, where uvicorn's SIGTERM handling resumes;
a `TestClient(app)` exit runs the identical drain, which is why `server/tests/conftest.py` pins
`SHUTDOWN_GRACE_SECONDS=0`. A table whose `GAME_OVER` persist is in flight is the drain's one
unbounded wait — `process_one` catches a persist that raises, logs the lost record, and still marks
the attempt finished, so the wait always exits.

Compose's default `stop_grace_period` (10s) is shorter than the drain; see
[infra.md §3](infra.md).

### 8.2 Abandoned tables

A table nobody is watching still costs a bot job per decision for the rest of the game, and
creating tables is free (throttled only per IP, §8.3), so a table with no human left is ended
rather than played out ([ADR 0024](decisions/0024-end-abandoned-tables.md)).

| Condition | Rule |
| --- | --- |
| Abandoned | `Table.started`, at least one human-bound seat, none `connected` (`_is_abandoned`). `bot` seats and spectators never count — a spectator keeping a table alive would be trivially exploitable. Pre-start tables keep the §8 seat-freeing path |
| Grace | `ABANDONED_TABLE_GRACE_SECONDS` (default 120s, `app/main.py`'s `lifespan` → `TableRegistry` → `Table.abandon_grace_seconds`). Must stay well above `disconnect_grace_seconds` (20s): a refresh or network blip never ends a game |
| Arm / disarm | one `TimerHeap` entry (`_abandon_timer_id`), armed at the tail of the `process_one()` tick that first sees the table abandoned, so it runs on the table's own loop like every other timer (§3 "Timer race"). `reconnect()` disarms it directly; expiry re-checks `_is_abandoned()` anyway, since a reclaim lands off-loop |
| Exempt | the showcase table: all-bot, no human-bound seat, and `start_showcase` passes no grace |

On expiry (`_handle_abandon_timeout`), all inside the table's own task:

1. `Table.end` sets `Table.closed`; `_poke_bots` and `_handle_bot_result` refuse from then on,
   `_pending_bot` is cleared and every in-flight `_await_bot_job` task cancelled, so a late worker
   answer is dropped harmlessly.
2. `error{code:"table_closed"}` goes to every seat stream and spectator; spectator sockets are
   closed. The long-lived inbox getter is cancelled — nothing will read the inbox again.
3. One `WARNING` log line: table id, `hand_no`, reason.
4. `run()` returns. The game never reached `GAME_OVER`, so nothing is persisted — same as a
   crash-abandoned table.
5. `TableRegistry._run` evicts the `Table` from `_tables` and keeps the id in `_closed`, so
   `POST /tables` never mints it again. A late `/ws?table=<id>` finds no table and gets
   `error{code:"table_closed"}`, then the socket closes, the same as any unknown id (§8.3). A
   connection that grabbed the `Table` in the instant before it ended gets the same error from
   `Session.handle`. The tombstone is a bare string per evicted table, capped (§8.3).

### 8.3 Table creation and retention limits

Every table costs memory (~20 KB idle; ring buffers and history take a live one to a few hundred
KB) and a task, on a 1.9 GiB box. Creation is anonymous, so each way of creating or keeping one
is bounded:

| Limit | Rule | Default (env, [infra.md §2](infra.md)) |
| --- | --- | --- |
| Only `POST /tables` creates | `ws_endpoint` looks the id up (`TableRegistry.get`); an unknown, abandoned or reaped id gets `error{code:"table_closed"}` (`TABLE_GONE_ERROR`) and the socket closes. A wrong join code or a stale link never makes a table | — |
| Unstarted TTL | a table that never started, is `UNSTARTED_TABLE_TTL_SECONDS` old, and has no seat `connected` (spectators don't count, as in §8.2) is reaped: `Table.end(TABLE_GONE_ERROR)`, its task cancelled, evicted. A waiting room someone is sitting in is kept; once they leave (pre-start seats free after the 20s disconnect grace, §8) it goes at the next sweep | 600s |
| Finished TTL | `FINISHED_TABLE_TTL_SECONDS` after `run()` returns at `GAME_OVER`, the table is evicted, sockets still on it told `table_closed` | 600s |
| Sweep | `TableRegistry.reap`, every `REAP_INTERVAL_SECONDS` (30s) from `start_reaper` (`lifespan`); cancelled by the shutdown drain. The showcase is exempt. `clock` is injectable, which is how the TTL tests drive it | — |
| Tombstones | `_closed` keeps the last `DEFAULT_CLOSED_IDS_CAP` (10,000) evicted ids, oldest dropped first. Only id reuse depends on it, and a fresh id colliding with a forgotten one is a 1 in 32⁶ draw | — |
| Global cap | `get_or_create` raises `TableLimitError` once `MAX_TABLES` non-showcase tables are in the registry (finished ones awaiting reaping included); `POST /tables` answers `503` with `Retry-After`. `0` disables. This also bounds `GET /tables`, which walks every table | 500 |
| Per-IP rate | `POST /tables` allows `TABLE_CREATE_RATE_LIMIT` creations per `TABLE_CREATE_RATE_WINDOW_SECONDS` per client IP (`app/rate_limit.py`'s sliding-window `RateLimiter`, in-process, no dependency); past it `429` with `Retry-After`. Idle IPs are pruned once 4,096 are tracked. `0` disables | 10 per 60s |

**Client IP.** `client_ip` trusts `CF-Connecting-IP` (Cloudflare Tunnel's client address) only when
the TCP peer is in `TRUSTED_PROXY_IPS`; from any other peer the header is client-controlled and
ignored. Under the prod overlay's `--proxy-headers`, uvicorn has already replaced a trusted peer
with the forwarded client address, which is untrusted, so that address is the key and the header
is ignored. Without it, the peer is the proxy and the header is used. Either way a direct client
can't pick its own key.

## 9. Anti-cheat

1. **Server-authoritative + per-seat redaction** (§5) closes information cheating, the dominant
   threat. If the client never receives a tile it shouldn't see, memory inspection is useless.
2. **Validate every intent against the server-computed legal-action set.** Never trust a
   client-declared meld, claim legality, faan count, or score.
3. **Reject malformed envelopes hard.** Per-session intent rate limiting is not implemented.
4. **Provable fairness is commitment only, not proof of an unbiased deal.** Commit
   `SHA256(hand_seed || nonce)` at hand start, reveal `hand_seed, nonce` at hand end (§3, §5,
   [protocol.md §3](protocol.md) "Fairness"). This proves the server didn't change the wall *after*
   committing. It does **not** prove the wall was fair: the server alone picks `hand_seed` and
   `nonce`, so it could grind pairs off-protocol until one deals a wall it likes, and the reveal
   still verifies. Closing that needs client-contributed entropy
   ([ADR 0005](decisions/0005-client-entropy-fairness.md)).
5. **Collusion** (two humans sharing a screen) is unsolvable technically. Mitigate socially: random
   seating for rated play, statistical review of suspicious deal-in patterns.
6. **Claim-window timing leak — masked up to the claim hold, the rest accepted (§4).** Don't
   change either without re-reading §4.
