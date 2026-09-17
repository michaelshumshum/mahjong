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
                                │  HTTPS (auth, lobby, history)
    ────────────────────────────┼────────────────────────────────────
                                ▼
                     ┌──────────────────────────────────────────────┐
   Python process    │  FastAPI / Starlette (uvicorn + uvloop)      │
                     │                                              │
                     │  REST router ──── auth (guest + ticket, §2.1)│
                     │                   profile, room list,        │
                     │                   replays, leaderboard       │
                     │                                              │
                     │  WS endpoint ──► Session (thin)              │
                     │                    · redeem WS ticket once   │
                     │                    · parse + validate envelope│
                     │                    · push Command to room    │
                     │                    · pump BOUNDED outbound   │
                     │                      queue (drop→state_sync) │
                     │                         │                    │
                     │                         ▼                    │
                     │  RoomRegistry ──► Room (one asyncio.Task)    │
                     │                    · owns GameState          │
                     │                    · inbox: asyncio.Queue    │
                     │                    · timer heap (§3, D17)    │
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
                     │                       worker pool, §3 D12)   │
                     └──────────────────────────────────────────────┘
                                │
                           Postgres
                       users, finished games,
                       action logs (replays)
```

### 2.1 Auth

Guest-first: a player joins and plays with no account. An account is an optional upgrade
(profile, persistent stats, ranked play) layered onto the same seat, not a separate code path.

The WS URL never carries a long-lived credential. REST issues a **short-lived, single-use WS
ticket**; the client exchanges that, not its JWT, for the socket:

```
client ──POST /api/rooms/{id}/ticket (cookie or JWT)──► REST ──► {ticket, expires_in}
client ──ws://…/ws?ticket=…──────────────────────────► WS endpoint ──► Session redeems it once
```

A JWT never goes in a query string — query strings land in access logs, proxies, and browser
history. The ticket is redeemable exactly once; a leaked ticket copied out of a log line is
worthless after the first handshake, and it expires fast enough (seconds) that a leaked-but-unused
one is worthless too.

## 3. Core model

### Pure engine

```python
def reduce(state: GameState, action: Action) -> tuple[GameState, list[Event]]:
    ...
```

No `async`, clock, sockets, logging, or randomness except tile shuffling, which is fully
determined by `game_seed`. `game_seed` is fixed once at game start and **never leaves this
process** — not even redacted, not ever, during play (D2). Each hand derives its own subseed,

```
hand_seed = SHA256(game_seed || hand_no)
```

and shuffles that hand's wall from `hand_seed` alone. Only `hand_seed` is ever revealed, and
only at that hand's end (§5, §9.4). Same `game_seed` + same action sequence → byte-identical
output, forever — determinism is unaffected — but no single reveal ever exposes a future hand's
wall. (Revealing `game_seed` itself after hand 1 would hand every later wall in the game to
every player; that combination was the bug this replaces.)

This gives 100k-game test runs in CI, replays as `(game_seed, actions)` through the same code
path as live play, and search bots that call `reduce` on a determinized copy rather than needing
a second rules implementation. Crash recovery by replaying a room's action log is **not** a v1
property — see §7.

**Two pure entry points, not one.** `reduce()` takes exactly one `Action` and returns once a
real decision is needed from some seat, or the hand ends (`Phase.HAND_OVER`). Advancing from
`HAND_OVER` to the next deal (or to `GAME_OVER`) is a second function,
`engine.start_next_hand(state) -> (state, events)` — there is no `Action` for "deal the next
hand" since it isn't a seat's decision (`legal_actions` is `()` for `HAND_OVER`/`GAME_OVER`), so
it can't fit `reduce`'s `(state, action)` shape. The Room loop above calls it right after a
`reduce()` call lands on `HAND_OVER`, in the same tick, before arming timers or publishing —
same pattern as `state.new_game()` starting hand 1.

### Room actor

Each table is a single `asyncio.Task` owning its `GameState` exclusively. All mutation happens
inside that task's loop, fed by an `asyncio.Queue` of commands:

```python
class Room:
    def __init__(self, room_id: str, ruleset: RuleSet, game_seed: int):
        self.inbox: asyncio.Queue[Command] = asyncio.Queue()
        self.state = new_game(ruleset, game_seed)
        self.event_id = 0                     # internal monotonic id: logging/replay only, NEVER on the wire
        self.seat_seq: list[int] = [0, 0, 0, 0]        # per-seat outbound seq: dense, gapless, per stream (D1)
        self.spectator_seq: dict[str, int] = {}        # per spectator-session, same discipline
        self.ring: dict[int | str, deque[Envelope]] = {  # per-seat/spectator, holds ALREADY-REDACTED frames
            seat: deque(maxlen=512) for seat in range(4)
        }
        self.seats: list[SeatBinding | None] = [None] * 4   # human session or bot
        self.deadlines = TimerHeap()          # claim window + per-seat clocks + bot budgets (D17)

    async def run(self):
        getter = asyncio.create_task(self._inbox_getter())    # long-lived; NEVER cancelled (D17)
        while True:
            cmd = await self._next(getter)     # races getter against self.deadlines.peek(); never cancels getter
            action = self._authorize(cmd)      # None if illegal for cmd.seat right now -- drop it
            if action is not None:
                self.state, events = reduce(self.state, action)
                self.event_id += 1
                self._publish(events)          # redact_event() per recipient; stamps that stream's own seq (§5)
                if self.state.phase == Phase.HAND_OVER:  # server-computed, no seat decision (§3 above)
                    self.state, events = start_next_hand(self.state)
                    self.event_id += 1
                    self._publish(events)
            self._arm_timers()
            self._poke_bots()                  # submits to a worker pool; never runs bot logic in this loop (D12)
