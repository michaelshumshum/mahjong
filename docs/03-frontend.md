# 03 — Frontend

Answers [05-roadmap.md §5](05-roadmap.md) open question #1 (rendering): **DOM/CSS, not PixiJS.**
~150 static, axis-aligned, rectangular tiles with no tick loop doesn't need a canvas renderer.

## 1. The split

```
┌─────────────────────────────────────────────────────────────┐
│ SvelteKit app (all DOM/CSS — no canvas)                      │
│                                                                │
│  Routes                │  Table route                        │
│  /            lobby    │  ┌──────────────────────────────┐   │
│  /tables      browser  │  │ table surface (DOM/CSS)       │   │
│  /demo        dev demos│  │   felt, wall, 4 hands, melds, │   │
│  /table/[id]  game     │  │   discard pools, dice, hints  │   │
│  /replay/[id] viewer   │  └──────────────────────────────┘   │
│  /profile     stats    │  overlay (Svelte):                  │
│                        │   claim buttons, timer ring,         │
│                        │   faan breakdown, score sheet,       │
│                        │   settings, toasts                   │
│                                                                │
│  lib/net/     ws client, seq tracking, reconnect, reducer     │
│  lib/game/    client state store ($state runes)                │
│  lib/table/   table-surface Svelte components (DOM)            │
└─────────────────────────────────────────────────────────────┘
```

**One-way data flow.** Server events → reducer → `$state` store → components read it. Components
own presentation state only (pending/lifted/hover classes, CSS transition state), never game
truth. Input goes `DOM event → intent → WebSocket`, never `DOM → local mutation` — the one
deliberate exception is a *pending visual* state, not a state mutation (§5).

No tick loop: state changes are discrete server events. All motion is CSS transitions/animations
driven by class/attribute changes, never a JS ticker or a tween library.

## 2. Rendering

**No canvas.** Absolutely-positioned elements with `transform` are GPU-composited — same cost
class as a single Pixi draw call, without owning the pipeline. That buys, for free:

- Hit-testing, focus, `:hover`, tab order, live regions, media queries,
  `prefers-reduced-motion`, CJK text flow, and devtools inspection — all platform, not hand-rolled.
- No async renderer bootstrap: the page hydrates like any other SvelteKit route. There's no
  `Application.init()` step gating first paint.
- The 2.5D look is `perspective` + `rotateX` on the table container (§3), not pre-rendered art.

Known costs:

- Animated paths must stay `transform`/`opacity`-only to avoid layout thrash across ~150 elements
  moving at once (e.g. `hand_start` reshuffling every seat).
- DOM order still matters for keyboard tab order and stacking; keep it stable so Svelte's keyed
  `{#each}` (§4, §6) reconciles elements instead of tearing down and remounting them.

## 3. Scene layout and responsive layout

No fixed logical canvas, no letterbox. A `1600×1000` letterboxed scene and a responsive 4-seat
layout are mutually exclusive — 16:10 letterboxed onto a 390×844 phone (~9:19.5) leaves the table
at ~35% of the screen with huge bars, while [05-roadmap.md](05-roadmap.md) separately lists "13
tiles on a 390px screen" as a risk to solve. With DOM, real responsive layout is free; use it
instead of a scaled logical space.

Seats are always rendered relative to **your** seat, at the bottom. Wall count and prevailing
wind live in the page header, not the table surface — dealer/turn aren't reproduced there since
the dealer badge and the current-turn seat's outline (`.seat-region--turn`) already say both.
No "turn" text badge: a text label that mounts/unmounts every turn change shifted the seat
header's `margin-inline-start: auto`-positioned score, so the indicator is a non-layout-affecting
outline instead. Desktop/tablet (≥768px):

```
  header: table/scenario · wall count · prevailing wind (東南西北) · chrome toggles

                    ┌─────────── opponent (across) ───────────┐
                    │       13 backs · melds · flowers        │
  ┌─────────┐       ├─────────────────────────────────────────┤       ┌─────────┐
  │ left    │       │     across's discard pool (top)         │       │ right   │
  │ opponent│       │                                          │       │ opponent│
  │ vertical│       │  left's   ┌──────────────┐   right's    │       │ vertical│
  │  strip  │       │  discards │   (empty —   │   discards   │       │  strip  │
  │         │       │  (rotated)│   wall/dice  │   (rotated)  │       │         │
  │         │       │           │   go here    │              │       │         │
  │         │       │           │   IRL)       │              │       │         │
  │         │       │           └──────────────┘              │       │         │
  │         │       │        YOUR discard pool (bottom)        │       │         │
  └─────────┘       ├─────────────────────────────────────────┤       └─────────┘
                    │  YOUR HAND: 13 faces, sorted, +drawn    │
                    │  tile held out at right, melds, flowers │
                    └─────────────────────────────────────────┘
```

Discard pool geometry: **all four in the centre** (`.table-center`), forming a box around the
middle of the table instead of each sitting at its own seat's edge — across on top, left/right
along the sides (rotated, below), self on the bottom, each still keyed to its own seat so "who
discarded this" stays legible without a shared/interleaved pool. Superseded from an earlier
**per-player-at-the-edge** layout (each opponent's pool below their own hand strip, resolving an
ASCII-vs-bullet conflict in an even earlier draft): edge placement put your own pool in an
easy-to-miss spot below your hand, in the same 6-column `1fr` grid that stretched a handful of
discards across the pool's full width, and left the centre area sitting on redundant text
(wall/prevailing/dealer/turn, moved to the header, dealer/turn dropped) once your own pool moved
out of it. Moving the other three in too gives the box shape a real table has, rather than only
half of it. Each pool keeps independent scroll/collapse behaviour on small screens (below).

CSS: `grid-template-areas` for the four seat regions + centre; `perspective` + `rotateX` on the
table container for the 2.5D tilt; `transform`/`opacity` only in animated paths. No global scale
factor — each region sizes to its own content via `clamp()`.

