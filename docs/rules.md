# Hong Kong mahjong rules

The rules `mahjong_core` implements. Every house-rule variation lives behind `RuleSet` (§10);
named presets are in `mahjong_core/presets.py` (`hk_classic`, `hk_casual`, `hk_strict`).

## 1. Tiles — 144

| Group | Types | Copies | Total |
| --- | --- | --- | --- |
| Characters 萬 (m) 1–9 | 9 | 4 | 36 |
| Bamboo 索 (s) 1–9 | 9 | 4 | 36 |
| Dots 筒 (p) 1–9 | 9 | 4 | 36 |
| Winds 風 E S W N (z1–z4) | 4 | 4 | 16 |
| Dragons 箭 中 發 白 (z5–z7) | 3 | 4 | 12 |
| **Playable subtotal** | **34** | | **136** |
| Flowers 花 (f1–f4) + Seasons 季 (f5–f8) | 8 | 1 | 8 |
| **Total** | | | **144** |

**Representation.** A `34`-length count array in the hot path (shanten, ukeire, pattern
matching). An ordered list only for UI tile ordering and animation identity.

```python
TileId = int          # 0..135, opaque per-hand identifier (see below)
TileType = int        # 0..33, suit/rank
Flower = int          # 0..7
```

**`TileId` is not a wall slot.** It is assigned via a permutation independent of shuffle order
(a per-hand relabeling applied after the deal), so a `TileId` never reveals where in the wall a
tile came from. Numbering tiles in shuffled-wall order would leak wall position through a field
redaction tests never flag.

Index layout: `0–8` = 1m–9m, `9–17` = 1p–9p, `18–26` = 1s–9s, `27–30` = E S W N,
`31–33` = 中 發 白 — the layout most open-source shanten implementations use, so results can be
cross-validated against them.

## 2. Seating and rounds

- Four seats: East 東, South 南, West 西, North 北, proceeding **counter-clockwise**
  (East → South → West → North) — opposite the visual clockwise order.
- **Seat frame (canonical, used everywhere):** seats are numbered `0..3` in turn order (East=0,
  South=1, West=2, North=3). "Next seat" always means `(seat + 1) % 4`. This is the only axis used
  for chow eligibility (§5) and claim priority (§6); "upstream"/"downstream" are not used.
- **Prevailing wind** (圈風) starts East. **Seat wind** (門風) is the player's position.
- Dealer is East. Dealer **repeats** (連莊) on a dealer win or, by config, on an exhaustive draw.
  Otherwise the deal passes counter-clockwise; after a full rotation the prevailing wind advances.
- `game_length`: `EAST_ONLY` (一圈, default), `EAST_SOUTH` (半莊 — a riichi convention, offered
  but not the HK norm), `FULL` (四圈 — the traditional long-session HK length).

## 3. Deal

1. Shuffle 144 tiles with the seeded PRNG (136 if `flowers_enabled=False` — flowers/seasons are
   dropped before shuffling and step 4 never triggers). Conceptually four walls of 18 stacks × 2.
2. Roll dice → break point. Cosmetic; derived from the same seed.
3. Deal 13 tiles to each player, 14 to the dealer, in seat order from the dealer: three rounds of
   four tiles then a round of one (mirroring the physical deal), dealer drawing one further tile
   at the end, all from the front of the wall. The interleaving is cosmetic — the wall is already
   a uniform random permutation — but fixed for reproducible replays and animation.
4. **Flower replacement**, in seat order from the dealer: each player reveals any flowers/seasons
   and draws replacements from the **back end** of the wall, repeating until they hold none. One
   seat's cascade (which may chain) fully resolves before the next seat's, not round-robin — order
   changes who gets which tile.
5. Dealer discards.

## 4. Turn state machine

