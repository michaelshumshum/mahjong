# Wire protocol

Transport: one WebSocket per client at `wss://…/ws?table={id}`. Plain JSON frames, no
`permessage-deflate` — at ~150 bytes/frame compression overhead exceeds the savings and adds
per-frame CPU to every connection. Plain HTTP handles what isn't live play: table listing and
creation (§10) and `/healthz`.

**Auth:** guest-only ([architecture.md §2.1](architecture.md),
[ADR 0001](decisions/0001-guest-only-identity.md)). A player picks a display name client-side,
persisted in `localStorage`, and sends it once on `join` (§2). `hello.seat` only ever means
"reclaim an already-bound seat"; the server already has the name from that seat's `join`.
**Seat possession**, unlike seat/name choice, *is* verified: `join`'s `ack` carries a one-time
`reconnect_secret`, and every later `hello{seat, secret}` must present it back (§5).

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

| Field | Meaning |
| --- | --- |
| `v` | protocol version; mismatch → `error{code:"version"}`, then close |
| `t` | message type |
| `seq` | server→client, **per-seat** (and per-spectator-session): dense and gapless within the stream sent to *that recipient*, not per table. What one player is or isn't offered (e.g. a `claim_offer`) never shows up as a gap for anyone else (§5, §7). The table's internal `event_id` never goes on the wire and is not what `last_seq` compares against |
| `id` | client→server idempotency key (below) |
| `ts` | server clock, ms |
| `d` | payload |

### Idempotency

- **Scope:** per seat binding, not per socket — a new socket resuming a seat via `hello{last_seq}`
  inherits the seat's id history (§5).
- **Retention:** the last 256 ids per seat, LRU-evicted. Not persisted across a server restart.
- **Same `id`, identical payload** (a genuine retry): not reapplied; the original `ack` is re-sent.
- **Same `id`, different payload** (client bug): rejected — `ack{id, ok:false,
  error:"id_conflict"}` — and neither payload is applied as the other.
- **`join` is the exception:** the cache lives on the seat binding `join` itself creates, so a
  `join` isn't deduplicated by `id` — it's answered directly (`seat_taken`/`table_full`/success)
  every time.

## 2. Client → server (intents)

The client sends *intent*, never *state*: "discard tile #47", not "my hand is now X".

