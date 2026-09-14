# 02 — Wire protocol

Transport: one WebSocket per client at `wss://…/ws?room={id}&ticket={ticket}`. Plain JSON frames
— no `permessage-deflate`: at ~150 bytes/frame it typically *grows* the payload (compression
overhead exceeds the savings) and adds per-frame CPU to every connection for no benefit at this
message size. REST (`/api/*`) handles everything that isn't live play: auth, profile, room
listing, replay download, leaderboard.

**Auth (D13):** guest-first, with optional account upgrade — never a hard signup wall. REST
issues a short-lived, single-use WS ticket: `POST /api/auth/ws-ticket` (works for a guest or a
logged-in session) returns `{ticket, expires_in}`. The client opens the socket with
`?ticket=...` and the server burns it during the `hello` handshake — one connect per ticket. A
JWT **never** goes in a query string: query strings land in proxy logs, browser history, and
Referer headers, none of which should hold a bearer credential. The long-lived session
credential (JWT or guest cookie) stays in an `Authorization` header / cookie on the REST call
that mints the ticket; the socket itself only ever sees the disposable ticket.

## 1. Envelope

Every frame, both directions:

```jsonc
{
  "v": 1,            // protocol version
  "t": "discard",    // message type
  "seq": 412,        // server->client only: monotonic per-seat stream, gapless
  "id": "c-7f3a",    // client->server only: idempotency key, echoed in ack
  "ts": 1757865432,  // server clock, ms
  "d": { }           // payload
}
```

- `v` — protocol version; mismatch → `error{code:"version"}`, then close.
- `t` — message type.
- `seq` — server→client, **per-seat** (and per-spectator-session): dense and gapless within the
  stream sent to *that recipient*, not per room. Two players never share a seq space, so what
  one player is or isn't offered (e.g. a `claim_offer` someone else didn't get) never shows up
  as a gap for anyone else — see §5 for the resync algorithm and §7 for a worked example. The
  room separately keeps an internal monotonic `event_id` for logging and replay ordering; it
  never goes on the wire and is not what `last_seq` is compared against.
- `id` — client→server idempotency key. See "Idempotency" below.
- `ts` — server clock, ms.
- `d` — payload.

### Idempotency