```
                    ┌─────────────┐
       ┌───────────►│  AWAIT_DRAW │◄────────────┐
       │            └──────┬──────┘             │
       │                   │ draw (or kong      │
       │                   │ replacement)       │
       │                   ▼                    │
       │          ┌──────────────────┐          │
       │          │ flower? -> reveal│          │
       │          │ + redraw, loop   │          │
       │          └────────┬─────────┘          │
       │                   ▼                    │
       │        ┌─────────────────────┐         │
       │        │   AWAIT_ACTION      │  self-draw win (自摸)
       │        │  discard | concealed│──────────────────────► SCORING
       │        │  kong | add-to-pung │
       │        │  | declare win      │
       │        └──────────┬──────────┘
       │                   │ discard
       │                   ▼
       │        ┌─────────────────────┐   no legal claims
       │        │   AWAIT_CLAIMS      │──────────────────────┘
       │        │  window_id, deadline│
       │        └──────────┬──────────┘
       │                   │ claim resolved
       │      ┌────────────┼────────────┐
       │      ▼            ▼            ▼
       │   win (食糊)   pung/kong      chow
       │      │            │            │
       │      ▼            └─────┬──────┘
       │   SCORING               ▼
       │                  ┌─────────────┐
       └──────────────────┤ AWAIT_ACTION│  (claimer now discards;
                          └─────────────┘   kong draws a replacement first)

   wall exhausted (`wall_reserve` tiles left, default 0) -> EXHAUSTIVE_DRAW (流局) -> next hand
```

Phases: `AWAIT_DRAW`, `AWAIT_ACTION`, `AWAIT_CLAIMS`, `AWAIT_KONG_ROB`, `SCORING`, `HAND_OVER`,
`GAME_OVER`.

## 5. Melds

| Meld | Cantonese | From | Notes |
| --- | --- | --- | --- |
| Chow 順子 | 上 | discard only, `claimer_seat == (discarder_seat + 1) % 4` | three consecutive, same suit |
| Pung 刻子 | 碰 | discard, any player | three identical |
| Exposed kong 明槓 | 槓 | discard, any player | four identical; draw replacement from back of wall |
| Added kong 加槓 | 加槓 | own draw added to an exposed pung | **opens a robbing-the-kong window** |
| Concealed kong 暗槓 | 暗槓 | four drawn by self | laid face down; identity hidden until hand end; cannot be undone; draw replacement |

Kong replacements come from the **live wall** (§9) — HK play has no separate dead wall, so each
kong brings the exhaustive draw one tile closer.

**Pung vs. kong, same holder.** A player holding 3 concealed matching tiles gets both a pung and
an exposed-kong option when the 4th is discarded and may elect the smaller meld. The kong-vs-pung
tiebreak in §6 is about two *different* players claiming the same discard.

## 6. Claim priority

**Canonical home** for claim priority, including the kong-vs-pung tiebreak. Other docs (e.g.
[architecture.md §4](architecture.md)) link here; if they conflict, this section wins.

```
Win  >  Kong / Pung  >  Chow
```

1. **Win (食糊)** beats every other claim on the same discard.
2. **Kong (槓) and Pung (碰)** beat Chow; either can come from any seat.
   - **Kong-vs-Pung tiebreak, same tile:** kong wins. With 4 copies per tile type (§1) this case
     can't actually arise at the table (point 5), but the resolver implements the ordering rather
     than assuming that invariant.
3. **Chow (上)** is only legal for `claimer_seat == (discarder_seat + 1) % 4`. A chow claim from
   any other seat is illegal and rejected.
4. **Win-vs-Win tie:** the smallest `(claimer_seat - discarder_seat) % 4` wins. Always
   single-winner; 一炮多響 (`multi_win`) is not implemented
   ([ADR 0007](decisions/0007-multi-win-and-pao.md)).
5. **Pung/Kong-vs-Pung/Kong tie:** cannot happen — a discard leaves at most 3 other copies of its
   type, and a kong claim alone consumes all 3. Listed for completeness of the algorithm.

**Resolution algorithm:** collect all legal claims on a discard during the `AWAIT_CLAIMS` window;
pick the highest-priority claim type present; if multiple claims tie within it, apply that type's
tiebreak above.

## 7. Faan table

Grouped into `CLASSIC`, `NEW_6`, `NEW_18` hand sets, each toggleable via `hand_sets` (§10).
Individual patterns can be re-valued or disabled via `faan_overrides`.

### Classic

