# 99 — Deferred

Ideas cut from the v1 plan during the 2026-09-14 design audit. Nothing here is rejected on
merit; it is out of scope for v1 and parked so the intent survives without the false precision
of a live spec. Each entry names the doc and section it came from.

Before reviving anything here, re-read the source section — the surrounding design has changed.

## From 00-architecture.md

### Client-contributed entropy for provable fairness

Provenance: `00-architecture.md` §9 (anti-cheat, item 4) and §3/§5 (D2) — deferred per doc-audit
finding 5: the server-only commit/reveal scheme proves the wall wasn't edited *after* commitment,
not that the deal was unbiased, since the server alone picks `hand_seed` and `nonce` and already
knows the resulting wall before it commits.

**Scheme (post-v1):** each seat contributes entropy the server cannot see in advance.

1. Before the deal, each of the four seats independently generates a private nonce `nᵢ` and
   sends a commitment `Cᵢ = SHA256(nᵢ)` to the server. The server does not yet know any `nᵢ`.
2. Once all four commitments are in, the server combines them:
   `hand_seed = SHA256(n₀ ‖ n₁ ‖ n₂ ‖ n₃)` — but it can only compute this *after* every seat has
   locked in its commitment, so no seat (including the server) can choose its own nonce in
   response to seeing another party's contribution or the resulting deal.
3. Deal proceeds as in v1: `hand_seed` shuffles the wall (§3), and it — not `game_seed` — is what
   gets revealed at hand end.
4. At hand end, each seat reveals its `nᵢ`; everyone checks `SHA256(nᵢ) == Cᵢ` and recomputes
   `hand_seed` independently. If it matches what was used to deal, no party (server included)
   could have picked their contribution knowing the outcome.

**Needs before un-deferring:**
- A commit round adds a network round-trip before every hand can start; needs a bounded timeout
  and a defined fallback (server-only entropy for that hand? seat forfeits and a bot substitutes
  its nonce?) for a seat that never sends `Cᵢ` or never reveals `nᵢ`.
- Bots need a nonce-generation story — a bot seat still needs to contribute unpredictable
  entropy, not a fixed or server-supplied value, or it reduces to the server picking its share.
- Decide whether this applies to every hand or only rated/ranked play, given the added latency.
- Protocol messages for the commit/reveal round don't exist yet (`02-protocol.md`).

---

### Multi-node scaling detail (stages 2–3) and mid-game durability