- **Scope:** per seat binding, not per socket — it survives reconnect (a new socket resuming an
  existing seat via `hello{last_seq}` inherits the seat's id history, §5).
- **Retention:** the last 256 ids per seat, LRU-evicted. Comfortably covers any realistic
  retry/reconnect storm without keeping unbounded state; ids are not persisted across a full
  server restart.
- **Same `id`, identical payload** (a genuine retry — e.g. client resent after a dropped ack):
  server does not reapply the action; it re-sends the original `ack` for that `id`.
- **Same `id`, different payload** (client bug, not a retry): server rejects the new frame —
  `ack{id, ok:false, error:"id_conflict"}` — and applies neither the old nor the new payload as
  if it were the other.

## 2. Client → server (intents)

The client sends *intent*, never *state*: "discard tile #47", not "my hand is now X".

| `t` | payload | notes |
| --- | --- | --- |
| `hello` | `{last_seq?, client_version}` | first frame after connect |
| `join` | `{seat?: 0-3}` | request a seat; omit `seat` for "first open seat" |
| `ready` | `{}` | lobby → start; only valid once seated |
| `discard` | `{tile_id}` | must be in hand, must be your turn |
| `claim` | `{window_id, choice, tiles?}` | `choice`: `pass\|chow\|pung\|kong\|win`. `tiles` disambiguates a chow (e.g. 4-5 vs 5-6 for a 6). Priority among competing claims is resolved per [01-rules-spec.md §6](01-rules-spec.md) — not restated here. |
| `declare` | `{kind, tiles}` | `concealed_kong \| added_kong \| win` on your own turn |
| `auto` | `{no_calls?, auto_pass_chow?}` | pre-arm toggles; server treats a pre-arm as an instant PASS ([00-architecture.md §4](00-architecture.md)) |
| `chat` | `{text}` | rate-limited; consider canned phrases only |
| `ping` | `{t0}` | clock offset measurement; also doubles as the liveness heartbeat (§8) |

The server rejects anything outside the legal-action set it computed itself. Client-side
legality is a UI hint only.

### Seat assignment

`join` is the only way to occupy a seat; a socket that never sends it is a spectator. The server
fills seats first-come-first-served among open ones unless `seat` is given, in which case it's
rejected (`error{code:"seat_taken"}`) if that seat is already bound, or `error{code:"room_full"}`
if none are free. A successful `join` is confirmed by a broadcast `seat_state{seat,
status:"connected"}`. `join` is for first entry only — a reconnecting player doesn't re-`join`;
`hello{last_seq}` on an already-bound seat reclaims it directly (§5). Once all four seats are
filled the room waits for `ready` from each before dealing.

### Declining a claim on purpose

`auto` has no `auto_win` toggle. Declining a winning claim is a real strategic choice under
`min_faan` rulesets — chasing a bigger hand, avoiding revealing information, waiting for a
better payout — and is called out explicitly in [06-ml.md §1](06-ml.md) ("`PASS` covers
declining a win"). A pre-arm that silently auto-accepted every offered win would remove that
choice. So a win-eligible claim is never auto-resolved by a pre-arm: it always opens a real
`claim_offer` to the eligible seat(s), and — consistent with every other claim — times out to
PASS, not to WIN, if the player doesn't respond.

## 3. Server → client (events)

| `t` | payload sketch |
| --- | --- |
| `state_sync` | full redacted snapshot — sent on join, reconnect-with-gap, and after any resync |
| `hand_start` | `{hand_no, prevailing, dealer, seats, seed_commit?}` — see Fairness below |
| `deal` | `{your_hand: [tile_id…], counts: {seat: n}, wall_remaining}` |
| `flower_replace` | `{seat, flower, replacement?}` (`replacement` only for you) |
| `draw` | `{seat, tile_id?}` — `tile_id` present **only** for the drawing player |
| `discard` | `{seat, tile_id, tile, pool_index}` |
| `claim_offer` | `{window_id, options: [...], deadline_ts}` — **unicast**, only to eligible seats |
| `claim_resolved` | `{window_id, seat?, kind, meld?, from_seat?}` — v1 is single-winner; `seat` is always singular (一炮多響 deferred, D16) |
| `meld` | `{seat, kind, tiles, from_seat?}` — except `concealed_kong`, which has a redacted per-seat form (see Redaction below) |
| `kong_replace` | `{seat, tile_id?}` |
| `turn` | `{seat, phase, deadline_ts, legal: [...]}` — `legal` unicast to the acting seat |
| `hand_end` | `{result, winner?, hands: {...}, faan_breakdown, payments, fairness?}` — see Fairness below |
| `score` | `{totals: {seat: n}}` |
| `game_end` | `{standings, game_id}` |
| `seat_state` | `{seat, status: connected\|disconnected\|autoplay\|bot}` |
| `ack` | `{id, ok, error?}` — **sender-only**, never broadcast: it would leak another player's client-chosen `id` |
| `error` | `{code, message}` |
| `pong` | `{t0, t1}` |

### Fairness (optional, ruleset flag)

The PRNG is seeded once per **game** (`game_seed`), not per hand. Revealing the raw `(seed,
nonce)` at `hand_end` would let any player recompute every remaining wall for the rest of the
game the moment hand 1 ends. Instead, derive a fresh subseed per hand (D2):

```
hand_seed = SHA256(game_seed || hand_no)
```

- `hand_start.seed_commit = SHA256(hand_seed || nonce)` — published before any tile of that hand
  is dealt.
- `hand_end.fairness = {hand_seed, nonce}` — reveals only that hand's subseed, **never**
  `game_seed`. A player can recompute that one wall and confirm it matches the earlier commit;
  every other hand stays opaque.
- Both fields exist only when `ruleset.provable_fairness` is set; omit the key entirely
  otherwise, don't send nulls.
- **Honest limit:** this proves the server didn't change the wall *after* it committed. It does
  **not** stop a malicious server from choosing `(seed, nonce)` adversarially *before* the
  commit — server-only entropy can be grinded by whoever controls the server. Defeating that
  needs player-contributed entropy or a VRF; out of scope for v1.

### Redaction

Two different functions, used in different places — [00-architecture.md §5](00-architecture.md):

- **`seat_view(state, seat | None) -> SeatView`** — a full redacted snapshot. Used for
  `state_sync`, and by bots/ML, which consume the identical view a human would see.
- **`redact_event(state, seat | None, event) -> dict`** — per-event wire redaction. Used for
  every other outbound message. Takes the *current* `state`; see §5 for why that rules out
  re-redacting old events at replay time.

`draw`, `claim_offer`, and `turn.legal` are unicast or differ per seat; render each logical event
through `redact_event` per recipient — never broadcast one frame and trust clients to ignore
fields. `claim_offer` goes **only** to eligible seats: an ineligible seat's stream simply has no
entry for that event at all, not a redacted stub — safe under per-seat `seq` (§1, §7).

Test by walking the schema: for every message type and every seat, the serialized bytes must
contain no tile identity that seat is not entitled to.

**Concealed kong (暗槓)** is the one meld not fully public until hand end
([00-architecture.md §5](00-architecture.md)), so `meld` has two per-seat wire forms:

```jsonc
// to the declaring seat:
{"t":"meld","d":{"seat":2,"kind":"concealed_kong","tiles":[9,10,11,12]}}

// to every other seat and spectators, for the rest of the hand:
{"t":"meld","d":{"seat":2,"kind":"concealed_kong","count":4}}
```

Non-owning seats learn the tile identity only via `hand_end.hands` if the hand goes to showdown.
All other `kind`s (`chow`, `pung`, `added_kong`) are fully public: full `tiles` to everyone, no
redaction.

## 4. Timers

The server is the only clock that matters.

- Every prompt carries an absolute `deadline_ts` in **server** time.
- The client measures offset with `ping`/`pong` (`offset ≈ t1 - (t0 + rtt/2)`), smooths it, and
  counts down against `deadline_ts + offset`. Never count down from a server-sent duration.
- Render the last ~1.5s of the bar as "about to expire", not as exact.
- On expiry the server acts: tsumogiri on turn timeout, PASS on claim timeout. It emits the
  resulting event normally.

Deferred — see [99-deferred.md](99-deferred.md).

## 5. Reconnect and resync

```
client reconnects
   └─► hello { last_seq: 412 }
         ├─ 412 == head of this seat's buffered stream   → nothing missed, resume live
         ├─ 412 in this seat's ring buffer (512)          → replay envelopes 413…N, then resume
         └─ too old / new session                          → state_sync (full redacted snapshot), then resume
```

The ring buffer lives on the `Room`: one `deque[Envelope]` (`maxlen=512`) **per seat** (and per
active spectator session), holding *already-redacted* frames exactly as sent. That's the only
implementable option — `redact_event(state, seat, event)` takes the current `state`, and by
replay time `state` has moved on to wherever the game is now, so re-redacting a buffered event
against today's state would produce wrong, and potentially leaky, output. Pre-redacting once at
send time and buffering the result is correct and cheap enough: 512 frames × ~150 bytes × 4
seats is a few hundred KB per room.

`last_seq` in `hello` is compared against *that seat's own* buffered stream, per D1 — the room's
internal `event_id` (used only for server-side logging and replay-viewer ordering) never appears
on the wire and plays no part in this comparison.

The client applies events through a reducer, so live play, gap replay, and the replay viewer
are one code path.

## 6. Schema generation

Pydantic v2 models in `server/app/protocol.py` are the single source of truth.

Pydantic v2 exports a tagged union as `$defs` + `oneOf` + `discriminator` in JSON Schema, but a
generic JSON-Schema→TS generator — `json-schema-to-typescript` included — doesn't reliably turn
that into a *narrowable* discriminated union: `const` tags get widened to `string`,
`additionalProperties` handling adds index signatures that swallow narrowing, and the generic
envelope here (`d: {}`, whose shape depends on `t`) isn't expressible in JSON Schema at all.
That silently voids the one guarantee this pipeline exists for — "TypeScript flags an unhandled
event at compile time" — so skip the JSON Schema hop:

```
protocol.py  ──(server/tools/gen_protocol.py: a small custom emitter walking
                the pydantic model graph)──►  web/src/lib/net/protocol.d.ts
```

`gen_protocol.py` discovers message types generically from `protocol.py`'s `ClientMessage` /
`ServerMessage` / `AnyMessage` unions via `typing.get_args` — it doesn't hardcode message names,
so a new Envelope subclass added to those unions is picked up without touching the generator.

- Each message `t` becomes a distinct interface with a literal `t` field. `Error` is emitted as
  `ErrorEvent` so importing it doesn't shadow the global `Error` constructor.
- `ClientMessage` and `ServerEvent` are unioned per direction (§2 vs §3); `AnyMessage` unions both,
  mirroring `protocol.py`'s `AnyMessage` — `ws.py` validates incoming frames against the full
  union so a wrong-direction message (e.g. a client sending `pong`) parses and is ignored rather
  than rejected as malformed, rather than against `ClientMessage` alone.
- `gen_protocol.py` also emits `web/src/lib/net/protocol.assertNever.ts`, a compile-time
  exhaustiveness fixture over `ServerEvent`:

  ```ts
  function assertNever(x: never): never { throw new Error(`unhandled: ${JSON.stringify(x)}`); }

  function handle(e: ServerEvent) {
    switch (e.t) {
      case "discard": /* ... */ break;
      // ... every case ...
      default: assertNever(e);   // compile error if a case is missing
    }
  }
  ```

  Regenerating this fixture alongside the types (rather than hand-maintaining it) means it can
  only fail to compile for one reason: the generated `ServerEvent` stopped being a genuinely
  narrowable discriminated union (e.g. codegen regressed `t` from a literal to `string`) — the
  exact failure mode the JSON-Schema hop had. `web/src/lib/net/reducer.ts` carries the same
  pattern in real production code, over the same type.
- `shared/protocol.schema.json` is still emitted (`TypeAdapter(AnyMessage).json_schema()`), but as
  a secondary, informational artifact only — nothing generates TS from it anymore.

Wire it into the build (`make proto`); `make proto-check` (`git diff --exit-code` after
regenerating) is the CI gate for "fails if the generated TS is stale" — see `docs/07-infra.md §9`
for why there's no CI running it yet.

## 7. Example exchange

Same logical sequence as before (Alice discards, Bob pungs), but `seq` is per-seat (D1), so
there is no single wire trace — each recipient has its own dense, gapless stream. The `turn` and
`discard` events are broadcast (redacted per seat where needed); `claim_offer` goes only to the
eligible seat; `ack` goes only to the sender. Below, room-internal `event_id`s (never on the
wire) are noted in comments purely to show what triggered each frame.

```jsonc
// ── Bob's stream (seat 1) — eligible for the pung, so he sees claim_offer and his own ack ──
{"v":1,"t":"turn","seq":41,"d":{"seat":0,"phase":"AWAIT_ACTION","deadline_ts":1757865447000}}
  // ^ Alice's turn; Bob isn't acting, so no "legal" field for him

{"v":1,"t":"discard","seq":42,"d":{"seat":0,"tile_id":47,"tile":"5s","pool_index":11}}
  // ^ event_id 100: Alice discarded

{"v":1,"t":"claim_offer","seq":43,"d":{"window_id":"w-204","deadline_ts":1757865452000,
  "options":[{"kind":"pung","tiles":[31,88]},{"kind":"pass"}]}}
  // ^ event_id 101: unicast — only Bob is eligible

// Bob -> server:
{"v":1,"t":"claim","id":"c-9e1","d":{"window_id":"w-204","choice":"pung","tiles":[31,88]}}

{"v":1,"t":"ack","seq":44,"d":{"id":"c-9e1","ok":true}}
  // ^ sender-only: only Bob's stream ever carries this

{"v":1,"t":"claim_resolved","seq":45,"d":{"window_id":"w-204","seat":1,"kind":"pung","from_seat":0}}
  // ^ event_id 102: window closed early, Bob was the only eligible seat

{"v":1,"t":"meld","seq":46,"d":{"seat":1,"kind":"pung","tiles":[31,88,47],"from_seat":0}}
  // ^ event_id 103: pung is fully public, full tiles to everyone

{"v":1,"t":"turn","seq":47,"d":{"seat":1,"phase":"AWAIT_ACTION","deadline_ts":1757865458000,
  "legal":[{"kind":"discard","tiles":[3,9,14,"..."]}]}}
  // ^ event_id 104: Bob is now acting, so he gets "legal"

// ── Carol's stream (seat 2) — never eligible; her stream is still dense, no gap ──
{"v":1,"t":"turn","seq":41,"d":{"seat":0,"phase":"AWAIT_ACTION","deadline_ts":1757865447000}}
{"v":1,"t":"discard","seq":42,"d":{"seat":0,"tile_id":47,"tile":"5s","pool_index":11}}
  // ^ event_id 101 (claim_offer to Bob) never appears in Carol's stream — not a gap, because
  //   Carol's seq only counts frames Carol actually receives
{"v":1,"t":"claim_resolved","seq":43,"d":{"window_id":"w-204","seat":1,"kind":"pung","from_seat":0}}
{"v":1,"t":"meld","seq":44,"d":{"seat":1,"kind":"pung","tiles":[31,88,47],"from_seat":0}}
{"v":1,"t":"turn","seq":45,"d":{"seat":1,"phase":"AWAIT_ACTION","deadline_ts":1757865458000}}
  // ^ no "legal" — Carol isn't acting
```

Compare: under the old per-room `seq`, Carol would have observed 90 → 92 (skipping Bob's
unicast `claim_offer` at 91) and been forced to full-resync on every claim window — and the
existence of the gap itself would have told her a claim was offered, defeating redaction (§3).
Per-seat `seq` makes that structurally impossible: Carol's stream was never going to contain
event 101, so there's nothing for her to detect.

## 8. Liveness

A mobile browser's WebSocket can sit open for minutes after the network actually dies without
firing `onclose` — TCP keepalive defaults to minutes-to-hours, and carrier NATs silently drop
idle mappings. `ping`/`pong` (§4) is specified only as a clock-offset measurement; it also has
to be the heartbeat, or a dead socket looks identical to an idle one:

- **Client → server:** the client sends `ping` at least every `heartbeat_interval` (default
  15s) regardless of whether it needs a fresh offset reading.
- **Server → client:** if no frame has gone out to a client in `heartbeat_interval`, the server
  sends an unsolicited `pong{t0: null, t1: now}` as a keepalive — harmless to a client that's
  only using real `ping`/`pong` pairs for offset.
- **Dead-socket detection:** if the server hasn't heard anything from a connection in
  `heartbeat_timeout` (default 45s — three missed intervals), it treats the socket as dead:
  closes it, marks the seat `DISCONNECTED`, and starts the normal grace-period/bot-takeover
  clock ([00-architecture.md §8](00-architecture.md)).
- **Client reconnect backoff:** on an unexpected close, reconnect with exponential backoff and
  jitter — `min(250ms * 2^attempt, 10s)` ± 20% — for as long as the seat is plausibly still
  reclaimable (through the disconnect grace period, and beyond it while the seat shows
  `AUTOPLAY` rather than `bot`-owned in `seat_state`).

## 9. Backpressure

The Session pumps an outbound queue per connection ([00-architecture.md §2](00-architecture.md));
that queue must be **bounded** (default 256 frames), not left to grow — an unbounded queue
behind a stalled TCP connection (dead peer, congested mobile network) is a memory leak that
scales with however long the peer stays half-open.

Policy when the queue is full:

- Drop the oldest *non-critical* queued frames first — `draw`, `discard`, `turn`, and similar
  state-deltas are superseded by a fresh snapshot anyway. Keep `ack`/`error` if still queued.
- The instant anything is dropped, stop trying to catch the stream up: clear the queue and
  enqueue a single `state_sync` instead. The client's reducer already treats `state_sync` as an
  idempotent full replace (§5), so a torn-out middle of the stream is harmless once the snapshot
  lands — this reuses the reconnect-with-gap code path rather than adding a second one.
- If the queue is still full after that (socket is dead, not just slow), the Session closes the
  connection; the room marks the seat `DISCONNECTED` and normal grace-period/bot-takeover
  ([00-architecture.md §8](00-architecture.md)) applies.