| Faan | Hand | Chinese |
| --- | --- | --- |
| 1 | All Sequences (any pair) | 平糊 |
| 1 | Seat Wind pung/kong | 門風 |
| 1 | Prevailing Wind pung/kong | 圈風 |
| 1 | Dragon pung/kong (each) | 箭刻 / 番牌 |
| 1 | No Flowers | 無花 |
| 1 | Self-Draw | 自摸 |
| 1 | Fully Concealed (no open melds, no concealed kong; self-draw or discard; never on Seven Pairs)³ | 門前清 |
| 1 | Seat Flower (each flower/season matching the seat, not counting one in a set) | 正花 |
| 2 | All four Flowers *or* all four Seasons (per set; replaces that set's Seat Flower faan) | 一台花 |
| 4 | Mixed Terminals (terminals + honors only, both present; replaces 對對糊)⁴ | 花么九 |
| 3 | All Pungs | 對對糊 |
| 3 | Half Flush (one suit + honors) | 混一色 |
| 5 | Small Three Dragons (pair of one dragon + pungs of the other two)¹ | 小三元 |
| 6 | Small Four Winds (pair of one wind + pungs of the other three)¹ | 小四喜 |
| 7 | Full Flush (one suit, no honors) | 清一色 |
| 8 | Big Three Dragons (pungs of all three)¹ | 大三元 |
| 8 | Four concealed pungs/kongs⁵ | 四暗刻 |
| **Limit 13** | Big Four Winds (pungs of all four)¹ | 大四喜 |
| **Limit 13** | Four Kongs | 十八羅漢 |
| **Limit 13** | Thirteen Orphans | 十三么 |
| **Limit 10** | All Honors | 字一色 |
| **Limit 10** | All Terminals | 清么九 |
| **Limit 10** | Nine Gates² | 九蓮寶燈 |
| **Limit 13** | Heavenly Hand (dealer wins on the deal, before any discard) | 天糊 |
| **Limit 13** | Earthly Hand (non-dealer wins on the dealer's first discard) | 地糊 |

¹ **Small vs. Big are mutually exclusive by construction; the dragon/wind ladders are inclusive totals.**
Pungs of all three dragons (or all four winds) commit 3 of each type's 4 tiles, leaving at most 1
— never enough for the pair Small needs. 小三元 (5) and 大三元 (8) already include their dragon
pungs, so they replace 箭刻 rather than stacking with it; 小四喜 (6) likewise replaces 門風/圈風.
Big Four Winds is a limit, so nothing stacks.

² **Nine Gates:** one suit, fully concealed (self-drawn or won on discard), 1-1-1-2-3-4-5-6-7-8-9-9-9
plus exactly one more tile of that suit, any rank 1-9. All nine 14th-tile ranks qualify.

³ **門前清 stacks with 自摸** on a concealed self-draw ("fully concealed self-drawn" = 2). A
concealed kong breaks it. 四暗刻 replaces it.

⁴ **花么九** (renamed from 混么九): composition is pungs only, so it always matches 對對糊's
shape and replaces it (inclusive total); can stack with 混一色.

⁵ **Concealed counts ron-aware.** A concealed kong counts; an exposed or added kong never does. On a
win off a discard, a pung of the winning tile's type is treated as completed by that discard, so it
is not concealed (`ScoringContext.winning_tile`). 四暗刻 replaces 對對糊 and 門前清.

### New 6 (新六番)

| Faan | Hand | Chinese |
| --- | --- | --- |
| 0 | Chicken Hand (zero other faan)² | 雞糊 |
| 1 | Win on last wall tile (self-draw, not a kong replacement) or on the last discard (claimed, not a kong rob)³ | 海底撈月 |
| 1 | Win on kong replacement | 槓上開花 |
| 1 | Robbing the Kong | 搶槓 |
| 8 | Chained Kong Win (replacement tile after a kong declared on a kong replacement; replaces 槓上開花 and 自摸)⁴ | 連槓開花 |

² **Conditional:** 雞糊 is only reachable when `min_faan == 0` — at `min_faan >= 1` a
zero-other-faan hand can't win at all. It is a baseline win worth 0 faan, not gated by a hand set.

³ **One pattern for both last-tile wins.** 河底撈魚 is not a separate pattern: the last discard
claimed for a win scores 海底撈月 as well. A kong replacement that is itself the wall's last tile
scores 槓上開花 only (§5, edge case §11.6), and a kong rob never scores it.

⁴ **Assumption:** 連槓開花 value (8) and its replacement of 槓上開花/自摸 follow common
HK house tables; no single authoritative source. Off by disabling `NEW_6`.

### New 18 (新十八番) — commonly used subset

**Off by default** (`hand_sets`, §10; opt-in, on in `hk_casual`). Seven Pairs is the one `NEW_18` pattern bot shanten also
cares about: `mahjong_core/shanten.py`'s `shanten()`/`ukeire()` run the Seven Pairs parse only when
`NEW_18` is present ([bots.md §8](bots.md)). Thirteen Orphans (十三么) is `CLASSIC` and always on.

| Faan | Hand | Chinese |
| --- | --- | --- |
| 4 | Seven Pairs (plain faan, not a limit hand) | 七對子 |


### Patterns deliberately not scored

Removed because they are not standard Hong Kong faan; the history is in the ADR log.

| Pattern | Why not |
| --- | --- |
| 缺一門, 三暗刻, 全求人, 雙箭 | not in the standard HK table (雙箭 is just two 箭刻) |
| 一般高, 三般高, 三步高, 四步高 | Taiwanese / Japanese-style sequence bonuses; HK pays no faan for chow patterns beyond 平糊 |
| 河底撈魚 | folded into 海底撈月 (§7 New 6 note ³) |

### Flower faan

`1` per flower matching the player's seat — 正花 (gated by `flowers_score`) — plus `無花` above. A
complete set of four flowers or four seasons is 一台花, `2` per set, replacing the seat flower of
that set. Both are `HandSet.CLASSIC`.

`seven_flowers_instant_win` (3 faan) and `eight_flowers_instant_win` (limit) aren't faan patterns:
an instant win ends the hand on flower count alone, with no decomposition to score, so they live
in `engine.py`'s `_flower_instant_win` (named `七花`/`八花`), not the pattern registry.

**Known gap:** instant win is only checked on a mid-hand replacement draw (`_draw_and_cascade`).
A hand holding 7+ flowers straight off the initial deal's replacement pass
(`wall.replace_flowers`) is not caught.

### Stacking and caps

- Faan **stack**: Full Flush (6) + All Pungs (3) = 9.
- **Seat Wind and Prevailing Wind stack on the same pung.** In the East round, the dealer's own
  East pung earns both 門風 and 圈風 — 2 faan.
- **Limit hands do not stack with anything** — not wind/dragon/flower faan, not each other. Two
  tiers: 字一色/清么九/九蓮寶燈 are worth 10, the rest 13; a limit pays `min(tier, faan_cap)` and
  the highest-paying limit wins.
- `faan_cap`: `8`, `10` (HK Mahjong Association) or `13` (common casual). Total is clamped.
- `min_faan`: `0 | 1 | 3 | 5`, default **3**. **A hand below the minimum cannot be declared a
  win** — enforced server-side (§11.8). This changes bot strategy fundamentally
  ([bots.md §4](bots.md)).

## 8. Faan → points → payment

Two conversion tables, selected by `score_table`:

```python
def points(faan: int, table: Literal["full_spicy", "half_spicy"]) -> int:
    if table == "full_spicy":            # 全辣
        return 2 ** faan
    # 半辣: same through 4 faan, then doubles every two faan; odd faan above 4 is 1.5x
    # the previous. 3->8, 4->16, 5->24, 6->32, 7->48, 8->64, 9->96, 10->128
```

Payment, where `P = points(faan, table)`:

| Win type | Config | Who pays what |
| --- | --- | --- |
| **Self-draw** 自摸 | — | Award is `1.5 × P` (keeps it divisible by three). Each of the three losers pays `0.5 × P`. |
| **Win on discard** 出銃 | `discard_payment = ALL` (default) | Discarder pays `P`. Others pay nothing. |
| **Win on discard** | `discard_payment = HALF` | Discarder pays `P/2`; the other two pay `P/4` each. |

Worked example: 3 faan, full spicy → `P = 8`.
- Discard win, pays-all: discarder −8, winner +8.
- Self-draw: each loser −4, winner +12.

**Rounding when `P` doesn't divide evenly.** Only reachable at `faan = 0` (`P = 1`, legal only at
`min_faan = 0`). Round each share to the nearest whole point, ties up; fix the winner's total (`P`
for a discard win, `3 ×` the rounded loser share for self-draw) and derive the rest from it so
payments always sum to zero. Under `discard_payment = HALF`, round the discarder's half first and
let any leftover from splitting the other half fall back onto the discarder.

