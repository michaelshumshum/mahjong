# 02 — Wire protocol

Transport: one WebSocket per client at `wss://…/ws?table={id}`. Plain JSON frames — no
`permessage-deflate`: at ~150 bytes/frame it typically *grows* the payload (compression overhead
exceeds the savings) and adds per-frame CPU to every connection for no benefit at this message
size. REST (`/api/*`) handles everything that isn't live play: table listing, replay download,
leaderboard.

**Auth:** guest-only, by design. No account, no password, no email, no REST auth endpoint
(`docs/00-architecture.md §2.1`). A player picks a display name client-side, persisted in
`localStorage` so it survives a reload, and sends it once as a plain field on `join` (§2's
table) — not `hello`: `hello.seat` only ever means "reclaim an already-bound seat", and the
server already has the name from that seat's original `join` (`JoinPayload.name`). Seat identity
is permanently client-asserted, not verified against anything — see §5's reconnect note.

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
  stream sent to *that recipient*, not per table. Two players never share a seq space, so what
  one player is or isn't offered (e.g. a `claim_offer` someone else didn't get) never shows up
  as a gap for anyone else — see §5 for the resync algorithm and §7 for a worked example. The
  table separately keeps an internal monotonic `event_id` for logging and replay ordering; it
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
- **`join` is the one exception:** the cache lives on the seat binding `join` itself creates, so
  there's no binding yet to scope a `join` retry to. A `join` isn't deduplicated by `id` — it's
  answered directly (`seat_taken`/`table_full`/success) every time, same as before this section's
  id contract existed.

## 2. Client → server (intents)

The client sends *intent*, never *state*: "discard tile #47", not "my hand is now X".