```

No locks. No `await` between read and write of shared state. Four simultaneous clicks are four
items in a queue.

**`start_next_hand()` on the loop (M3 sub-task 2 fix).** An earlier version of this sketch had
`_authorize` return a plural `actions` and never called `start_next_hand()` at all — engine.py's
own docstring already says the Room must call it right after a `reduce()` lands on `HAND_OVER`,
"before offering anyone anything else," so the loop above does that in the same tick, before
`_arm_timers`/`_poke_bots`. `_authorize` returns at most one `Action` (or `None` to drop an
illegal command) since `Command` carries exactly one already-validated `(seat, Action)` pair —
there was never a second action to loop over.

> In-room messages never leave the owning task. A room lives on exactly one node and its
> members are routed there (§7); room state is never distributed.

**Sequencing (D1).** `seq` is per-seat (and per-spectator-session): dense and gapless *within
that stream*, never per-room. Two seats' `seq` counters have no relationship to each other — seat
0 being at `seq=40` says nothing about where seat 1 is. `event_id` is a separate, internal,
room-global monotonic counter used only for server-side logging and (future) replay; it is never
serialized to a client. The ring buffer (`self.ring`) is per-seat, and it stores frames *after*
`redact_event()` has already run — never raw `Event` objects — so a reconnect replay
(§8, [02-protocol.md §5](02-protocol.md)) can never accidentally hand a redacted-out tile back to
a seat because the redaction step ran once, at publish time, not at replay time.

**Timer race (D17).** The naive `asyncio.wait_for(inbox.get(), timeout)` or
`asyncio.wait({get_task, timer_task}, return_when=FIRST_COMPLETED)` pattern is wrong here: when
the timer wins, the *cancelled* `get()` can silently drop an item that arrived in the same
scheduler tick. `_next()` instead holds one long-lived `_inbox_getter()` task for the room's
entire lifetime and only ever awaits `asyncio.wait({getter, sleep_until_next_deadline})`, without
cancelling `getter` on either branch. A room has several concurrent deadlines live at once — the
current claim window, each connected human's per-turn clock, each pending bot's budget — so
`self.deadlines` is a heap keyed by `(deadline_ts, id)`, not a single scalar; `_next()` sleeps
until the heap's soonest entry or a new inbox item, whichever comes first.

**Bots off the loop (D12).** `_poke_bots()` never runs bot search inline. It submits
`(room_id, window_id, state_version, seat_view)` to a `ProcessPoolExecutor` — the GIL makes a
thread pool useless for CPU-bound pure-Python search — with a hard deadline, and returns
immediately; the Room task keeps servicing its inbox while the worker computes. The worker's
result re-enters through the same `inbox` as any human command, tagged with the
`(window_id, state_version)` it was computed against, and is **dropped** if either has moved on
by the time it arrives — the same staleness protection a laggy human click gets (§4).

**Implemented (M3 sub-task 6).** `server/app/room.py`'s `_poke_bots()`/`BotJobTag`/`BotResult`
match this sketch: `state_version` is `Room.event_id` (already the room's own "did anything
change" counter, reused rather than duplicated); `key` covers both a claim `window_id` and a
plain turn (`kind: "turn"|"claim"`), since a bot-handled `AWAIT_ACTION` turn has no window to tag
against. The worker itself is `bots/worker.py`'s `compute_action(seat_view, seed)` — uniform
over `seat_view.legal_actions`, the same T0 policy as `RandomBot` but built against `SeatView`
instead of `GameState` (see that module's docstring for why this closes the redaction gap for
the one path that crosses a real process boundary, without migrating `bots/base.py`'s tier
interface, which `04-bots.md` is replacing wholesale in M4 anyway). On a worker crash or a hard
timeout, no synthesized default action is applied for a *turn* decision — per-turn timeout
enforcement has no driver at all yet (own note above); a live *claim* offer still resolves
correctly regardless, through its own real `TimerHeap` entry, independent of whether the bot
ever answers.

**Session/WS integration (M3 sub-task 4).** `SeatBinding` (`app/room.py`) ended up holding a
live socket's push callback, `ready`/pre-arm (`auto`) state, and a per-seat `IdempotencyCache`
(`app/idempotency.py`, §1's "per seat binding, not per socket" scope) — richer than this
sketch's one-line placeholder, but the same object. `join`/`mark_ready`/`set_auto` mutate it
directly from `Session` rather than through `inbox`/`Command` — safe because they're
synchronous, no-`await` calls on the room's own event loop, same single-writer discipline as
everything else here, just not routed through `reduce()` (which only ever applies a
`mahjong_core.actions.Action`, and joining/pre-arming isn't one). A room built with
`require_ready=True` (every room `app/ws.py` creates) additionally refuses every command until
all four seats have both joined *and* sent `ready` (§2's "seat assignment"); `Room.__init__`
still deals hand 1 immediately as this sketch always did, but nothing gets published to a seat
until that gate opens. Several server events sketched in [02-protocol.md
§3](02-protocol.md) — `hand_start`, `deal`, `turn`, `claim_offer`, `score` — have no backing
`mahjong_core.engine.Event`: the pure engine returns none for a hand's opening deal (`new_game`/
`start_next_hand` build `GameState` directly, not through `reduce()`) and never modeled "it's
now someone's turn" or "a claim window opened" as `Event`s in the first place, since deciding
*when a client should be told* is a wire-recipient concern (the same boundary `redact_event`'s
own docstring already draws for `discard.pool_index`). `Room` synthesizes all five directly,
at the exact points in its own loop that would otherwise have called `redact_event`.

### Outbound backpressure

Session pumps a **bounded** outbound queue per connection (default 64 frames), not an unbounded
one. An unbounded queue behind a stalled TCP socket — bad wifi, a backgrounded mobile tab — is a
slow memory leak: it doesn't crash anything locally, it just grows until the process OOMs under
real traffic.

Overflow policy: drop the oldest queued frames first (a stale `draw` matters less than the
`discard` that followed it), and once a `state_sync` frame is enqueued, drop everything queued
ahead of it and send that instead. Because `seq` is per-seat and gapless (D1, above), a drop is
self-healing: the client's next `last_seq` is behind, the resume protocol
([02-protocol.md §5](02-protocol.md)) notices the gap on its own and requests exactly the
`state_sync` this policy already forces.

**Implementation (M3 sub-task 4, `app/outbox.py`'s `BoundedOutbox`).** Room isolation from a
slow consumer comes from task separation, not a socket-write timeout: `Room.publish_to_seat`
only ever calls `SeatBinding.send`, a synchronous, non-blocking `push()` onto the queue —
never `await`s the actual socket write. A separate `Session.writer()` task owns the real
`websocket.send_text()` loop, so a stalled TCP connection blocks only that task; the Room task
is never waiting on Session for anything. The overflow policy itself: drop the oldest frame
that isn't `ack`/`error`, and the instant anything is dropped, clear every remaining
non-critical frame and ask `Room` to publish a fresh `state_sync` in its place (allocating a
real `seq` the normal way, rather than the queue fabricating one — see `app/outbox.py`'s module
docstring). If the queue is still over capacity after that (every frame queued was `ack`/
`error`, or stayed over capacity post-collapse), the connection is dead, not just slow, and
`Session` closes it.

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
  does nothing yet — deferred past v1 (D7); see [99-deferred.md](99-deferred.md).

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

**Implementation split (M3 sub-task 3).** `claims.can_close_early`/`resolve_claims` are pure
and reason only over responses already collected — they don't know about a clock. Early exit
is therefore invoked from inside `mahjong_core.engine._apply_claim_response` itself, the moment
a real claim response makes the window ready; `app/room.py`'s `Room` never has to re-derive it.
What `Room` owns is what the pure engine *can't*: arming `deadline_ts` (`TimerHeap`, keyed
`(deadline_ts, window_id)`, D17 above) when a window opens, and — on timer expiry, staleness-
checked against the live `window_id` — synthesizing `Pass` for every seat that never responded
and feeding it through that exact same `reduce()`/`resolve_claims` path. Window duration is
`RuleSet.claim_seconds` (`mahjong_core/config.py`, default 5s) — already real config, not a gap.

Gotchas:

- **Only offer claims to players who actually have one.** Broadcasting "someone may claim" leaks
  information and trusts the client.
- **`window_id` on every claim.** Claims tagged with a stale window are dropped silently;
  without it a laggy click from the previous discard fires on the current one.
- **Early exit is a UX feature, not an optimisation — kept deliberately (D8).** If the only
  eligible chow passes, the game must continue instantly; waiting out a 5s timer every discard
  feels dead. Conversely, if a chow claim arrives while a pung is still possible from another
  seat, wait. **Accepted information leak:** this trades a UX necessity for two signals an
  attentive opponent can read — (1) how long the window stays open at all tells non-claimants
  that *someone* had a claim (an instantly-closed window means nobody did); (2) a player who
  passes immediately, before the window closes, learns from the window staying open afterward
  that another seat still holds a live claim. Both leak partial information about opponents'
  hands. This is accepted, not mitigated — timing-obfuscation (padding `claim_offer` delivery to
  make "no offer" and "offer" indistinguishable) was considered and rejected: it's incompatible
  with instant early exit, which is the whole point of this bullet.
- **Pre-declared intent.** Clients pre-arm "auto-pass on chow" / "no calls" toggles; the server
  treats a pre-arm as an instant PASS. Keeps strong players from being prompted 40 times a hand.
- **Robbing the kong (搶槓)** opens a claim window on a *kong declaration*, not a discard. Same
  machinery, different trigger.

## 5. Redaction

The room never serializes `GameState`. Redaction is **two named functions**, not one
overloaded one — they answer different questions (D5):

```python
def seat_view(state: GameState, seat: int | None) -> SeatView:
    """Full redacted snapshot for one recipient. seat=None -> spectator view.
    Used by anything that needs 'the whole table as seat X may see it right now'
    rather than one wire event: bots (§3, D12), state_sync, ML encoders (06-ml.md)."""