**Robbing the kong (搶槓)** pays exactly like a win on discard, with the robbed seat standing in
for the discarder.

### Penalty / responsibility rules (包)

Not implemented (`pao_rules` is reserved; [ADR 0007](decisions/0007-multi-win-and-pao.md)).
Reference, applicable under `discard_payment = HALF`:

| Rule | Chinese | Trigger |
| --- | --- | --- |
| 9-Piece Penalty | 九張包 | Discarder feeds a full-flush hand that already has 3 melds in one suit |
| 12-Piece Penalty | 十二張包自摸 | Same, allowing a 4th meld, winner then self-draws |
| Fifth-Tile Penalty | 五子包生 | Discarding a fresh tile with ≤5 wall tiles left, feeding the win |
| Great Dragons/Winds feeder | 大三元/大四喜包 | Discarder completes the third dragon or fourth wind pung |

## 9. Exhaustive draw (流局)

HK play has no dead wall: the wall is drawn down to nothing, kong replacements come off the same
live wall (§5), and the literal last drawable tile is 海底 (§7, 海底撈月). `wall_reserve` lets a
table hold tiles back (e.g. a riichi-style dead wall) but **defaults to `0`**. Wall exhausted with
`wall_reserve` tiles remaining → no winner, no payment (`tenpai_payments`, off by default). Dealer
repeats or passes per `dealer_repeat_on_draw`.