| `t` | payload | notes |
| --- | --- | --- |
| `hello` | `{last_seq?, client_version, seat?}` | first frame after connect. `seat` present + already bound -> reconnect (§5); omitted -> the M0 no-op ahead of `join`. No `name` field — the server already has it from that seat's original `join`, so a reconnect never resends it |
| `join` | `{seat?: 0-3, name?}` | request a seat; omit `seat` for "first open seat". `name` (M5) is a client-chosen guest display name, set once here — trimmed, capped at 24 chars, defaulted to `"Guest N"` (1-indexed) when empty/omitted; never hard-rejected (`server/app/table.py`'s `_normalize_name`). A `hello` reconnect never resends it |
| `ready` | `{}` | lobby → start; only valid once seated |
| `hand_end_ack` | `{}` | dismiss the hand-end hold early ([00-architecture.md §3](00-architecture.md) "Hand-end hold") — every hand end (win or exhaustive draw) holds the table at `HAND_OVER` until all four seats send this or `ruleset.hand_end_seconds` elapses, whichever first |
| `discard` | `{tile_id}` | must be in hand, must be your turn |
| `claim` | `{window_id, choice, tiles?}` | `choice`: `pass\|chow\|pung\|kong\|win`. `tiles` disambiguates a chow (e.g. 4-5 vs 5-6 for a 6). Priority among competing claims is resolved per [01-rules-spec.md §6](01-rules-spec.md) — not restated here. |
| `declare` | `{kind, tiles}` | `concealed_kong \| added_kong \| win` on your own turn |
| `auto` | `{no_calls?, auto_pass_chow?}` | pre-arm toggles; server treats a pre-arm as an instant PASS ([00-architecture.md §4](00-architecture.md)) |
| `ping` | `{t0}` | clock offset measurement; also doubles as the liveness heartbeat (§8) |

The server rejects anything outside the legal-action set it computed itself. Client-side
legality is a UI hint only.

### Seat assignment

`join` is the only way to occupy a seat; a socket that never sends it is a spectator. The server
fills seats first-come-first-served among open ones unless `seat` is given, in which case it's
rejected (`error{code:"seat_taken"}`) if that seat is already bound, or `error{code:"table_full"}`
if none are free. A successful `join` is confirmed by a broadcast `seat_state{seat,
status:"connected", name}` — sent to every already-bound seat (this one included), so a client
rendering the empty seats it saw in its own `state_sync` (§3) updates live as the rest of the
table fills in, not only on its next full resync; `name` is this seat's resolved guest display
name (M5, above), so an already-connected seat learns a new player's chosen name the moment they
join, not just on its next `state_sync`. `join` is for first entry only — a reconnecting player doesn't re-`join`;
`hello{last_seq}` on an already-bound seat reclaims it directly (§5). Once all four seats are
filled the table waits for `ready` from each before dealing.

**Spectating** is triggered by an explicit `?spectate=true` query parameter on the WS URL
(`app/ws.py`'s `ws_endpoint`, mirroring `?practice=true`) — not a new envelope message. A passive
"never sent `join`" trigger would race the `hello{client_version}`-then-`join` handshake every
real client uses. A `?spectate=true` connection gets a spectator-redacted `state_sync`
(`seat_view(state, None)`, [00-architecture.md §5](00-architecture.md)) the moment it's
registered, then every broadcast event and the public half of `turn`; a `join`/`hello{seat}` from
that same connection promotes it to a seat. See [00-architecture.md §3](00-architecture.md) for
why a spectator session, unlike a seat, is never reconnectable.

### Declining a claim on purpose

`auto` has no `auto_win` toggle. Declining a winning claim is a real strategic choice under
`min_faan` rulesets — chasing a bigger hand, avoiding revealing information, waiting for a
better payout — and is called out explicitly in [06-ml.md §1](06-ml.md) ("`PASS` covers
declining a win"). A pre-arm that silently auto-accepted every offered win would remove that
choice. So a win-eligible claim is never auto-resolved by a pre-arm: it always opens a real
`claim_offer` to the eligible seat(s), and — consistent with every other claim — times out to
PASS, not to WIN, if the player doesn't respond.

## 3. Server → client (events)

Payload shapes below match `server/app/protocol.py` (§6) exactly.

| `t` | payload | notes |
| --- | --- | --- |
| `state_sync` | full redacted snapshot (`app/views.py`'s `SeatView`, wire-serialized) | sent on join, reconnect-with-gap, and after any resync (§9); `d.seat_status` is `connected\|disconnected\|autoplay\|empty` per seat (`bot` is reserved, unused) — `empty` means nobody has ever joined that seat yet, real from the moment a client can see `state_sync` before all four seats join (a lobby/"waiting for the rest of the table" screen). `d.names` (M5) is each seat's resolved guest display name, same indexing — `null` for an `empty` seat, always a real non-empty string for any bound seat, human or bot |
| `hand_start` | `{hand_no, prevailing, dealer, seats, seed_commit?}` | `seats` is each seat's `seat_status` (same vocabulary as `state_sync` above, `empty` included — unreachable for a `require_ready=True` table, where dealing gates on all four seats bound, but a direct-construction `require_ready=False` table can reach hand 2+ with seats that were never joined at all); see Fairness below for `seed_commit`. No backing engine `Event` — synthesized by `app/table.py` at the hand boundary (ready-triggered for hand 1, chained off `start_next_hand()` after) |
| `deal` | `{your_hand: [tile_id…], counts: {seat: n}, wall_remaining}` | unicast per seat; same "no backing `Event`" note as `hand_start` |
| `flower_replace` | `{seat, flower, replacement?}` | `replacement` only for you. **Not yet emitted for the opening deal's flower swaps** — `new_game()`/`_deal_hand()` build state directly, not through `reduce()`, so there's no `Event` to redact for those; mid-hand flower reveals (a normal draw) go through `reduce()` normally and *are* emitted |
| `draw` | `{seat, tile_id?}` | `tile_id` present **only** for the drawing player |
| `discard` | `{seat, tile_id, tile, pool_index}` | |
| `claim_offer` | `{window_id, options: [{kind, tiles?}...], deadline_ts}` | **unicast**, only to eligible seats. `options` always ends with `{kind:"pass"}`. No backing `Event` (same synthesis note) — sent by `app/table.py` the moment a window's deadline is armed, so it always carries a real `deadline_ts` |
| `claim_resolved` | `{window_id, claim_kind, seat?, action_kind?}` | `claim_kind` is the window kind (`discard`\|`kong_rob`), not the winning meld kind — that's `action_kind` (`claim_chow`\|`claim_pung`\|`claim_kong`\|`claim_win`\|`pass`). v1 is single-winner; `seat`/`action_kind` are both `null` when nobody's claim beat a Pass (一炮多響 deferred, D16) |
| `meld` | `{seat, meld_kind, tiles, from_seat?}` | except `concealed_kong`, which has a redacted per-seat form: `{seat, meld_kind:"concealed_kong", tiles?, count?}` (see Redaction below) |
| `kong_replace` | `{seat, tile_id?}` | |
| `turn` | `{seat, phase, deadline_ts, legal?: [...]}` | `legal` unicast to the acting seat. No backing `Event` (same synthesis note); `deadline_ts` is a real, enforced `TimerHeap` entry (00-architecture.md §8 "Turn timeout", the turn-timeout sub-task) — on expiry the table tsumogiris the drawn tile (or discards the lowest-`tile_id` concealed tile after a claimed pung/chow with nothing drawn) and auto-passes any pending claims (structurally never any, in `AWAIT_ACTION`), same enforcement the claim-window deadline (`claim_offer.deadline_ts` above) already had |
| `hand_end` | `{hand_no, outcome, winner?, win_type?, discarder?, faan?, faan_breakdown?, points?, payments?, revealed, winning_hand?, deadline_ts}` | `outcome` is `win`\|`exhaustive_draw`. `winning_hand`/faan/points/payments are `null` until `revealed` (self-draw/flowers immediately, a claimed win only once `HAND_OVER`). `deadline_ts` is the hand-end hold's deadline ([00-architecture.md §3](00-architecture.md) "Hand-end hold") — the same value on every seat's stream, held open until all four `hand_end_ack` or this elapses |
| `score` | `{totals: {seat: n}}` | broadcast alongside `hand_end` (absolute post-payment totals, not a delta) — no backing `Event` of its own |
| `game_end` | `{hand_no, scores}` | `hand_no` is the last hand actually played; `scores` are final absolute per-seat totals |
| `seat_state` | `{seat, status: connected\|disconnected\|autoplay\|bot, name?}` | `connected`/`disconnected`/`autoplay` transitions are real as of M3 sub-task 6 (`app/table.py`'s `mark_disconnected`/`reconnect`/the disconnect-grace timer); `bot` is unused — every seat here started as a human `join`, so there's no seat that was *never* human to label `bot` instead of `autoplay`. `empty` (`state_sync`/`hand_start` above) never appears here either — a seat only ever gets a `seat_state` frame once it's bound (`join`'s own broadcast is what announces the empty→`connected` transition live to every already-bound seat), and nothing ever unbinds a seat afterward. `name` (M5) is this seat's resolved guest display name, carried on every `seat_state` broadcast for that seat, not just its first |
| `server_shutdown` | `{deadline_ts}` | broadcast once, to every seat ever bound in the table, when a graceful-shutdown drain starts (`00-architecture.md §8.1`); `deadline_ts` is the shared grace-window deadline every table in the drain gets. Clients show a "reconnect shortly" banner instead of reading the eventual dropped socket as an error |
| `ack` | `{id, ok, error?}` | **sender-only**, never broadcast: it would leak another player's client-chosen `id`. Acknowledges receipt/idempotency outcome, not eventual game legality — `Table` silently drops a well-formed but currently-illegal command the same as before this existed |
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

**`discard.pool_index` isn't implemented by `redact_event` yet.** It isn't derivable from the
`state` `redact_event(state, seat, event)` receives in general: if the discard is claimed later
in the *same* `reduce()` call, the claiming seat's discard-pool entry is removed again by the
time `state` reaches the redaction layer (`engine._apply_claim_response`), so recomputing it
from final state would be wrong for exactly the discards that most need a correct wire form.
The Table actor (a later M3 sub-task) sees each event against its own intermediate state and can
compute this there — `redact_event` alone cannot, by its own `(state, event)` contract.

## 4. Timers

The server is the only clock that matters.

- Every prompt carries an absolute `deadline_ts` in **server** time. Never count down from a
  server-sent duration.
- Render the last ~1.5s of the bar as "about to expire", not as exact — real
  (`web/src/lib/ui/timer-ring.ts`'s `computeRingTiming`).
- On expiry the server acts: tsumogiri on turn timeout, PASS on claim timeout. It emits the
  resulting event normally.
- **Not implemented:** offset correction. `ping`/`pong` exists (§8) but the client never calls
  it, so `deadline_ts` is compared against local `Date.now()` with no clock-skew correction —
  fine on a synced clock, wrong by however far the client's clock actually drifts otherwise.

## 5. Reconnect and resync

```
client reconnects
   └─► hello { last_seq: 412 }
         ├─ 412 == head of this seat's buffered stream   → nothing missed, resume live
         ├─ 412 in this seat's ring buffer (512)          → replay envelopes 413…N, then resume
         └─ too old / new session                          → state_sync (full redacted snapshot), then resume
```

The ring buffer lives on the `Table`: one `deque[Envelope]` (`maxlen=512`) **per seat** (and per
active spectator session — built, "Spectating" sub-task: `Table.ring` is keyed by seat number
*or* a spectator's `session_id` string, `app/table.py`'s `register_spectator`/
`publish_to_spectator`), holding *already-redacted* frames exactly as sent. **A spectator session
is deliberately never reconnectable, unlike a seat** — there is nothing shaped like `hello{seat}`
for "the same spectator, again" (no seat number, no `SeatBinding` to reclaim, and a spectator's
own `session_id` isn't a value a client could present back on a fresh connection), so the
three-way branch above only ever applies to a seat. A spectator's ring/seq entry is dropped
outright the moment its connection closes (`unregister_spectator`) rather than kept for a future
reconnect the way a seat's is; reconnecting later is, correctly, a brand-new spectator session
with a fresh `state_sync`, not a resumed one. That's the only implementable option —
`redact_event(state, seat, event)` takes the current `state`, and by
replay time `state` has moved on to wherever the game is now, so re-redacting a buffered event
against today's state would produce wrong, and potentially leaky, output. Pre-redacting once at
send time and buffering the result is correct and cheap enough: 512 frames × ~150 bytes × 4
seats is a few hundred KB per table.

`last_seq` in `hello` is compared against *that seat's own* buffered stream, per D1 — the table's
internal `event_id` (used only for server-side logging and replay-viewer ordering) never appears
on the wire and plays no part in this comparison.

The client applies events through a reducer, so live play, gap replay, and the replay viewer
are one code path.

`hello.seat` (§2's table) is how the server knows which seat is reconnecting: a
`hello{last_seq, seat}` where `seat` is already bound is treated as that seat reconnecting —
`Table.reconnect()` rebinds the live connection, `Table.resume()` runs the branch above. A `seat`
that was never joined gets `error{code:"no_such_seat"}`. `hello.seat` is trusted at face value,
permanently — there is no ticket or credential anywhere in this design to check it against (the
Auth note above); a malicious client can claim any seat.

**Mid-claim-window disconnect forfeits, not re-arms** (00-architecture.md §8). A seat that
disconnects while it holds a live, unresolved claim offer forfeits it immediately (`Pass`),
rather than a reconnect later re-arming a fresh window for it — `state_sync`'s `claim_options`
(§3) carries no `window_id`, so a reconnect mid-window had nothing to actually hand a client back
to act on even when the server was still nominally waiting. By the time any reconnect happens,
there is nothing claim-shaped left for it to resolve; `hello.seat` above is ordinary replay/
`state_sync`, same as any other reconnect.

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

Wired into the build (`make proto`); `proto-check` (`git diff --exit-code` after regenerating) is
the CI gate for "fails if the generated TS is stale" — see `docs/07-infra.md §9`.

## 7. Example exchange

Same logical sequence as before (Alice discards, Bob pungs), but `seq` is per-seat (D1), so
there is no single wire trace — each recipient has its own dense, gapless stream. The `turn` and
`discard` events are broadcast (redacted per seat where needed); `claim_offer` goes only to the
eligible seat; `ack` goes only to the sender. Below, table-internal `event_id`s (never on the
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

{"v":1,"t":"claim_resolved","seq":45,
  "d":{"window_id":"w-204","claim_kind":"discard","seat":1,"action_kind":"claim_pung"}}
  // ^ event_id 102: window closed early, Bob was the only eligible seat

{"v":1,"t":"meld","seq":46,"d":{"seat":1,"meld_kind":"pung","tiles":[31,88,47],"from_seat":0}}
  // ^ event_id 103: pung is fully public, full tiles to everyone

{"v":1,"t":"turn","seq":47,"d":{"seat":1,"phase":"AWAIT_ACTION","deadline_ts":1757865458000,
  "legal":[{"kind":"discard","tile_id":3},{"kind":"discard","tile_id":9},"..."]}}
  // ^ event_id 104: Bob is now acting, so he gets "legal" -- one entry per legal Action
  //   (mahjong_core.actions.action_to_dict), not one entry listing every tile at once

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

Compare: under the old per-table `seq`, Carol would have observed 90 → 92 (skipping Bob's
unicast `claim_offer` at 91) and been forced to full-resync on every claim window — and the
existence of the gap itself would have told her a claim was offered, defeating redaction (§3).
Per-seat `seq` makes that structurally impossible: Carol's stream was never going to contain
event 101, so there's nothing for her to detect.

## 8. Liveness

**Only the `client reconnect backoff` bullet below is implemented.** The rest of this section
describes the intended design for detecting a dead-but-not-closed socket; none of it has a
driver yet. Today, disconnect is detected only by the WS connection actually closing
(`app/ws.py`'s `Session`) — a mobile browser's WebSocket can sit open for minutes after the
network actually dies without firing `onclose` (TCP keepalive defaults to minutes-to-hours,
carrier NATs silently drop idle mappings), and nothing here currently catches that case.

- **Client → server:** the client would send `ping` at least every `heartbeat_interval` (15s)
  regardless of whether it needs a fresh offset reading. `ping`/`pong` (§4) exists and works for
  on-demand clock-offset measurement today; the client just never calls it on a timer.
- **Server → client:** if no frame had gone out to a client in `heartbeat_interval`, the server
  would send an unsolicited `pong{t0: null, t1: now}` as a keepalive.
- **Dead-socket detection:** if the server hadn't heard anything from a connection in
  `heartbeat_timeout` (45s), it would treat the socket as dead: close it, mark the seat
  `DISCONNECTED`, start the normal grace-period/bot-takeover clock
  ([00-architecture.md §8](00-architecture.md)).
- **Client reconnect backoff (real):** on an unexpected close, the client reconnects with
  exponential backoff and jitter — `min(250ms * 2^attempt, 10s)` ± 20%
  (`web/src/lib/net/socket.ts`).

## 9. Backpressure

The Session pumps an outbound queue per connection ([00-architecture.md §2](00-architecture.md));
that queue is **bounded** (`app/outbox.py`'s `BoundedOutbox`, default 64 frames), not left to
grow — an unbounded queue behind a stalled TCP connection (dead peer, congested mobile network)
is a memory leak that scales with however long the peer stays half-open.

Policy when the queue is full:

- Drop the oldest *non-critical* queued frame first — `draw`, `discard`, `turn`, and similar
  state-deltas are superseded by a fresh snapshot anyway. Keep `ack`/`error` if still queued.
- The instant anything is dropped, stop trying to catch the stream up: clear the queue and
  enqueue a single `state_sync` instead. The client's reducer already treats `state_sync` as an
  idempotent full replace (§5), so a torn-out middle of the stream is harmless once the snapshot
  lands — this reuses the reconnect-with-gap code path rather than adding a second one.
- If the queue is still full after that (socket is dead, not just slow), the Session closes the
  connection; the table marks the seat `DISCONNECTED` and normal grace-period/bot-takeover
  ([00-architecture.md §8](00-architecture.md)) applies.
