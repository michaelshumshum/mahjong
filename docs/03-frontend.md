# 03 — Frontend

Answers [05-roadmap.md §5](05-roadmap.md) open question #1 (rendering): **DOM/CSS, not PixiJS.**
~150 static, axis-aligned, rectangular tiles with no tick loop doesn't need a canvas renderer.

## 1. The split

```
┌─────────────────────────────────────────────────────────────┐
│ SvelteKit app (all DOM/CSS — no canvas)                      │
│                                                                │
│  Routes                │  Table route                        │
│  /            landing  │  ┌──────────────────────────────┐   │
│  /lobby       rooms    │  │ table surface (DOM/CSS)       │   │
│  /table/[id]  game     │  │   felt, wall, 4 hands, melds, │   │
│  /replay/[id] viewer   │  │   discard pools, dice, hints  │   │
│  /profile     stats    │  └──────────────────────────────┘   │
│                        │  overlay (Svelte):                  │
│                        │   claim buttons, timer ring,         │
│                        │   faan breakdown, score sheet,       │
│                        │   chat, settings, toasts             │
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

Seats are always rendered relative to **your** seat, at the bottom. Desktop/tablet (≥768px):

```
                    ┌─────────── opponent (across) ───────────┐
                    │  13 backs · melds right · flowers left  │
                    │  discard pool: 6 cols × N (their side)  │
  ┌─────────┐       ├─────────────────────────────────────────┤       ┌─────────┐
  │ left    │       │                                         │       │ right   │
  │ opponent│       │    wall count · prevailing wind ·       │       │ opponent│
  │ vertical│       │    dealer marker · turn indicator       │       │ vertical│
  │  strip  │       │                                         │       │  strip  │
  │ discard │       ├─────────────────────────────────────────┤       │ discard │
  │  pool   │       │  YOUR HAND: 13 faces, sorted, +drawn    │       │  pool   │
  └─────────┘       │  tile held out at right, melds, flowers │       └─────────┘
                    │  discard pool: 6 cols × N (your side)   │
                    └─────────────────────────────────────────┘
```

Discard pool geometry: **per-player**, at that player's edge of the table — resolves the earlier
ASCII-vs-bullet conflict (the diagram showed one shared centre pool, the bullet said per-player;
per-player wins). Matches physical play, keeps "who discarded this" legible without reading a
shared pool, and gives each pool independent scroll/collapse behaviour on small screens (below).

CSS: `grid-template-areas` for the four seat regions + centre; `perspective` + `rotateX` on the
table container for the 2.5D tilt; `transform`/`opacity` only in animated paths. No global scale
factor — each region sizes to its own content via `clamp()`.

Left/right opponent hand strips run top-to-bottom via `writing-mode: vertical-lr`/`vertical-rl`,
not `transform: rotate()` — rotate repaints the box in place without resizing the space its
parent grid cell reserves for it, so a rotated strip's actual (post-rotation) footprint can
extend outside its grid area into whatever sits past its edge. `writing-mode` reflows the flex
axes instead, so the element's own width/height already reflect the vertical footprint the grid
cell needs to reserve. Tile art stays upright (not rotated 90°) as a result — acceptable since
concealed backs are orientation-agnostic and exposed meld faces stay legible.

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
| CSS ring visually completes, no `claim_resolved`/`turn` yet (latency) | Buttons stay up but go visually inert (dimmed, non-interactive) until the authoritative event arrives. The ring is cosmetic; it never triggers client-side resolution. |
| A pre-armed toggle covers this offer (`auto`) | No buttons render — the server already resolves it as an instant choice. |

### Countdown mechanics

- Clock offset is measured via `ping`/`pong` using `performance.now()`, not `Date.now()` — the
  latter can jump under NTP slew or a user changing their system clock mid-measurement. Re-measure
  periodically (e.g. every 30s); anchor each individual countdown once, at render time.
- The ring is a CSS animation (`animation-duration` set once from `deadline_ts + offset - now`,
  `linear`), not a `setInterval`/`requestAnimationFrame` loop. Background tabs clamp JS timers to
  ≥1000ms, so a JS-ticked ring visibly stalls when the tab loses focus (e.g. during an opponent's
  long think); a CSS animation keeps compositing and is correct the instant the tab regains focus.
- The ring is cosmetic only; the authoritative close is the server event (claim table above, or
  `turn` for your own timeout).
- The protocol's chess-clock bonus-second bank ([02-protocol.md §4](02-protocol.md)) doesn't get a
  dedicated meter in v1 — deferred, see [99-deferred.md](99-deferred.md). The ring reflects only
  the current `deadline_ts`, which already folds in any bonus time the server granted.

## 6. Client state

```ts
// lib/game/store.svelte.ts
class GameStore {
  seq      = $state(0);        // last seq seen on THIS seat's own event stream (per-seat, not per-room — see below)
  version  = $state(0);        // bumped every apply(); cheap change signal for non-reactive consumers
  phase    = $state<Phase>('IDLE');
  seats    = $state<SeatView[]>([]);
  myHand   = $state<TileId[]>([]);
  drawn    = $state<TileId | null>(null);
  pool     = $state<Discard[]>([]);         // per-seat pools, see §3
  offer    = $state<ClaimOffer | null>(null);
  deadline = $state<number | null>(null);   // server ts, corrected by clock offset

  apply(ev: ServerEvent) { /* pure reducer, one switch, no side effects */ this.version++; }
}
```

Rules:

- The reducer is pure and exhaustively switched over the generated `ServerEvent` union, so
  TypeScript flags unhandled events.
- **Sequence numbers are per-seat**, dense and gapless within *your own* stream — not per-room. A
  room-wide seq would advance on every unicast `claim_offer`/`turn.legal` sent to other seats, so
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

### SSR

`web/Dockerfile` builds with `pnpm build` and runs `node build` — adapter-node, so SvelteKit SSR
is on by default for every route unless opted out. Posture:

- `/`, `/lobby`, `/profile` — SSR stays on; cheap, no live-socket dependency.
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
- Server-only time: every deadline is an absolute `deadline_ts` plus a measured clock offset,
  never a client-started duration.
- Always render yourself at the bottom, rotating the other three; seat wind is a badge, not
  position.
- The drawn tile sits apart from the sorted hand, as in physical play.
- The discard pool is append-only, ordered by discard sequence — never shuffled, never compacted.