`four_kong_abort` and `nine_terminals_abort` (九種九牌) are declared but not implemented (§11.5).

## 10. `RuleSet`

```python
@dataclass(frozen=True)
class RuleSet:
    # scoring
    min_faan: int = 3                       # one of 0 | 1 | 3 | 5; below this a hand cannot win
    faan_cap: int = 10                      # one of 8 | 10 (HKMA) | 13 (casual); total is clamped
    score_table: ScoreTable = ScoreTable.HALF_SPICY
    hand_sets: frozenset[HandSet] = frozenset({CLASSIC, NEW_6})
    faan_overrides: dict[str, int] = field(default_factory=dict)
        # per-pattern faan overrides, keyed by the Chinese name in §7 (e.g. {"雞糊": 0} to
        # disable, {"清一色": 7}) — applied after hand_sets selection, before stacking/caps.
    discard_payment: DiscardPayment = DiscardPayment.ALL
    self_draw_multiplier: float = 1.5
    flowers_score: bool = True              # 正花: +1 faan per flower matching seat, see §7
    seven_flowers_instant_win: bool = False # 3 faan, see §7
    eight_flowers_instant_win: bool = False # limit hand, see §7
    thirteen_orphans_wait_bonus: bool = False  # declared, not implemented (§11.10)

    # flow
    game_length: GameLength = GameLength.EAST_ONLY  # 一圈; see §2
    dealer_repeat_on_win: bool = True
    dealer_repeat_on_draw: bool = True
    wall_reserve: int = 0                   # HK default: no dead wall, see §9
    four_kong_abort: bool = False           # declared, not implemented (§11.5)
    nine_terminals_abort: bool = False      # 九種九牌; declared, not implemented (§11.5)
    tenpai_payments: bool = False           # pay tenpai players on exhaustive draw, see §9

    # variants
    flowers_enabled: bool = True
    multi_win: bool = False                 # 一炮多響 — reserved, must stay False (ADR 0007)
    kong_rob_enabled: bool = True
    concealed_kong_robbable: bool = False   # only for 十三么, some tables
    pao_rules: bool = False                 # 包 — reserved, not implemented (§8)

    # fairness (see protocol.md §3 "Fairness")
    provable_fairness: bool = False         # gates hand_start.seed_commit / hand_end.fairness

    # timing (server-enforced)
    turn_seconds: int = 15                  # AWAIT_ACTION timeout
    claim_seconds: int = 5                  # AWAIT_CLAIMS window
    hand_end_seconds: int = 10              # HAND_OVER hold, until all seats ack or timeout
    turn_timeout_strikes: int = 3           # timeouts before seat flips to AUTOPLAY
    disconnect_grace_seconds: float = 20.0  # DISCONNECTED -> AUTOPLAY, architecture.md §8
```

`ScoreTable`/`HandSet`/`DiscardPayment`/`GameLength` are `StrEnum`s (`mahjong_core/config.py`).
`self_draw_multiplier` (§8 hardcodes 1.5), `four_kong_abort`, `nine_terminals_abort`,
`thirteen_orphans_wait_bonus`, `tenpai_payments`, `multi_win` and `pao_rules` have no reader —
setting them has no effect. The create-table editor hides them (`INERT_RULE_FIELDS`, frontend.md §7).