def redact_event(state: GameState, seat: int | None, event: Event) -> dict:
    """Per-event wire redaction: the JSON actually sent for one logical Event,
    to one recipient. Concealed tiles become counts, never identities."""
```

### `SeatView`

**This subsection is the canonical definition** — `server/app/views.py` — depended on by
[04-bots.md](04-bots.md) (bot `act()` input) and [06-ml.md](06-ml.md) (encoder input), neither
of which may change its shape unilaterally. Lives in `app/`, not `mahjong_core/`
(`05-roadmap.md §1`'s layout): `server/AGENTS.md` reserves `mahjong_core` for pure rules, and
"what may this specific recipient see" is a wire-recipient concern, not a rule.

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
    scores: tuple[int, int, int, int]
    legal_actions: tuple[Action, ...]              # non-empty whenever actions.legal_actions(state, seat) is
    claim_options: tuple[ClaimOffer, ...]          # this seat's own live claim offer (§4), if any
    deadline_ts: int | None                        # the deadline relevant to this seat, if any
```

`legal_actions`/`claim_options` reuse `mahjong_core.actions.Action` / `mahjong_core.state.
ClaimOffer` directly rather than a separate `LegalAction`/`ClaimOption` wire type — neither
name is defined anywhere, and both real types already carry only this seat's own tiles or
already-public tiles, so a parallel type would add translation with no redaction benefit.
`legal_actions` is non-empty whenever `actions.legal_actions(state, seat)` is — that's "seat's
own `AWAIT_ACTION` turn" *or* "seat holds a live claim/kong-rob offer", not just `seat == turn`
(a claim-window seat needs its options too — `04-bots.md`'s bot `act()` is called then as well).

There is no field on `SeatView` capable of holding another seat's concealed tile identity —
`own_hand` is the only tile-id field, and it's populated only for the view's own seat. That's a
property of the shape, and it's what the schema walker below checks.

`seat_status` and `deadline_ts` have no real backing yet as of the redaction sub-task that
first implements this module: `mahjong_core/state.py` deliberately keeps connection status out
of `SeatState` (own-module rationale: `app/room.py`'s future `SeatBinding` should own it
without a pure-engine round-trip), and no timer heap exists yet to arm a per-turn deadline (§3
D17, a later M3 sub-task). `seat_view()` takes `seat_status` as an override, defaulting every
seat to `"connected"`, and surfaces `deadline_ts` only from `ClaimWindow.deadline_ts` when this
seat holds a live claim offer. Both get real data once their owning sub-tasks land.

**`seat_status` got its real data in M3 sub-task 6.** `app/room.py`'s `SeatBinding.status`
(`connected`/`disconnected`/`autoplay`) is now what `Room` passes as `seat_view()`'s
`seat_status` override everywhere it builds a view (`state_sync_wire`, `_poke_bots`) — see
`Room.mark_disconnected`/`reconnect`. `deadline_ts` for a *claim* offer has had real backing
since sub-task 3/5; a per-turn `deadline_ts` is still advisory-only (§3's own note above).

**`empty` distinguishes "never joined" from "connected" (post-M3, `/table/[id]` sub-task).**
`Room._seat_status_tuple()` reported `"connected"` for an unbound seat too — the only default
`seat_view()` itself ever had — until the frontend's live table wiring started reading
`state_sync` before all four seats join (to render a "waiting for the rest of the table"
screen) and needed a real signal for "nobody's here" distinct from "someone's connected".
`Room._seat_status_tuple()` now reports `empty` for a `None` slot in `seat_bindings` instead;
`seat_view()`'s own default (no caller-supplied override) is unchanged at `"connected"` — it
still serves callers with no `Room`/lobby concept at all (bots, arena, selfplay).

### Redaction test

Invariants are enforced by a **schema walker**, not a substring scan of serialized bytes.
Scanning JSON text for tile-shaped integers is a false-positive machine — `"tile_id": 5` and
`"pool_index": 5` are indistinguishable as raw digits — so entitlement is instead an explicit,
per-field annotation that a walker checks structurally:

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
either absent from the payload or holds a count/placeholder — never a real tile id. This checks a
structural property of the schema plus the redaction output, field by field; it cannot be fooled
by a field that merely happens to contain the number 5.

Invariants this enforces:

- Another player's concealed hand → `{"count": 13}`. Never a tile list.
- The wall → `{"remaining": 42}`. Never contents, never `game_seed`. Only that hand's
  `hand_seed = SHA256(game_seed || hand_no)` is revealed, and only at that hand's end (§3, §9.4,
  D2) — `game_seed` itself is never on the wire during play, at any point, for any hand.
- A concealed kong (暗槓) → `{"kind": "concealed_kong", "count": 4}` to others; the tile
  identity is revealed only at hand end.
- Flowers, melds, discard pool, scores: fully public — send them.
- A spectator sees the union of what all four players show publicly, **not** their private
  hands. Showing hands to spectators requires a 30–60s delay.

**Bots consume the identical `seat_view` output a human's client would render from** — proof
they can't cheat, and any bot is runnable as a client against a real server for integration
testing.

## 6. Stack

### Backend: FastAPI + native WebSockets

ASGI-native, WebSockets through Starlette, and pydantic models double as the protocol schema,
codegen'd into TypeScript (see [02-protocol.md](02-protocol.md)). Run on uvicorn with uvloop.

### Serialization: JSON

Payloads are tiny: ~2KB for a full state snapshot, ~150 bytes for a typical event.

### Frontend: SvelteKit 2 (Svelte 5, runes) — DOM/CSS, no canvas

"SvelteKit 5" isn't a real version: SvelteKit and Svelte version independently, and the stack is
SvelteKit 2.x on Svelte 5.x. **PixiJS is cut (D10).** The table is DOM/CSS like everything else
in the client — this is a turn-based, low-tick-rate game (§1); there's no draw-call budget worth
a second rendering system to protect, and DOM/CSS gets text layout, hit-testing, and
accessibility for free instead of fighting a canvas for them. The old plan's "one texture atlas,
~150 sprites, one draw call" claim is cut along with Pixi — it was false as stated even on its
own terms: Text objects, masks, and filters each break Pixi's batch, so it was never actually one
draw call. Svelte owns the whole client: lobby, HUD, claim buttons, score sheet, chat, settings,
and the table surface (tiles, melds, discard pool). Details in [03-frontend.md](03-frontend.md).

### Storage

**Postgres** — users, room metadata, finished games as `(ruleset, game_seed, action_log)` with
`action_log` as JSONB, leaderboards. Matchmaking, presence, rate limiting and session state are
v1 **module-level dicts in the API process** — no `KV`/`Queue`/`Bus` abstraction layer. A
Protocol-per-backend split earns its keep once there's a second real backend to swap in (Redis,
say); v1 has exactly one backend (in-process memory), so the abstraction has no job yet. It would
also invite `async def` on a plain dict lookup, which has no I/O behind it and violates this
project's own "`async def` only where there is real I/O or concurrency" rule
(`server/AGENTS.md`). Deferred — see [99-deferred.md](99-deferred.md).

