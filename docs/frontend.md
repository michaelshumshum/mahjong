# Frontend

SvelteKit 2 + Svelte 5 (runes). Everything is DOM/CSS styled with SCSS — including the table
surface ([ADR 0002](decisions/0002-dom-rendering.md)). ~150 static, axis-aligned, rectangular tiles
with no tick loop don't need a canvas renderer.

## 1. Structure

```
┌─────────────────────────────────────────────────────────────┐
│ SvelteKit app (all DOM/CSS — the table has no canvas)        │
│                                                                │
│  Routes                │  Table route                        │
│  /            lobby    │  ┌──────────────────────────────┐   │
│  /tables      browser  │  │ table surface (DOM/CSS)       │   │
│  /demo        dev demos│  │   4 hands, melds, flowers,    │   │
│  /table/[id]  game     │  │   discard pools               │   │
│                        │  └──────────────────────────────┘   │
│                        │  overlay (Svelte):                  │
│                        │   claim buttons, timer ring,         │
│                        │   faan breakdown, score sheet,       │
│                        │   settings, toasts                   │
│                                                                │
│  lib/net/     ws client, seq tracking, reconnect, reducer     │
│  lib/game/    client state store ($state runes)                │
│  lib/table/   table-surface Svelte components (DOM)            │
│  lib/ui/      dialogs, overlays, shared widgets                │
│  lib/i18n/    locale switcher                                  │
│  lib/styles/  SCSS tokens and mixins (§8)                      │
└─────────────────────────────────────────────────────────────┘
```

Principles:

- **One-way data flow.** Server event → reducer → `$state` store → components. Components own
  presentation state only (pending/lifted/hover classes, transition state), never game truth.
- **Intent, not state.** Input goes `DOM event → intent → WebSocket`, never `DOM → local
  mutation`. The one exception is a _pending visual_ state, not a state mutation (§5).
- **Server-only time.** Every deadline is an absolute `deadline_ts`, never a client-started
  duration ([protocol.md §4](protocol.md)).
- **No tick loop.** All motion is CSS transitions/animations driven by class/attribute changes,
  never a JS ticker or tween library.
- **You are always at the bottom**, the other three rotated around you; seat wind is a badge, not
  a position.
- **The drawn tile sits apart** from the sorted hand, as in physical play.
- **Discard pools are append-only**, ordered by discard sequence — never shuffled or compacted.

## 2. Rendering

**No canvas on the table.** Absolutely-positioned elements with `transform` are GPU-composited.
That buys, for free:

- Hit-testing, focus, `:hover`, tab order, live regions, media queries,
  `prefers-reduced-motion`, CJK text flow, devtools inspection.
- No async renderer bootstrap: the page hydrates like any other SvelteKit route.
- A flat table: no `perspective`/`rotateX` (§3), no pre-rendered art.

Costs:

- Animated paths must stay `transform`/`opacity`-only to avoid layout thrash across ~150 elements
  moving at once (e.g. `hand_start` reshuffling every seat).
- DOM order matters for tab order and stacking; keep it stable so keyed `{#each}` (§4, §6)
  reconciles elements instead of remounting them.

**Exception: the background mural.** `lib/ui/TileMuralBackground.svelte` is a real `<canvas>`: a
continuously vertically-scrolling grid of randomized tile faces (the 34 playable faces plus the
tile back), under a `backdrop-filter: blur() brightness()` scrim (a sibling element in front of the
canvas) so foreground content stays legible. Purely decorative (`aria-hidden`,
`pointer-events: none`), so it loses nothing the DOM would give. A DOM version would animate ~200
elements' `transform` every frame; the canvas does one `drawImage` blit of a pre-rendered
off-screen buffer.

| Behaviour | Detail |
| --- | --- |
| Tile faces | the same ivory `--color-tile` box `TileFace.svelte` uses; backs drawn without a box per `.tile-face--back`. No two backs share an edge (a cluster reads as a hole); adjacent cells never share a suit (honors and backs exempt) |
| Reduced motion | reduced motion (§9: the setting, else `prefers-reduced-motion`) renders the grid once, statically |
| Resize | the grid is persistent — a resize only appends cells to cover the new viewport, never re-rolls placed ones, so a spurious `resize` (webfont swap, scrollbar toggle) can't read as the mural "switching". Unchanged `innerWidth`/`innerHeight` short-circuits the handler |
| Scroll | the buffer's row window advances one row each time its leading row scrolls out of view, rather than wrapping a fixed buffer (which reads as the layout snapping back) |

**Mounted once, shared across routes.** The mural shows on `/`, `/tables`, and `/table/[id]`'s
pre-game states — never on the game table itself, mock or live. It is mounted once in the root
`+layout.svelte`; a per-route instance would tear down and rebuild the grid on every navigation
between mural routes. `lib/ui/mural-visibility.svelte.ts` holds the shared visibility state: a page
calls `claimMuralVisible()` (or `claimMuralVisible(() => condition)` for a route whose need varies)
from its `<script>`, which claims visibility in an `$effect` and releases it on unmount.

- Visibility only toggles the canvas's CSS opacity (`transition: opacity 220ms`, skipped under
  reduced motion); the draw loop keeps running, so there's no pause/resume state.
- Claims are a `SvelteSet` of per-caller tokens, not a boolean: a releasing page and a newly-mounted
  page land in the same reactive flush, and a boolean is last-write-wins (observed stuck hidden).
  A plain `Set` inside `$state` doesn't work either — `$state` makes only the reference reactive,
  not `.add()`/`.delete()`.
- Each mural page's own content needs `position: relative` plus a real `z-index`
  (`var(--z-hud)`): a static-positioned element always paints _below_ a `position: fixed`
  `z-index: 0` element, regardless of DOM order.

## 3. Layout

No fixed logical canvas, no letterbox — a 16:10 letterboxed scene on a 390×844 phone leaves the
table at ~35% of the screen. Each region sizes to its own content via `clamp()`; there is no
global scale factor.

