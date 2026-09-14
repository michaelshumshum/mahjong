# 03 — Frontend

## 1. The split

```
┌─────────────────────────────────────────────────────────────┐
│ SvelteKit app                                               │
│                                                             │
│  Routes (DOM)          │  Table route                       │
│  /            landing  │  ┌──────────────────────────────┐  │
│  /lobby       rooms    │  │ <canvas> — PixiJS            │  │
│  /table/[id]  game     │  │   felt, wall, 4 hands, melds,│  │
│  /replay/[id] viewer   │  │   discard pool, dice, hints  │  │
│  /profile     stats    │  └──────────────────────────────┘  │
│                        │  DOM overlay (Svelte):             │
│                        │   claim buttons, timer ring,       │
│                        │   faan breakdown, score sheet,     │
│                        │   chat, settings, toasts           │
│                                                             │
│  lib/net/     ws client, seq tracking, reconnect, reducer   │
│  lib/game/    client state store ($state runes)             │
│  lib/table/   Pixi renderer (pure view of game store)       │
└─────────────────────────────────────────────────────────────┘
```

**One-way data flow.** Server events → reducer → `$state` store → Pixi renderer reads it.
The renderer owns presentation state only (sprite positions, tweens in flight, hover), never
game truth. Input goes `Pixi hit-test → intent → WebSocket`, never `Pixi → local mutation`.
No optimistic updates: round-trip is 50ms and a wrong guess shows an illegal board.

## 2. Rendering

- SvelteKit DOM owns the chrome: routes, overlay, buttons, menus, score sheet.
- PixiJS v8 owns the table surface (one `<canvas>`).

Known costs:

- You write your own hit-testing and layout.
- No a11y from the canvas. Mitigated by keeping every interactive control except the tiles in
  DOM, plus a DOM text representation of your hand.

## 3. Scene layout

Logical space `1600 × 1000`, letterboxed with `Application.resizeTo` + a root container scale.
Seats are rendered relative to **your** seat, always at the bottom:

```
                    ┌─────────── opponent (across) ───────────┐
                    │  13 backs · melds right · flowers left  │
  ┌─────────┐       ├─────────────────────────────────────────┤       ┌─────────┐
  │ left    │       │        discard pool 6 cols × N          │       │ right   │
  │ opponent│       │  (in claim order, newest highlighted)   │       │ opponent│
  │ rotated │       │                                         │       │ rotated │
  │   +90°  │       │      wall count · prevailing wind ·     │       │   -90°  │
  └─────────┘       │      dealer marker · turn indicator     │       └─────────┘
                    ├─────────────────────────────────────────┤
                    │  YOUR HAND: 13 faces, sorted, +drawn    │
                    │  tile held out at right, melds, flowers │
                    └─────────────────────────────────────────┘
```

Playability:

- Always render yourself at the bottom, rotating the other three; seat wind shown by a badge, not position.
- The drawn tile sits slightly apart from the sorted hand, as in physical mahjong.
- Discard pool ordered by discard sequence, per player, most recent pulsed; never shuffled or compacted.
- Sprites keyed by `tile_id`, so a tile drawn, held, and discarded is one continuous sprite.

## 4. Interaction model

| Action | Desktop | Touch |
| --- | --- | --- |
| Select tile | hover lifts it, click selects | tap lifts |
| Discard | click a lifted tile, or drag up past a threshold | tap again, or swipe up |
| Claim | DOM buttons, bottom-center, with countdown ring | same, larger targets |
| Sort hand | auto by default; drag to reorder, sticky per session | drag |
| Inspect discard pool | hover shows who discarded and when | long-press |

Non-negotiables:

- Confirm-on-second-tap for discard: lift-then-commit, plus a one-click-discard setting.
- Claim buttons appear only when the server offered them; never speculative.
- Pre-arm toggles ("no calls this hand", "auto-pass chow"), sent via `auto`, enforced server-side.
- Faan preview on a hovered discard candidate: shanten, wait count, and whether the hand can reach the 3-faan minimum. Gated behind a training-mode setting for rated play.

## 5. Asset pipeline

- Tile art: **[FluffyStuff/riichi-mahjong-tiles](https://github.com/FluffyStuff/riichi-mahjong-tiles)**
  — public domain SVG + PNG, regular and black variants. HK uses the same 34 faces as riichi;
  add the 8 flowers/seasons, swap out the red-5 variants.
  [libreriichi-assets](https://codeberg.org/davidgomez/libreriichi-assets) (CC0) has 3D
  textures and Blender sources for the pre-rendered-2.5D route.
- Build step: SVG → PNG at 2× → pack into one atlas with `free-tex-packer` or `assetpack` →
  emit `tiles.webp` + `tiles.json`. Two atlases (@1x, @2x), picked by DPR.
- 2.5D look: pre-render tiles in Blender at the table's fixed camera angle, ship as sprites —
  real lighting and bevels at zero runtime cost.
- Sound: draw click, discard clack, claim call (recorded Cantonese 「碰」「上」「槓」「食糊」),
  shuffle. Short, compressed, preloaded. Mute default-on until the user opts in.

## 6. Client state

```ts
// lib/game/store.svelte.ts
class GameStore {
  seq      = $state(0);
  phase    = $state<Phase>('IDLE');
  seats    = $state<SeatView[]>([]);
  myHand   = $state<TileId[]>([]);
  drawn    = $state<TileId | null>(null);
  pool     = $state<Discard[]>([]);
  offer    = $state<ClaimOffer | null>(null);
  deadline = $state<number | null>(null);   // server ts, corrected by clock offset

  apply(ev: ServerEvent) { /* pure reducer, one switch, no side effects */ }
}
```

Rules:
- The reducer is pure and exhaustively switched over the generated `ServerEvent` union, so
  TypeScript flags unhandled events.
- A `seq` gap triggers a resync request, never a silent patch.
- Pixi subscribes via `$effect` and diffs against its own sprite map; never re-creates the scene graph per event.
- Same reducer drives the replay viewer, fed from a recorded event log instead of a socket.

## 7. Accessibility and i18n

- Traditional Chinese (zh-Hant) and English from day one; Cantonese terms (碰/上/槓/食糊) in both locales.
- Colourblind-safe: dragons distinguished by glyph, not just red/green. High-contrast tile theme.
- DOM live region announcing "East discarded 5 bamboo", and a keyboard path through your hand
  (arrow keys + Enter) that bypasses the canvas.