**`RoomRegistry` (M3 sub-task 6, `server/app/registry.py`)** is exactly this: an in-process
`dict[str, Room]` plus the bookkeeping to run each room's `asyncio.Task`, replacing `app/ws.py`'s
earlier bare dict. **Room lifecycle gap found implementing it:** nothing in this doc described
when a room's background task should stop, so `Room.run()` looped forever even after
`GAME_OVER`, leaking one idle `asyncio.Task` per finished game for the rest of the process's
life. Fixed minimally, not with a full expiry policy: `Room.run()` now returns on `GAME_OVER`,
and `RoomRegistry` drops the task-bookkeeping entry the moment it does. The `Room` object itself
is **not** evicted — reconnecting after the game ends is still a supported, synchronous path
(`Room.reconnect`/`resume`), and no session-expiry/TTL policy exists anywhere in this doc to
size a real eviction from. Full room eviction (freeing a long-dead finished game's memory) stays
a real, open gap, narrower now than the "no eviction, no capacity limit" it replaces.

**Real-game Postgres persistence (a later M3 sub-task).** M1 only wired `save_game_record` up to
`bots/selfplay.py`'s bot-only self-play loop; a `Room`-driven game (real humans, or bot handover
mid-game) had no path to it at all -- `Room` tracked no action log and had no DB dependency.
Closed by giving `Room` a full-game `self.actions: list[Action]` (every `Action` that actually
ran through `reduce()`, appended in `_apply` -- never a `start_next_hand()` transition, which
isn't an `Action`; replay reconstructs those automatically off `Phase.HAND_OVER`, the same
convention `bots/selfplay.py`'s `play_game` docstring already states) and an optional
`session_factory: async_sessionmaker[AsyncSession] | None` threaded through `Room.__init__` /
`RoomRegistry.__init__` / `RoomRegistry.get_or_create`. `app/main.py`'s `lifespan` builds the
real engine/session factory from a `DATABASE_URL` env var (unset -> no persistence, matching
every bare `Room()`/`RoomRegistry()` construction that predates this) and installs it into a
fresh `RoomRegistry` via `app/ws.py`'s `reset_registry()` on every ASGI startup -- "fresh", not a
mutated eternal singleton, matters for the shutdown-drain state below (§8.1). On
`Phase.GAME_OVER`, `Room.process_one()` calls `save_game_record` at most once with the
accumulated `self.actions` and `players` taken from each seat's `SeatBinding.session_id` -- the
closest thing to a stable per-seat identity that exists before real auth ships (M5); a real
`players` identity (an account id, not a per-connection session id) is M5 scope, not invented
here.

## 7. Scaling path

**Stage 1 — one process (v1, this doc's scope).** In-memory rooms, Postgres for durable records
(users, finished games, leaderboards). Handles hundreds of concurrent tables. **No mid-game
durability:** a room's live `GameState` exists only in that process's memory. If the process
dies, every room in it dies too — **games in progress are abandoned**, full stop. This is a
deliberate v1 answer, not an oversight; see the shutdown story in §8 for the one case (a planned
deploy, not a crash) where we do better than that.

Everything past Stage 1 is deferred intent, sketched here only so the single-writer-per-room
invariant (§3) isn't accidentally violated later: **Stage 2** would shard rooms across N nodes,
each room pinned to exactly one node for its lifetime via a router that holds nothing but a
room→node directory, the matchmaking queue, and lobby presence (`shard by room, never split a
room`). **Stage 3** would add durability — surviving a node loss without abandoning the room —
which is the genuinely hard, currently-unwritten part: exact replay needs *every* source of
non-determinism logged as a first-class action, not just player intents, including bot decisions
(ε-random, [04-bots.md](04-bots.md)) and every timer expiry (tsumogiri-on-timeout,
auto-pass-on-timeout, bot-deadline defaults). Nobody has designed that log format, or picked
between per-action and per-hand write granularity and lived with the crash-window tradeoff either
choice implies. Deferred — see [99-deferred.md](99-deferred.md).

## 8. Failure handling

| Event | Behaviour |
| --- | --- |
| Player disconnects | Seat marked `DISCONNECTED`. Room continues. Grace period (default 20s) before the bot takes over; the seat keeps playing as `AUTOPLAY`. **Implemented (M3 sub-task 6):** detected only by the WS connection actually closing (`app/ws.py`'s `Session` `finally` block) — a heartbeat-driven dead-socket timeout (§8 "Liveness" below) has no driver anywhere in this codebase yet, so it isn't what starts this clock today. The grace timer reuses the same `TimerHeap`/id space claim-window deadlines already use (`app/room.py`'s `TimerHeap` docstring), not a second mechanism, and a new external-to-the-room-loop deadline (this one, or a mid-claim-window reconnect re-arm below) has to explicitly wake a possibly-already-sleeping `Room._next()` — see `_WakeUp`'s docstring for why that's a real correctness requirement, not a nicety. |
| Player reconnects | Auth, rejoin room, send `last_seq`. Server replays from that seat's ring buffer or sends a fresh `state_sync` (§3, D1). Bot relinquishes the seat. **Mid-claim-window:** if this seat's claim hasn't resolved yet — the bot hasn't answered and the window is still open — the server re-arms *only this seat's* entry in the timer heap (§3, D17) to a full human-length window measured from the reconnect moment; the original deadline was sized for a bot answering in milliseconds and handing it to a just-reconnected human would be a de facto auto-pass. Other seats' deadlines are untouched. If the claim already resolved before the human reconnected, there's no do-over — they get a `state_sync` reflecting the resolved state, same as a human whose own click lands after the window closed. **Implemented (M3 sub-task 5), and re-checked once bot handover landed (sub-task 6):** bot handover exists now, but every offered seat — human, or `AUTOPLAY`-and-bot-answered — still gets the same `ruleset.claim_seconds` window (`RandomBot`-equivalent's `compute_action` policy is instant, so it always answers well inside that window regardless); nothing gave bots a separate, shorter claim-window deadline. So the doc's "sized for a bot" scenario never literally existed either before or after sub-task 6 — read as the *general* case this guards ("whatever the deadline was armed for, a just-reconnected human gets a fresh full window instead of its leftover sliver"), not literally "detect it was a bot." This re-arm needed no changes once bot handover landed — it already always won over whatever the seat was offered before, bot-answered or not. Building it required splitting the claim-window timer heap from one shared entry per window to one entry per offered seat (`server/app/room.py`'s `TimerHeap` docstring) — a shared entry can't move for one seat without moving for all of them. |
| Player never returns | Bot plays out the game. Result recorded against the human. |
| Turn timeout | Server acts for them. **After a draw:** tsumogiri — discard the drawn tile. **After a claimed pung or chow:** there is no drawn tile — the claimer goes straight from the claim to `AWAIT_ACTION` with nothing new in hand to reflexively discard ([01-rules-spec.md §4](01-rules-spec.md); kong is unaffected, a kong claim always draws a replacement tile first). The fallback there is deliberately dumb, not defensive: discard the tile in the concealed hand with the lowest `tile_id`. Smart defensive discarding is a bot-tier concern ([04-bots.md](04-bots.md)), not a timeout default — the default only needs to be legal, deterministic, and boring. Either case, auto-pass any pending claims. Three strikes → seat flips to `AUTOPLAY` for the rest of the game. |
| Bot raises / hangs | Bot runs in a worker pool with a hard deadline, outside the room loop (§3, D12). On timeout, the room applies the same deterministic default action as a human timeout. A bot must never be able to wedge a table. **Implemented (M3 sub-task 6), one gap:** a *claim* offer a bot fails to answer in time is unaffected — it resolves via its own real `TimerHeap` entry (default-to-`Pass`) regardless of whether the bot ever responds, same as a silent human. A bot's own *turn* (`AWAIT_ACTION`) has no deterministic-default fallback to apply on a crash/timeout, because per-turn timeout enforcement itself has no driver at all yet for anyone, human or bot (§3's own note) — `app/room.py`'s `_await_bot_job` just clears the pending job tag on failure so the next tick retries from scratch, which cannot wedge the table (the claim-window path is unaffected) but also doesn't force a stalled turn to resolve. Closing that is the same pre-existing "turn timeout has no driver" gap, not new to bots. |
| Planned shutdown / deploy | See §8.1 — different from a crash; the process gets to say goodbye. |
| Node dies (deferred, stage 3) | Not a v1 behavior — see §7. Sketch: router reassigns; new owner replays the action log; clients reconnect and `state_sync`. |

### 8.1 Graceful shutdown

Nothing in this doc's v1 (§7) survives a crash — a killed process abandons every room in it.
That's acceptable for a crash, which is rare and unplanned. It is **not** acceptable for a
routine deploy, which is frequent and entirely planned: `restart: unless-stopped` with a
single in-memory process otherwise means every deploy kills every live table, silently, mid-hand.

v1's answer is a drain, not durability — it buys the process time to reach a safe stopping point
instead of trying to survive past one:

1. On `SIGTERM`, the process stops accepting new WebSocket connections and stops matchmaking new
   rooms; the health check starts failing so a load balancer drains inbound traffic.
2. Every room still holding players is told: broadcast a `server_shutdown{deadline_ts}` event so
   clients can show a "reconnect shortly" banner instead of reading a dropped socket as an error.
3. A room that is mid-hand is allowed to *finish that hand* — but no further — within a bounded
   grace window (default 90s, tunable). Reaching a hand boundary before the window elapses is a
   clean stop: the room can be torn down with no player mid-decision.
4. If the grace window elapses first, the room is torn down anyway and that hand is abandoned,
   same as a crash — but the players were warned, which a crash can't offer.
5. The process exits once every room has reached a hand boundary or the grace window has expired,
   whichever comes first for that room — not a single global sleep.

This turns "every deploy kills every live table" into "every deploy costs at most the tail of one
hand per table, with warning," without requiring the mid-game durability that §7 defers.

**Implemented (a later M3 sub-task).** `app/registry.py`'s `RoomRegistry.begin_shutdown` is
steps 2-5: it sets `.draining` (read by `app/ws.py`'s connection accept -- new connections,
reconnects included, get closed with code 1013 "try again later" rather than accepted -- and by
`/healthz`, which serves `503 {"status":"draining"}` once it's set), broadcasts a new
`server_shutdown{deadline_ts}` event (`app/protocol.py`) to every room with a seat ever bound,
then waits on each such room's own `Room.wait_for_shutdown_boundary` *concurrently*
(`asyncio.gather`, not a loop of sequential awaits) so the total wall-clock cost is the grace
window once, not once per room. A room that never reaches a boundary is logged as abandoned, not
force-torn-down by this call itself -- the process exiting afterward is what actually ends it,
same "abandoned, same as a crash, but warned" story, not a second teardown path.

`app/main.py`'s `lifespan` is the hook: the drain runs in the code after `yield`, which uvicorn's
default SIGTERM handling resumes into (verified against a real `uvicorn.run()` process sent a
real SIGTERM, not assumed — see that module's own docstring). The grace window defaults to 90s,
tunable via a `SHUTDOWN_GRACE_SECONDS` env var rather than a `RuleSet` field, since it's a
process-level shutdown parameter, not a per-game rule. One real consequence of hooking the
*generic* ASGI shutdown phase rather than a SIGTERM-specific handler: a `TestClient(app)`
context exiting runs this exact same drain code, which is why `server/tests/conftest.py` pins
`SHUTDOWN_GRACE_SECONDS=0` for the whole test session (the usual test-time-control pattern this
codebase already uses elsewhere, e.g. `disconnect_grace_seconds=0`, applied via env var here
since this parameter lives outside any single game's `RuleSet`).

## 9. Anti-cheat

1. **Server-authoritative + per-seat redaction** (§5) closes information cheating, the dominant
   threat. If the client never receives a tile it shouldn't see, memory inspection is useless.
2. **Validate every intent against the server-computed legal-action set.** Never trust a
   client-declared meld, claim legality, faan count, or score.
3. **Rate-limit intents per session** and reject malformed envelopes hard.
4. **Provable fairness — commitment only, not proof of an unbiased deal.** Commit
   `SHA256(hand_seed || nonce)` at hand start, reveal `hand_seed, nonce` at hand end (§3, §5,
   D2). Be precise about what this proves: it shows the server didn't change the wall *after*
   committing. It does **not** show the wall was fair. The server alone picks both `hand_seed`
   and `nonce`, and — because dealing is a pure function of `hand_seed` (§3) — it already knows
   the resulting wall before it commits to anything. Nothing stops a malicious server from
   grinding `(hand_seed, nonce)` pairs off-protocol until one deals a wall it likes, *then*
   publishing that commitment; the reveal still verifies cleanly, because the commitment scheme
   never claimed the seed was chosen without seeing its outcome. Treat this control as "the
   server can't edit the deal retroactively," not as "the deal was unbiased" — the two are
   different claims and only the first one is true here. Closing the real gap needs
   client-contributed entropy so the server can no longer see the outcome before it's locked in.
   Deferred — see [99-deferred.md](99-deferred.md).
5. **Collusion** (two humans sharing a screen) is unsolvable technically. Mitigate socially:
   random matchmaking for rated play, statistical review of suspicious deal-in patterns.
6. **Claim-window timing leak (accepted, not mitigated) — see §4, D8.** Early exit means both the
   window's duration and a fast-passer's view of whether the window stays open afterward leak
   partial claim information to an attentive opponent. This isn't a control this section closes;
   it's a deliberate, documented trade of a small leak against a UX regression that's worse than
   the leak. Don't "fix" it locally without re-reading §4 — the fix (padding) was evaluated and
   rejected there.
