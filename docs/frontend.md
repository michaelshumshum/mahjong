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
tile back), blurred and dimmed by a CSS `filter: blur() brightness()` on the canvas plus a
radial-darkening scrim in front of it, so foreground content stays legible. Purely decorative (`aria-hidden`,
`pointer-events: none`), so it loses nothing the DOM would give. A DOM version would animate ~200
elements' `transform`; the canvas is one element whose `transform` a CSS animation slides up one
row, so scrolling runs on the compositor with no per-frame paint or JS.

| Behaviour | Detail |
| --- | --- |
| Tile faces | the same ivory `--color-tile` box `TileFace.svelte` uses; backs drawn without a box per `.tile-face--back`. No two backs share an edge (a cluster reads as a hole); adjacent cells never share a suit (honors and backs exempt) |
| Reduced motion | reduced motion (§9: the setting, else `prefers-reduced-motion`) renders the grid once, statically |
| Resize | the grid is persistent — a resize only appends cells to cover the new viewport, never re-rolls placed ones, so a spurious `resize` (webfont swap, scrollbar toggle) can't read as the mural "switching". Unchanged `innerWidth`/`innerHeight` short-circuits the handler |
| Scroll | the canvas is one row taller than the viewport; `@keyframes mural-scroll` translates it up by exactly one row, and each `animationiteration` (dispatched before that frame paints) advances `topRow` and redraws, so the reset is invisible. The grid grows rather than wrapping (wrapping reads as the layout snapping back) |
| Blur | CSS `filter` on the canvas itself, not a `backdrop-filter` on the scrim. The earlier `requestAnimationFrame` loop repainted the full-viewport canvas every frame, even while hidden, with a full-viewport `backdrop-filter` re-sampling it. The cursor flickered over every clickable element on macOS Chrome |
| Atmosphere (P3) | `blur(4px) brightness(0.42) saturate(0.55)` on the canvas, plus a darker centre scrim, read calmer behind the lobby/tables/waiting-room content column than P0's first pass — tuned in the scrim/filter values only, the CSS-transform scroll (below) is unchanged. P4's contrast audit (§8) raised the scrim's outer stops to ≥ 0.5 so muted text holds 4.5:1 anywhere |

**Mounted once, shared across routes.** The mural shows on `/`, `/tables`, and `/table/[id]`'s
pre-game states — never on the game table itself, mock or live. It is mounted once in the root
`+layout.svelte`; a per-route instance would tear down and rebuild the grid on every navigation
between mural routes. `lib/ui/mural-visibility.svelte.ts` holds the shared visibility state: a page
calls `claimMuralVisible()` (or `claimMuralVisible(() => condition)` for a route whose need varies)
from its `<script>`, which claims visibility in an `$effect` and releases it on unmount.

- Visibility toggles the canvas's CSS opacity (`transition: opacity 220ms`, skipped under
  reduced motion) and `animation-play-state`, so a hidden mural costs nothing and resumes where it
  stopped.
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
arm's length without crowding the centre box at 390×844 or 1024×768. Pool grid tracks are sized to the tile's
own footprint (`--discard-h` long edge, `--discard-w` short edge), so every pool, rotated or not,
has the same 2px gap. Discard faces drop `TileFace`'s thickness/drop `box-shadow`: it bled onto the
next row of the pool. `.table-center` carries a
1px `--color-felt-line` outline (offset `--space-2`) as a zone guide, reading as a dealt-area
marking on the felt rather than UI chrome.

Seats are rendered relative to **your** seat, at the bottom. Each seat's header is `SeatPlate`
(`lib/table/SeatPlate.svelte`): name, wind glyph, dealer badge, a slot for extra badges (the bot/
status chips on an opponent, nothing extra on your own), and the score.

**Header rail.** `TableToolbar` (`routes/table/[id]/_components/`) is the walnut rim's top edge, not
page chrome: the same `--color-rim` background with top-only `--radius-lg` corners, and
`.table-surface` drops to a 4px top border and bottom-only corners so the two read as one frame.
One row at every width, mock and live alike:

| Slot | Content |
| --- | --- |
| left | ghost "Leave game" button (chevron + label) |
| ident | the table code as a small tile-coloured chip (cousin of the waiting room's `.pretable-code`), then one brass tag: "Spectating" or "Practice" |
| status | the connection pill (§6), right-aligned |
| right | ghost icon buttons: Guide, Score sheet, Settings (Settings hidden while spectating) |

Below `tablet-up` every button goes icon-only, its label kept as an `sr-only` accessible name, so the
rail never wraps. It carries nothing seat- or hand-specific: your wind is on your `SeatPlate`,
wall/prevailing/hand on `CenterHub` (below, including its phone compact row). On phone landscape the
page hands `CenterHub` itself to the rail (a `hub` snippet prop, centred in the status slot as a
bare summary line): the rail's middle is otherwise empty, and the hub's own felt row cost ~40px of
a ~330px-tall surface. `+page.svelte` picks the one place to render it with a `MediaQuery` on
`lib/ui/breakpoints.ts`'s `PHONE_LANDSCAPE_QUERY` (kept equal to `_layout.scss`'s
`phone-landscape`), so there is only ever one `.center-hub` in the DOM. An earlier free-
standing toolbar (wood buttons on the page background, a "Table X · 東 · practice vs bots" label,
a phone-only wall/prevailing copy) wrapped to 3-4 rows on phones and duplicated both.

**Turn indication.** The acting seat's `SeatPlate` gets a red halo (`--color-accent` border plus a
`--color-accent-glow` box-shadow) and a gentle `motion-ok` pulse, via an absolutely-positioned
`::before` so the plate's own box — and the header's layout — never changes size between turns (the
original whole-region outline is gone from `OpponentRegion`, which previously shifted against the
felt grain; `.seat-region--turn` stays as a class-only hook so existing specs/e2e still find it,
carrying no visual rule of its own). Your own seat gets the same plate and no extra text prompt:
the halo, the hub's timer ring and the raised/clickable hand tiles already say it's your turn.
Desktop/tablet (≥768px):

```
  header rail: leave · table code · tags · guide/score sheet/settings

                    ┌─────────── opponent (across) ───────────┐
                    │       13 backs · melds · flowers        │
  ┌─────────┐       ├─────────────────────────────────────────┤       ┌─────────┐
  │ left    │       │     across's discard pool (top)         │       │ right   │
  │ opponent│       │                                          │       │ opponent│
  │ vertical│       │  left's   ┌──────────────┐   right's    │       │ vertical│
  │  strip  │       │  discards │  (CenterHub) │   discards   │       │  strip  │
  │         │       │  (rotated)│              │   (rotated)  │       │         │
  │         │       │           └──────────────┘              │       │         │
  │         │       │        YOUR discard pool (bottom)        │       │         │
  └─────────┘       ├─────────────────────────────────────────┤       └─────────┘
                    │  YOUR HAND: 13 faces, sorted, +drawn    │
                    │  tile held out at right, melds, flowers │
                    └─────────────────────────────────────────┘
```

**Centre compass hub.** `CenterHub.svelte` sits in `.table-center`'s own middle grid cell
(`grid-area: hub`, previously unused — the pools form a box around it, never over it): the
prevailing wind glyph, "Hand N", the wall-remaining count (`.wall-count strong`, pinned by
`table.e2e.ts`), a min-faan chip (this table's `RuleSet.min_faan`; mocks default to the server's own
default of 3 since no fixture carries a ruleset), and one small wind marker per seat positioned
toward that seat (top/left/right/bottom, matching the box above). The acting seat's marker gets the
same halo treatment as its `SeatPlate` and additionally carries `TimerRing`, for every seat's turn:
`turn` is broadcast with the acting seat's `deadline_ts` to all seats and spectators
([protocol.md](protocol.md)), and the reducer stores it as `ClientGameState.deadlineTs` (§6). The
ring shows only while `phase === 'AWAIT_ACTION'` — a `state_sync`'s own `deadline_ts` is this
seat's claim/hand-end deadline, not the acting seat's — so after a reconnect an opponent's ring
reappears with their next `turn`. Below
768px the pools leave the centre for their own seats (below), leaving the markers nothing to
point at, so the hub collapses to a compact single-row summary (wind/hand/wall/faan only, no
markers) — in its own felt row in portrait, in the header rail on phone landscape (above).

**Discard pools: all four in the centre** (`.table-center`, tablet-up), forming a box — across on top,
left/right along the sides (rotated), self on the bottom — each still keyed to its own seat so
"who discarded this" stays legible. This mirrors a real table and keeps your own pool in view;
pools placed at each seat's edge put yours below your hand, easy to miss.

Each pool overflows toward the centre:

| Pool | Mechanism |
| --- | --- |
| left | `grid-auto-flow: column` already advances rightward |
| across | your pool turned 180°: `direction: rtl`, so tiles run right-to-left and rows wrap downward; faces stay upright for legibility. The across hand strip gets the same `direction: rtl` (melds below, toward the centre) |
| right | the left pool turned 180° (`transform: rotate(180deg)` on the pool, faces rotated 90° so they net −90°): tiles run bottom-to-top and columns advance leftward, rotationally matching every other seat rather than mirroring the left one; `justify-self: end` keeps it against the seat |
| self | flex with `flex-wrap: wrap-reverse`, so overflow lines stack upward |