**Table surface material.** `.table-surface` (`routes/table/[id]/+page.svelte`) is a radial felt
gradient (`--color-felt-lit` at 50% 35% fading to `--color-felt`, then `--color-felt-deep` at the
rails) inside a 10px `--color-rim` walnut border, with an inset `--color-rim-hi` highlight ring and
an outer drop shadow. A `::before` layer adds a static inline-SVG `feTurbulence` grain at ~4%
opacity (`background-image`, not canvas — ADR 0002) for a felt-woven texture cue;
`position: absolute` keeps it out of the grid so it never competes with `seat-region-grid`'s own
layout. `--color-text-muted` (tuned for walnut chrome) drops under 4.5:1 on the felt greens, so
`.table-surface` locally overrides it to `--color-felt-muted` (`#c3d4c8`) — every descendant using
the token (seat-wind, seat-score, …) picks it up for free via custom-property inheritance, no
per-component change needed. Tile faces get real thickness from a layered `box-shadow`
(`--color-tile-edge`/`--color-tile-side` bands + a drop shadow) instead of an inset bevel; backs
are CSS jade (`--color-tile-back`/`--color-tile-back-edge` gradient, lighter top edge), no image
asset — `Back.svg` stays only for the canvas mural (§2), which draws tile art directly rather than
through `TileFace`.

Discard tiles are `clamp(30px, 3.2vw, 44px)` (up from `clamp(22px, 3.5vw, 36px)`) — legible at
arm's length without crowding the centre box at 390×844 or 1024×768. `.table-center` carries a
1px `--color-felt-line` outline (offset `--space-2`) as a zone guide, reading as a dealt-area
marking on the felt rather than UI chrome.

Seats are rendered relative to **your** seat, at the bottom. Wall count and prevailing wind live
in the page header. Dealer and turn are not repeated there: the dealer badge and the acting seat's
outline (`.seat-region--turn`) already show both. The turn indicator is a non-layout-affecting
outline because a text badge mounting/unmounting every turn shifted the seat header's
auto-positioned score. Desktop/tablet (≥768px):

```
  header: table/scenario · wall count · prevailing wind (東南西北) · chrome toggles

                    ┌─────────── opponent (across) ───────────┐
                    │       13 backs · melds · flowers        │
  ┌─────────┐       ├─────────────────────────────────────────┤       ┌─────────┐
  │ left    │       │     across's discard pool (top)         │       │ right   │
  │ opponent│       │                                          │       │ opponent│
  │ vertical│       │  left's   ┌──────────────┐   right's    │       │ vertical│
  │  strip  │       │  discards │    (empty)   │   discards   │       │  strip  │
  │         │       │  (rotated)│              │   (rotated)  │       │         │
  │         │       │           └──────────────┘              │       │         │
  │         │       │        YOUR discard pool (bottom)        │       │         │
  └─────────┘       ├─────────────────────────────────────────┤       └─────────┘
                    │  YOUR HAND: 13 faces, sorted, +drawn    │
                    │  tile held out at right, melds, flowers │
                    └─────────────────────────────────────────┘
```

**Discard pools: all four in the centre** (`.table-center`), forming a box — across on top,
left/right along the sides (rotated), self on the bottom — each still keyed to its own seat so
"who discarded this" stays legible. This mirrors a real table and keeps your own pool in view;
pools placed at each seat's edge put yours below your hand, easy to miss.

Each pool overflows toward the centre:

| Pool | Mechanism |
| --- | --- |
| left | `grid-auto-flow: column` already advances rightward |
| across | wraps downward naturally |
| right | `direction: rtl` so auto-placed columns advance leftward (rotated faces are absolutely positioned, unaffected) |
| self | flex with `flex-wrap: wrap-reverse`, so overflow lines stack upward |

CSS: `grid-template-areas` for the four seat regions + centre; `transform`/`opacity` only in
animated paths.

Side columns are `minmax(88px, auto)`: they hug their vertical strips, so the centre column (and
your hand under it) gets the rest of the width.

**Hand sizing.** The hand sizes to its own seat region, not the viewport:
`.seat-region--self` is a `container-type: inline-size` container, and `YourSeatRegion`'s
`.hand-row` computes the tile width from `100cqi` so 13 tiles + the drawn tile (2px gaps, a
`--space-4` drawn-tile gap) always fit, at every breakpoint:

| Fit width | Tile |
| --- | --- |
| > 63px | capped at 63×84px |
| 44–63px | shrinks to fit |
| < 44px | stays 44px (touch target) and overlaps via negative `margin-inline-start`, same formula |

No horizontal scroll. Pinned by `table.e2e.ts` at 390×844 and 1024×768 (last tile and drawn tile
inside the viewport, clear of the right opponent at 1024).

**Side seats.** Left/right hand strips run top-to-bottom via `writing-mode: vertical-lr`/
`vertical-rl`, not `transform: rotate()` — rotate repaints in place without resizing the box the
grid reserves, so the rotated footprint spills outside its grid area. Tiles inside are rotated 90°
to face the table: each `.mini-tile` keeps an unrotated box pre-sized to the landscape footprint,
and only the face inside is absolutely positioned and rotated (paint-only). Left/right discard
pools use the same technique (`.discard-tile`).