Left/right opponent hand strips run top-to-bottom via `writing-mode: vertical-lr`/`vertical-rl`,
not `transform: rotate()` on the strip itself — rotate repaints the box in place without resizing
the space its parent grid cell reserves for it, so a rotated strip's actual (post-rotation)
footprint can extend outside its grid area into whatever sits past its edge. `writing-mode`
reflows the flex axes instead, so the element's own width/height already reflect the vertical
footprint the grid cell needs to reserve. The individual tiles inside are rotated 90° to face the
table (the physically-correct read for a side seat): each `.mini-tile` keeps an unrotated box
already sized to the *post*-rotation (landscape) footprint, and only the tile face inside it is
absolutely-positioned and rotated — paint-only, so it never changes what the strip/grid measure.
Same avoid-rotating-the-sized-box principle as the strip-level decision above, just applied one
level deeper. The left/right discard pools in the centre box reuse the identical technique (an
unrotated `.discard-tile` box pre-sized to the landscape footprint, rotated face inside it) so
they read parallel to that seat's own hand rather than upright like the across/self pools.

Seat wind badges and the header's prevailing indicator render the wind as its Chinese character
(東/南/西/北), not the `E`/`S`/`W`/`N` letter `seatWind()` returns internally — a screen reader
gets the full English name via `aria-label`, since the glyph alone has no accessible name. The one
exception is the pre-game "You're seated as East" sentence (§"Join flow" note below): that's a
full English sentence read as a unit, where a bare glyph substituted into it would read as
unlabelled.