**Presets** (`mahjong_core.presets.RULESET_PRESETS`): `hk_classic` (the defaults above),
`hk_casual` (`min_faan=1`, `faan_cap=13`, `score_table=FULL_SPICY`, `NEW_18` on), `hk_strict` (`min_faan=5`, `discard_payment=HALF`). `custom` takes a full
`RuleSet.from_dict` body. `resolve_ruleset` never hard-rejects: an unknown preset or invalid custom
body falls back to `hk_classic`.

## 11. Edge cases

Each has a named test.

1. Flower drawn as a kong replacement → another replacement; can chain.
   `test_flower_drawn_mid_game_chains_to_a_replacement`.
2. Winning on a flower replacement = 槓上開花. A kong replacement that's a flower and chains
   through further replacements still scores it — `last_draw_was_kong_replacement` is set once,
   from the original draw.
   `test_win_after_flower_chain_from_kong_replacement_still_scores_kong_replacement`.
3. Robbing an **added** kong (加槓); robbing a **concealed** kong only for 十三么 and only if
   `concealed_kong_robbable`. `engine.py`'s `_kong_rob_offers` restricts concealed-kong robbing to
   a candidate hand that resolves to 十三么 specifically.
   `test_concealed_kong_robbing_denied_to_a_non_thirteen_orphans_win`/
   `test_concealed_kong_robbing_allowed_for_a_thirteen_orphans_win`.
4. Concealed kong that changes an already-tenpai hand's wait — legal in HK. `legal_self_melds` is a
   tile-count check only, so it's legal by construction.
5. Four kongs across different players → `four_kong_abort`. **Not implemented:** `four_kong_abort`
   and `nine_terminals_abort` are never read by `engine.py`; no abort ever fires.
6. Last-tile draw and last-discard win scoring after kongs shorten the wall.
   `wall_exhausted_at_last_draw` compares against `wall_reserve`, not literal emptiness.
   `test_last_tile_flag_accounts_for_wall_reserve_after_a_kong_shortens_the_wall`.
7. Multi-win on one discard — not implemented ([ADR 0007](decisions/0007-multi-win-and-pao.md)).
8. Mechanically complete hand below `min_faan` — win is **disabled server-side**.
   `mahjong_core/actions.py`'s `can_declare_win`/`legal_actions` run
   `scoring.faan.score_winning_hand` against the current `GameState` and only offer `DeclareWin`
   when `clears_min_faan` is true; `engine.py`'s `_discard_claim_offers`/`_kong_rob_offers` do the
   same for `ClaimWin`.
9. Seven Pairs vs. standard parse of the same 14 tiles → scoring maximizes over *all* valid
   decompositions. `_detect_seven_pairs`/`_detect_thirteen_orphans`/`_detect_nine_gates` in
   `patterns.py` require an empty `hand` argument — these shapes never carry exposed melds, so that
   identifies the raw, no-decomposition candidate.
   `test_seven_pairs_vs_standard_decomposition_maximizes` (test_faan.py).
10. Thirteen Orphans 13-way wait vs. single wait (some tables double the latter). **Not
    implemented:** `thirteen_orphans_wait_bonus` is never read; no wait-width tracking exists.
11. Wall runs out **during** a flower-replacement cascade: already-revealed flowers stay revealed,
    and the hand ends as an exhaustive draw there — checked before *every* draw in the cascade.
    `test_wall_exhaustion_during_flower_cascade_ends_hand_as_exhaustive_draw`.

## 12. References

- [Hong Kong mahjong scoring rules — Wikipedia](https://en.wikipedia.org/wiki/Hong_Kong_mahjong_scoring_rules) — faan tables, spicy conversion, payments, penalties
- [Complete Faan Guide — TileBuddy](https://tilebuddy.app/blog/complete-faan-guide/) — Classic / New 6 / New 18 hand sets
- [HK Mahjong Scoring Chart — mahjonggame.hk](https://www.mahjonggame.hk/learn/hk-mahjong/scoring) — faan cross-reference
- [Hong Kong Mahjong Rules — Table Mahjong](https://tablemahjong.com/mahjong-rules/) — gameplay flow