**Winds** render as Chinese characters (東/南/西/北), not the `E`/`S`/`W`/`N` code `seatWind()`
returns, with a full word via `aria-label` (`wind.ts`'s `windWord()`). In full sentences ("You're
seated as East") `windWord()` returns `WIND_LABEL`'s English word in `en` and `WIND_CHAR`'s glyph in
`zh-Hant`, so a Chinese sentence never embeds an English word.

Below 768px (phone portrait):

- Opponent hands collapse to a thin overlapping-backs strip; positional identity (§4) is still
  tracked.
- Each opponent's discard pool collapses to a horizontally-scrollable strip; full history stays in
  the DOM (§9).
- Your hand is `position: sticky; bottom: 0` with `env(safe-area-inset-bottom)` padding. It keeps
  its own last grid row (`auto 1fr auto`, the surface filling at least the rest of the viewport),
  so it starts at the bottom and nothing above needs padding reserved under it; the page scrolls
  rather than clipping when the table is taller than the screen.
- Claim buttons stay ≥44px, pinned above the safe-area inset.

## 4. Tile identity

The hand model keys elements by `tile_id`, so a tile drawn, held and discarded is one continuous
element — but the protocol only gives `tile_id` to the seat that owns the tile. Opponents arrive as
counts (`deal.counts`, `draw {seat}`, `{count: 13}`, `concealed_kong → {count: 4}`).

The client assigns a **positional** identity instead — stable per seat, opaque until revealed:

- Each opponent hand is a fixed slot array: `seat:0..12` (concealed) plus `seat:drawn`. Backs are
  interchangeable, so only element stability across a diff matters.
- `draw {seat}` (13→14): append `seat:drawn`.
- A discard carries the real identity (`discard {seat, tile_id, tile}`). The slot it left is
  chosen by a fixed rule: `seat:drawn` if it exists (covers tsumogiri), else the rightmost
  concealed slot (`seat:12`), with later slots shifting down. That element morphs face-up in place,
  then animates to the pool keyed by `tile_id`. From reveal onward its key is the real `tile_id`.
- `concealed_kong {seat, count: 4}`: remove 4 concealed slots (same rule: `seat:drawn` + the 3
  rightmost), replace with 4 backs in the meld area. `hand_end` reveals identity later.
- An open meld (`meld {seat, kind, tiles, from_seat}`) carries real ids directly.

Client-only bookkeeping — it doesn't touch the protocol or leak information. Opponent slot count
always matches the server's redacted `count`.

## 5. Interaction

Built today:

| Action    | Desktop and touch                                                                          |
| --------- | ------------------------------------------------------------------------------------------ |
| Discard   | one click/tap on a legal hand tile (a `.hand-tile-btn`) sends `discard` immediately         |
| Claim     | `ClaimDialog`: one button per offered option plus Pass, with a CSS countdown ring, ≥44px    |
| Declare   | win / concealed kong / added kong buttons under your hand (`.declare-actions`)              |
| Sort hand | automatic; no manual reorder                                                               |

**Planned, not built:**

| Action               | Desktop                                                       | Touch                       |
| -------------------- | ------------------------------------------------------------- | --------------------------- |
| Select tile          | hover lifts it, click selects                                 | tap lifts                   |
| Discard              | a setting: two-step (lift, then confirm) or one-tap (today's) | same, plus swipe up         |
| Inspect discard pool | hover shows who discarded and when                            | long-press                  |

- **Swipe vs. scroll (planned):** the swipe gesture is scoped to the lifted tile (`touch-action:
  none` on that element while lifted) with distance + direction thresholds, so the rest of the
  page scrolls normally. Tap-to-discard stays the safe default; swipe is a convenience on top.
- **Pre-arm toggles** ("no calls this hand", "auto-pass chow") are sent via `auto` and enforced
  server-side.
- **Claim buttons** appear only when the server offered them; never speculatively.
- **Claim/declare button labels** are the kind only ("Pung", "Concealed kong") plus small
  `TileFace` previews of the option's distinct tiles (`lib/ui/TileOptionLabel.svelte`), never
  raw codes. The previews are `aria-hidden`; the accessible name spells the tiles out
  (`tile-name.ts`'s `tileOptionAriaLabel`: "Chow: 4 Bamboo, 5 Bamboo").
- There is no faan/shanten preview — no protocol message carries it, and a TypeScript
  reimplementation would duplicate the pure Python engine
  ([ADR 0010](decisions/0010-client-scope-cuts.md)).

### Discard: pending state (planned)

Not built yet: today a discard click sends the intent and the tile simply stays put until the
echo arrives. The design:

A mobile round trip to one server is 100–300ms — long enough that a tile with no feedback between
tap and server echo reads as broken. Still no local mutation of game truth; a **pending**
presentation state instead:

- Sending `discard {tile_id}` adds a `pending` class to that tile (dimmed, non-interactive, small
  spinner). It stays in your hand, in place.
- The matching `discard` echo (or a superseding `turn`/`hand_end`) clears it, and the normal
  discard animation runs.
- A discard from the server's own `turn.legal` essentially can't be rejected, so there is no
  revert path. If no echo arrives within ~3s, the tile shows a stalled indicator, resolved by the
  normal reconnect/resync path (§6) — never a client-side guess.

### Claim window

The server closes claim windows **early** ([architecture.md §4](architecture.md)), so "buttons
are up" is not a stable client state:

| Scenario | Client behaviour |
| --- | --- |
| `claim_offer` received | Render offered options + PASS, keyed by `window_id`, and start the countdown ring. A new `window_id` fully replaces the previous set. |
| `claim_resolved` names this seat | Remove buttons immediately, play the meld/win animation. |
| `claim_resolved` names another seat while this seat's buttons were live | Remove buttons immediately, no fade — the option stopped existing. Toast only for a non-obvious loss (someone else won/konged the tile). |
| `claim_resolved` with no seat | Remove buttons immediately; play continues. |
| Local `claim` arrives after the window closed | Server drops it (stale `window_id`) or acks `{ok:false}`. Brief "too slow" toast; nothing else changes. |
| Dialog's own timer runs out before `claim_resolved` arrives | Auto-select `pass` through the same `onChoose` path as a click (`DialogTimer.svelte`), mirroring the server's own claim-timeout PASS ([protocol.md §4](protocol.md)). |
| A pre-armed toggle covers this offer | No buttons render — the server resolves it instantly. |

Accepted tradeoff: a click in the last few ms before the local timer fires can lose to the
auto-pass, since the server treats a seat's first-received choice as final. Preferred over a
dialog that never closes on its own. `hand_end_ack` gets the same auto-close with none of this
risk: it's an acknowledgment, and the table advances at the same `deadline_ts` regardless.

### Countdown mechanics

- The ring is a CSS animation (`animation-duration` set once from `deadline_ts - now`, `linear`),
  not a JS loop. Background tabs clamp JS timers to ≥1000ms; a CSS animation keeps compositing and
  is correct the instant the tab regains focus.
- The ring is cosmetic. `DialogTimer.svelte` pairs it with a one-shot `setTimeout`
  (`auto-close.ts`'s `scheduleAutoDismiss`, also used by `Toast.svelte`) on the same
  `durationMs`; the timeout, not the ring, calls `onClose`. Used by the claim dialog (auto-pass)
  and the hand-end hold (auto-ack). The turn ring has no `DialogTimer` — the server alone handles
  tsumogiri on expiry.
- **No clock-offset correction** ([protocol.md §4](protocol.md)): the ring reads early/late by the
  client clock's drift.

## 6. Client state

```ts
// lib/game/state.ts — plain data, no runes, so lib/net/reducer.spec.ts can test it directly
interface ClientGameState {
  seat: number | null; // learned from state_sync.seat once joined
  handNo: number;
  prevailing: string;
  dealer: number;
  turn: number;
  phase: string;
  ownHand: number[]; // real tile_ids — this seat's own concealed hand only
  concealedCounts: number[]; // length-4, count-only for every seat incl. this one
  melds: MeldState[][]; // length-4; concealed_kong is {tiles:null,count} until reveal
  discardPools: number[][]; // length-4, append-only, indexed by pool_index
  flowers: string[][];
  wallRemaining: number;
  seatStatus: string[];
  names: (string | null)[];
  hostSeat: number | null;
  hands: number[][] | null; // open-hands spectator only
  scores: number[];
  legalActions: Record<string, unknown>[]; // this seat's turn options, else []
  deadlineTs: number | null;
  claimOffer: {
    windowId: number | null;
    options: Record<string, unknown>[];
    deadlineTs: number | null;
  } | null;
  lastHandEnd: HandEndState | null; // latest hand_end only — the just-finished-hand overlay
  handHistory: HandHistoryEntry[]; // every hand_end seen, oldest first (below)
  gameEnd: GameEndState | null;
  shutdownDeadlineTs: number | null;
}

// lib/game/store.svelte.ts
class GameStore {
  state = $state<ClientGameState>(initialClientGameState());
  connection = $state<ConnectionStatus>("idle"); // mirrors the socket's own status
  seq = $state<number | null>(null); // last seq applied — UI/debug bookkeeping only
  version = $state(0); // bumped every apply(); non-reactive-consumer signal

  constructor(socket: MahjongSocket) {
    /* $effect.root(() => { $effect(() => socket.onEvent(...)); ... }) */
  }
  #apply(event: ServerEvent) {
    this.state = reduce(this.state, event);
    this.version++;
  }
  destroy(): void {
    /* disposes the $effect.root */
  }
}
```

Rules:

- The reducer is pure and exhaustively switched over the generated `ServerEvent` union, so
  TypeScript flags unhandled events ([protocol.md §6](protocol.md)).
- **Sequence numbers are per-seat** — a gap on your own stream triggers a resync request, never a
  silent patch.
- Deep-reactive fields are Svelte proxies. Non-reactive consumers (a worker, a non-Svelte helper,
  structural comparisons) get `$state.snapshot(store.field)` plus `store.version` as a cheap "did
  anything change" check — never the live proxy.
- Code that subscribes outside a `.svelte` file throws `effect_orphan` unless wrapped in
  `$effect.root(() => { ... })` with an explicit disposer — a module isn't an effect owner.
- Table-surface components read the store directly and let keyed `{#each}` (by `tile_id`, or the
  positional id from §4) diff the DOM. There is no manual DOM diff.

### Socket (`lib/net/socket.ts`)

`MahjongSocket` owns wire-level correctness; `GameStore`'s `seq` is only a read-model mirror.

- **Intents:** `join`/`ready`/`startWithBots`/`discard`/`claim`/`declare` (+ `declareWin`/
  `declareConcealedKong`/`declareAddedKong`)/`auto`/`ping`, each with a fresh idempotency `id`
  (`crypto.randomUUID()`-derived; [protocol.md §1](protocol.md)). There is no client-side retry.
- **Seq-gap detection:** tracks `lastSeq`. `state_sync` is always accepted as a full replace;
  `seq <= lastSeq` is a stale duplicate and ignored; `seq > lastSeq + 1` is a gap — the frame is
  dropped and `#requestResync()` re-sends `hello{last_seq, seat}` on the live connection
  ([protocol.md §5](protocol.md)'s branch is keyed only on `last_seq`, so asking mid-connection is
  the same request). `status` is `'resyncing'` meanwhile.
- **Reconnect:** unexpected closes reconnect with backoff (`min(250ms * 2^attempt, 10s) ± 20%`).
  `connect(resume?)` accepts `{lastSeq, seat}` to seed a fresh instance.
- **Connect URL:** adds `&spectate=true` whenever there is no persisted seat to resume, so the page
  gets real seat occupancy before joining (§7 "Join flow").

### Persistence

All `localStorage` access (`lib/ui/settings-storage.ts`) is wrapped in `try/catch` and falls back
to defaults on missing, corrupted or blocked storage — the page must render in private browsing.

| Key | Holds | Notes |
| --- | --- | --- |
| `mahjong:seat:v2:<tableId>` | this browser's seat at that table (`saveSeatForTable`/`loadSeatForTable`) | saved the moment `state_sync` confirms a seat; fed back into `connect()` on mount. Without it a reload falls into the seat picker and `join` fails with `table_full` |
| `mahjong:reconnectSecret:v2:<tableId>` | `join`'s `reconnect_secret` (`saveSecretForTable`/`loadSecretForTable`) | presented on every `hello{seat, secret}` ([architecture.md §2.1](architecture.md)); stale `v1` keys are swept on load |
| `mahjong:clientPrefs:v1` | `soundEnabled`, `motion` | purely local |
| `mahjong:autoArm:v1` | `no_calls`, `auto_pass_chow` | see below |
| `mahjong:displayName:v1` | guest display name | prefilled on the seat picker, saved on every keystroke |

`lastSeq` is not persisted: a reload has lost the in-memory reducer state anyway, so it needs a
full `state_sync`.

**`autoArm` is re-asserted, not read back.** No wire event reports a seat's auto-arm state, so the
persisted value is this client's last known intent. Once a fresh live connection seats us,
`+page.svelte` re-sends it via `socket.auto(...)` exactly once for that connection, pulling the
server back in line. Live mode only (`?mock=` has no socket). Making the server the source of truth
would need a wire field first.

**Display name is sent once.** It travels only on `join` (`MahjongSocket.join(seat?, name?)`); the
server trims/caps/defaults it, so the client doesn't validate. `ClientGameState.names` carries every
seat's *resolved* name back: set from `state_sync.names`, kept live from `seat_state.name`. Bot
seats get a random per-table-unique display name (`server/app/table.py`'s `_draw_bot_name`, from
`_BOT_NAME_POOL`) — cosmetic, not the tier.

### Hand history

`hand_end` accumulates into `handHistory`, not just `lastHandEnd` — `game_end` carries no per-hand
breakdown, so the score sheet needs the running list.

- `dealer`/`prevailing` aren't on `hand_end`; the reducer captures them off `state` when it sees
  the event (only `hand_start` changes them).
- `HandHistoryEntry.winnerMelds` snapshots `state.melds[winner]` at `hand_end` (`null` for a
  draw). The live overlay reads melds from the seat directly, but that resets on the next
  `hand_start`; the snapshot keeps past rounds renderable.
- A `state_sync` merges its `hand_history` field ([protocol.md §3](protocol.md)) into what the
  session already accumulated, by `handNo` (`reducer.ts`'s `mergeHandHistory`), so a resync or late
  join still has every past hand.

### `state_sync` and resync

A `state_sync` is a store replace — set every field from the snapshot, bump `version`. Keyed
`{#each}` blocks reconcile existing elements automatically, so there is no teardown path.

On reconnecting to your own seat after the `AUTOPLAY` handover
([architecture.md §8](architecture.md)), the snapshot already reflects what the bot did; missed
turns are not replayed as animation.

**Planned, not built:** a brief CSS crossfade on the table container (`motion-ok` only, §9) so a
full resync reads as "refreshed," not a glitch; and a one-line dismissable banner, shown once,
saying the bot played for you during the `AUTOPLAY` handover.

### Wire-shape gotchas

The mock fixtures hardcode values the real wire doesn't send this way:

- The reducer clears `legalActions` and `deadlineTs` on this seat's own `discard`. Stale entries
  would render legal-looking discard buttons the server then drops as out-of-turn. Pinned by a
  `reducer.spec.ts` regression test.
- `prevailing` goes over the wire as the `Wind` enum's member _name_ (`"EAST"`…), not the
  `'E'|'S'|'W'|'N'` code mocks use and `WIND_LABEL` indexes by. `live-view.ts`'s
  `wireWindToCode()` maps it — the one enum-shaped field needing this; `phase`/meld `kind`/claim
  `kind` serialize through `StrEnum.value`.
- `hand_end.faan_breakdown` keys are Chinese pattern names. `lib/ui/faan-pattern-labels.ts`'s
  `faanPatternLabel()` maps all 36 patterns to the active locale and passes anything unrecognized
  through, so mock fixtures' English literals render unchanged.

## 7. Routes

| Route | SSR | Notes |
| --- | --- | --- |
| `/` | on | lobby: "Create a table", "Join a game" (→ `/tables`), "Practice vs Bots", "Faan guide", a language toggle, over the mural |
| `/tables` | on | table browser; fetches its listing client-side |
| `/demo` | on | dev component demos, no backend |
| `/table/[id]` | off (`export const ssr = false`) | the game; WebSocket and per-seat redacted state are client-only, so pre-rendering an empty table to hydrate over has no value |
| `/replay/[id]` | off | placeholder; blocked on a server replay endpoint ([ADR 0011](decisions/0011-replay-viewer.md)) |
| `/profile` | on | placeholder heading only |

The web image builds with adapter-node (`pnpm build`, `node build`), so SSR is on unless a route
opts out.

### API health gate (`ApiConnectGate`)

Every route except `?mock=`/`/demo` is wrapped in `lib/ui/ApiConnectGate.svelte` (mounted once in
the root `+layout.svelte`), which polls `GET /healthz` (`lib/net/lobby.ts`'s `waitForApiHealthy`)
before rendering the page. Without it a page looks interactive before the backend is reachable.

- Up to 5 attempts, backoff 1s, 2s, 4s, 8s (capped at 30s, unreachable at these defaults).
- Held at least 1s even if the first ping succeeds, so it never flashes for one frame.
- After a failure the panel shows the attempt count and a static "next attempt in Ns" line
  (`onRetryScheduled`) — static, per `web/AGENTS.md`'s no-JS-ticker rule.
- Exhausted: a "Can't reach the server" panel with a manual Retry.
- Claims mural visibility (§2) while up, releasing it as the page mounts.

### Create a table

The lobby's "Create a table" opens `CreateTableDialog.svelte`: preset radios, or "Custom" exposing
every `RuleSet` field except `multi_win`, grouped scoring/flow/variants/fairness/timing. Submitting
calls `POST /tables` ([protocol.md §10](protocol.md)) and navigates to `/table/<table_id>`. The
waiting room shows the resolved preset name (`PretableScreen.svelte`).

### Faan guide and language toggle

Two buttons under "Practice vs Bots". The language button calls `setLocale()` with the other locale
(label is the target language's own name, so it reads right in either locale); `LocaleSwitcher`
stays in `Settings`. "Faan guide" opens `lib/ui/GuideDialog.svelte`: one tab per faan count (1-8)
plus Limit, each a list of patterns with a description and a tile example. The dialog is a fixed
`90dvh` tall and the tab panel scrolls, so switching to a shorter tab doesn't resize it. The data lives in
`lib/ui/faan-guide.ts` (`GUIDE`, keyed by faan value; examples are strings of concatenated tile
codes, one group each); a spec pins it to `FAAN_PATTERN_LABEL` so a new pattern can't be left out.
Situational patterns (self-draw, last tile, ...) show the description only. A ruleset select (All or
one of the `RULESET_PRESET_OPTIONS`) hides patterns whose hand set the preset disables and tabs left
empty; `GUIDE_PRESET_RULES` mirrors the server presets' `hand_sets`/`min_faan`, and 雞糊 only
shows under All since every preset has `min_faan > 0` ([rules.md §7](rules.md)).

### Practice mode

"Practice vs Bots" opens `lib/ui/PracticeSetupDialog.svelte` before creating anything — bot tier is
fixed at table construction. Three radio groups, one per bot seat (Right opponent / Across / Left
opponent, matching `mock-game-state.ts`'s `relativeSeat` offsets; seat 0 is the human), each
Easy/Normal/Impossible ([bots.md §6](bots.md)), default Normal. Submitting sends `POST /tables`
with `{practice: true, bot_tiers: {1: …, 2: …, 3: …}}` and navigates to `/table/<id>?practice=1`.

`?practice=1` is this route's own param; the live-connect effect appends `&practice=true` to the
WS URL, which binds seats 1-3 at construction (`server/app/ws.py`'s `ws_endpoint`,
`Table.__init__(practice=..., seat_bot_tiers=...)`). The human still goes through the seat picker
(seat 0 is the only open slot). The toolbar label appends "· practice vs bots".

### `/table/[id]` wiring

`[id]` is a table id. A direct visit to an unknown id auto-creates the table on first WS connect
(`server/app/ws.py`'s `_get_or_create_table`).

| Query | Renders |
| --- | --- |
| (none) | live: a `MahjongSocket` at `${PUBLIC_WS_URL}?table=<id>` driven through `GameStore` |
| `?mock=<scenarioId>` (or bare `?mock`) | a frozen `MOCK_SCENARIOS` fixture, no backend — used by the screenshot workflow (`.claude/skills/frontend-screenshots/SKILL.md`) and design iteration |
| `?pregame=connecting\|join\|waiting` | freezes one pre-game state (below) with no socket — mock scenarios are always fully seated |

**Tab title.** `<svelte:head><title>` reads live turn/claim state: "Your turn · Mahjong" while this
seat has a legal discard, "Claim? · Mahjong" while a claim offer is open, else "Table `<id>` ·
Mahjong". Mock scenarios are frozen snapshots, not live turn state, so they always show the
generic table title regardless of which scenario is selected.

**One view model, two sources.** `lib/table/live-view.ts`'s `viewFromClientState()` projects a real
`ClientGameState` into the same `MockGameState` shape the template renders, so mock and live share
one render tree (`TileFace`/`ClaimButtons`/`TimerRing`/`FaanBreakdown`/`ScoreSheet`/…) and can't
visually drift. Mock tiles are bare `TileCode`s; `LiveTableView.ownHand` carries the real
`tile_id`s index-aligned with `concealedHand`/`drawn`, so a clicked tile maps to a real intent.

**Join flow.** No auto-join: a live table shows a seat picker that sends `join{seat, name?}` for
the clicked seat. Sitting down implies readiness — `ready` fires right behind a successful join.
Until all four seats are joined and ready, the page shows a waiting screen. The picker has real
occupancy data before joining because the socket connects with `&spectate=true` when there's no
persisted seat, getting a spectator `state_sync` with every seat's `seat_status`/`names`; `join`
promotes the connection off spectator status ([architecture.md §3](architecture.md)).

### Pre-game states

Connecting, seat picker and waiting are recurring moments in a multiplayer game, so they use the
app's panel/button vocabulary (`panel-elevated`, `_buttons.scss`). All three share one panel —
table code plus a "copy invite link" button (the table URL _is_ the invite) — and a seat ring: four
slots arranged across/left/right/self like `layout.seat-region-grid`.

- **Before joining:** each slot is a `<button>` (`seatPicker`/`seatPickerSlot`) reading
  `seatStatus`/`names` — "Open" and clickable, or the occupant's name/"Bot" and disabled.
- **After joining:** the ring (`seatRing`) keeps the self slot on real wind (the dealer is fixed
  at construction) and the other three become a live occupancy readout (`seatOccupancySlot`, kept
  current by `seat_state`). A toast ("`{name} took a seat.`") fires the first time each other seat
  flips to `connected`/`bot` before the game starts.
- **Host: start with bots.** The first seat to `join` is the host (`state_sync.host_seat`). While
  waiting, the host alone sees "Start with bots", which sends `start_with_bots {}`: the server binds
  every empty seat to a bot (`_bind_bot_seat`) and deals once every seat is bound and ready. The
  server enforces host-only and not-started (`Table.start_with_bots`); the button is a convenience.

**Detecting "game started".** `state_sync` has no "started" field, and `new_game()` deals hand 1
at table construction, before any `ready` — so the first joiner's snapshot already shows a dealt
hand. The client flips a local flag permanently once either the snapshot shows play in progress
(non-empty discards/melds, `hand_no > 1`, a nonzero score) or a post-start event arrives
(`hand_start`/`turn`/`draw`/…). A real `started` field on `state_sync` would remove this
heuristic.

### Table browser (`/tables`)

A join-by-code form and a responsive grid of table cards (`repeat(auto-fill, minmax(16rem, 1fr))`)
showing code, open/in-progress and all four seats. Polls `GET /tables` every 5s
([protocol.md §10](protocol.md)), open tables first. "Sit down" and "Watch" both go to
`/table/<id>`, which decides picker vs. spectator itself, so a table that fills between poll and
click still lands sensibly. If the browser holds a reconnect credential for the table, the card
shows "Rejoin".

### Spectating

`/table/[id]` renders a spectator view whenever this connection has no seat, a real `state_sync`
has landed (`handNo > 0`), and no seat is `empty`. The view is `viewFromClientState(state, 0)`:
seat 0 at the bottom as backs — unless the table shows spectators every hand (`state_sync.hands`),
in which case the reducer keeps `ClientGameState.hands` live from `draw`/`kong_replace`/`discard`/
`meld` and every seat renders face-up and sorted. No discard/declare/claim controls, no Settings
(auto-arm is per-seat), and the hand-end overlay dismisses locally instead of sending
`hand_end_ack`.

### Leave game

Every `/table/[id]` view has "Leave game" instead of a plain back link. Holding a seat (`isPlayer`:
not mock, `effectiveSeat !== null`, including the pre-start waiting room) confirms first ("Your
seat switches to autoplay until you reconnect"); otherwise it navigates straight to `/`. Either way
`goto('/')` runs the socket effect's cleanup, which disconnects.

### Bot seat badge

`MockSeatState.status` (populated from `ClientGameState.seatStatus` by `viewFromClientState`, never
set by mocks) drives a `.bot-badge` chip ("Bot") next to the dealer badge when `status === 'bot'` —
a quiet bordered chip, not `--color-accent`, since a bot seat doesn't change mid-hand. Other
statuses have no visual treatment.

### Game-end summary

`ClientGameState.gameEnd` (from `game_end`) shows `GameEndScreen.svelte`, auto-shown and not
dismissable. `game_end` only fires after the final hand's hold resolves, so nothing in progress is
preempted — but the hold overlay normally clears on the next `hand_start`, which never comes, so
`+page.svelte` gates it on `!gameEndReached` and the game-end screen replaces it.

- Reuses `ScoreSheet` (score table, running totals, `standings`) plus a "game over" frame and a
  link home; there is no rematch flow.
- `ScoreSheet`'s per-round expand: when `HandRecord.result` (a `RoundResult`) is present, the hand
  number becomes a toggle revealing that round's winning hand via `FaanBreakdown`'s tile rendering,
  or "Exhaustive draw". Serves both the mid-game "Score sheet" toggle (`mockRoundResult`) and the
  game-end screen (`liveRoundResult`, converting `winnerMelds`/`winningHand` tile ids to
  `TileCode`s as `live-view.ts` does).
- Mock: `mock-game-state.ts`'s `gameJustEnded` (`?mock=game-ended`) is a frozen `GAME_OVER`
  snapshot carrying `MockGameState.gameEnd`; `+page.svelte`'s `gameEndReached`/`scoreHands`/
  `scoreStandings` branch on `isMock` rather than forking the render path.

## 8. Assets and styling

### Assets

- **Tile art:** [samoheen/mahjong-tiles](https://github.com/samoheen/mahjong-tiles), public-domain
  SVG Hong Kong set, vendored in `web/static/tiles/` (credited in `NOTICE`): all 42 faces (Man1-9,
  Pin1-9, Sou1-9, Ton, Nan, Shaa, Pei, Chun, Hatsu, Haku, Flor1-4, Seas1-4). The back (`Back.svg`)
  is this project's own: a flat `--color-border` (`#4a3826`) rounded rect matching the set's
  300×420/rx40 geometry.
- **Rendered via `<img src>`**, not inlined/`<use>`: the vendored SVGs carry non-namespaced ids
  (clipPath/filter/gradient) that collide when tiles are inlined more than once. `<img>` isolates
  each instance, at the cost of `currentColor` styling.
- **No build step, no atlas, no DPR split** — SVG is resolution-independent.
- **Sound (planned, deferred):** draw click, discard clack, shuffle — short, preloaded, muted
  until opt-in. Settings' "Sound effects" toggle is persisted but nothing plays yet. No recorded
  call-outs ([ADR 0010](decisions/0010-client-scope-cuts.md)).

### Styling: SCSS

SCSS (`sass`, Dart implementation) through Vite; component styles use `<style lang="scss">`. It
compiles to plain CSS, so it's an authoring-layer choice only.

```
src/lib/styles/
  _tokens.scss      colour (walnut chrome, felt/rim/tile materials, accent, brass, ±deltas),
                    spacing, radii, type scale, motion durations/easings, z-layers
  _buttons.scss     btn-primary/secondary/ghost, panel-elevated, modal-scrim, input-recessed
  _forms.scss       panel-header/title/badge, form-group, option row chrome
  _tile.scss        seat-meta/dealer-badge/tile-row/mini-tile/meld mixins shared by every
                    seat-hand-strip implementation -- per-face geometry stays in TileFace
  _layout.scss      seat-region grid, breakpoint mixins
  _a11y.scss        mixins only: focus-ring, sr-only, motion-ok/motion-reduced (§9), and
                    `globals` (the :focus-visible ring and .sr-only class) that app.scss emits
  app.scss          entry: tokens, layout, a11y globals, global resets
```

Tokens (`_tokens.scss`, all CSS custom properties on `:root`):

| Group | Tokens | Use |
| --- | --- | --- |
| chrome | `--color-bg/surface/surface-raised/border/text/text-muted` | walnut app chrome |
| table materials | `--color-rim`, `--color-rim-hi`, `--color-felt`, `--color-felt-deep`, `--color-felt-lit`, `--color-felt-line`, `--color-text-on-felt`, `--color-felt-muted` | dark green felt inside a walnut rim, applied to `.table-surface` (`routes/table/[id]/+page.svelte`) |
| tile body | `--color-tile`, `--color-tile-ink`, `--color-tile-edge`, `--color-tile-side`, `--color-tile-back`, `--color-tile-back-edge` | face, edge/side layers, jade back |
| signal | `--color-accent`, `--color-accent-glow` | the one urgent signal (turn, claim window, win marker); never decorative |
| highlight | `--color-brass` | selection, focus ring, your own seat, dealer; never a signal |
| deltas | `--color-positive`, `--color-negative` | score/faan gains and losses only |
| seats | `--color-seat-right/across/left` | opponent seat hues (self uses brass) |
| status | `--color-status-error`, `--color-rank-gold/silver/bronze` | error states; game-end podium |
| shape/type/space | `--radius-sm/md/lg`, `--radius-tile`, `--space-1…8`, `--font-size-xs…2xl`, `--font-size-display`, `--tap-target-min` | |
| motion | `--dur-1` 120ms … `--dur-4` 600ms, `--ease-out`, `--ease-place` (overshoot) | wrap motion in `a11y.motion-ok` (§9) |
| layers | `--z-table/tiles/hud/overlay/modal` | |

Conventions:

- `@use`, never `@import` (deprecated, leaks globals).
- SCSS variables **only for compile-time values** (breakpoints, the tile aspect ratio in `calc()`).
  Anything toggled at runtime is a CSS custom property (`--tile-w`, `--seat-accent`) — SCSS
  variables don't exist in the browser.
- Nesting: two levels maximum. Svelte already scopes styles; deep nesting defeats the flat
  selectors the table surface needs.
- Mixins for the four seat rotations and the breakpoint set; avoid mixins that emit layout.
- Keep the tile rule set flat — the hot path is a transform on a keyed element, one class plus
  custom properties. `@extend` and deep nesting cause selector bloat on ~150 elements.

## 9. Accessibility and i18n

### i18n

English and zh-Hant via Paraglide JS — runes-native and SSR-safe, unlike store-based libraries
(`svelte-i18n`) that risk locale bleed across SSR requests.

| Aspect | Detail |
| --- | --- |
| Locale strategy | cookie only (`['cookie', 'baseLocale']`), no URL prefix, so invite links (`/table/ABC123`) stay locale-agnostic. `lib/i18n/LocaleSwitcher.svelte` (in `Settings.svelte`) writes the cookie and reloads |
| Sources | `messages/en.json`, `messages/zh-Hant.json`, edited directly |
| Generated | `src/lib/paraglide/` — never hand-edited; `pnpm run paraglide:compile` (wired into `build`/`check`) |
| Keys | semantic, namespaced `component_field` (e.g. `lobby_createTableButton`), called as `m.lobby_createTableButton()`; interpolation via `{placeholder}` args |
| Cantonese terms | 碰/上/槓/食糊 stay as glyphs in both locales, UI and live-region text |

**Adding a message:** `import { m } from '$lib/paraglide/messages.js'`; add the key to **both**
locale files in the same change — a missing key falls back to English silently
(`web/AGENTS.md`'s "No literal user-facing strings").

**Plurals:** the inlang plugin (`@inlang/plugin-message-format@4`) does *not* support flat ICU
strings like `"{count, plural, one {...} other {...}}"` — it compiles but mangles the braces into
garbage placeholders. Use the variant-array form:

```json
"concealedTiles_count": [{
  "declarations": ["input count", "local countPlural = count: plural"],
  "selectors": ["countPlural"],
  "match": {
    "countPlural=one": "{count} concealed tile",
    "countPlural=other": "{count} concealed tiles"
  }
}]
```

zh-Hant has no grammatical plural; every variant there is the same phrasing.

**Not translated, deliberately:** fixture/dev-only strings — `mock-game-state.ts`'s
`MOCK_SCENARIOS` labels and `MockTableToolbar`'s scenario picker (read verbatim by
`table.e2e.ts`), `AnimationDemoPanel` controls, demo `data-testid` readouts. `lib/table/wind.ts`'s
`WIND_LABEL` is only ever interpolated into already-translated messages.

**Tile names.** `lib/table/tile-name.ts`'s `tileName(code)` maps every `TileCode` to a localized
spoken name (`tileName_<code>` keys: "3 Bamboo"/三索, "Red Dragon"/紅中, "Plum Flower"/梅) —
`TileFace`'s `alt`, discard/claim/declare `aria-label`s. A raw code (`z5`) never reaches a
player. `tile-name.spec.ts` pins the map to `TILE_ASSET` and both locale files. `TileFace` also
sets `data-tile="<code>"` as the locale-independent hook specs match on.

Tests assert on `data-testid`/stable classes for core flows, not English wording. Locale switching
and SSR `<html lang>` have e2e coverage (`lib/i18n/locale-switch.e2e.ts`, `hooks.server.e2e.ts`).

The zh-Hant file (406/406 keys, parity-checked) is machine-generated and not yet reviewed by a
fluent Hong Kong mahjong player.

### Accessibility

- **Colourblind-safe:** dragons are distinguished by glyph, not just red/green.
- **Focus:** `_a11y.scss`'s global `:focus-visible` ring (2px `--color-brass`, 2px offset) covers
  every control; components don't restyle it.
- **Keyboard:** legal hand tiles are native `<button>`s in normal tab order, `Enter`/`Space`
  discards — the same elements pointer and touch use, so there is one selection model.
  **Planned:** roving `tabindex` over the hand with arrow keys moving focus, and `Enter`/`Space`
  lift-then-discard once the two-step discard setting exists (§5).
- **Names:** tiles are announced by localized name, never code (§9 i18n "Tile names").
- **Reduced motion:** Settings' Motion radio (`system`/`reduced`/`full`, persisted in
  `clientPrefs`) is mirrored onto `html[data-motion]` by `lib/ui/motion.ts`'s `applyMotionPref`
  — from the root `+layout.svelte` on load, and on every Settings change. `reduced`/`full`
  override the OS; `system` defers to `prefers-reduced-motion`.
  - CSS: `_a11y.scss`'s `motion-ok` mixin emits its content only when motion is allowed —
    the default for new motion (toast entry, timer ring). `motion-reduced` is the inverse, for
    neutralizing motion a base rule must keep (seat-slot breathing, spinners, mural fade, the
    animation demo's near-instant transitions).
  - JS: `isMotionReduced()` applies the same resolution (the mural canvas checks it once at
    mount).
  - State changes always apply instantly; only the motion is dropped.
- **Discard pools** are real DOM and stay fully present when visually truncated on mobile.

**Designed, not implemented:** per-discard announcements. Intended shape: each discard a focusable
`role="listitem"` in a per-seat `role="list"` with `aria-label="{seat} discarded {tile}, turn {n}"`,
plus an `aria-live="polite"` region with one line per discard. At ~80 discards/hand, default
verbosity would announce claim-relevant discards, claim results and hand end, with a setting for
"every discard". `CenterDiscardPool.svelte` has none of this yet.