CSS: `grid-template-areas` for the four seat regions + centre; `transform`/`opacity` only in
animated paths.

Side columns are `minmax(88px, auto)`: they hug their vertical strips, so the centre column (and
your hand under it) gets the rest of the width.

**Meld rows are reserved.** Every seat's meld/flower row (`.meld-row`) is always rendered with a
`min-block-size` of one mini-tile (`_tile.scss`'s `meld-row-reserved`), so a seat's first meld or
flower doesn't grow its grid row/column and shift the centre box. Below 768px an empty row
collapses instead. Your own meld row sits above your name, toward the centre.

**Hands are centred** in their seat region at tablet-up: your `.hand-row` (`justify-content:
center`; a spectator's bottom-seat `.backs-row` likewise), the across strip horizontally and the side strips vertically (`.seat-hand-strip` fills
its region with `align-items: center`). Melds and flowers don't centre: an opponent's `.meld-row`
is `align-self: start`, the seat's own left once the strip is rotated. Your hand recentres by half a tile when the drawn tile
comes and goes.

**Hand sizing.** The hand sizes to its own seat region, not the viewport:
`.seat-region--self` is a `container-type: inline-size` container, and `YourSeatRegion`'s
`.hand-row` computes the tile width from `100cqi` so 13 tiles + the drawn tile (2px gaps, a
`--space-4` drawn-tile gap) always fit, at every breakpoint:

| Fit width | Tile |
| --- | --- |
| > 63px | capped at 63×84px |
| 44–63px | shrinks to fit |
| < 44px | stays 44px (touch target) and overlaps via negative `margin-inline-start`, same formula |

**Portrait phone** (`phone-portrait`: `phone-only` minus `phone-landscape`) wraps the hand into two
rows of 8 instead (`flex-wrap`, tile width `clamp(36px, fit-8, 63px)`, ~40px at 390px; a 7-tile hand
plus the drawn tile stays on one row) — one row of
14 overlapped to ~half a face there, hiding tiles and sending taps to the neighbour, while the
centre had height to spare. Page padding, rim and felt padding shrink there too (they took ~84px of
390). The rows sit `--hand-gap` (2px) apart, like the columns, and there is no top pad: on every
phone layout the hand sits flush under your `SeatPlate` (the self region's `row-gap: 0`). So a
lifted tile (`z-index: 1`, the desktop 30% lift) overlaps the plate or the row above. In portrait
it only takes taps in its own original slot (`pointer-events: none` on the button, `auto` on its
`::after` hit area), so a tap on the tile it overlaps reaches that tile instead of discarding the
lifted one (pinned by `YourSeatRegion.svelte.spec.ts`).

**Phone landscape** keeps one row, with tiles `clamp(44px, min(fit-14, 16dvh × 3/4), 56px)` —
height-bound, since the hand can't take more of a ~390px-tall screen. The bar is one grid:

| Hand | Grid | Why |
| --- | --- | --- |
| ≥ 12 slots (no meld yet) | `'plate melds actions' 'hand hand hand'` | flowers and declare buttons share the plate's line instead of each taking a row |
| ≤ 11 slots | `'plate plate actions' 'hand melds melds'` | each meld frees three hand tiles' width (~140px) for a ~65px meld, so the melds fit beside the hand and the plate line shrinks to the plate |

`.your-hand` is `display: contents` there so the hand row and `.declare-actions` are grid items; your
meld tiles drop to 26px (× tile scale), and the bar's vertical padding to `--space-1`.

No horizontal scroll; two-row, non-overlapping at 390×844. Pinned by `table.e2e.ts` at 390×844, 390×700, 844×390, 1024×768 and
1440×900 (last tile and drawn tile inside the viewport, clear of the right opponent at tablet-up),
plus claim buttons fully in view and clickable at 390×844, 844×390, 1024×768 and 1440×900, and the
first hand row flush under the plate at 390×844 and 844×390. Phone landscape also pins the box
placement (left/right side by side, the hub in the rail, your pool on your hand), the `late-hand`
fit at 844×390/740×360/667×375, and melds beside a short hand.

**Breakpoints** (`_layout.scss`; `tablet-up` and `phone-only` partition every viewport):

| Mixin | Query | Layout |
| --- | --- | --- |
| `phone-only` | `max-width: 767px`, or `max-height: 500px` | opponent chips each over its own wrapping pool, sticky hand bar (below) |
| `phone-landscape` | `max-height: 500px` and landscape | on top of `phone-only`: no page scroll; the table as a box — across chip and pool full width, left and right side by side under it, your pool on your hand (`'across across' 'pool-across pool-across' 'left right' 'pool-left pool-right' 'pool-self pool-self' 'self self'`; your pool's row is the `1fr` one, bottom-aligned), the hub in the header rail; chip tiles `clamp(20px, 5.6dvh, 26px)`, discard tiles 26px; the `late-hand` fixture fits without scrolling at 844×390, 740×360 and 667×375 (an earlier 3fr/2fr two-column stack overflowed 667×375 by ~120px and hid a whole opponent under the hand bar, with the right column half empty); if a hand still overflows, `.table-surface` itself scrolls (`overflow-y: auto`, no bottom padding) with the hand bar sticky at its bottom — rows are `minmax(min-content, …)` so the bar isn't squeezed; hand tiles 44–56px (above) |
| `tablet-up` | `min-width: 768px` and `min-height: 501px` | the box layout above |
| `desktop-up` | `min-width: 1180px` and `min-height: 501px` | roomier page and surface padding |

A phone held sideways (844×390) is wide enough for `tablet-up` but its vertical side strips (13
backs ≈ 350px) can't fit, so short viewports count as phone. **Container queries:** `.table-surface`
is a named inline-size container (`container: table / inline-size`); discard tiles, side-strip
tiles, the hub circle and the centre box's side tracks size in `cqi` of the table rather than `vw`,
since the toolbar, page padding and rim make the two differ.

**Side seats.** Left/right hand strips run vertically via `writing-mode` (`vertical-lr` on the
left; `vertical-rl` plus `direction: rtl` on the right, so its tiles run bottom-to-top — the left
seat turned 180°, not mirrored), not `transform: rotate()` — rotate repaints in place without resizing the box the
grid reserves, so the rotated footprint spills outside its grid area. Tiles inside are rotated 90°
to face the table: each `.mini-tile` keeps an unrotated box pre-sized to the landscape footprint,
and only the face inside is absolutely positioned and rotated (paint-only). Left/right discard
pools use the same technique (`.discard-tile`).

**Winds** render as Chinese characters (東/南/西/北), not the `E`/`S`/`W`/`N` code `seatWind()`
returns, with a full word via `aria-label` (`wind.ts`'s `windWord()`). In full sentences ("You're
seated as East") `windWord()` returns `WIND_LABEL`'s English word in `en` and `WIND_CHAR`'s glyph in
`zh-Hant`, so a Chinese sentence never embeds an English word.

Below 768px (phone portrait):

- All three opponents become compact chips, one full-width grid row each, each followed by its
  own discard pool (`left`, `pool-left`, `across`, `pool-across`, `right`, `pool-right`, then
  `center`, `pool-self`, `self`; `layout.seat-region-grid`) — three chips side by side left each
  ~99px, with 18px meld tiles wrapping after four. Each chip is one wrapping flex line: the
  `SeatPlate` (fixed 8rem so the counts align, long names truncate), a single jade back with a `×N`
  count (`.backs-count`, `aria-hidden` — the row's own label already states the count), then
  the flower group and each meld at 28px tall. The strip and meld row are `display: contents`, so
  every meld is its own flex item: flowers join the name line when they fit and a meld wraps
  whole to the next line, never split across two. The single back matches the meld height so it
  never sets the name line's height. Phone landscape uses the same chip, full width (across) or half width (left/right). The other backs stay in the DOM, hidden
  (`display: none`), so positional identity (§4) and the specs counting `.backs-row .mini-tile`
  are unchanged.
- Each discard pool is a full-width wrapping row (no horizontal scroll — a single-row strip ran
  past the viewport late in a hand) placed under its own seat: `.table-center` is
  `display: contents`, so the hub and the four pools are `.table-surface` grid items and each pool
  takes its seat's `pool-*` area. An opponent's pool pulls up by the grid gap and shares the chip's
  tint with only its bottom corners rounded (the chip's are squared), so chip and pool read as one
  card; your own pool is a separate tinted card just above the sticky hand bar (portrait) or under
  the hub (landscape) — inside the bar, under your melds, it would grow the sticky bar by ~2 tile
  rows late in a hand. Placement says whose pool it is, so there's no seat-name label (an earlier
  `::before` label cost 3.25rem of every row). Still exactly four pools in the DOM, one list each
  (`aria-label` names the seat); full history stays in the DOM (§9). The hub centres in whatever
  height is left over. The `late-hand` mock scenario (full pools, 4 melds + 3 flowers) is the
  stress fixture for all of this.
- Your hand is a `position: sticky; bottom: 0` bar with `env(safe-area-inset-bottom)` padding.
  `app.html`'s viewport meta carries `viewport-fit=cover` — without it every `env(safe-area-inset-*)`
  resolves to 0 on iOS — and `body` pads by the side insets for landscape notches. It keeps
  its own last grid row (`auto 1fr auto`, the surface filling at least the rest of the viewport),
  so it starts at the bottom and nothing above needs padding reserved under it; the page scrolls
  rather than clipping when the table is taller than the screen. `.table-surface` clips its
  rounded corners with `overflow: clip`, not `hidden` — `hidden` makes it a scroll container and
  the sticky row would then stick within the surface, scrolling off-screen with it.
- Claim buttons stay ≥44px, pinned above the safe-area inset.

## 4. Tile identity

The hand model keys elements by `tile_id`, so a tile drawn, held and discarded is one continuous
element — but the protocol only gives `tile_id` to the seat that owns the tile. Opponents arrive as
counts (`deal.counts`, `draw {seat}`, `{count: 13}`).

The client assigns a **positional** identity instead — stable per seat, opaque until revealed:

- Each opponent hand is a fixed slot array: `seat:0..12` (concealed) plus `seat:drawn`. Backs are
  interchangeable, so only element stability across a diff matters.
- `draw {seat}` (13→14): append `seat:drawn`.
- A discard carries the real identity (`discard {seat, tile_id, tile}`). The slot it left is
  chosen by a fixed rule: `seat:drawn` if it exists (covers tsumogiri), else the rightmost
  concealed slot (`seat:12`), with later slots shifting down. That element morphs face-up in place,
  then animates to the pool keyed by `tile_id`. From reveal onward its key is the real `tile_id`.
- `meld {seat, kind, tiles, from_seat}` carries real ids for every kind. A concealed kong removes 4
  concealed slots (same rule: `seat:drawn` + the 3 rightmost); the other kinds remove
  `tiles.length` minus the claimed tile.
- A concealed kong (暗槓) is drawn HK-style, both end tiles as backs and the middle two face-up
  (`lib/table/meld-face.ts`'s `meldTileFace`, used by every meld renderer — table and win
  screens alike; [ADR 0023](decisions/0023-concealed-kong-public.md)).

Client-only bookkeeping — it doesn't touch the protocol or leak information. Opponent slot count
always matches the server's `count`.

## 5. Interaction

Built today:

| Action    | Desktop and touch                                                                          |
| --------- | ------------------------------------------------------------------------------------------ |
| Discard   | legal hand tile (a `.hand-tile-btn`): one-tap mode discards immediately, two-step lifts then confirms |
| Claim     | `ClaimDialog`: one big button per offered option plus Pass, with a CSS countdown ring, ≥44px |
| Declare   | win (hero when self-drawn) / concealed kong / added kong under your hand (`.declare-actions`) |
| Sort hand | automatic by default; manual arrangement is a setting (below)                                |

**Double-tap zoom** is off app-wide: `html { touch-action: manipulation }` (`app.scss`), which
keeps pinch-zoom. Not a `touchend` `preventDefault` guard — on iOS that also cancels the synthesized
`click`, eating the second tap of a two-step discard. Hand tile buttons also drop the iOS tap
highlight, callout and text selection that rapid taps triggered.

**Discard mode.** A client pref (`ClientPrefs.discardMode`, `lib/ui/client-prefs.ts`, edited in `lib/ui/Settings.svelte`), default
`'two-step'`, persisted the same way as `motion`/`soundEnabled` (§6 Persistence):

| Mode | Desktop and touch |
| --- | --- |
| `two-step` | Tap/click a legal tile to lift it (`translateY`, `z-index` raised above overlapping neighbours so the full face stays visible even in phone's negative-margin overlap mode, §3). A second tap, or `Enter`/`Space` on the same (now-focused) button, discards it — the same `onclick` path, no separate key handling needed. Tapping a different tile just moves the lift; clicking outside the hand or pressing `Escape` clears it with no discard. Hovering a tile previews the lift on fine pointers only (`@media (hover: hover) and (pointer: fine)`, both modes) — a CSS-only affordance, not committed state. A raised tile's `::after` extends its hit area down by the lift amount, so hovering its bottom edge can't lift it off the pointer and flicker hover/cursor. |
| `one-tap` | The original behaviour: one click/tap sends `discard` immediately. Same fine-pointer hover preview as `two-step`. |

Both modes are presentation only, never a state mutation (`web/AGENTS.md`): the lift is local UI
state, and the actual intent still only ever goes `tap → discard{tile_id}`, same as before.
Mock mode renders hand tiles as non-interactive in the first place (no `tile_id` to discard
against), so neither mode has anything to do there — a deliberate no-op, not an oversight.

**Hand order.** `ClientPrefs.handOrder`, default `'auto'` (sorted by tile type, `live-view.ts`).
`'manual'` keeps the player's arrangement, live mode only (mock tiles have no `tile_id`):

| Piece | Behaviour |
| --- | --- |
| state | `+page.svelte`'s `manualOrder` (in memory, not persisted): `reconcileHandOrder` (`lib/table/hand-order.ts`) keeps held tiles in place, drops gone ones and appends new ones at the right; an effect writes it back, so tiles kept from later draws stack in arrival order. Switching back to auto clears it |
| keys | live hand tiles key by `t-<tile_id>` (drawn tile included) in both modes, so a reorder, or the drawn tile joining the hand, is the same element under `animate:flip` |
| drag | `pointerdown` on the hand row (delegated), activates after 8px. The tile follows the pointer (`translate`, no flip while dragged) and the target is the nearest slot to the tile's centre, measured from layout boxes (`offsetLeft`/`offsetTop`), not `getBoundingClientRect`: mid-flip neighbours report transformed boxes and the target would oscillate. The click fired on release is swallowed in the capture phase, so a drag never lifts or discards. Slots get `touch-action: none` |
| keyboard | `Shift`+`←`/`→` moves the focused tile one place (focusable only when discardable, i.e. your turn) |
| drawn tile | never draggable; it stays apart until discarded or kept, then joins at the right |

Presentation only: the wire only ever sees `discard{tile_id}`.

**Planned, not built:**

| Action               | Desktop                            | Touch       |
| --------------------- | ----------------------------------- | ----------- |
| Inspect discard pool | hover shows who discarded and when | long-press  |

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

### Discard: pending state

A mobile round trip to one server is 100–300ms — long enough that a tile with no feedback between
tap and server echo reads as broken. Still no local mutation of game truth; a **pending**
presentation state instead, the same in both discard modes:

- Sending `discard {tile_id}` sets a local `pendingTileId`, which adds a `hand-tile--pending` class
  to that tile (dimmed, `disabled`, a small spinner overlay). It stays in your hand, in place.
- An `$effect` clears it once that `tile_id` is no longer in `ownHandTiles` (the matching `discard`
  echo landed) or it's no longer this seat's turn (a superseding `turn`/`hand_end`) — never a
  client-side guess at the outcome, just noticing the tile isn't ours to discard anymore.
- A discard from the server's own `turn.legal` essentially can't be rejected, so there is no
  revert path. If no echo arrives within ~3s (`PENDING_STALL_MS`), the spinner swaps to a steady
  accent-error ring (stalled), resolved by the normal reconnect/resync path (§6) rather than any
  client guess. The spinner itself spins unconditionally — a functional in-progress signal, one of
  the base-motion exceptions §9 lists (alongside seat-slot breathing and the mural fade), not
  decorative motion gated behind the reduced-motion setting.

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
| Dialog's own timer runs out before `claim_resolved` arrives | Auto-select `pass` through the same `onChoose` path as a click (`DialogTimer.svelte`), mirroring the server's own claim-timeout PASS ([protocol.md §4](protocol.md)). When the server's timeout wins the race, the late pass is still acked `ok:true`, so no toast. |
| A pre-armed toggle covers this offer | No buttons render — the server resolves it instantly. |

Accepted tradeoff: a click in the last few ms before the local timer fires can lose to the
auto-pass, since the server treats a seat's first-received choice as final. Preferred over a
dialog that never closes on its own. `hand_end_ack` gets the same auto-close with none of this
risk: it's an acknowledgment, and the table advances at the same `deadline_ts` regardless.

**`ClaimDialog` layout.** Each option is a big button (meld preview above it, the localized kind
label inside, a `1`-`N` key-hint badge; no CJK call glyph, no sub-label) — Win gets the same
accent-glow treatment as a `SeatPlate` turn halo, since it's the one choice worth making
unmissable, but every call button (Win included) shares one fixed size. Pass is always its own full-width row below the call options,
never beside them, and carries an "Esc" hint instead of a number; `1`-`N` index the call options
only. Initial focus lands
on Pass (`data-autofocus`, focused once by `ModalDialog` on open — the dialog only mounts while a
claim window is open, i.e. once per window) so keyboard users have a safe default under their
fingers immediately; number keys `1`-`N` and `Esc` drive the same `onChoose` path as a click. The
host `ModalDialog` gets no `onCancel`, so the native Escape close request is swallowed rather than
firing a second pass. Below 768px the dialog becomes a bottom sheet
(`align-self: flex-end` on the overlay's centering flexbox, full width, top corners only) instead of
a centred card. On phone landscape it is instead a ~110px top sheet, one row (timer and header,
the call options, then Pass filling the rest) with bottom corners only, over a lighter scrim: the
bottom sheet covered the whole table there, your hand included, while you decided on a call.
**Not built:** a CSS-only (`@property`/`counter()`) seconds-remaining readout on
the ring — skipped for now; the ring's `aria-label` already states the remaining seconds for
assistive tech, and a purely visual number is a small enough win to defer rather than risk the
`@property`-registration edge cases cross-browser.

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

### Toasts

`Toast.svelte` takes a `severity: 'info' | 'warn' | 'error'` (`lib/ui/toasts.ts`'s `ToastEntry`,
default `'info'`), each with its own accent colour and glyph icon (colourblind-safe, matching the
dragon-glyph convention) rather than colour alone; `error` renders `role="alert"` instead of
`role="status"`. While a modal `<dialog>` is open everything outside it is inert and below the top
layer, so `ToastStack` moves its stack element into the topmost open dialog (`ModalDialog`'s
`topmostDialog()`, re-checked on its `TOP_LAYER_EVENT`) and back home when it closes — a toast stays
visible, clickable and announced over a dialog. A `popover="manual"` stack was tried first: it paints
above the modal but is inert like the rest of the page (no dismiss click, dropped from the a11y tree). Current call sites (`routes/table/[id]/+page.svelte`): a rejected `ack` is `warn`,
a server `error` frame is `error`, a waiting-room arrival is the default `info`. `error` frames map
through `lib/net/server-error-messages.ts`'s `serverErrorToastMessage()` — its map is keyed by
the generated `ErrorCode` (`server/app/errors.py`), so a new server code fails `pnpm check` until
it has a Paraglide message; a code this build doesn't know (a newer server) falls back to the raw
wire message via `tablePage_serverErrorToast`.

### Motion (P3)

Durations come from `lib/ui/motion.ts`'s `motionMs(ms)` (JS) or the `_a11y.scss` `motion-ok` mixin
(CSS) — both collapse to 0ms under reduced motion, never a second code path.

| Surface | Mechanism |
| --- | --- |
| Own hand reflow | `YourSeatRegion`'s hand tiles are keyed `{#each ownHandTiles as tile (tile.key)}` with `animate:flip` on a wrapper (`.hand-tile-slot` — `animate:` needs the each-block's sole child, so the slot carries it and the interactive/static tile swap happens inside) |
| Discard settle | `CenterDiscardPool`'s landing tile slides in a short distance from the discarder's own side (`--discard-enter-x/y`, set per `.discard-pool--*`) plus the existing scale pulse, both via `--ease-place`. `translate`/`scale` are independent CSS properties from `transform`, so this composes with the side pools' static rotate `transform` instead of replacing it — a prior version animated `transform` directly and overrode the rotated faces. The self pool's `scaleY(-1)` (tablet-up) is cancelled by each tile's own `scaleY(-1)` before the face's `translate` applies, so `--discard-enter-y` needs no sign flip there; every pool's direction is pinned in screen space at tablet and phone widths (`CenterDiscardPool.svelte.spec.ts`) |
| Meld slide-in | `_tile.scss`'s `meld-enter` mixin (`@include tile.meld-enter` alongside `@include tile.meld`) — plays automatically on DOM insert, same `demo-meld-in` pattern `AnimationDemoPanel` proved out first |
| Claim seal stamp | `SealStamp` (`lib/table/`), rendered inside `.table-center` and `{#key}`ed so the CSS entrance replays on a repeat: the call glyph (碰/上/槓) as a round badge in the hub cell on the claimer's side — between the hub and that seat's pool, not over the hub (centred on the table surface below tablet-up, where `.table-center` has no box) — scales 1.4→1 with a slight rotate and ink-fades out. `+page.svelte` derives the signal off a seat's `melds.length` growing between renders — presentation only, never game truth, and never set under reduced motion (the information is redundant with the meld tile itself) |
| Score-delta chips | `SeatPlate`'s `scoreDelta` prop (`{value, key}`), derived off `handResult.payments` once per hand end, floats up and fades near the plate — same transient-signal pattern as the seal stamp |
| Haptics | `lib/ui/haptics.ts`'s `vibrate(ms)`: `navigator.vibrate`, feature-detected to `(pointer: coarse)` so it's a no-op on desktop. Fired on your turn starting and a claim offer landing, gated on the new `ClientPrefs.haptics` (default on, separate from `motion`) |

Both the seal stamp and score-delta chip have no mock-scenario trigger (the frozen fixtures never
produce the state transition that fires them) — `AnimationDemoPanel` previews them directly on a
real `SealStamp`/`SeatPlate` instance instead, with buttons that call the same prop shape `+page.svelte` does.

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
  melds: MeldState[][]; // length-4; real tile_ids for every kind
  discardPools: number[][]; // length-4, append-only, indexed by pool_index
  lastDiscard: { seat: number; tileId: number } | null; // most recent unclaimed discard
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
  An `error{code:"table_closed"}` frame (an abandoned table, [architecture.md §8.2](architecture.md))
  closes the socket and turns reconnecting off, as `disconnect()` does; the frame still reaches
  the page for its toast.
  `connect(resume?)` accepts `{lastSeq, seat}` to seed a fresh instance.
- **Connect URL:** adds `&spectate=true` whenever there is no persisted seat to resume, so the page
  gets real seat occupancy before joining (§7 "Join flow").

### Settings dialog

`lib/ui/Settings.svelte`, opened from the table header (`DismissablePanel`). Three tabs
(`TabBar.svelte`, shared with the custom rules editor: `role="tablist"`, roving focus, `←`/`→`
wrap, `Home`/`End`):

| Tab | Controls |
| --- | --- |
| Calls | `autoArm`: No calls, Auto-pass chow (switches) |
| Gameplay | discard mode and hand order (segmented), Announce every discard (switch) |
| Display | tile size and motion (segmented), Sound effects and Haptic feedback (switches), language (`LocaleSwitcher`, segmented) |

- Every control carries a one-line description; a segmented control (`SegmentedControl.svelte`,
  a native radio group) shows only the selected option's description.
- Inactive panels stay mounted with `hidden`, and the dialog has a fixed height
  (`min(36rem, 100dvh - 2rem)`) whose body scrolls, so switching tabs never resizes it.
- **Reset to defaults** restores `DEFAULT_CLIENT_PREFS` and `DEFAULT_AUTO_ARM`
  (`settings-storage.ts`) through the same change callbacks, so live mode re-sends `auto`. Locale
  is untouched. Disabled while everything already matches the defaults.
- **Tile size** (`ClientPrefs.tileSize`: `small`/`medium`/`large`, default `medium`) is mirrored
  onto `html[data-tile-size]` by `lib/ui/tile-size.ts`'s `applyTileSize` (root `+layout.svelte` on
  load, and on every change), which `app.scss` turns into `--tile-scale` (0.85 / 1 / 1.2). Discard
  pools, meld/flower mini tiles, the across opponent's strip and the phone opponent chips multiply
  their whole `clamp()` by it. The hand scales only its cap, so it keeps the 44px floor and still
  fits the row; on a narrow phone it barely changes. The rotated left/right opponent strips are not
  scaled: they are height-bound, and a larger tile wraps their melds into the backs column.
- Switches are `<input type="checkbox" role="switch">`; e2e specs select them with
  `getByRole('switch', …)` after opening the right tab (hidden panels drop out of the a11y tree).

### Persistence

All `localStorage` access (`lib/ui/settings-storage.ts`) is wrapped in `try/catch` and falls back
to defaults on missing, corrupted or blocked storage — the page must render in private browsing.

| Key | Holds | Notes |
| --- | --- | --- |
| `mahjong:seat:v2:<tableId>` | this browser's seat at that table (`saveSeatForTable`/`loadSeatForTable`) | saved the moment `state_sync` confirms a seat; fed back into `connect()` on mount. Without it a reload falls into the seat picker and `join` fails with `table_full` |
| `mahjong:reconnectSecret:v2:<tableId>` | `join`'s `reconnect_secret` (`saveSecretForTable`/`loadSecretForTable`) | presented on every `hello{seat, secret}` ([architecture.md §2.1](architecture.md)); stale `v1` keys are swept on load |
| `mahjong:clientPrefs:v1` | `soundEnabled`, `motion`, `discardMode`, `haptics`, `announceAllDiscards`, `tileSize`, `handOrder` | purely local; every field after `motion` postdates this key, so `loadClientPrefs` defaults each when missing/invalid instead of discarding an older stored object (`settings-storage.ts`) |
| `mahjong:autoArm:v1` | `no_calls`, `auto_pass_chow` | see below |
| `mahjong:displayName:v1` | guest display name | prefilled on the seat picker, saved on every keystroke |
| `mahjong:onboarding:v1` | `coachMarksDone` | set when the first-hand coach marks (§7 "Practice mode") are finished or skipped; never shown again in this browser |
| `mahjong:practiceSetup:v1` | last practice table's bot level per seat (`{1,2,3}` → `easy`/`normal`/`impossible`) | saved when the practice dialog creates a table; prefills that dialog and drives the game-end "Play again" (§7) |

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
`_BOT_NAME_POOL`) — cosmetic, not the tier. The tier is `state_sync.bot_levels` →
`ClientGameState.botLevels` (typed by the generated `BotTier`), shown by `BotBadge.svelte` as the
level word alone (`practice-difficulty.ts`'s `TIER_LABEL`, derived from
`PRACTICE_DIFFICULTY_TO_TIER`; "Expert", plain "Bot" for an unknown tier) on opponents, and on
the bottom seat too while spectating.

### Last-discard marker

`lastDiscard` is set on `discard`, cleared on `meld` (claimed or not — the marked tile either left
the pool or the turn moved on) and `hand_start`. `live-view.ts`'s `viewFromClientState()` resolves
the real `tileId` to that seat's position in its own (unclaimed-filtered) `discards` array —
`null` once claimed, since the tile no longer appears there. `CenterDiscardPool` gives that tile a
brief landing pulse (`motion-ok`) and a `title` tooltip ("`<name>` discarded"); there is no
persistent underline. The pulse animates the standalone `scale` property, not `transform`: a
`transform` keyframe replaces the side pools' rotation for its duration, so the tile flashed
upright. A `state_sync` only derives `lastDiscard` for an embedded claim window (needed there
for `ClaimDialog`'s `sourceSeat`/`tile`) — a resync outside an active claim window loses the
marker until the next discard, a deliberate, cosmetic-only tradeoff (no wire field names "last
discard" generally).

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

**In-game connection status.** `GameStore.connection` (`'idle' | 'connecting' | 'open' |
'resyncing' | 'closed'`) drives two layers, both live-only (no socket in `?mock=`):
`TableToolbar`'s `.connection-pill` (a quiet pulsing label — "Resyncing…"/"Reconnecting…") shows
the instant the connection leaves `'open'`, no delay — it's a toolbar detail, not alarming on its
own. `lib/ui/ConnectionBanner.svelte` dims the whole table (`--z-overlay`, inside `.table-wrap`)
with a "Reconnecting…" card, but only once `'closed'`/`'resyncing'` outlasts 2s
(`scheduleAutoDismiss`'s disposer cancels the pending reveal the instant the connection recovers
first) — a brief drop reads as a glitch, not an outage worth dimming over.

**Planned, not built:** a brief CSS crossfade on the table container (`motion-ok` only, §9) so a
full resync reads as "refreshed," not a glitch; and a one-line dismissable banner, shown once,
saying the bot played for you during the `AUTOPLAY` handover.

### Wire-shape gotchas

The mock fixtures hardcode values the real wire doesn't send this way:

- The reducer clears `legalActions` on this seat's own `discard`. Stale entries would render
  legal-looking discard buttons the server then drops as out-of-turn. Pinned by a
  `reducer.spec.ts` regression test. `deadlineTs` is cleared on any seat's `discard` or `meld`
  (the turn it timed is over).
- `prevailing` goes over the wire as the `Wind` enum's member _name_ (`"EAST"`…), not the
  `'E'|'S'|'W'|'N'` code mocks use and `WIND_LABEL` indexes by. `live-view.ts`'s
  `wireWindToCode()` maps it (generated type `WindName`) — the one enum-shaped field needing
  this; `phase`/meld `kind`/claim `kind` serialize through `StrEnum.value`.
- `hand_end.faan_breakdown` keys are Chinese pattern names. `lib/ui/faan-pattern-labels.ts`'s
  `faanPatternLabel()` maps all 36 patterns to the active locale and passes anything unrecognized
  through, so mock fixtures' English literals render unchanged.

## 7. Routes

| Route | SSR | Notes |
| --- | --- | --- |
| `/` | on | lobby (below), over the mural |
| `/tables` | on | table browser; fetches its listing client-side |
| `/demo` | on | dev component demos, no backend |
| `/table/[id]` | off (`export const ssr = false`) | the game; WebSocket and per-seat redacted state are client-only, so pre-rendering an empty table to hydrate over has no value |
| `/replay/[id]` | off | placeholder; blocked on a server replay endpoint ([ADR 0011](decisions/0011-replay-viewer.md)) |
| `/profile` | on | placeholder heading only |
| `+error.svelte` | — | status heading plus "Page not found" (404) or a generic message, and a lobby back link |

The web image builds with adapter-node (`pnpm build`, `node build`), so SSR is on unless a route
opts out.

**Page titles.** Every route (and `+error.svelte`) sets its own `<svelte:head><title>`, as
"`<page>` · Mahjong" (`*_pageTitle` keys, so it's localized). The lobby uses the bare app name
(`lobby_title`). `app.html` has no `<title>`. A static one there would be emitted before
`%sveltekit.head%`, and browsers honour the first `<title>`, so it would shadow the page's title in
SSR HTML. Svelte never restores `document.title` when a component unmounts, so a page without its
own title would keep the previous page's, e.g. a stale "Your turn · Mahjong" after leaving a table.
`ApiConnectGate` shows the app name while it holds the page back.

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

"Create a table" on `/tables` (header, and the empty state) opens `CreateTableDialog.svelte`, two
views in one dialog:

- **Presets** — one radio per `RULESET_PRESET_OPTIONS` entry (an `OptionRow` with its
  `description` as a muted second line), plus "Custom". Picking a named preset and pressing Create
  posts `{ruleset: <id>}`. Picking Custom opens the editor; back in this view the Custom row reads
  "Based on <preset> · N changes" with an "Edit custom rules" button.
- **Custom rules** (`RulesEditor.svelte`) — a back button, then one scroll region holding "Start
  from" (a segmented control over the presets), a change summary, and four tabs (`TabBar.svelte`,
  sticky inside the scroll region):

| Tab | Controls |
| --- | --- |
| Scoring | minimum faan, faan cap, score table, discard payment (segmented, each option described) |
| Hands | hand sets, flowers (switches), faan overrides |
| Play | game length (segmented); dealer repeats, kong robbing (switches); wall reserve (stepper) |
| Table | turn, claim window, hand result, timeouts allowed, reconnect grace (steppers); provable fairness (switch) |

- **Seeded from a preset.** `RULESET_PRESET_RULES` (`lib/net/ruleset.ts`) mirrors server
  `RULESET_PRESETS` field-for-field — update both together. "Start from" and "Reset" replace the
  draft with that preset; the replaced draft is offered back via "Undo" until the next edit.
  `countRuleChanges` drives the "N changes from <preset>" summary.
- **Dependent switches** disable rather than hide: seat flowers and the 7/8-flower instant wins
  need flowers enabled; concealed-kong robbing needs kong robbing.
- **Faan overrides** pick a pattern from a `<select>` (`OVERRIDABLE_PATTERNS` in `faan-guide.ts`,
  localized labels, grouped by default faan, limited to the enabled hand sets and to patterns not
  already overridden) — the wire key is `patterns.py`'s Chinese name, never typed by hand. Values
  are integers `0..13`; 0 turns the pattern off.
- **Validation is client-side**, because `resolve_ruleset` silently falls back to `hk_classic` on
  an invalid custom body ([rules.md §10](rules.md)). `invalidRuleFields` checks integer steppers
  against `NUMERIC_RULE_MIN`, at least one hand set, and override range. Create with errors stays
  open, switches to the first tab with an error (each such tab carries a red dot plus
  screen-reader text), and focuses the offending field.
- **Inert fields** (`INERT_RULE_FIELDS`: every `RuleSet` field with no server reader, rules.md §10,
  including `multi_win`) are never shown and always posted at their defaults (`withInertDefaults`)
  — a toggle must not promise a rule the engine ignores.
- **Remembered.** A successful create stores `{presetId, customBase, custom}` under
  `mahjong:createTableSetup:v1`; the next open restores the selection and the custom draft.
  `loadCreateTableSetup` drops an unknown preset id and repairs a stale ruleset field-by-field
  (`sanitizeRuleSet`) instead of discarding it.
- The custom view has a fixed height (`min(44rem, 100dvh - 2rem)`) so switching tabs never resizes
  it; Cancel/Create stay pinned below the scroll region.

Submitting calls `POST /tables` ([protocol.md §10](protocol.md)) and navigates to
`/table/<table_id>`. The waiting room shows the resolved preset name (`PretableScreen.svelte`).

### Lobby

A brand lockup (a 麻雀 seal mark beside a visible `--font-size-display` "Mahjong" `h1`), then
three **equal-weight** action cards — "Play online", "Practice vs Bots",
"Faan guide" — each a tile-glyph icon and a title. No hero card: the three
are peers by design. "Play online" is a link to `/tables`, the one multiplayer hub (create, join
by code, browse): invitees arrive by table URL, not through the lobby, so separate create/join
entries here split one intent across two controls. The other two are `<button>`s opening dialogs.
Each card's control holds only the title (its accessible name, which e2e matches exactly), and its
`::after` stretches the hit area over the whole card. Below the cards, a quiet underlined language
toggle. A muted "Source code" link (GitHub mark + label, new tab) sits in the page's
bottom-right corner. Three columns at ≥768px, one stacked column below. The mural scrim (§2) is darker in the
middle (a radial gradient) so this copy reads over the tiles.

### Faan guide and language toggle

The language link calls `setLocale()` with the other locale
(label is the target language's own name, so it reads right in either locale); `LocaleSwitcher`
stays in `Settings`. "Faan guide" opens `lib/ui/GuideDialog.svelte`: one tab per faan count (0-8)
plus Limit, each a list of patterns with a description and a tile example. The dialog is a fixed
`90dvh` tall and the tab panel scrolls, so switching to a shorter tab doesn't resize it. The data lives in
`lib/ui/faan-guide.ts` (`GUIDE`, keyed by faan value; examples are strings of concatenated tile
codes, one group each); a spec pins it to `FAAN_PATTERN_LABEL` so a new pattern can't be left out.
Situational patterns (self-draw, last tile, ...) show the description only. A ruleset select (All or
one of the `RULESET_PRESET_OPTIONS`) hides patterns whose hand set the preset disables and tabs left
empty; `GUIDE_PRESET_RULES` mirrors the server presets' `hand_sets`/`min_faan`, and 雞糊 only
shows under All since every preset has `min_faan > 0` ([rules.md §7](rules.md)); it sits on its
own 0 tab, the faan it actually scores.

### Practice mode

"Practice vs Bots" opens `lib/ui/PracticeSetupDialog.svelte` before creating anything — bot tier is
fixed at table construction. A seat ring with one tap-to-cycle difficulty pill per bot seat
(seats 1-3, matching `wind.ts`'s `relativeSeat` offsets — the position names are
aria-labels only, no visible captions; seat 0 is the
human, shown as bold "You" text) around the same `CompassFelt` centerpiece as the pre-game
rings and `/tables` cards,
each Easy/Normal/Expert/Impossible ([bots.md §6](bots.md)), defaulting to the last practice setup
(else Normal), above a short legend
with a one-line blurb per level. Submitting sends `POST /tables`
with `{practice: true, bot_tiers: {1: …, 2: …, 3: …}}` and navigates to `/table/<id>?practice=1`.

**First-hand coach marks.** On a practice table's hand 1, until `mahjong:onboarding:v1` says
they're done, `lib/ui/CoachMarks.svelte` shows one tip at a time in a card pinned to the top of the
table (above the felt, below every overlay; hidden while a claim or result dialog is up): how to
discard (worded for the current discard mode), where the newest discard pulses, and that claims pop
up over the table. The current tip's target — your seat region, or the centre pools (each pool
on phone, where they sit under their seats) — gets a brass outline via `.table-wrap[data-coach]`. "Next"/"Got it" and "Skip tips" both end it for good.
Practice only: in a multiplayer game nobody should be reading tips while three people wait.

**In-game guide.** The header rail carries a "Guide" button opening the same `GuideDialog` as the
lobby, so the faan library is reachable mid-hand.

`?practice=1` is this route's own param; the live-connect effect appends `&practice=true` to the
WS URL, which binds seats 1-3 at construction (`server/app/ws.py`'s `ws_endpoint`,
`Table.__init__(practice=..., seat_bot_tiers=...)`). The human still goes through the seat picker
(seat 0 is the only open slot). The header rail shows a "Practice" tag beside the table code.

### `/table/[id]` wiring

`[id]` is a table id. A direct visit to an unknown id auto-creates the table on first WS connect
(`server/app/ws.py`'s `_get_or_create_table`).

| Query | Renders |
| --- | --- |
| (none) | live: a `MahjongSocket` at `${PUBLIC_WS_URL}?table=<id>` driven through `GameStore` |
| `?mock=<scenarioId>` (or bare `?mock`) | a frozen `MOCK_SCENARIOS` fixture, no backend — used by the screenshot workflow (`.claude/skills/frontend-screenshots/SKILL.md`) and design iteration. The url is the only scenario picker: the page wears the real header rail (§3), no dev controls, so a capture shows exactly what players see. `/demo`'s "Table scenarios" section links every scenario and `?pregame=` preview, and hosts `AnimationDemoPanel` ("Animate a turn") |
| `?pregame=connecting\|join\|waiting` | freezes one pre-game state (below) with no socket — mock scenarios are always fully seated |

**Tab title.** `<svelte:head><title>` reads live turn/claim state: "Your turn · Mahjong" while this
seat has a legal discard, "Claim? · Mahjong" while a claim offer is open, else "Table `<id>` ·
Mahjong". Mock scenarios are frozen snapshots, not live turn state, so they always show the
generic table title regardless of which scenario is selected.

**One view model, two sources.** `lib/table/live-view.ts`'s `viewFromClientState()` projects a real
`ClientGameState` into the same `TableView` shape the template renders, so mock and live share
one render tree (`TileFace`/`ClaimButtons`/`TimerRing`/`FaanBreakdown`/`ScoreSheet`/…) and can't
visually drift. Mock tiles are bare `TileCode`s; `LiveTableView.ownHand` carries the real
`tile_id`s index-aligned with `concealedHand`/`drawn`, so a clicked tile maps to a real intent.

Types and shared constants live apart from the components and the fixture:

| Module | Holds |
| --- | --- |
| `lib/game/types.ts` | domain types (`Seat`, `Wind`, `Phase`, `MeldKind`, `ClaimKind`/`ClaimOption`, `HandOutcome`, `WinType`, `FaanPattern`, `WinningMeld`, `Payments`) and the score-sheet shapes (`HandRecord`, `RoundResult`, `SeatInfo`, `Totals`, `Standing`). Wire vocabularies are aliases of `protocol.d.ts` (`Seat`, `Phase`, `HandOutcome`, `WinType`; `ClaimKind` = `ClaimChoice`; `MeldKind` = the wire `MeldKind` minus `pair`); `Wind` is the client's own `'E'…'N'` code |
| `lib/table/view-types.ts` | the view model (`TableView`, `SeatView`, `MeldView`, …, plus `OwnHandTile`/`DeclareOption`) |
| `lib/table/mock-game-state.ts` | the frozen `MOCK_SCENARIOS` fixtures only |
| `lib/ui/client-prefs.ts` | `ClientPrefs`/`AutoArm` and their field types (`settings-storage.ts` holds the defaults) |
| `lib/net/practice-difficulty.ts` | `PRACTICE_DIFFICULTIES` (cycle order), `PracticeDifficulty`, the difficulty → `BotTier` map and both label maps; free of `lobby.ts`'s `$env` import |
| `lib/table/tile-code.ts`, `meld-face.ts` | `sortTiles`/`tileSortKey` (reading order), `sortMelds`, `MELD_SEAL_GLYPH` |
| `lib/table/pregame-preview.ts` | `?pregame=` values, shared by `/table/[id]` and `/demo` |

**Join flow.** No auto-join: a live table shows a seat picker that sends `join{seat, name?}` for
the clicked seat. Sitting down implies readiness — `ready` fires right behind a successful join.
Until all four seats are joined and ready, the page shows a waiting screen. The picker has real
occupancy data before joining because the socket connects with `&spectate=true` when there's no
persisted seat, getting a spectator `state_sync` with every seat's `seat_status`/`names`; `join`
promotes the connection off spectator status ([architecture.md §3](architecture.md)).

### Pre-game states

Connecting, seat picker and waiting are recurring moments in a multiplayer game, so they use the
app's panel/button vocabulary (`panel-elevated`, `_buttons.scss`). All three share one panel —
the table code, large on a tile-coloured chip, plus a primary "Invite friends" button (the table URL
_is_ the invite) — and a seat ring: four slots arranged across/left/right/self like
`layout.seat-region-grid`, around the same mini felt square (`lib/table/CompassFelt.svelte`) the
`/tables` cards use, laid out on the same compass grid (`layout.seat-compass-grid`; top/bottom seats span the felt's width,
side seats hug the felt like the cards' compass names) and styled like the cards' compass seats — an open seat is a dashed pill
(accent-tinted and clickable in the picker; muted and gently breathing while waiting), a taken
seat is plain bold name text, and your own seat is your wind glyph in bold text — once seated,
`CompassFelt`'s `rotate` prop turns the felt so that wind sits at its bottom edge, matching the
seat you're holding (the cards keep the fixed decorative orientation). The picker, the waiting
ring and a table card all read as the same table seen from above. The panel itself sits on
`--color-surface`, the cards' surface.

- **Invite.** `lib/ui/share-invite.ts`'s `shareOrCopy()` opens the OS share sheet
  (`navigator.share`, gated on `canShare`) where one exists — i.e. phones — else copies the URL.
  Dismissing the sheet (`AbortError`) is a no-op, not an error; any other share failure falls
  through to the clipboard. After a copy the button reads "Link copied" (also announced through a
  polite live region) and resets after 2s (`scheduleAutoDismiss`). Hidden in practice mode, where
  bots already hold every other seat. The host's "Start with bots" is secondary-styled so the
  invite stays the panel's one primary action.

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

A header with Refresh and a primary "Create a table" (always shown, opening
`CreateTableDialog`), a join-by-code form, and a responsive grid of table cards (`repeat(auto-fill, minmax(19rem, 1fr))`)
showing code, an open/in-progress status chip and a mini compass of the four seats around a felt
square (seat 0 at the bottom, then 1 right / 2 top / 3 left — the same arrangement the table
itself uses; open seats as dashed "Open" pills, bots badged). The felt carries the four wind
glyphs (東 bottom / 南 right / 西 top / 北 left, rotated to read from each seat's side) as
decorative direction markers — they don't imply dealt seat winds. The header's Refresh is a real
secondary button beside a static "Updated <time>" stamp of the last successful poll (not a ticking
"n seconds ago" — no JS ticker). With no tables, an empty-state panel repeats "Create a table". Polls `GET /tables` every 5s
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

### Bot seat badge and status chips

`SeatView.status` (populated from `ClientGameState.seatStatus` by `viewFromClientState`, never
set by mocks) drives a `.bot-badge` chip ("Bot") next to the dealer badge when `status === 'bot'` —
a quiet bordered chip, not `--color-accent`, since a bot seat doesn't change mid-hand.
`disconnected`/`autoplay` get their own `.status-chip--away`/`.status-chip--autoplay` chips
(`SeatStatusChip.svelte`, on opponents and on the bottom seat while spectating), tinted (`--color-status-error`/`--color-accent`) rather than neutral —
both are transient, in-hand signals, unlike the bot badge's fixed identity. `connected` has no
visual treatment. Own-seat equivalents and a one-time AUTOPLAY-handover toast are not built yet.

### Hand-end reveal

`HandEndOverlay` is one panel (a bottom sheet below 768px; a wide centred card on phone landscape,
where `FaanBreakdown` goes two-column — the hand left, patterns/total/payments right — so the
payments are in view at 740×360) whose header carries a seal-ink result
stamp — 食糊 (discard win), 自摸 (self-draw, from `winType`), 流局 (draw, muted ink rather than the
accent) — the hand number, the hold's `DialogTimer` ring, and the close button. The ring renders
only when `handEndHoldMs` is known; a zero-length timer would auto-close the panel instantly.

Entrance (`motion-ok` only; reduced motion shows the final state at once): the stamp presses in
(`--ease-place` overshoot), then `FaanBreakdown`'s winning tiles fan in one by one on a felt
inset, then pattern rows, then the total and the payments. Delays are custom-property maths
(`--i` per element, `--tile-count`/`--pattern-count` on the section), so the sequence scales with
the hand. Payments render as name plates with a `--color-positive`/`--color-negative` tinted ±
chip, the winner's plate outlined in brass.

**Fairness check.** On a `provable_fairness` table, `FairnessBadge` closes the panel: it hashes
`hand_end.fairness` against the `seed_commit` the reducer kept from that hand's `hand_start`
(`lib/net/fairness.ts`, WebCrypto) and shows verified / mismatch / unverifiable (no live commit,
or no `crypto.subtle` on an insecure origin), with the hex values in a `<details>` for
`tools/verify_fairness.py` ([protocol.md §3](protocol.md) "Fairness").

**Turn halos hide under a result overlay.** Neither the mock fixtures nor the reducer clear `turn`
at `hand_end`/`game_end`, so `+page.svelte` passes a `haloTurn` of `-1` to every seat and the hub
while a hand-end or game-end overlay is up — otherwise the last actor's halo glows behind it.

### Game-end summary

`ClientGameState.gameEnd` (from `game_end`) shows `GameEndScreen.svelte`, auto-shown and not
dismissable. `game_end` only fires after the final hand's hold resolves, so nothing in progress is
preempted — but the hold overlay normally clears on the next `hand_start`, which never comes, so
`+page.svelte` gates it on `!gameEndReached` and the game-end screen replaces it.

- One panel: a "Game over" heading, a "You placed Nth" line (omitted for spectators), all four
  final standings as ranked rows, the actions, then the full `ScoreSheet` (score table, running
  totals) under a "Hand-by-hand scores" label. On phone landscape it is a viewport-high two-column
  grid — heading, standings and actions left, the score sheet scrolling on its own right — so Play
  again is in view without scrolling the dialog (stacked, it opened scrolled part-way down).
- **Ties** use competition ranking (`rank.ts`'s `placements`: totals 50/10/−30/−30 place
  1st/2nd/3rd/3rd, never 3rd/4th): tied rows share a place and a "Tied" tag, and the line reads
  "You tied for 3rd". `ScoreSheet`'s own standings list uses the same places.
- **Play again** (practice tables only, i.e. `?practice` on the URL) is the primary action:
  `POST /tables` with the bot levels from `mahjong:practiceSetup:v1` (§6), then a full-page
  navigation to the new `/table/<id>?practice=1` — not `goto()`, since SvelteKit would reuse this
  route's component and carry the finished table's local flags (game-started, dismissals) into the
  new one. "Back to home" is the secondary action there, and the only (primary-styled) one
  otherwise. Multiplayer rematch is not built.
- `ScoreSheet`'s per-round expand: when `HandRecord.result` (a `RoundResult`) is present, the hand
  number becomes a toggle revealing that round's winning hand via `FaanBreakdown`'s tile rendering,
  or "Exhaustive draw". Serves both the mid-game "Score sheet" toggle (`mockRoundResult`) and the
  game-end screen (`liveRoundResult`, converting `winnerMelds`/`winningHand` tile ids to
  `TileCode`s as `live-view.ts` does).
- Mock: `mock-game-state.ts`'s `gameJustEnded` (`?mock=game-ended`) is a frozen `GAME_OVER`
  snapshot carrying `TableView.gameEnd`; `+page.svelte`'s `gameEndReached`/`scoreHands`/
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
- **UI icons:** [`@lucide/svelte`](https://lucide.dev), imported per icon
  (`@lucide/svelte/icons/<name>`), never hand-written inline `<svg>`. One 24px grid and stroke
  style keeps chrome icons consistent, and per-icon imports tree-shake to only the icons used.
  Size and weight are props (`size`, `strokeWidth`); colour is `currentColor`, and an icon is
  `aria-hidden` unless given an `aria-*`/`title` prop, so the button's label stays the accessible
  name. Not icons: `TimerRing` (a countdown ring) and the favicon.
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
  _buttons.scss     btn-base(padding-inline) (tap-target size, include before a tier),
                    btn-primary/secondary/ghost, panel-elevated, input-recessed
  _forms.scss       panel-header/title/badge, form-group, option row chrome, field-text/
                    label/desc (label-over-description column), settings-card
  _tile.scss        seat-meta/dealer-badge/tile-row/mini-tile/meld mixins shared by every
                    seat-hand-strip implementation -- per-face geometry stays in TileFace
  _layout.scss      seat-region grid, breakpoint mixins, seat-compass-grid (four seats
                    around a mini felt) and seat-ring (the pre-game `.seat-ring*` rules)
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
| signal | `--color-accent`, `--color-accent-glow`, `--color-accent-on-dark` | the one urgent signal (turn, claim window, win marker); never decorative. `-on-dark` is the same signal as text/icon on dark chrome or felt, where the accent itself is under 3:1 |
| highlight | `--color-brass` | selection, focus ring, your own seat, dealer; never a signal |
| deltas | `--color-positive`, `--color-negative` | score/faan gains and losses only |
| seats | `--color-seat-right/across/left` | opponent seat hues (self uses brass) |
| status | `--color-status-error`, `--color-rank-gold/silver/bronze` | error states; game-end podium |
| shape/type/space | `--radius-sm/md/lg`, `--radius-tile`, `--radius-pill`, `--space-1…8`, `--font-size-xs…2xl`, `--font-size-display`, `--tap-target-min` | |
| motion | `--dur-1` 120ms … `--dur-4` 600ms, `--dur-control` 130ms (control hover/press/selected colour), `--dur-spin` 900ms (`lib/ui/Spinner.svelte`, the connecting spinner), `--ease-out`, `--ease-place` (overshoot) | wrap motion in `a11y.motion-ok` (§9) |
| layers | `--z-table/tiles/hud/overlay/modal/toast` | modal dialogs are in the top layer, which no z-index reaches; toasts move into the open dialog instead (§5 Toasts) |

### Contrast audit

`web/scripts/contrast-audit.mjs` reads the colour tokens straight from `_tokens.scss`, composites
each translucent layer onto the background it really sits on, and exits non-zero if any pair is
under WCAG AA (4.5:1 text, 3:1 icons/UI). "Mural" is the worst case: a lit ivory tile face under the
canvas filter (`brightness(0.42) saturate(0.55)`) behind the scrim at that radius. `felt-lit` is the
lightest felt stop, so every felt row is the worst case too. Measured (P4):

| Text | Background | Ratio | Needs |
| --- | --- | --- | --- |
| text-muted | surface-raised | 5.54 | 4.5 |
| text-muted | surface | 6.16 | 4.5 |
| text-muted | bg | 6.61 | 4.5 |
| felt-muted | felt-lit (lightest felt) | 4.64 | 4.5 |
| text-on-felt | felt-lit | 6.24 | 4.5 |
| text-muted | mural, scrim 0.72 (centre) | 6.25 | 4.5 |
| text-muted | mural, scrim 0.52 (75%) | 4.88 | 4.5 |
| text-muted | mural, scrim 0.5 (edge) | 4.75 | 4.5 |
| text | mural, scrim 0.5 (edge) | 10.51 | 4.5 |
| bot badge text-muted (felt override) | surface-raised | 9.83 | 4.5 |
| status-chip away (status-error) | black 45% on felt-lit | 4.69 | 4.5 |
| status-chip autoplay (accent-on-dark) | black 45% on felt-lit | 5.41 | 4.5 |
| dealer badge text | accent 85% + black | 5.49 | 4.5 |
| hub min-faan chip (felt-muted) | black 12% on felt-lit | 5.48 | 4.5 |
| toast text | surface-raised | 12.27 | 4.5 |
| toast warn icon (status-error) | surface-raised | 5.40 | 3 |
| toast error icon (accent-on-dark) | surface-raised | 6.23 | 3 |
| toast info icon (text-muted) | surface-raised | 5.54 | 3 |
| + delta chip | positive 16% on surface-raised | 5.94 | 4.5 |
| - delta chip | negative 14% on surface-raised | 4.77 | 4.5 |
| + score-delta float | black 55% pill on felt-lit | 8.20 | 4.5 |
| - score-delta float | black 55% pill on felt-lit | 5.97 | 4.5 |
| connection pill (accent-on-dark) | bg | 7.43 | 4.5 |
| score-sheet round toggle hover (accent-on-dark) | bg | 7.43 | 4.5 |
| open-table chip (positive) | surface | 9.30 | 4.5 |

Fixes this audit drove: the mural scrim's outer stops went 0.42/0.28 → 0.52/0.5 (muted text measured
4.22/3.42 there); status chips' backing 15% → 45% black and autoplay text to
`--color-accent-on-dark` (accent on felt was 1.66:1); the dealer badge's fill darkened to 85% accent
(4.28:1); `--color-negative` `#ef7a6b` → `#f2857a` (4.42:1 on its own chip); the floating score-delta
chip got a dark pill (bare on felt: 3.95/2.62); the error toast icon uses `--color-accent-on-dark`
(2.87:1); so do the toolbar's connection pill and the score-sheet round toggle's hover (accent on
`--color-bg` was 3.42:1). `--font-size-xs` rose 0.7 → 0.75rem: chip/badge text is bold but not "large" by WCAG's
definition, so it gets no 3:1 allowance — every xs row above is held to 4.5.

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
| Generated | `src/lib/paraglide/` — never hand-edited; `pnpm run paraglide:compile` (wired into `build`/`check`). During `pnpm dev` the vite plugin watches `messages/` and recompiles on save, then Vite reloads the page (message modules aren't HMR-acceptable, so it's a full reload, not a patch) |
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
`MOCK_SCENARIOS` labels (listed verbatim on `/demo`'s scenario links), the `/demo` pre-game preview
links, `AnimationDemoPanel` controls, demo `data-testid` readouts. `lib/table/wind.ts`'s
`WIND_LABEL` is only ever interpolated into already-translated messages.

**Tile names.** `lib/table/tile-name.ts`'s `tileName(code)` maps every `TileCode` to a localized
spoken name (`tileName_<code>` keys: "3 Bamboo"/三索, "Red Dragon"/紅中, "Plum Flower"/梅) —
`TileFace`'s `alt`, discard/claim/declare `aria-label`s. A raw code (`z5`) never reaches a
player. `tile-name.spec.ts` pins the map to `TILE_ASSET` and both locale files. `TileFace` also
sets `data-tile="<code>"` as the locale-independent hook specs match on.

Tests assert on `data-testid`/stable classes for core flows, not English wording. Locale switching
and SSR `<html lang>` have e2e coverage (`lib/i18n/locale-switch.e2e.ts`, `hooks.server.e2e.ts`).

The zh-Hant file (484/484 keys, parity-checked) is machine-generated and not yet reviewed by a
fluent Hong Kong mahjong player.

### Accessibility

- **Colourblind-safe:** dragons are distinguished by glyph, not just red/green.
- **Focus:** `_a11y.scss`'s global `:focus-visible` ring (2px `--color-brass`, 2px offset) covers
  every control; components don't restyle it.
- **Modals:** every overlay dialog (claim, hand end, game end, settings/score sheet via
  `DismissablePanel`, leave, create table, practice setup, guide, animation demo) is a native
  `<dialog>` opened with `showModal()` through `lib/ui/ModalDialog.svelte`: focus trap, inert
  background and top layer come from the platform. The `<dialog>` box itself is the full-viewport
  scrim (`placement`: `center`, `sheet` — bottom sheet below 768px, a lighter scrim on phone
  landscape — or `scroll`), so panels keep
  their own layout. It focuses a `[data-autofocus]` descendant on open and returns focus to the
  opener on unmount.

  | Dialog | Escape |
  | --- | --- |
  | claim | Pass (`ClaimDialog`'s own key handler; the dialog's close request is swallowed) |
  | hand end | dismiss, same as the close button (an acknowledgment, not a decision) |
  | game end | nothing — not dismissable |
  | leave game | Cancel (`alertdialog`, focus starts on Cancel) |
  | panels, create/practice/guide | close (ignored while a create request is in flight) |

  Escape's `cancel` is always `preventDefault`ed and routed to `onCancel`, so the owning `{#if}`
  unmounts the dialog — the DOM never closes itself out from under Svelte. Chrome force-closes a
  dialog whose cancel was already prevented once without user activation in between; the `close`
  handler treats that as a cancel, or reopens a non-dismissable dialog.
- **Keyboard hand model:** legal hand tiles are native `<button>`s — the same elements pointer and
  touch use, so there is one selection model. The hand row (`role="toolbar"`) is a single tab stop
  via roving `tabindex`, defaulting to the last discardable tile (the drawn tile), else the focused
  or lifted one:

  | Key | Effect |
  | --- | --- |
  | `←`/`→`, `Home`/`End` | move focus between discardable tiles (clamped, no wrap) |
  | `Enter`/`Space` | the button's own click: two-step lifts then discards, one-tap discards (§5) |
  | `Escape` | clears a lift |
  | `Shift`+`←`/`→` | moves the focused tile one place, manual hand order only (§5 "Hand order") |
  | `H` | jumps focus to the hand from anywhere (`aria-keyshortcuts`), ignored while typing in an input/select/contenteditable or with a modifier; with nothing discardable the row itself takes focus (`tabindex="-1"`) |

  Spectators have no hand row, so none of this applies there.
- **Names:** tiles are announced by localized name, never code (§9 i18n "Tile names").
- **Reduced motion:** Settings' Motion control (`system`/`reduced`/`full`, persisted in
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

**Live announcements.** One polite region per table page (`lib/ui/Announcer.svelte`, `role="status"`,
`aria-atomic`). `+page.svelte` snapshots the same view model the table renders
(`lib/ui/announcements.ts`'s `announceSnapshot`) after every update and `announcementsBetween(prev,
next, everyDiscard)` turns the difference into lines:

| Event | Line (en) | When |
| --- | --- | --- |
| a discard you can claim | "Bob discarded 3 Bamboo. You can claim it" | claim offer's rising edge (a robbable kong reads "Carol is adding Red Dragon to a kong") |
| any discard | "Bob discarded 3 Bamboo" / "You discarded …" | only with Settings' "Announce every discard" (`ClientPrefs.announceAllDiscards`, default off — ~80 discards a hand is noise by default) |
| a call / concealed kong | "Bob called Pung" / "Carol declared Concealed kong" | a seat's meld count grows |
| your turn | "Your turn" | rising edge of having a legal discard (live only) |
| hand end | "Bob wins" / "You win" / "Hand ended in a draw" | the hand result appearing |

- A hand or mock-scenario change only re-baselines: a jump between snapshots is not an event.
- Spectators have no "you"; every seat is named.
- `announce()` debounces: lines queue and flush 300ms after the last one, at most the latest 4,
  joined into one update, so a resync burst or a discard+claim pair doesn't interrupt itself. A
  toggled trailing zero-width space makes an identical repeat ("Your turn" twice) still change the
  region.
- The region follows the topmost open modal (`ModalDialog`'s `followTopmostDialog`, same as
  toasts), or it would be inert — and silent — under the claim and hand-end dialogs.
- Each discard-pool tile is a `role="listitem"` labelled "Bob discarded 3 Bamboo" inside its seat's
  labelled `role="list"`. Not focusable: the pools are browsed with the screen reader's own
  list navigation, and ~80 extra tab stops would bury the hand.