| `t` | payload | notes |
| --- | --- | --- |
| `hello` | `{last_seq?, client_version, seat?, secret?}` | first frame after connect. `seat` present + already bound → reconnect (§5), authenticated by `secret`; a missing or wrong one refuses the reclaim (`error{code:'bad_secret'}`). Omitted `seat` → no-op ahead of `join`. Never carries a name |
| `join` | `{seat?: 0-3, name?}` | request a seat; omit `seat` for "first open seat". `name` is the guest display name, set once here — trimmed, capped at 24 chars, defaulted to `"Guest N"` (1-indexed) when empty; never rejected (`app/table.py`'s `_normalize_name`) |
| `ready` | `{}` | lobby → start; only valid once seated |
| `start_with_bots` | `{}` | host only, before the table starts: bind every empty seat to a bot and deal once all seats are bound and ready. `error{code:'not_host'}` / `error{code:'already_started'}` otherwise |
| `hand_end_ack` | `{}` | dismiss the hand-end hold early ([architecture.md §3](architecture.md) "Hand-end hold") |
| `discard` | `{tile_id}` | must be in hand, must be your turn |
| `claim` | `{window_id, choice, tiles?}` | `choice`: `pass\|chow\|pung\|kong\|win`. `tiles` disambiguates a chow (e.g. 4-5 vs 5-6 for a 6). Priority: [rules.md §6](rules.md) |
| `declare` | `{kind, tiles}` | `concealed_kong \| added_kong \| win` on your own turn |
| `auto` | `{no_calls?, auto_pass_chow?}` | pre-arm toggles; the server treats a pre-arm as an instant PASS ([architecture.md §4](architecture.md)) |
| `ping` | `{t0}` | clock-offset measurement (§4) |

The server rejects anything outside the legal-action set it computed itself. Client-side legality
is a UI hint only.

### Seat assignment

`join` is the only way to occupy a seat. The server fills the first open seat unless `seat` is
given, in which case it rejects with `error{code:"seat_taken"}` if bound, or
`error{code:"table_full"}` if none are free. A successful `join` is confirmed by a broadcast
`seat_state{seat, status:"connected", name}` to every bound seat (this one included), so clients
rendering empty seats from their `state_sync` update live. A reconnecting player doesn't
re-`join` — `hello{last_seq, seat, secret}` reclaims directly (§5). Once all four seats are filled
the table waits for `ready` from each before dealing.

The first seat to `join` is the table's **host** (`Table.host_seat`, `state_sync.host_seat`) — the
only seat that may send `start_with_bots`.

### Connect-time query parameters

Table-*creation* choices are query parameters on the WS URL, not envelope messages. All are only
meaningful the first time a table id is created ("first creation wins",
[architecture.md §3](architecture.md)); `POST /tables` (§10) is the primary path for the same
choices.

| Param | Effect |
| --- | --- |
| `?ruleset=<preset_id>` | one of `mahjong_core.presets.RULESET_PRESETS` (default `hk_classic`) |
| `?ruleset=custom&rules=<json>` | a full `RuleSet.from_dict` body |
| `?practice=true` | seats 1-3 are bound to bots at construction |
| `?spectate=true` | connect as a spectator (below) |

Ruleset input is never rejected: an unknown preset id, malformed JSON, or a body failing
`RuleSet` validation falls back to `hk_classic` (`app/ws.py`'s `_resolve_ruleset`). The resolved
ruleset comes back on every `state_sync` as `ruleset` (full `RuleSet.to_dict()`) and
`ruleset_preset` (the matching preset id, or `null`).

**Spectating.** `?spectate=true` (`app/ws.py`'s `ws_endpoint`) gets a spectator-redacted
`state_sync` (`seat_view(state, None)`, [architecture.md §5](architecture.md)) on registration,
then every broadcast event and the public half of `turn`. A `join`/`hello{seat}` on the same
connection promotes it to a seat. A spectator session is never reconnectable (§5).

On a table with `spectators_see_hands` ([architecture.md §3](architecture.md)), spectators get the
open-hands view: `state_sync.hands` is every seat's concealed tiles and `draw`/`kong_replace` carry
`tile_id`. Spectators get no `deal`, so each new hand is
followed by a fresh `state_sync` to every spectator. Seats' own streams are unchanged (`hands` is
always `null` for a seat).

### Declining a claim on purpose

`auto` has no `auto_win` toggle. Declining a win is a real strategic choice under `min_faan`
rulesets — chasing a bigger hand, avoiding revealing information — and `PASS` covers it
([ml.md §1](ml.md)). A win-eligible claim always opens a real `claim_offer` and, like every other
claim, times out to PASS, not WIN.

## 3. Server → client (events)

Payload shapes match `server/app/protocol.py` (§6).

| `t` | payload | notes |
| --- | --- | --- |
| `state_sync` | full redacted snapshot (`app/views.py`'s `SeatView`, wire-serialized) | sent on join, reconnect-with-gap, and after any backpressure collapse (§9). Fields below |
| `hand_start` | `{hand_no, prevailing, dealer, seats, seed_commit?}` | `seats` is each seat's `seat_status` (`empty` is only reachable on a `require_ready=False` table built directly). `seed_commit`: see Fairness. Synthesized by `app/table.py` at the hand boundary — no backing engine `Event` |
| `deal` | `{your_hand: [tile_id…], counts: {seat: n}, flowers: [[code…]×4], wall_remaining}` | unicast per seat; synthesized, no backing `Event`. `flowers` is every seat's flowers revealed by the opening swap (public) |
| `flower_replace` | `{seat, flower, replacement?}` | `replacement` only for you. **Not emitted for the opening deal's flower swaps** — `new_game()`/`_deal_hand()` build state directly, not through `reduce()`, so there's no `Event`; those arrive in `deal.flowers`. Mid-hand reveals are emitted |
| `draw` | `{seat, tile_id?}` | `tile_id` **only** for the drawing player |
| `discard` | `{seat, tile_id, tile, pool_index}` | `pool_index` is computed by `Table` against its own post-event state — `redact_event` alone can't, since a discard claimed in the same `reduce()` call is already gone from the pool |
| `claim_offer` | `{window_id, options: [{kind, tiles?}...], deadline_ts}` | **unicast**, only to eligible seats. `options` always ends with `{kind:"pass"}`. Sent when the window's deadline is armed, so it always carries a real `deadline_ts` |
| `claim_resolved` | `{window_id, claim_kind, seat?, action_kind?}` | `claim_kind` is the window kind (`discard`\|`kong_rob`); `action_kind` is the winner's action (`claim_chow`\|`claim_pung`\|`claim_kong`\|`claim_win`\|`pass`). `seat`/`action_kind` are `null` when nobody's claim beat a Pass |
| `meld` | `{seat, meld_kind, tiles, from_seat?}` | every kind, `concealed_kong` included, carries real `tiles` to everyone (Redaction, below) |
| `kong_replace` | `{seat, tile_id?}` | `tile_id` only for the drawing player |
| `turn` | `{seat, phase, deadline_ts, legal?: [...]}` | `legal` unicast to the acting seat, one entry per legal `Action` (`mahjong_core.actions.action_to_dict`). `deadline_ts` is an enforced `TimerHeap` entry ([architecture.md §8](architecture.md) "Turn timeout") |
| `hand_end` | `{hand_no, outcome, winner?, win_type?, discarder?, faan?, faan_breakdown?, points?, payments?, revealed, winning_hand?, deadline_ts, fairness?}` | `fairness`: see Fairness. `outcome` is `win`\|`exhaustive_draw`. `winning_hand`/faan/points/payments are `null` until `revealed`. `faan_breakdown` keys are the Chinese pattern names (`mahjong_core.scoring.patterns.PATTERNS`). `deadline_ts` is the hand-end hold's deadline, identical on every seat's stream |
| `score` | `{totals: {seat: n}}` | broadcast alongside `hand_end`; absolute post-payment totals, not a delta |
| `game_end` | `{hand_no, scores}` | `hand_no` is the last hand played; `scores` are final absolute totals. Sent only after the final hand's hold resolves |
| `seat_state` | `{seat, status, name?}` | `status`: `connected\|disconnected\|autoplay\|bot`. Sent for every status change of a bound seat, including the empty→`connected` transition `join` causes. `name` is carried on every broadcast for that seat |
| `server_shutdown` | `{deadline_ts}` | broadcast once to every seat ever bound when a graceful-shutdown drain starts ([architecture.md §8.1](architecture.md)) |
| `ack` | `{id, ok, error?, reconnect_secret?}` | **sender-only**, never broadcast — it would leak another player's `id`. Acknowledges receipt/idempotency, not legality: `Table` still silently drops a well-formed but illegal command. `reconnect_secret` only on a successful `join` (§5). A `claim` `pass` naming a closed/superseded window is acked `ok:true` as a no-op (the client's auto-pass races the server's own timeout); any other choice on a stale window gets `ok:false, error:"illegal"` |
| `error` | `{code, message}` | |
| `pong` | `{t0, t1}` | |

**`state_sync` fields** beyond `SeatView`'s ([architecture.md §5](architecture.md)):

| Field | Meaning |
| --- | --- |
| `seat_status` | `connected\|disconnected\|autoplay\|bot\|empty` per seat. `empty` = nobody has joined that seat yet |
| `names` | each seat's resolved display name; `null` for an `empty` seat, a real string for any bound seat, human or bot |
| `host_seat` | the first seat to `join`, or `null` |
| `bot_levels` | each `bot` seat's tier (`T1`\|`T2`\|`T4`\|`ORACLE`, [bots.md §6](bots.md)), `null` for every other seat, `autoplay` included. Fixed for the table's life (bot seats are bound at construction). Defaults to `[]` |
| `hands` | every seat's concealed tiles for an open-hands spectator, `null` otherwise |
| `hand_history` | every completed hand, oldest first: `hand_end`'s fields plus `dealer`/`prevailing`/`winner_melds`. Lets a client with no earlier live stream (mid-game spectator, resync) render past hands. Defaults to `[]` |
| `ruleset` / `ruleset_preset` | the table's fixed `RuleSet.to_dict()` and matching preset id (or `null`) |
| `seed_commit` | the current hand's commit, `provable_fairness` tables only (see Fairness) |

### Fairness (optional, ruleset flag)

The PRNG is seeded once per **game** (`game_seed`). Revealing it at `hand_end` would let any
player recompute every remaining wall, so each hand uses a derived subseed:

```
hand_seed = SHA256(game_seed || hand_no)
```

- `hand_start.seed_commit = SHA256(hand_seed || nonce)` — published before any tile of that hand
  is dealt.
- `hand_end.fairness = {hand_seed, nonce}` — reveals only that hand's subseed, **never**
  `game_seed`. A player can recompute that one wall and check it against the commit.
- `state_sync.seed_commit` repeats the current hand's commit for a client that missed
  `hand_start`; `state_sync.hand_history[i].fairness` repeats each past hand's reveal.
- All of these exist only when `ruleset.provable_fairness` is set; the keys are omitted otherwise,
  not sent as nulls.
- Hex-encoded. `nonce` is 16 random bytes per hand, minted in `app/fairness.py` (never in the
  pure engine). `game_seed` is 63 random bits (`new_game_seed`; signed `BIGINT` columns), not a
  clock reading: a revealed `hand_seed` is a SHA-256 preimage target, and a guessable seed would let
  a player grind it and predict every later wall.
- **Checking a hand.** The client recomputes `SHA256(hand_seed || nonce)` against the commit it saw
  and shows the result on the hand-end panel (`FairnessBadge.svelte`; a hand known only from
  `hand_history` has no live commit to check against). To check the wall itself, run
  `uv run python tools/verify_fairness.py --commit … --hand-seed … --nonce …` from `server/`: it
  verifies the commit and prints the wall `hand_seed` shuffles to, front to back.
- **Limit:** this proves the server didn't change the wall *after* committing. It does not stop a
  malicious server from choosing `(seed, nonce)` adversarially *before* the commit
  ([architecture.md §9](architecture.md), [ADR 0005](decisions/0005-client-entropy-fairness.md)).

### Redaction

Two functions, used in different places ([architecture.md §5](architecture.md)):

- **`seat_view(state, seat | None) -> SeatView`** — full redacted snapshot. Used for `state_sync`,
  and by bots/ML, which consume the identical view a human would.
- **`redact_event(state, seat | None, event) -> dict`** — per-event wire redaction for every other
  outbound message. Takes the *current* `state`, which is why buffered events can't be
  re-redacted at replay time (§5).

`draw`, `claim_offer` and `turn.legal` are unicast or differ per seat; each logical event is
rendered through `redact_event` per recipient — never one frame broadcast with clients trusted to
ignore fields. An ineligible seat's stream simply has no `claim_offer` entry at all, not a redacted
stub — safe under per-seat `seq` (§1, §7).

Every `meld` is fully public, **concealed kong (暗槓)** included: HK play shows it, end tiles
face-down and the middle two face-up ([ADR 0023](decisions/0023-concealed-kong-public.md)). Showing the end tiles as backs is the client's
job (`web/src/lib/table/meld-face.ts`); the wire carries all four ids.

## 4. Timers

The server is the only clock that matters.

- Every prompt carries an absolute `deadline_ts` in **server** time. Never count down from a
  server-sent duration.
- The last ~1.5s of the countdown renders as "about to expire", not as exact
  (`web/src/lib/ui/timer-ring.ts`'s `computeRingTiming`).
- On expiry the server acts: tsumogiri on turn timeout, PASS on claim timeout, and emits the
  resulting events normally.
- **No clock-offset correction.** `ping`/`pong` exists, but the client never measures an offset,
  so `deadline_ts` is compared against local `Date.now()` — correct on a synced clock, off by the
  client's drift otherwise.

## 5. Reconnect and resync

```
client reconnects
   └─► hello { last_seq: 412, seat, secret }
         ├─ 412 == head of this seat's buffered stream   → nothing missed, resume live
         ├─ 412 in this seat's ring buffer (512)          → replay envelopes 413…N, then resume
         └─ too old / new session                          → state_sync (full redacted snapshot), then resume
```

The ring buffer lives on the `Table`: one `deque[Envelope]` (`maxlen=512`) **per seat** and per
active spectator session (`Table.ring`, keyed by seat number or spectator `session_id`), holding
*already-redacted* frames exactly as sent. Pre-redacting once at send time is the only correct
option — `redact_event` takes the current `state`, so re-redacting a buffered event against
later state would produce wrong, potentially leaky output. Cost: 512 frames × ~150 bytes × 4 seats
is a few hundred KB per table.

`last_seq` is compared against *that seat's own* stream; `event_id` plays no part.

The client applies events through one reducer, so live play and gap replay are one code path.

**Seat reclaim.** A `hello{last_seq, seat, secret}` where `seat` is already bound is that seat
reconnecting: `Table.reconnect()` checks `secret` against `SeatBinding.reconnect_secret`
(`secrets.compare_digest`) before rebinding, and only then does `Table.resume()` run the branch
above.

| Case | Result |
| --- | --- |
| `seat` never joined | `error{code:"no_such_seat"}` |
| bound seat, missing or wrong `secret` | `error{code:"bad_secret"}`; the current holder keeps the seat |
| bound seat, correct `secret` | rebind, then resume |

**Spectators are never reconnectable.** There is no `hello{seat}` equivalent for "the same
spectator again" — no seat, no `SeatBinding`, and a spectator's `session_id` isn't something a
client can present back. `unregister_spectator` drops its ring/seq entry when the connection
closes; reconnecting is a brand-new spectator session with a fresh `state_sync`.

**A mid-claim-window disconnect forfeits the offer** ([architecture.md §8](architecture.md),
[ADR 0004](decisions/0004-claim-forfeit-on-disconnect.md)), so a reconnect never has anything
claim-shaped to resolve.

## 6. Schema generation

Pydantic v2 models in `server/app/protocol.py` are the single source of truth.

```
protocol.py  ──(server/tools/gen_protocol.py: a small custom emitter walking
                the pydantic model graph)──►  web/src/lib/net/protocol.d.ts
```

**Why not JSON Schema → TS.** Pydantic exports a tagged union as `$defs` + `oneOf` +
`discriminator`, but generic JSON-Schema→TS generators (`json-schema-to-typescript` included)
don't reliably turn that into a *narrowable* discriminated union: `const` tags widen to `string`,
`additionalProperties` adds index signatures that swallow narrowing, and the generic envelope
(`d: {}`, shape depending on `t`) isn't expressible in JSON Schema at all. That silently voids the
one guarantee this pipeline exists for — TypeScript flagging an unhandled event at compile time.

- `gen_protocol.py` discovers message types from `protocol.py`'s `ClientMessage` /
  `ServerMessage` / `AnyMessage` unions via `typing.get_args`; a new Envelope subclass added to
  those unions is picked up without touching the generator.
- Each message `t` becomes a distinct interface with a literal `t` field. `Error` is emitted as
  `ErrorEvent` so it doesn't shadow the global `Error`.
- `ClientMessage` and `ServerEvent` are unioned per direction (§2 vs §3); `AnyMessage` unions both.
  `ws.py` validates incoming frames against the full union, so a wrong-direction message (e.g. a
  client sending `pong`) parses and is ignored rather than rejected as malformed.
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

  Being regenerated alongside the types, it can only fail to compile if `ServerEvent` stopped
  being a narrowable union (e.g. `t` regressed from a literal to `string`).
  `web/src/lib/net/reducer.ts` uses the same pattern in production code.
- `shared/protocol.schema.json` is still emitted (`TypeAdapter(AnyMessage).json_schema()`) as an
  informational artifact; nothing generates TS from it.

`make proto` regenerates both; the `proto-check` CI job fails if the committed output is stale
([infra.md §9](infra.md)). §10's HTTP payloads are typed by hand, not generated.

## 7. Example exchange

Alice (seat 0) discards, Bob (seat 1) pungs. `seq` is per-seat, so each recipient has its own
dense, gapless stream. `turn` and `discard` are broadcast (redacted per seat where needed);
`claim_offer` goes only to the eligible seat; `ack` only to the sender. Table-internal `event_id`s
(never on the wire) are noted in comments.

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

{"v":1,"t":"claim_resolved","seq":45,
  "d":{"window_id":"w-204","claim_kind":"discard","seat":1,"action_kind":"claim_pung"}}
  // ^ event_id 102: window closed early, Bob was the only eligible seat

{"v":1,"t":"meld","seq":46,"d":{"seat":1,"meld_kind":"pung","tiles":[31,88,47],"from_seat":0}}
  // ^ event_id 103: pung is fully public, full tiles to everyone

{"v":1,"t":"turn","seq":47,"d":{"seat":1,"phase":"AWAIT_ACTION","deadline_ts":1757865458000,
  "legal":[{"kind":"discard","tile_id":3},{"kind":"discard","tile_id":9},"..."]}}
  // ^ event_id 104: Bob is now acting, so he gets "legal" -- one entry per legal Action

// ── Carol's stream (seat 2) — never eligible; her stream is still dense, no gap ──
{"v":1,"t":"turn","seq":41,"d":{"seat":0,"phase":"AWAIT_ACTION","deadline_ts":1757865447000}}
{"v":1,"t":"discard","seq":42,"d":{"seat":0,"tile_id":47,"tile":"5s","pool_index":11}}
  // ^ event_id 101 (claim_offer to Bob) never appears in Carol's stream — not a gap, because
  //   Carol's seq only counts frames Carol actually receives
{"v":1,"t":"claim_resolved","seq":43,
  "d":{"window_id":"w-204","claim_kind":"discard","seat":1,"action_kind":"claim_pung"}}
{"v":1,"t":"meld","seq":44,"d":{"seat":1,"meld_kind":"pung","tiles":[31,88,47],"from_seat":0}}
{"v":1,"t":"turn","seq":45,"d":{"seat":1,"phase":"AWAIT_ACTION","deadline_ts":1757865458000}}
  // ^ no "legal" — Carol isn't acting
```

**Why per-seat `seq`.** With a per-table `seq`, Carol would observe 42 → 44 (skipping Bob's
unicast `claim_offer`), be forced to resync on every claim window, and learn from the gap itself
that a claim was offered — defeating redaction.

## 8. Liveness

Disconnect is detected only by the WS connection closing (`app/ws.py`'s `Session`). There is no
heartbeat: a mobile browser's socket can sit open for minutes after the network dies without
firing `onclose`, and nothing catches that case. The intended heartbeat design is
[ADR 0009](decisions/0009-liveness-heartbeat.md).

**Client reconnect backoff:** on an unexpected close, the client reconnects with exponential
backoff and jitter — `min(250ms * 2^attempt, 10s)` ± 20% (`web/src/lib/net/socket.ts`).

## 9. Backpressure

The Session's outbound queue per connection is **bounded** (`app/outbox.py`'s `BoundedOutbox`,
default 64 frames, [architecture.md §3](architecture.md)). An unbounded queue behind a stalled
TCP connection is a memory leak that scales with how long the peer stays half-open.

When the queue is full:

- Drop the oldest *non-critical* frame first — `draw`, `discard`, `turn` and similar deltas are
  superseded by a snapshot anyway. Keep `ack`/`error`.
- The instant anything is dropped, clear the queue and enqueue a single `state_sync`. The client's
  reducer treats `state_sync` as an idempotent full replace (§5), so this reuses the
  reconnect-with-gap path rather than adding a second one.
- If the queue is still full after that, the socket is dead: the Session closes it, the table
  marks the seat `DISCONNECTED`, and normal grace-period/bot-takeover applies
  ([architecture.md §8](architecture.md)).

## 10. HTTP: table listing and creation

Plain HTTP in `app/main.py`, outside the WS envelope and not generated by `make proto`
(`web/src/lib/net/lobby.ts`/`create-table.ts` type these by hand against `TableList`/
`CreateTableResponse`). Cross-origin requests are allowed only for `CORS_ORIGINS`
(comma-separated); `POST` also needs `Content-Type` in `allow_headers`, since a JSON body isn't a
CORS-safelisted content type.

```
GET /tables
{"tables": [{"id": "ABC123", "status": "open" | "in_progress", "hand_no": 1,
             "seats": [{"status": "connected", "name": "Alice"}, {"status": "empty", "name": null}, …]}]}
```

| Rule | Why |
| --- | --- |
| Only still-running tables (`TableRegistry.is_running`) | finished `Table`s are never evicted from the registry |
| Only tables with at least one non-bot seat bound | every `/table/<id>` visit creates a table, and a practice table is bot-only until its owner joins |
| …except the showcase table (`BOTS`), always listed | it's bot-only by design ([architecture.md §3](architecture.md)) |
| `open` = not started and some seat `empty`; otherwise `in_progress` | an `in_progress` table can only be spectated |

`seats[i].status` uses the `state_sync.seat_status` vocabulary.

```
POST /tables
{"ruleset"?: "hk_classic", "rules"?: {…RuleSet.to_dict() shape…}, "practice"?: false,
 "bot_tiers"?: {"1": "T1"|"T2"|"T4"|"ORACLE", "2": …, "3": …}}
->
{"table_id": "ABC123", "ruleset_preset": "hk_classic" | null, "ruleset": {…RuleSet.to_dict()…}}
```

- Resolves the ruleset and mints a fresh six-character id together (`_generate_table_id`:
  look-alike-free alphabet, `secrets.choice`, collision-checked against the registry), so a client
  configuring custom rules navigates straight to `/table/<table_id>`.
- `ruleset`/`rules`/`practice` have the same semantics as the WS query params (§2) — both call
  `mahjong_core.presets.resolve_ruleset` and fall back to `hk_classic` on bad input.
- `bot_tiers` is practice mode's per-seat difficulty ([bots.md §6](bots.md)): seat keys `1`-`3`
  only (seat `0` is the human), values `T1`/`T2`/`T4`/`ORACLE` (`_PRACTICE_BOT_TIERS`; `T0` is
  never selectable). A plain string field, not in `shared/protocol.schema.json`: adding a tier
  needs no `make proto`. An out-of-range seat or unknown tier is dropped and that seat falls back to
  `DEFAULT_BOT_TIER` (`T2`). Ignored when `practice` is false.
- A table created via `POST /tables` and one auto-created by a direct WS connect behave
  identically; whichever happens first for an id sticks.