Below 768px (phone portrait — the roadmap's stated risk case):

- Opponent hands collapse to a thin overlapping-backs strip (count-only, no per-tile grid).
  Positional identity (§4) is still tracked, just rendered compactly.
- Each opponent's discard pool collapses to a horizontally-scrollable strip; full history stays
  in the DOM (a11y, §8) even when visually truncated.
- Your hand is pinned to the bottom safe area (`env(safe-area-inset-bottom)`); tile width is
  `clamp()`-computed so it never drops below a 44px touch target. If 13 tiles + a held-apart 14th
  can't all hit 44px at the viewport width, tiles overlap slightly (fan/cascade) rather than
  shrink under the touch-target floor.
- Claim buttons stay ≥44px, pinned above the safe-area inset, never crowded by the hand.

## 4. Tile identity

The hand model requires elements "keyed by `tile_id`, so a tile drawn, held, and discarded is one
continuous element" — but the protocol only gives `tile_id` to the seat that owns the tile.
Opponents send `deal → counts: {seat: n}`, `draw {seat}` with no `tile_id` for non-drawers, a
concealed hand as `{count: 13}` at any time, and `concealed_kong → {count: 4}`. An opponent's
backs have no server identity to key on.

The client assigns a **positional** identity instead — stable per seat, opaque until revealed:

- Each opponent hand is a fixed slot array: `seat:0..12` (concealed) plus `seat:drawn` for a 14th
  tile. Slot index is a DOM/array position, not a tile value — backs are visually interchangeable,
  so *which* slot holds *which* physical tile doesn't matter, only that a slot stays a stable
  element across a diff.
- `draw {seat}` (count 13→14): append `seat:drawn`, same "held apart" convention as your own hand.
- A discard from that seat carries the real identity (`discard {seat, tile_id, tile}`). Resolve
  which slot it left by a fixed rule, not by guessing which back it "really" was: if `seat:drawn`
  exists, it left (covers the common tsumogiri case) — it morphs from back to face-up in place,
  then animates to that seat's discard pool keyed by `tile_id`. Otherwise the rightmost concealed
  slot (`seat:12`) morphs instead, and slots above it shift down one index. Any consistent rule
  works, because the tiles are indistinguishable prior to reveal — only element continuity for the
  CSS transition matters. From the moment of reveal onward the element's key is the real `tile_id`.
- `concealed_kong {seat, count: 4}`: remove 4 concealed slots (same rule, extended: `seat:drawn` +
  the 3 rightmost), replace with 4 backs in that seat's meld area. `hand_end` reveals identity
  later; morph in place, no animation needed post-game.
- An open meld (`meld {seat, kind, tiles, from_seat}`) gives real ids directly — no positional
  guessing, the claimed tile and the contributed concealed tiles all arrive named.

Client-only bookkeeping — doesn't touch the protocol or leak information. Opponent slot count
always matches the redacted `count` the server already sends.

## 5. Interaction model

| Action | Desktop | Touch |
| --- | --- | --- |
| Select tile | hover lifts it, click selects | tap lifts |
| Discard | click a lifted tile (pending state, below), or drag up past a threshold | tap again, or swipe up (gesture note below) |
| Claim | DOM buttons, bottom-center, with CSS countdown ring | same, ≥44px targets |
| Sort hand | auto by default, no manual reorder in v1 | auto |
| Inspect discard pool | hover shows who discarded and when | long-press |

- Faan preview on hover: deferred — see [99-deferred.md](99-deferred.md). No protocol message
  carries shanten/ukeire, and a client-side TypeScript reimplementation duplicates the one
  deliberately-pure Python engine ([00-architecture.md §3](00-architecture.md)). Alternative for
  whoever owns [02-protocol.md](02-protocol.md): a rate-limited `hint` request/response reusing
  `mahjong_core.shanten`/`ukeire` server-side — hover-rate polling (60Hz) would collide with
  intent rate limiting, so this has to be an explicit, debounced request, not a stream.
- Touch gesture note: swipe-up-to-discard competes with page scroll. Scope the gesture to the
  lifted tile only (`touch-action: none` on that element while lifted) with a distance + direction
  threshold, so an un-lifted hand or the rest of the page scrolls normally. Tap-to-discard is the
  safe default; swipe is a convenience on top of it, never the only path.
- Pre-arm toggles ("no calls this hand", "auto-pass chow"), sent via `auto`, enforced server-side.
- Claim buttons appear only when the server offered them; never speculative.

### Discard: pending state

"No optimistic updates" ([00-architecture.md §1](00-architecture.md)) assumed a wired same-region
round trip (~50ms median). Mobile 4G to a single HK server is realistically 100–300ms — long
enough that a tile with zero feedback between tap and server echo reads as broken, not safe.

Rule: still no local mutation of game truth. Add a **pending** presentation state instead:

- Sending `discard {tile_id}` adds a `pending` class to that tile element (dimmed,
  non-interactive, small latency-only spinner). It stays in your hand, in place.
- Cleared by the matching `discard` event echo (or a superseding `turn`/`hand_end`) → the normal
  discard-to-pool animation takes over.
- A discard already present in the server's own `turn.legal` essentially cannot be rejected, so
  there's no "revert" case to design for. The real failure mode is a dropped connection: if no
  echo arrives within a short bound (e.g. 3s), show a stalled indicator ("reconnecting…") on that
  tile, resolved by the normal reconnect/resync path (§6) — never by a client-side guess at the
  outcome.

### Claim window

The server closes claim windows **early** — as soon as no better claim is possible
([00-architecture.md §4](00-architecture.md)) — so "buttons are up" is not a stable client state:

| Scenario | Client behaviour |
| --- | --- |
| `claim_offer` received | Render offered options + PASS, keyed by `window_id`. Start the CSS countdown ring (below). A new `window_id` always fully replaces the previous button set. |
| `claim_resolved` names this seat | Remove buttons immediately, play the meld/win animation. |
| `claim_resolved` names another seat while this seat's buttons were still live (e.g. a higher-priority win beat your pending pung) | Remove buttons immediately, no fade-out — the option didn't get declined, it stopped existing. Toast only for a non-obvious loss (someone else won/konged the tile); a plain timeout-to-PASS needs no toast. |
| `claim_resolved` with no seat (sole eligible claim passed, or all eligible seats passed) | Remove buttons immediately; play continues without waiting out the full deadline. |
| Local `claim` sent but arrives after the window already closed | Server drops it by stale `window_id`, or acks `{ok:false}`. Client shows a brief "too slow" toast and changes nothing else — no local state was ever applied. |
| Dialog's own timer runs out, no `claim_resolved`/`turn` yet (latency) | Client auto-selects `pass` through the same `onChoose` path a manual click uses (`DialogTimer.svelte`, below), sending `claim{window_id, choice:'pass'}`. Mirrors what the server already does on its own claim-window timeout ([02-protocol.md §4](02-protocol.md), "PASS on claim timeout"), so this isn't a decision the server wasn't already going to make — it's just not waiting for the round trip. |
| A pre-armed toggle covers this offer (`auto`) | No buttons render — the server already resolves it as an instant choice. |

Deliberate tradeoff in the row above: a real click landing in the last few ms before the local
timer fires can lose to the auto-pass if the server treats a seat's first-received choice as
final. Accepted in favor of a dialog that actually closes on its own — see `DialogTimer.svelte`
below and [02-protocol.md §4](02-protocol.md)'s timer note. `hand_end_ack` gets the same
auto-close treatment with none of this risk: it's an acknowledgment, not a choice with
alternatives, and the table already advances at the same `deadline_ts` with or without it
([00-architecture.md §3](00-architecture.md) "Hand-end hold") — the client firing it early just
lets the *other* seats stop waiting on this one sooner.

### Countdown mechanics

- The ring is a CSS animation (`animation-duration` set once from `deadline_ts - now`, `linear`),
  not a `setInterval`/`requestAnimationFrame` loop. Background tabs clamp JS timers to ≥1000ms,
  so a JS-ticked ring visibly stalls when the tab loses focus (e.g. during an opponent's long
  think); a CSS animation keeps compositing and is correct the instant the tab regains focus.
- The ring itself is still cosmetic — it never drives anything on its own. `DialogTimer.svelte`
  (`web/src/lib/ui/`) pairs it with a real one-shot `setTimeout` (`auto-close.ts`'s
  `scheduleAutoDismiss`, also used standalone by `Toast.svelte`) anchored off the same
  `durationMs`, so the *timeout*, not the ring, is what calls the dialog's `onClose`. Used by the
  claim dialog (auto-pass, above) and the hand-end hold (auto-ack). The turn ring (your own
  discard/draw deadline) stays purely cosmetic with no `DialogTimer` behind it — the server alone
  handles tsumogiri on expiry, and there's no local dialog for the client to close.
- **Not implemented: clock-offset correction.** `deadline_ts - now` uses local `Date.now()`
  directly — `ping`/`pong` exists on the wire ([02-protocol.md §4](02-protocol.md)) but nothing
  in the client calls it, so there's no `performance.now()`-based offset measurement to anchor
  against yet. Fine on a synced clock; the ring reads early/late by however far the client's
  clock actually drifts otherwise.
- The protocol's chess-clock bonus-second bank ([02-protocol.md §4](02-protocol.md)) doesn't get a
  dedicated meter in v1 — deferred, see [99-deferred.md](99-deferred.md). The ring reflects only
  the current `deadline_ts`, which already folds in any bonus time the server granted.

## 6. Client state

```ts
// lib/game/state.ts — plain data, no runes, so lib/net/reducer.spec.ts can test it directly
interface ClientGameState {
  seat: number | null;                 // learned from state_sync.seat once joined
  handNo: number; prevailing: string; dealer: number; turn: number; phase: string;
  ownHand: number[];                   // real tile_ids — this seat's own concealed hand only
  concealedCounts: number[];           // length-4, count-only for every seat incl. this one
  melds: MeldState[][];                // length-4; concealed_kong is {tiles:null,count} until reveal
  discardPools: number[][];            // length-4, append-only, indexed by pool_index
  flowers: string[][];
  wallRemaining: number; seatStatus: string[]; names: (string | null)[]; scores: number[];
  legalActions: Record<string, unknown>[];     // this seat's turn options, else []
  deadlineTs: number | null;
  claimOffer: { windowId: number | null; options: Record<string, unknown>[]; deadlineTs: number | null } | null;
  lastHandEnd: HandEndState | null;    // latest hand_end only — the just-finished-hand overlay
  handHistory: HandHistoryEntry[];     // every hand_end this session has seen, oldest first (below)
  gameEnd: GameEndState | null; shutdownDeadlineTs: number | null;
}

// lib/game/store.svelte.ts
class GameStore {
  state      = $state<ClientGameState>(initialClientGameState());
  connection = $state<ConnectionStatus>('idle');   // mirrors the socket's own status
  seq        = $state<number | null>(null);        // last seq applied — UI/debug bookkeeping only
  version    = $state(0);                          // bumped every apply(); non-reactive-consumer signal

  constructor(socket: MahjongSocket) { /* $effect.root(() => { $effect(() => socket.onEvent(...)); ... }) */ }
  #apply(event: ServerEvent) { this.state = reduce(this.state, event); this.version++; }
  destroy(): void { /* disposes the $effect.root */ }
}
```

`GameStore` doesn't own seq-gap detection — `lib/net/socket.ts` does (below), since it needs to
act on a gap (re-send `hello`) independently of whether anything is even listening yet. The
store's own `seq` field is just a read-model mirror of whatever the socket already accepted.

**`lib/net/socket.ts`** (`MahjongSocket`) owns the wire-level correctness rules:

- Every real client intent (`join`/`ready`/`discard`/`claim`/`declare` + the `declareWin`/
  `declareConcealedKong`/`declareAddedKong` convenience wrappers/`auto`/`ping`), each
  building its own envelope with a fresh idempotency `id` (`crypto.randomUUID()`-derived —
  satisfies docs/02-protocol.md §1's per-seat-binding uniqueness; no client-side retry logic
  exists to need de-duplication beyond that).
- **Seq-gap detection**: tracks `lastSeq` for this stream; `state_sync` is always accepted
  as a full replace regardless of its own seq (that *is* the resync mechanism); a frame with
  `seq <= lastSeq` is a stale replay duplicate and is ignored; a frame with `seq > lastSeq + 1`
  is a real gap — it's dropped (never forwarded to listeners) and triggers `#requestResync()`
  (re-sends `hello{last_seq, seat}` on the live connection — docs/02-protocol.md §5's three-way
  branch isn't reconnect-only, it's keyed only on what `last_seq` compares against, so re-asking
  mid-connection is the same request). `status` exposes `'resyncing'` while this is in flight.
- **Reconnect**: unexpected closes schedule a reconnect with exponential backoff + jitter
  (`min(250ms * 2^attempt, 10s) ± 20%`, docs/02-protocol.md §8); `connect(resume?)` also accepts
  caller-supplied `{lastSeq, seat}` to seed a fresh instance (the page-reload case). `+page.svelte`
  persists this seat per table (`lib/ui/settings-storage.ts`'s `saveSeatForTable`/`loadSeatForTable`,
  `mahjong:seat:v1:<tableId>`) the moment `state_sync` confirms one, and feeds it back into
  `connect()` on mount — without this, a fresh page load has `seat: null` and falls into the
  seat-picker screen's `join`, which fails with `table_full` once all four seats are already bound
  to this game's players, the same seat included. `lastSeq` is intentionally not persisted:
  omitting it just means a full `state_sync` instead of ring-buffer replay (docs/02-protocol.md
  §5's "too old / new session" branch), which a page reload needs anyway since the in-memory
  reducer state is gone.

### Settings persistence (`autoArm`/`clientPrefs`)

`Settings.svelte`'s two prop objects (`AutoArm`, `ClientPrefs`) are held as plain `$state` in
`/table/[id]/+page.svelte`, not in `ClientGameState` — they're UI-owned, not game truth. Both
persist to `localStorage` (`lib/ui/settings-storage.ts`, `mahjong:clientPrefs:v1`/
`mahjong:autoArm:v1`): loaded once on mount, saved on every change, every read/write wrapped in
`try/catch` and falling back to the hardcoded defaults on missing, corrupted, or malformed stored
data — the page must render correctly with storage blocked or unavailable (private browsing).

`clientPrefs` (`soundEnabled`, `motion`) has no server component at all; persistence is the whole
story.

`autoArm` (`no_calls`/`auto_pass_chow`, sent via `auto`, docs/02-protocol.md §2) is different:
**the server has no wire event that reports a seat's current auto-arm state back to a client** —
neither `state_sync` (`seat_view_wire`) nor any other event carries `no_calls`/`auto_pass_chow`,
so there is nothing to read this back from. The persisted value is therefore "this client's last
known intent," never verified server truth — a page reload builds a fresh `GameStore`/
`MahjongSocket` with no memory of what was last chosen, even though the server's own
`SeatBinding` may still hold the real value from before, and the two can silently disagree with no
way for the client to notice. The fix is **re-assert on (re)connect, not read-back**: once a fresh
live connection seats us (`ClientGameState.seat` goes non-null), `+page.svelte` re-sends the
persisted `autoArm` via `socket.auto(...)` exactly once for that connection, pulling the server
back in line with the client's last choice rather than leaving the two free to drift. This only
runs in live mode — `?mock=` has no real socket to re-assert against; `clientPrefs`'s persistence
applies to both paths since it's purely local. A future change that wants the server to be the
source of truth for auto-arm state needs a real wire field for it first; this model is a
deliberate stopgap around that gap, not an assumption that it doesn't exist.

### Guest display name (`displayName`)

M5's guest-identity mechanism (`docs/02-protocol.md`'s Auth section): a plain text field on the
pre-game "Take a seat" screen (`/table/[id]/+page.svelte`), persisted to `localStorage`
(`lib/ui/settings-storage.ts`, `mahjong:displayName:v1`) the same way as `autoArm`/`clientPrefs`
above — prefilled from a prior session, saved on every keystroke. Unlike `autoArm`, this is
**not** re-asserted on reconnect: it's sent exactly once, as a plain field on `join`
(`MahjongSocket.join(seat?, name?)`), which is the only message that ever carries it — a `hello`
reconnect never resends it, since the server already has it on the seat binding from the original
`join` (`docs/02-protocol.md §2`'s `join` row). No client-side validation beyond "send whatever's
in the box, or omit it if empty" — the server trims/caps/defaults it (`JoinPayload.name`), so
there's nothing to duplicate here.

`ClientGameState.names: (string | null)[]` (length 4, same indexing as every other per-seat
array) carries every seat's *resolved* name back down: populated from `state_sync.names` on
every full snapshot, kept live from `seat_state.name` the same way `seatStatus` is kept live from
`seat_state.status` (`lib/net/reducer.ts`'s `seat_state` case). `lib/table/live-view.ts`'s
`viewFromClientState` reads this array for every seat's `MockSeatState.name` in the live path —
including a practice-mode bot seat, whose name is its real server-assigned tier name (e.g.
"FaanBot"), rendered alongside the existing `.bot-badge` chip, not in place of it. `null` until a
seat's own name has actually arrived; the mock scenarios (`mock-game-state.ts`) are untouched —
they hardcode their own fixed sample names and have no `ClientGameState` behind them at all.

Rules:

- The reducer is pure and exhaustively switched over the generated `ServerEvent` union, so
  TypeScript flags unhandled events.
- **Sequence numbers are per-seat**, dense and gapless within *your own* stream — not per-table. A
  table-wide seq would advance on every unicast `claim_offer`/`turn.legal` sent to other seats, so
  under that scheme a gap would fire on essentially every claim window. A gap on your own stream
  triggers a resync request, never a silent patch.
- Deep-reactive fields (`$state<TileId[]>`, `SeatView[]`, …) are Svelte proxies. Non-reactive
  consumers (a Web Worker, a non-Svelte helper, structural-sharing comparisons) get a plain
  snapshot via `$state.snapshot(store.field)` plus `store.version` as a cheap "did anything
  change" check — never the live proxy.
- Code that subscribes outside a `.svelte` file (e.g. a `lib/net/` socket manager wiring an
  `$effect` to flush outbound intents) throws `effect_orphan` unless wrapped in
  `$effect.root(() => { ... })` with an explicit disposer — effects need an owner, and a module
  isn't one.
- Table-surface components (`lib/table/`) read the store directly and let Svelte's keyed
  `{#each}` (keyed by `tile_id`, or the positional id from §4) diff the DOM. There's no separate
  renderer to sync by hand, so there's no manual "diff against current DOM" decision for ordinary
  events (see `state_sync` below for the one full-replace case).
- Same reducer drives the replay viewer (§9), fed from the server's per-seat redacted event
  stream — not raw action log.
- **`hand_end` accumulates into `handHistory`**, not just `lastHandEnd`: `game_end`
  (`{hand_no, scores}`, `docs/02-protocol.md §3`) is a terminal, fires-once event with no
  per-hand ranking on the wire, but `hand_end` fires once per hand for the life of a live game,
  so a score sheet needs the running list, not just the latest one. `dealer`/`prevailing` aren't
  on `hand_end`'s own payload — the reducer captures them off `state` at the moment it sees the
  event, since only `hand_start` (always the prior event) changes them. Survives `state_sync`
  unchanged (a redacted snapshot carries no hand history to replace it with); `ScoreSheet.svelte`'s
  `historyComplete` flag is what surfaces a reconnect that landed on a full resync rather than
  gap-replay, missing hands from before this session began. `/table/[id]`'s live path maps this
  into `ScoreSheet`'s `HandRecord[]`; the mock path (`MOCK_SCENARIOS`) still synthesizes a single
  row from the current snapshot, unaffected — a mock scenario is always one frozen, already-dealt
  hand with no real `hand_end` stream behind it.
  - **`HandHistoryEntry.winnerMelds`** snapshots `state.melds[winner]` at the exact moment
    `hand_end` fires (`null` for a non-win outcome). `hand_end`'s own wire payload only carries
    `winning_hand` (the winner's *concealed* tiles) — the winner's melds are never redacted, so
    the live hand-end overlay just reads them straight off `gameState.seats[winner].melds`
    (`+page.svelte`'s `FaanBreakdown` invocation) at the moment it renders. That live seat data
    resets on the next `hand_start`, so it's gone by the time a player looks at a *past* round in
    a game-end summary — `winnerMelds` is the client-side capture that keeps it around past the
    hand it belonged to. Not a wire gap: nothing here needed a protocol change.

### Game-end summary

`ClientGameState.gameEnd` (from the terminal `game_end` event) triggers an auto-shown, non-
dismissable screen (`GameEndScreen.svelte`) once the game is genuinely over — unlike the per-hand
hold overlay, there's no next hand to advance back into. On the wire, `game_end` only ever fires
*after* the final hand's own hold has already resolved (every seat acked, or the hold's own
timeout — `app/table.py`'s `_apply`/`_open_hand_end_window`/`_advance_to_next_hand`, which is the
only path that calls `start_next_hand()`, the sole producer of `GameEnded`). So the game-end
screen doesn't preempt anything genuinely still in progress — but the client's own hold overlay
has no other way to know that hold is over (it normally clears on the *next* `hand_start`, and
there isn't one for the final hand), so `+page.svelte` gates that overlay on `!gameEndReached` and
lets the game-end screen replace it outright once `gameEnd` lands.

`GameEndScreen` reuses `ScoreSheet` wholesale (score table, running totals, `standings`) rather
than a second table implementation, adding only the "game over" framing and a plain `<a href="/">`
back to the home page — the game is over, and the home page's create/browse/practice panels already
cover starting a new one; no dedicated rematch/new-game flow.

`ScoreSheet.svelte` itself grew an optional per-round expand: `HandRecord.result` (a
`RoundResult`), when present, turns that row's hand number into a toggle button revealing the
round's winning hand inline, reusing `FaanBreakdown`'s own tile rendering rather than a second
implementation of it — or a plain "Exhaustive draw" note when the round has no winner. One
capability serves both call sites: the manual mid-game "Score sheet" toggle (`+page.svelte`'s
`mockRoundResult`/current-hand-only detail) and the new auto-shown game-end screen (past rounds,
`liveRoundResult`, converting `HandHistoryEntry.winnerMelds`/`winningHand` tile_ids to `TileCode`s
the same way `live-view.ts` already does for the live seats).

The mock path gets its own scenario (`mock-game-state.ts`'s `gameJustEnded`, `?mock=game-ended`):
a frozen `GAME_OVER` snapshot carrying a `MockGameState.gameEnd` summary (rounds + standings) —
the one field only this scenario sets, mirroring `liveStore.state.gameEnd` closely enough that
`+page.svelte`'s `gameEndReached`/`scoreHands`/`scoreStandings` derivations branch on `isMock`
rather than forking into a second render path.

### SSR

`web/Dockerfile` builds with `pnpm build` and runs `node build` — adapter-node, so SvelteKit SSR
is on by default for every route unless opted out. Posture:

- `/`, `/tables`, `/demo`, `/profile` — SSR stays on; cheap, no live-socket dependency (`/tables`
  fetches its listing client-side, in an `$effect`).
- `/table/[id]`, `/replay/[id]` — `export const ssr = false` in `+page.ts`. Auth token, WebSocket
  connection, and per-seat redacted state are all client-only; pre-rendering a stale or empty
  table just to hydrate over it a moment later has no SEO benefit and is wasted work.

### `state_sync` and resync

A `state_sync` is a store replace — set every field from the redacted snapshot, bump `version`.
Keyed `{#each}` blocks reconcile existing DOM elements against the new list automatically
(matching ids survive; unmatched ones mount/unmount), so there's no manual teardown-and-rebuild
path and no separate diff algorithm to write. Wrap the replace in a brief CSS crossfade on the
table container (`prefers-reduced-motion` disables it) so a full resync reads as "refreshed," not
a glitch.

On reconnect to your own seat after the 20s `AUTOPLAY` handover
([00-architecture.md §8](00-architecture.md)): the `state_sync` already reflects everything the
bot did. Show a one-line, dismissable banner ("Auto-played 3 turns while you were away") once;
don't replay the missed turns as animation.

### `/table/[id]` wiring

`[id]` is a real table id (the lobby's client-generated invite code already works as one against the backend's
auto-create-on-first-connect, `server/app/ws.py`'s `_get_or_create_table` — no table API needed).

`?mock=<scenarioId>` (any value, including a bare `?mock`) renders a frozen `MOCK_SCENARIOS`
fixture instead — needed by the screenshot workflow (`.claude/skills/frontend-screenshots/
SKILL.md`) and design iteration, both of which run with no backend. Omitted, the route opens a
real `MahjongSocket` at `${PUBLIC_WS_URL}?table=<id>` and drives it through `GameStore`.

`?pregame=connecting|join|waiting` is the equivalent escape hatch for the three pre-game states
below (§"Join flow"): `?mock=` can't stand in for them (a mock scenario is always a fully-seated,
already-dealt table), so this freezes on one of them with no `MahjongSocket` constructed at all
— same no-backend repeatability, used by the screenshot workflow's `table-pregame-*` entries and
by design iteration on this specific part of the page.

**One view model, two sources.** `lib/table/live-view.ts`'s `viewFromClientState()` projects a
real `ClientGameState` into the same `MockGameState`-shaped object `+page.svelte`'s template
already renders, so the mock and live paths share one render tree (`TileFace`/`ClaimButtons`/
`TimerRing`/`FaanBreakdown`/`ScoreSheet`/...) rather than forking into a second one that could
visually drift. The one thing the mock shape has no room for is real tile identity (mock tiles
are bare `TileCode`s, no id); `viewFromClientState`'s `LiveTableView.ownHand` carries the real
`tile_id`s alongside, index-aligned with the view's `concealedHand`/`drawn`, so the page can wire
a real `discard`/`claim`/`declare` intent off a tile the user actually clicked.

**Join flow.** No auto-join, no assumed seat: a live table shows a seat picker (sends
`join{seat, name?}` for the specific seat clicked) until seated, matching the standing "intent,
not silent state" rule. The screen carries a plain text field for the M5 guest display name
(above), prefilled from `localStorage` — editable right up until the click, since `join` is what
actually sends it. Sitting down implies readiness (`ready` fires right behind a successful join)
— there's no strategic reason to gate it behind a second button once the player already made the
one real decision. Until all four seats are joined and ready, the page shows a waiting screen.

Picking a specific seat (rather than the old "first open seat" button) needs real occupancy data
before you've joined anything — the socket-setup effect connects with `&spectate=true` whenever
there's no persisted seat to resume (`lib/net/socket.ts`'s connect URL), which gets an immediate
spectator-shaped `state_sync` (`seat=None`, `app/table.py`'s `register_spectator`) carrying real
`seat_status`/`names` for all four seats. `join` promotes the connection off spectator status the
moment a seat is actually clicked (`docs/00-architecture.md §3`'s "Spectating" note), so this
never blocks becoming a real seat — it's a strict improvement on data available, not a new state
to reconcile.

**Pre-game states** — connecting, seat-picker, and waiting are real, recurring moments in a
genuinely multiplayer game (arriving at a table, waiting for others to show up), not filler
between "real" screens, so they use the same `panel-elevated`/button vocabulary as the rest of
the app (`_buttons.scss`) rather than bare text and an unstyled `<button>`. All three share one panel (table code +
a "copy invite link" button — the table's URL *is* the invite, and waiting-for-players is exactly
when you need to hand it to someone) and a seat ring: four slots arranged across/left/right/self,
the same relative arrangement `layout.seat-region-grid` uses for the real table, so the pre-game
screen visually foreshadows the seats you're about to sit at. Pre-join, each slot is a real
`<button>` (`seatPicker`/`seatPickerSlot`) reading `seatStatus`/`names` off the spectator snapshot
above — "Open" and clickable, or the occupant's name/"Bot" and disabled; once seated, the ring
geometry (`seatRing`) keeps the self slot on real *wind* (the dealer is fixed at table
construction, before any `ready`, so `seatWind()` works unchanged here) but the other three switch
to a non-interactive occupancy readout (`seatOccupancySlot`, same `seatStatus`/`names` fields,
kept current post-join via `seat_state` broadcasts) — a seated player waiting for the table to
fill can watch the next arrival land instead of staring at a ring that can never change. A toast
("`{name} took a seat.`") fires alongside it the first time each seat flips to `connected`/`bot`
while `!handEverStarted`, so the arrival is noticed even if this screen isn't being watched;
`disconnected`/`autoplay` churn and any `seat_state` for this browser's own seat are excluded —
not "a new player," and not news about yourself.

**Host: start with bots (M5.1).** Whichever seat's `join` was this table's first is that table's
host (`app/table.py`'s `Table.host_seat`, mirrored on the wire as `state_sync.host_seat`) — the
simplest rule that needs no extra client-asserted identity, matching this design's existing
guest-only, client-asserted-seat posture (`00-architecture.md §2.1`). While the waiting screen is
up, the host alone sees a "Start with bots" button (`ClientGameState.hostSeat === state.seat`)
that sends `start_with_bots {}`: the server binds every still-empty seat to a bot (the same
`_bind_bot_seat` M4.5 practice mode already uses, just invoked at runtime instead of only at table
construction) and deals immediately once that makes every seat bound and ready — exactly as if a
fourth human had clicked `ready`. Lets a table start with fewer than four humans without forcing
everyone through practice mode's separate solo-vs-bots entry point. A non-host sender gets
`error{code:'not_host'}`; a call after the table's already started gets `error{code:'already_started'}`
— both are asserted server-side (`Table.start_with_bots`), the client button is a convenience, not
the actual gate.

**There is no backend "has this table started" field to gate that screen on.** `new_game()` deals
hand 1 into `Table.state` immediately at table construction, before any `ready` — so a `state_sync`
sent to the very first joiner already shows a fully dealt hand, computed `legal_actions`, all of
it indistinguishable on the wire from "already playing." (`app/table.py`'s `require_ready` gate
blocks *processing* an early command, but the redacted view was never told to hide the
already-dealt state behind it.) The client works around this itself: a local flag flips
permanently once either the current snapshot already shows unambiguous play-in-progress evidence
(a reconnect mid-game — non-empty discard pools/melds, `hand_no > 1`, a nonzero score) or a
genuine post-start broadcast is observed (`hand_start`/`turn`/`draw`/... — events that structurally
cannot exist before `Table.started`). Good enough for v1; a real `started`/seat-fill count on the
wire would be a cleaner fix, filed as a gap here rather than a roadmap doc since it's small enough
to fold into whoever next touches `state_sync`'s payload.

**Practice mode entry point (M4.5, `docs/05-roadmap.md`).** The lobby (`/`) has a third panel, "Practice,"
alongside create/find: its "Play vs bots" button generates a table id the same way "Create table"
does and navigates straight to `/table/<id>?practice=1` — no invite code to share, but "Create
table" has no copy step to skip either (below): both buttons go straight from the lobby to the
table. `?practice=1` is this route's own query param, unrelated in spelling to
the wire's own `&practice=true`; `/table/[id]`'s live-connect effect appends the latter to the
`MahjongSocket` URL when the former is present, which is what actually binds seats 1-3 to real
`FaanBot`s at table creation server-side (`server/app/ws.py`'s `ws_endpoint`, `app/table.py`'s
`Table.__init__(practice=...)`). The human's own `join`/`ready` — the existing seat-picker flow —
is unchanged (seat 0 is the only "Open" slot in the picker, since seats 1-3 already read `bot`); a
practice table's bot seats are already bound and auto-ready the instant the table
exists, so the "waiting for the rest of the table" screen should almost never show for long, though
the client still goes through it structurally since there's still no real "has this table started"
signal (below). The table label in the live table's dev toolbar appends "· practice vs FaanBot" when
this flag is set, matching this milestone's "don't invent a tier selector" scope — one fixed
default tier, named plainly, not a difficulty picker.

**Table browser (`/tables`).** Reached from the lobby's "Find a table" panel; holds the
join-by-code form and a responsive grid of table cards (`repeat(auto-fill, minmax(16rem, 1fr))`),
each showing its code, open/in-progress state and all four seats. The grid polls `GET /tables`
every 5s ([02-protocol.md §10](02-protocol.md), `lib/net/lobby.ts`), open tables first. "Sit
down" (open) and "Watch" (in progress) both navigate to the same `/table/<id>` — the route itself decides
picker vs. spectator view (below), so a table that fills between the poll and the click still
lands somewhere sensible.

**Spectating.** `/table/[id]` renders the table as a spectator whenever this connection has no
seat, a real `state_sync` has landed (`handNo > 0`), and no seat is `empty` — i.e. nothing left
to pick. No separate URL flag: the socket already connects with `&spectate=true` whenever
there's no persisted seat (Join flow, above). The view is `viewFromClientState(state, 0)`: seat
0 is drawn at the bottom as a hand of backs (a spectator snapshot carries no concealed tiles) —
unless the table shows spectators every hand (`state_sync.hands`, docs/02-protocol.md §2), in
which case the reducer keeps `ClientGameState.hands` live from `draw`/`kong_replace`/`discard`/
`meld` and every seat, bottom and opponents alike, renders its hand face-up and sorted —
with no discard/declare/claim controls (`legalActions`/`claimOffer` are always empty for a
spectator), no Settings (auto-arm is per-seat), and a "Leave game" link in the toolbar. The
hand-end overlay dismisses locally instead of sending `hand_end_ack` — the hold only waits on
seats.

**Leave game.** Every `/table/[id]` view — pre-game and live — gets a "Leave game" control instead
of a plain "back" link, since navigating away can have a real effect on a seat, not just close a
tab. Whether it confirms first turns on holding a seat (`isPlayer`: not mock, `effectiveSeat !==
null`) — the pre-start waiting room counts, since `join`/`ready` already fired there, but the
pre-join connecting/seat-picker screens and spectating don't, since there's no seat to lose yet or
at all. A held seat confirms via a dialog first ("Your seat switches to autoplay until you
reconnect," matching the real `AUTOPLAY` handover, §6); everything else navigates to `/`
straight away. Either path ends at the same `goto('/')` — the socket-setup effect's own cleanup
(§6) disconnects it, the same as closing the tab already did.

**Bot seat badge.** `MockSeatState` grew an optional `status?: string` field (`mock-game-state.ts`)
that `live-view.ts`'s `viewFromClientState` populates from `ClientGameState.seatStatus[seat]` —
mock fixtures never set it, so this is a no-op there. `+page.svelte`'s opponent seat header renders
a small `.bot-badge` chip ("Bot") next to the existing dealer badge whenever `status === 'bot'`,
styled as a quiet persistent-identity chip (bordered, muted text) rather than borrowing
`--color-accent` the way the transient dealer badge does — a bot seat's status doesn't change
mid-hand the way whose turn it is does. Other `seat_status` values (`connected`/`disconnected`/
`autoplay`/`empty`) have no visual treatment yet; this sub-task only covers `bot`, the one value
that just gained real backend meaning.

**Two wire-shape gotchas the mock fixtures can't surface** (they hardcode values the real wire
doesn't actually send this way):

- The reducer clears both `legalActions` and `deadlineTs` on a seat's own `discard` — leaving
  stale entries would let a client render "legal-looking" discard buttons for a tile still in
  `ownHand` after this seat had already acted, and clicking one sends a command the server
  silently drops as out-of-turn ([02-protocol.md §1](02-protocol.md)'s `ack` note). Pinned by a
  `reducer.spec.ts` regression test.
- `state.prevailing`/`hand_start.prevailing` go over the wire as the `Wind` `IntEnum`'s *member
  name* (`app/views.py`/`app/table.py`: `.name` — `"EAST"`/`"SOUTH"`/`"WEST"`/`"NORTH"`), not the
  single-letter code (`'E'|'S'|'W'|'N'`) mock scenarios use and `WIND_LABEL` indexes by.
  `live-view.ts`'s `wireWindToCode()` maps it — the one enum-shaped wire field that needs this;
  `phase`/meld `kind`/claim `kind` already serialize through a `StrEnum`'s `.value`, the same
  string either way.

## 7. Asset pipeline

- Tile art: **[FluffyStuff/riichi-mahjong-tiles](https://github.com/FluffyStuff/riichi-mahjong-tiles)**
  — public domain SVG, regular and black variants. Vendored (`web/static/tiles/`, see `NOTICE`):
  the 34 playable faces HK shares with riichi, "Regular" style, skipping the source repo's red-5
  ("-Dora") variants — a riichi-only concept this ruleset has no use for. The source repo has **no
  flower/season art** (it covers only the 34 riichi types) — the 8 flower/season faces
  (`01-rules-spec.md §1`) still need a separate source; `TileFace.svelte` currently renders the
  tile back for those codes.
- Rendered via `<img src>` per face, not inlined/`<use>`: the vendored SVGs carry
  non-namespaced ids (clipPath/filter/gradient) that collide when the same or different tiles are
  inlined into the DOM more than once, which a hand of tiles does constantly. `<img>` isolates
  each instance's rendering context at the cost of not being stylable via `currentColor`.
- No build step, no atlas. Served as static files as-is. No @1x/@2x split, no DPR-keyed picking —
  SVG is resolution-independent, which is the no-pipeline version of the problem the atlas build
  step existed to solve. (The @1x atlas specifically is moot now, not just deferred — there's no
  atlas at all — see [99-deferred.md](99-deferred.md).)
- 2.5D look: `perspective` + `rotateX` on the table container (§2), not pre-rendered art. The
  Blender pre-render route is deferred — see [99-deferred.md](99-deferred.md).
- Sound: draw click, discard clack, shuffle — short, compressed, preloaded, mute default-on until
  opt-in. Recorded Cantonese call-outs (碰/上/槓/食糊) are deferred — see
  [99-deferred.md](99-deferred.md); unrecorded, unbudgeted content task, not a code task.

## 7.1 Styling: SCSS

Stylesheets are **SCSS** (`sass`, the Dart implementation, as a dev dependency). SvelteKit wires
it through Vite; component styles use `<style lang="scss">`.

SCSS compiles to plain CSS, so nothing above changes: the GPU-compositing argument (§2), the
CSS-animation countdown ring (§5), `grid-template-areas` (§3) and `prefers-reduced-motion` (§8)
are all web-platform features and behave identically. This is an authoring-layer choice only.

```
src/lib/styles/
  _tokens.scss      colour, spacing, type scale, z-layers, seat colours
  _tile.scss        tile geometry: face size, corner radius, stack depth, back pattern
  _layout.scss      seat-region grid, perspective/rotateX, breakpoint mixins
  _a11y.scss        focus rings, high-contrast hooks, reduced-motion guards
  app.scss          entry: forwards the above, global resets
```

Conventions:

- `@use`, never `@import` — the latter is deprecated in Dart Sass and leaks globals.
- Tokens are SCSS variables **only when compile-time** (breakpoints, the tile aspect ratio used in
  `calc()`). Anything a component or the theme toggles at runtime stays a CSS custom property —
  `--tile-w`, `--seat-accent` — because SCSS variables don't exist in the browser. The tile-size
  cascade in §3 is `clamp()` on a custom property, not a Sass variable.
- Nesting: two levels maximum. Svelte already scopes component styles, so deep nesting buys
  nothing and defeats the flat selectors the table surface needs for fast restyle.
- Mixins for the four seat rotations and the breakpoint set; avoid mixins that emit layout.

The one real risk is nesting and `@extend` producing selector bloat on a surface with ~150
elements. Keep the tile rule set flat — the hot path is a transform on a keyed element, and it
should stay one class plus custom properties.

## 8. Accessibility and i18n

- English only for v1; all UI strings in one module. Cantonese term glyphs (碰/上/槓/食糊) stay as
  labels in the UI and in live-region text regardless — they're not translated content. zh-Hant
  locale switching is deferred — see [99-deferred.md](99-deferred.md); matches
  [05-roadmap.md](05-roadmap.md) M6, which already places i18n in the ongoing bucket ("from day
  one" was wrong).
- Colourblind-safe: dragons distinguished by glyph, not just red/green — fixed art asset, ships
  regardless. A switchable high-contrast theme *system* is deferred — see
  [99-deferred.md](99-deferred.md).
- Discard pools are real DOM now, not canvas-only — free a11y that used to need a parallel text
  representation. Each discard is a focusable element (`role="listitem"` within a per-seat
  `role="list"`) with `aria-label="{seat} discarded {tile}, turn {n}"`, reachable by keyboard from
  a landmark region.
- Live region: `aria-live="polite"`, one rolling line per discard event — not a re-announcement
  of the whole pool. At ~80 discards/hand, default verbosity announces claim-relevant context only
  (what was just discarded that you can act on, claim results, hand-end); a settings toggle raises
  it to "every discard" for users who want full parity. Claim-relevant discards are never silent
  by default — that's the actual safety-critical information.
- Keyboard path: with no canvas, there's one implementation, not two. Hand tiles are real
  focusable elements (roving `tabindex`, arrow keys to move focus, `Enter`/`Space` to
  lift/discard) — the same elements pointer and touch use. No separate "bypasses the canvas" path,
  no sync problem between two selection models.
- `prefers-reduced-motion` disables non-essential CSS transitions (lift, drag, crossfade on
  resync); state changes still apply instantly, just without motion.

## 9. Replay viewer

"Same reducer, fed from a recorded event log" doesn't match what's persisted:
[00-architecture.md §6](00-architecture.md) stores finished games as `(ruleset, seed,
action_log)` — *actions*, not a redacted event stream for any particular seat. A client can't
replay that directly: an action log has no seat-of-view baked in, and actions aren't redacted at
all (`redact_event()` is applied server-side, per outbound message, at play time, not stored).

Replay needs a server endpoint that re-runs `reduce()` over the stored `(seed, action_log)` and
re-applies `redact_event(state, seat, event)` to produce the same shape of per-seat event stream the live client
already consumes. Client-side this is the same reducer (§6); server-side it's a different source.
Endpoint shape and default seat (most likely the public/spectator composite view unless the
requester was one of the four players) belong to whoever owns
[02-protocol.md](02-protocol.md)/the server API — not specified further here. `/replay/[id]` is
blocked on that endpoint existing.

## 10. What stays

Unaffected by the DOM change or any finding above:

- One-way data flow: server event → reducer → store → view. Never the reverse.
- Intent, not state: the client sends "discard tile #47," never "my hand is now X."
- Server-only time: every deadline is an absolute `deadline_ts`, never a client-started duration
  (clock-offset correction against it is not yet implemented — §6).
- Always render yourself at the bottom, rotating the other three; seat wind is a badge, not
  position.
- The drawn tile sits apart from the sorted hand, as in physical play.
- The discard pool is append-only, ordered by discard sequence — never shuffled, never compacted.