Provenance: `00-architecture.md` §7 (scaling path) — deferred per doc-audit findings 7 and 8.
v1 (this doc's actual scope) is single-process with no mid-game durability: a process death
abandons every live room in it. Everything below is the deferred design space for surviving that,
compressed to intent in §7 itself.

**Stage 2 — N nodes, sticky rooms.** A room is pinned to exactly one node for its lifetime; a
lightweight router in front holds only a room→node directory, the matchmaking queue, and lobby
presence, and redirects `GET /rooms/{id}/route` to the right node's WebSocket URL. Room state
itself is never distributed — `shard by room, never split a room` (the single-writer invariant
in §3 depends on this).

**Stage 3 — durability.** The originally-drafted plan was "append each action to Postgres as it's
applied," with a parenthetical alternative of "or batch per hand." These are not interchangeable
and the doc previously left both standing at once, which is the bug this entry replaces:

- **Per-action append** conflicts directly with §3's own invariant — "no `await` between read and
  write of shared state" — since a Postgres write is real I/O and awaiting it inside the room's
  synchronous reduce-and-publish step reintroduces exactly the race the single-task-per-room
  design exists to avoid. Making it safe requires moving the write off the hot path (e.g. a
  separate writer task fed by a queue the room enqueues into without awaiting), which changes the
  durability guarantee: a write can now be lost between "room applied it" and "writer persisted
  it," narrowing but not eliminating the crash window.
- **Batch per hand** has a larger, differently-shaped crash window: it loses exactly the
  in-progress hand on a crash — the one hand a durability feature exists to protect — while
  being cheaper and easier to keep off the room's hot path.
- Whichever is chosen, **exact replay is the hard unsolved part**, independent of write
  granularity: `reduce` is pure only over its explicit inputs, and two categories of
  non-determinism currently happen *outside* `reduce` and are not logged as actions at all:
  - **Bot decisions** are ε-random ([04-bots.md](04-bots.md)) — replaying "what the bot decided"
    requires logging the decision itself as a first-class action, not just re-running bot logic
    against replayed state, since re-running would pick a different ε-random branch.
  - **Timer expiries** (tsumogiri-on-timeout, auto-pass-on-timeout, bot-deadline defaults,
    §8) are server-clock-driven, not derived from `GameState`; an exact replay needs each expiry
    logged as the action it produced, with enough info to know *why* it fired, not just recompute
    a new deadline against a possibly-different wall-clock on the replaying node.

None of this — write granularity, the async-invariant fix, or the non-determinism log format —
has a chosen design yet. It needs one before Stage 3 is buildable; §7 states the v1 fallback
(process dies → games abandoned, softened only by the planned-shutdown drain in §8.1) rather than
committing to an unresolved durability story.

## From 01-rules-spec.md

### Multi-win (一炮多響)

Provenance: `01-rules-spec.md` §6 (claim priority), §10 (`RuleSet.multi_win`), §11 (edge case
7) — deferred per canonical decision D7: v1 is single-winner; 一炮多響 is deferred past v1.

**Full behavior (post-v1):** when two or more players can declare a win off the same
discard, instead of resolving to a single winner by seat-order tiebreak
(`(claimer_seat - discarder_seat) % 4`, smallest wins — the v1 rule, see
`01-rules-spec.md` §6), all claimants win simultaneously. The discarder pays each winner in
full (i.e. the discarder's total liability is the sum of `P` for every winning hand, not
split). Each winning hand is scored independently — no `1.5×` self-draw-style adjustment,
since this is still a discard win for each claimant. Dealer continuity (連莊) follows
whichever house rule the table has configured for multi-winner hands (commonly: dealer
repeats only if the dealer is among the winners).

Needs before un-deferring:
- Decide whether all winners are required to reveal their full hand simultaneously or in
  seat order (affects information leakage in the reveal sequence).
- Decide interaction with `pao_rules` (包) if a discarder is liable under a responsibility
  rule for one hand but not another among the multiple winners.
- Client/protocol support for a multi-winner `SCORING` payload (currently single-winner
  shaped, see `02-protocol.md`).

`RuleSet.multi_win: bool` field stays in the dataclass as a reserved flag (`False` in v1) so
the shape doesn't need to change when this is implemented.

## From 02-protocol.md

### Deferred material cut from docs/02-protocol.md

### Chess-clock bonus bank

From `02-protocol.md` §4 (Timers).

Each player gets `bonus_seconds` (default 20) for the whole game, drawn down only after the
per-turn budget is spent — like a chess byoyomi/bank.

Cut per D16: a bank means the deadline for a prompt can extend mid-flight (spend some of the
bank, get more time), but the rest of §4 is built entirely around a single immutable
`deadline_ts` per prompt with no message that pushes a *revised* deadline to the client. Adding
the bank properly requires:

- A new server→client event (or a mutable field on the existing prompt) that updates
  `deadline_ts` when a player draws on their bank, plus client handling to extend an
  already-rendered countdown instead of just reading the deadline once.
- A decision on what the client is even allowed to see before the bank is spent — does the
  timer bar show "you may extend" as an affordance, or is spending the bank an explicit action
  (e.g. a `use_bonus` intent) rather than automatic?
- Interaction with §9 (turn timeout auto-action) and §8/backpressure — a revised-deadline event
  arriving late or getting dropped under backpressure must not leave the client counting down
  against a stale deadline.

None of that is designed yet. Keep the absolute-`deadline_ts` + measured-clock-offset model
as-is (it's correct) and revisit the bank as a follow-up feature with its own event type once
the extension-message design is worked out.

Related: the `bonus_seconds: int = 20` field this feature needed has been removed from the
`RuleSet` in `01-rules-spec.md` §10. Reviving the bank means adding it back alongside the
deadline-extension message described above.

## From 03-frontend.md

### Deferred — 03-frontend.md

Cut during the docs audit (2026-09) that resolved the Pixi → DOM rendering decision. Content here
was removed from `docs/03-frontend.md` for scope, not because it's wrong; nothing here is
designed, just parked. Main-doc pointers read "Deferred — see [99-deferred.md](99-deferred.md)."

### Faan preview on hover

Provenance: was `03-frontend.md §4` (Interaction model), cut — no protocol message carries
shanten/ukeire, and a client-side TypeScript reimplementation duplicates the one deliberately-pure
Python engine (`00-architecture.md §3`).

Original: "Faan preview on a hovered discard candidate: shanten, wait count, and whether the hand
can reach the 3-faan minimum. Gated behind a training-mode setting for rated play."

Revisit as: a rate-limited server `hint` request/response reusing `mahjong_core.shanten`/
`ukeire`, not a client-side reimplementation. Needs a new protocol message — out of scope here,
flagged for whoever owns `02-protocol.md`.

### zh-Hant locale switching

Provenance: was `03-frontend.md §7`, cut — contradicted `05-roadmap.md` M6, which already places
i18n in the ongoing/later bucket; "from day one" was wrong.

Original: "Traditional Chinese (zh-Hant) and English from day one; Cantonese terms (碰/上/槓/食糊)
in both locales."

v1 ships English only, strings in one module. Cantonese term glyphs stay as untranslated labels
in both states — not blocked by this defer.

### Recorded Cantonese call-out audio

Provenance: was `03-frontend.md §5` (Asset pipeline), cut — nobody has recorded it; unbudgeted
content task, not a code task.

Original: "Sound: draw click, discard clack, claim call (recorded Cantonese 「碰」「上」「槓」
「食糊」), shuffle."

v1 ships draw/discard/shuffle UI SFX only, mute default-on.

### High-contrast tile theme system

Provenance: was `03-frontend.md §7`, cut — a switchable theme engine is more surface area than v1
needs. The colourblind-safe glyph is a fixed asset, not a theme, and ships regardless
(`03-frontend.md §8`).

Original: "Colourblind-safe: dragons distinguished by glyph, not just red/green. High-contrast
tile theme."

### Drag-to-reorder hand, sticky per session

Provenance: was `03-frontend.md §4`, cut — extra interaction + persistence surface for v1;
auto-sort covers the actual need (finding tiles fast).

Original: "Sort hand: auto by default; drag to reorder, sticky per session [desktop] / drag
[touch]."

### Chess-clock bonus-bank meter

Provenance: `02-protocol.md` §4 (Timers), where the bank was cut along with the `bonus_seconds`
config field; no dedicated client UI was specified for v1 either.

v1 behaviour: bonus seconds are enforced server-side and folded into `deadline_ts` like any other
deadline; no separate meter/visualization. Revisit once the base countdown ring (`03-frontend.md
§5`) ships and there's a UX reason to distinguish "spending bonus time" from "spending turn time."

### @1x tile atlas

Provenance: was `03-frontend.md §5` (Asset pipeline: two atlases, @1x/@2x, picked by DPR) — moot,
not really deferred. SVG tile art is resolution-independent, so there's no atlas, DPR split, or
build pipeline at all. Noted for history only.

### 2.5D Blender pre-render

Provenance: was `03-frontend.md §5`, cut — the DOM approach gets the 2.5D look from `perspective`
+ `rotateX` on the table container (`03-frontend.md §2`) at zero asset cost.

Original: "2.5D look: pre-render tiles in Blender at the table's fixed camera angle, ship as
sprites — real lighting and bevels at zero runtime cost."

Source asset pack for a future higher-fidelity pass:
[libreriichi-assets](https://codeberg.org/davidgomez/libreriichi-assets) (CC0 3D textures +
Blender sources), kept for reference.

## From 04-bots.md

### Deferred from 04-bots.md

Cut per audit decision D16. Original source: `docs/04-bots.md`, pre-audit versions of §2 (T3
row), §6 ("T3 — search"), and §7 (bot personas paragraph, Expert row detail).

### T3 `SearchBot`

Provenance: `04-bots.md` §2, tier table row for T3 (pre-audit).

| Tier | What it is | Effort | Use |
| --- | --- | --- | --- |
| **T3** `SearchBot` | determinized rollouts / MCTS over the pure engine | large | "Expert", post-launch |

### T3 — search

Provenance: `04-bots.md` §6, "T3 — search" (pre-audit; cut because T1/T2 alone satisfy the M4
done-gate per the D9/§4 fix, and the 300–800ms budget below is incompatible with the
single-worker, single-event-loop process described in `07-infra.md` — it would block every room,
every socket, and every heartbeat on that process if run inline, and even off-loop it competes
for the same `ProcessPoolExecutor` capacity flagged as a real constraint in §3).

With a pure engine, determinized MCTS is straightforward:

1. Sample N worlds consistent with the redacted view (unseen tiles distributed among opponents
   and wall, respecting counts and light discard-based inference).
2. Run rollouts with T2 policies as the default policy.
3. Average action values across worlds; pick the best.

Budget 300–800ms per decision, inside human think time. The known weakness is **strategy
fusion** (the search assumes it can act differently per world when it can't); information-set
MCTS mitigates it. Read [arXiv:1904.07491](https://arxiv.org/pdf/1904.07491) on MDP abstraction
for mahjong before building this.

Before reviving this: re-derive the per-decision CPU budget against whatever the
`ProcessPoolExecutor` sizing turns out to be (see `04-bots.md` §3) — 300–800ms per decision at
200 concurrent tables × 3 bot seats is a much larger capacity ask than the T1/T2 shanten-table
path and needs its own worker-pool sizing pass, not a shared one.

### Bot personas

Provenance: `04-bots.md` §7, paragraph following the difficulty table (pre-audit); the Expert row
that referenced this tier is also cut, see above.

Give each bot a **persona** — a name, an avatar, a play-style bias (aggressive / defensive /
flush-lover) and a think-time distribution. A bot that reliably chases full flushes is more
memorable than one that's marginally more optimal.

| Level | How |
| --- | --- |
| Expert | T3 with search budget |

## From 05-roadmap.md and 06-ml.md

### Deferred from 05-roadmap.md and 06-ml.md

Cut during the post-audit fix pass (D10, D11, and the doc-8/12 directive to trim `06-ml.md` down
to the two things worth doing now). Original sources noted per item.

### Pixi golden-PNG screenshot tests

Provenance: `05-roadmap.md` §3, Client testing row (pre-audit).

Cut because D10 removed PixiJS entirely — the table is DOM/CSS, so there is no `<canvas>` scene
to screenshot-test. Also worth remembering if a canvas renderer ever comes back: golden-PNG scene
tests are notoriously flaky across GPU/driver/font differences regardless of which renderer
produced the canvas, so re-adopting this pattern later needs a flakiness budget, not just a
revived test file.

### 3D / 2.5D table rendering

Provenance: `05-roadmap.md` §5, open question #6 (pre-audit): "A genuinely 3D table changes the
asset pipeline; decide now."

Cut, not merely deferred as a live "decide later" question — D10 settled rendering as DOM/CSS.
A 3D/2.5D asset pipeline is out of scope for this project, full stop. Recorded here only because
the question and its framing existed in the doc and the audit wants cuts to leave a trail.

### Early bot-vs-bot game recording as training data

Provenance: `06-ml.md` §1 (pre-audit): "Start recording now — every bot-vs-bot game from M1
onward is training data later."

Cut as pointless rather than merely early: M1's only bots are `RandomBot`s, the
behaviour-cloning prior needs to be `FaanBot` (`06-ml.md` §4/§5), and the engine's pure +
seeded design means regenerating self-play data on demand is free. `GameRecord` persistence
itself is *not* cut — it still happens from M1 (`06-ml.md` §2) — only the "this is training data,
starting now" framing is.

### `SeatView` input-boundary writeup

Provenance: `06-ml.md` §2 (pre-audit), "Input boundary."

```
GameState ──seat_view(state,seat)──► SeatView ──► bot ──► Intent
                                 │
                                 └──► (day 2) encode() ──► tensor ──► policy
```

The encoder takes `SeatView`, never `GameState`, so a network trained this way is structurally
un-cheatable. The rule to hold in M3: `seat_view()` is the only path to seat-visible state — no
shortcuts for bots, ever. Cut from the trimmed `06-ml.md` because it mostly restates
`04-bots.md` §1's existing plan rather than adding new ML-specific work; revive alongside the
day-2 encoder.

### Shared feature functions (shanten / ukeire / safety as pure `SeatView` functions)

Provenance: `06-ml.md` §4 (pre-audit), "Shared feature functions."

T1/T2 need shanten, ukeire, safe-tile inference, and faan-reachability regardless
(`04-bots.md`). Put them in `mahjong_core` as pure functions of a `SeatView`, not buried inside
bot classes, so a day-2 encoder can call the same functions. The bot-side need for these
functions is not deferred — only their framing as ML-boundary work is.

### Feature-plane encoding

Provenance: `06-ml.md` §4 (pre-audit), closing paragraph.

Feature planes over the 34 tile types, thermometer-encoded counts, players in relative seat
order. Day-2 work in the pre-audit doc, unchanged by this pass — still day 2.

### PettingZoo AEC environment wrapper

Provenance: `06-ml.md` §6 (pre-audit), "Day-2 work" list.

[PettingZoo AEC](https://pettingzoo.farama.org/api/aec/) wrapper around the pure engine, for
training-loop compatibility with standard RL tooling.

### Behaviour cloning from `FaanBot`

Provenance: `06-ml.md` §6 (pre-audit), "Day-2 work" list.

Blocked on two things beyond just "day 2": `FaanBot` existing (now M4 per D11, not M6), and a
compute budget / target metric being defined somewhere — neither exists in the doc set yet. See
`06-ml.md` §3 for the honest version of this constraint.

### Self-play PPO + batched inference serving

Provenance: `06-ml.md` §6 (pre-audit), "Day-2 work" list.

Was listed as a casual day-2 bullet alongside behaviour cloning. Realistically thousands of
GPU-hours (see Suphx, arXiv:2003.13590) with no compute budget or success metric defined
anywhere in this doc set — do not schedule this against a milestone until both exist.

## From 07-infra.md

### Deferred from 07-infra.md

Material cut from `docs/07-infra.md` during the D16 audit pass. Feed into
`docs/99-deferred.md` when that file exists.

### KV / Queue / Bus ports

Cut from §1. A Redis-shaped `Protocol` abstraction (`app/infra/ports.py`) for matchmaking,
presence and rate limiting, backed by in-process implementations — written for a Redis that
doesn't exist yet, fronting a single process that doesn't need the indirection. Revisit if/when
stage 2 (multi-node) actually happens; until then this is over-engineering for a one-process
server.

```python
class KV(Protocol):
    async def get(self, k: str) -> bytes | None: ...
    async def set(self, k: str, v: bytes, ttl: int | None = None) -> None: ...

class Queue(Protocol):                       # matchmaking
    async def push(self, q: str, item: bytes) -> None: ...
    async def pop_n(self, q: str, n: int) -> list[bytes]: ...   # atomic

class Bus(Protocol):                         # lobby presence fan-out, never in-room
    async def publish(self, ch: str, msg: bytes) -> None: ...
    def subscribe(self, ch: str) -> AsyncIterator[bytes]: ...
```

In-process matchmaking/presence/rate-limiting can live as plain module-level state or a small
non-`Protocol` class until a second node is actually on the roadmap.

### Multi-node scaling infrastructure

Cut from §2. The router, room→node directory, and `ws://node-N/ws?room=...` routing scheme
described as "stage 2" in `00-architecture.md §7`. There is one process and no `scale` compose
profile; this is a stage-2+ concern and shouldn't be designed against until stage 1 (one
process, hundreds of tables) is actually load-bearing.

## From web/AGENTS.md

### TypeScript 7 as the primary compiler (svelte-check)

Provenance: `web/AGENTS.md` "Commands" section. `typescript` is currently pinned to `^6.0.3` as
the primary dependency; TS7 is installed only as a secondary aliased package
(`@typescript/native`, `npm:typescript@^7`) and used exclusively via `svelte-check --tsgo`
(`web/package.json`'s `check`/`check:watch` scripts).

Not a v1 scope cut — a genuine upstream blocker, not a project decision. `svelte-check`'s own
CLI does an unconditional `require('typescript')` at its top level and hard-requires that to
resolve to TS5/6 even in `--tsgo` mode (confirmed against `sveltejs/language-tools#3063`);
TypeScript 7 doesn't yet expose a stable programmatic API for embedding tools — Volar,
svelte-check, Vue, and Astro all hit the same wall. From Microsoft's own TS7 announcement,
quoted in that issue: "tools which embed TypeScript into their own compilers and language
services can only currently rely on TypeScript 6.0 ... We expect this to be a point-in-time
issue." No date attached as of 2026-09. The `svelte-check` maintainer's own stated plan
(2026-08-31): even TS 7.1's "content mapper" support — the next incremental step — "will
currently still require both TypeScript 6 and 7."

**Needs before un-deferring:**
- TypeScript ships a stable programmatic API `svelte-check` (and the rest of the Volar-based
  tooling ecosystem) can embed directly — the actual blocker, owned upstream by the TypeScript
  team, not by us or by Svelte's maintainers.
- `svelte-check` drops the TS6-primary requirement once that API exists.
- Before then, if still relying on `--tsgo` in the meantime: re-check its own open bugs —
  `sveltejs/language-tools#3120` (includes more files than expected under `--tsgo`) and `#3095`
  (crashes on Linux/arm64 CI, not repro'd on macOS — our CI runs `ubuntu-latest`/x86_64, so
  likely not hit, but worth reconfirming before depending on it further).

**When it lands:** drop the `@typescript/native` alias, bump `typescript` straight to whatever
TS7.x is current, remove `--tsgo` from `web/package.json`'s `check`/`check:watch` scripts, and
delete the rationale note in `web/AGENTS.md`.

