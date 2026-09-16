# 01 — Hong Kong Mahjong rules specification

All rules live behind a `RuleSet` config object; HK house rules vary widely.

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

**Representation.** `34`-length count array in the hot path (shanten, ukeire, pattern
matching). Ordered list only for UI tile ordering and animation identity.

```python
TileId = int          # 0..135, opaque per-hand identifier (see below)
TileType = int        # 0..33, suit/rank
Flower = int          # 0..7
```

**`TileId` is not a wall slot.** Assign it via a permutation independent of wall/shuffle
order (e.g. a per-hand random relabeling applied after the deal), so a `TileId` value never
reveals where in the wall a tile was drawn from. A naive implementation that numbers tiles in
shuffled-wall order leaks wall position through a field redaction tests would never flag —
don't do that.
Index layout: `0–8` = 1m–9m, `9–17` = 1p–9p, `18–26` = 1s–9s, `27–30` = E S W N,
`31–33` = 中 發 白. (Matches the layout used by most open-source shanten implementations, so
you can cross-validate against them.)

## 2. Seating and rounds

- Four seats: East 東, South 南, West 西, North 北, proceeding **counter-clockwise**
  (East → South → West → North) — opposite the visual clockwise order.
- **Seat frame (canonical, used everywhere in this spec):** seats are numbered `0..3` in
  turn order (East=0, South=1, West=2, North=3). "Next seat" always means
  `(seat + 1) % 4` — i.e. the player who plays immediately *after* you in turn order. This
  is the only axis used for chow eligibility (§5) and claim priority (§6); the terms
  "upstream"/"downstream" are not used in this spec.
- **Prevailing wind** (圈風) starts East. **Seat wind** (門風) is the player's position.
- Dealer is East. Dealer **repeats** (連莊) on a dealer win or, by config, on an exhaustive
  draw. Otherwise the deal passes counter-clockwise; after a full rotation the prevailing
  wind advances.
- Game length config: `EAST_ONLY` (一圈, default — East round only), `EAST_SOUTH` (半莊 —
  a riichi/Japanese convention, offered for players who want it, not the HK norm), `FULL`
  (四圈 — four full rounds, the traditional long-session HK length).

## 3. Deal

1. Shuffle 144 tiles with the seeded PRNG (136 if `flowers_enabled=False` — the 8
   flowers/seasons are dropped from the physical set before shuffling, and step 4 never
   triggers). Conceptually four walls of 18 stacks × 2.
2. Roll dice → break point. Cosmetic; derive the dice from the same seed.
3. Deal 13 tiles to each player, 14 to the dealer. Dealt in seat order starting from the
   dealer, three rounds of four tiles then a round of one (mirroring the physical deal),
   dealer drawing one further tile at the end. All from the front of the wall. The exact
   interleaving is cosmetic — the wall is already a uniform random permutation — but fixed
   here for reproducible replays/animation.
4. **Flower replacement**, in seat order starting from the dealer: each player reveals any
   flowers/seasons and draws replacements from the **back end** of the wall, repeating until
   they hold none. Order matters — it changes who gets which tile. Implemented as: fully
   resolve one seat's cascade (which may chain through several replacements) before moving
   to the next seat, not round-robin across seats.
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

   wall exhausted (`wall_reserve` tiles left, default 0, config) -> EXHAUSTIVE_DRAW (流局) -> next hand
```

Explicitly named phases: `AWAIT_DRAW`, `AWAIT_ACTION`, `AWAIT_CLAIMS`, `AWAIT_KONG_ROB`,
`SCORING`, `HAND_OVER`, `GAME_OVER`.

## 5. Melds

| Meld | Cantonese | From | Notes |
| --- | --- | --- | --- |
| Chow 順子 | 上 | discard only, `claimer_seat == (discarder_seat + 1) % 4` | three consecutive, same suit |
| Pung 刻子 | 碰 | discard, any player | three identical |
| Exposed kong 明槓 | 槓 | discard, any player | four identical; draw replacement from back of wall |
| Added kong 加槓 | 加槓 | own draw added to an exposed pung | **opens a robbing-the-kong window** |
| Concealed kong 暗槓 | 暗槓 | four drawn by self | laid face down; identity hidden until hand end; cannot be undone; draw replacement |

Kong replacements come from the **live wall** (§9) — HK play has no separate dead wall. Each
kong replacement shrinks the live wall by one tile, so each kong brings the exhaustive draw one
tile closer.

**Pung vs. kong, same holder.** A player holding 3 concealed matching tiles gets both a pung
and an exposed-kong option when the 4th is discarded — they may elect the smaller meld. The
kong-vs-pung tiebreak in §6 is about two *different* players each claiming the same discard
(one as pung, one as kong), not a restriction on one player's own choice.

## 6. Claim priority

**Canonical home.** This section is the single source of truth for claim priority,
including the kong-vs-pung tiebreak. Other docs (e.g.
[00-architecture.md §4](00-architecture.md)) link here rather than restating the rule —
if they conflict with this section, this section wins.

Seat frame: as defined in §2, `claimer_seat == (discarder_seat + 1) % 4` for chow eligibility.

```
Win  >  Kong / Pung  >  Chow
```

1. **Win (食糊)** beats every other claim on the same discard.
2. **Kong (槓) and Pung (碰)** beat Chow. Both require the claiming tile to complete the
   meld; either can come from any seat.
   - **Kong-vs-Pung tiebreak, same tile:** if two players could claim the same discard, one
     as a pung and one as a kong (i.e. one already holds a concealed pair and the other
     holds a concealed triple), **kong wins**. With 4 copies per tile type (§1) this specific
     case — a *different* seat holding the pair from the one holding the triple — can't
     actually arise at the table (see point 5: a kong claim already accounts for all 3
     copies left after the discard, leaving none for another seat's pair), but the resolver
     implements the ordering anyway rather than assuming that invariant.
3. **Chow (上)** is only legal for `claimer_seat == (discarder_seat + 1) % 4` — i.e. the
   next seat in turn order. No other seat may claim a chow on this discard, regardless of
   priority; a chow claim from any other seat is illegal and must be rejected.
4. **Win-vs-Win tie** (two or more players can win off the same discard): resolve by seat
   order starting from the discarder and going in turn-order — i.e. the smallest
   `(claimer_seat - discarder_seat) % 4` wins. v1 is **always single-winner** (一炮多響 /
   `multi_win` is deferred — see [99-deferred.md](99-deferred.md)).
5. **Pung/Kong-vs-Pung/Kong tie** (two players can both pung and/or kong the same discard,
   in any combination): cannot happen — with 4 copies per tile type, a discard leaves only 3
   copies of that type available as pung/kong material beyond what's already in hands, and a
   kong claim alone consumes all 3. So at most one player can hold enough for a claim at
   this tier at all, mixed pung-vs-kong (point 2) included. Not a real tiebreak case; listed
   for completeness of the resolution algorithm.

**Resolution algorithm:** collect all legal claims on a discard during the `AWAIT_CLAIMS`
window; pick the highest-priority claim type present (win > kong/pung > chow); if multiple
claims tie within that type, apply the tiebreak rule for that type above.

## 7. Faan table

Grouped into `CLASSIC`, `NEW_6`, `NEW_18` sets, each toggleable.

### Classic

| Faan | Hand | Chinese |
| --- | --- | --- |
| 1 | All Sequences | 平糊 |
| 1 | Seat Wind pung/kong | 門風 |
| 1 | Prevailing Wind pung/kong | 圈風 |
| 1 | Dragon pung/kong (each) | 箭刻 / 番牌 |
| 1 | No Flowers | 無花 |
| 1 | Self-Draw | 自摸 |
| 1 | Fully Concealed (win on discard, no open melds) | 門前清 |
| 2 | Voided Suit (exactly one of the three numbered suits absent)¹ | 缺一門 |
| 3 | All Pungs | 對對糊 |
| 3 | Half Flush (one suit + honors) | 混一色 |
| 3 | Small Three Dragons (pair of one dragon + pungs of the other two)² | 小三元 |
| 3 | All four Flowers *or* all four Seasons (as a set) | 正花 (flower set) |
| 5 | Small Four Winds (pair of one wind + pungs of the other three)² | 小四喜 |
| 6 | Full Flush (one suit, no honors) | 清一色 |
| 7 | Big Three Dragons (pungs of all three)² | 大三元 |
| 8 | Big Four Winds (pungs of all four)² | 大四喜 |
| **Limit** | Thirteen Orphans | 十三么 |
| **Limit** | All Honors | 字一色 |
| **Limit** | All Terminals | 清么九 |
| **Limit** | Nine Gates³ | 九蓮寶燈 |
| **Limit** | Heavenly Hand (dealer wins on the deal, before any discard) | 天糊 |
| **Limit** | Earthly Hand (non-dealer wins on the dealer's first discard) | 地糊 |

³ **Nine Gates' exact tile pattern**, not specified elsewhere in this doc: one suit, fully
concealed (no calls at all — self-drawn or won on discard, either is fine), 1-1-1-2-3-4-5-6-
7-8-9-9-9 plus exactly one more tile of that same suit, any rank 1-9. All nine possible
14th-tile ranks qualify (the "nine-fold wait" the name refers to), not just the one actually
drawn/claimed to complete it.

² **Small vs. Big are mutually exclusive by construction, and both stack with the base
per-pung faan.** Small needs a pair of the "leftover" dragon/wind; Big needs pungs of all of
them. A hand can never qualify for both: pungs of all three dragons (or all four winds)
already commit 3 of each type's 4 physical tiles, leaving at most 1 — never enough for the
pair Small requires. Same trick as 缺一門 vs Half/Full Flush below, no special-cased mutual
exclusion needed at scoring time. Nothing above says 箭刻 (per dragon pung) or 門風/圈風 stop
applying once Small/Big Three Dragons or Small/Big Four Winds also fire on the same pungs —
they stack, the same way Seat Wind and Prevailing Wind already stack on a dealer's own East
pung.

¹ **Exactly one, not "at most one."** A hand using tiles from only one suit (or zero, all
honors) is Half Flush/Full Flush/All Honors territory — stronger patterns that already imply
"at least one suit absent." Requiring *exactly two* of the three suits present keeps 缺一門
mutually exclusive with those by construction: a hand can never satisfy both, so there's no
separate "don't stack these" rule to enforce at scoring time.

### New 6 (新六番)

| Faan | Hand | Chinese |
| --- | --- | --- |
| 3 | Mixed Terminals (terminals + honors only, both present)² | 混么九 |
| 1 | Chicken Hand (zero other faan)¹ | 雞糊 |
| 1 | Win on last wall tile³ | 海底撈月 |
| 1 | Win on last discard | 河底撈魚 |
| 1 | Win on kong replacement³ | 槓上開花 |
| 1 | Robbing the Kong | 搶槓 |

³ **Mutually exclusive by construction.** A kong replacement can itself be the wall's last
drawable tile (each kong replacement shrinks the live wall by one, §5) — see edge case §11.6.
When it is, this is scored as 槓上開花 only, not also 海底撈月: the more specific "you won
because of the kong" pattern takes it, the same ladder convention as Small/Big Three
Dragons/Four Winds and the step-sequence patterns above.

² **Both a terminal and an honor must be present, not "at most either."** Mirrors 缺一門/半
清一色's exact-count trick: a terminals-only hand is All Terminals territory (清么九, limit)
and an honors-only hand is All Honors territory (字一色, limit) — requiring both present keeps
混么九 mutually exclusive with those by construction. Composition is pungs only (any chow
necessarily includes a non-terminal, non-honor middle tile), so 混么九 always stacks with
對對糊, and can also stack with 缺一門/混一色 when the suit-count conditions for those happen
to hold on the same hand too — nothing above forbids it.

¹ **Conditional, not dead config:** 雞糊 is only reachable when `min_faan == 0` — at
`min_faan >= 1` a zero-other-faan hand is already blocked from winning by the `min_faan`
check itself, so 雞糊 never fires and the entry is inert. This mirrors real HK play, where
雞糊 exists specifically for no-minimum tables. Servers should skip evaluating this pattern
entirely when `min_faan >= 1`. Also gated on the `NEW_6` `hand_set`, same as every other
entry in this table — disabling `NEW_6` disables 雞糊 too, even at `min_faan == 0`.

### New 18 (新十八番) — subset most commonly used

**On by default** (see `hand_sets` in §10) — Seven Pairs (七對子) is not an optional extra:
the bot's shanten parser treats it as one of three mandatory hand-shape parses (see
[04-bots.md §2, §4](04-bots.md)), so a `RuleSet` without `NEW_18` makes documented bot
behavior illegal. Unlike `NEW_18` as a whole, individual patterns in this set may still be
toggled off via `faan_overrides` (§10) if a table wants to disable a specific one.

| Faan | Hand | Chinese |
| --- | --- | --- |
| 4 | Seven Pairs (plain faan, not a limit hand) | 七對子 |
| 2 | Three or more concealed pungs/kongs⁴ | 三暗刻 |
| 2 | All Revealed (every group claimed, win claimed off a discard)⁵ | 全求人 |
| 2 | Two Dragon pungs/kongs, any pair⁶ | 雙箭 |
| 1 | Two Identical Sequences⁷ | 一般高 |
| 6 | Three or more identical sequences⁷ | 三般高 |
| 2 | Three Step Sequences⁸ | 三步高 |
| 6 | Four Step Sequences⁸ | 四步高 |

⁴ **"At least three," not "exactly."** A fourth concealed pung has no separate, higher-value
tier in this ruleset's tables (unlike Small/Big Three Dragons or Small/Big Four Winds), so a
hand with all four groups as concealed pungs folds into this one rather than scoring nothing.
A concealed kong counts as a concealed pung (self-declaring a kong doesn't break concealment);
an exposed kong or a kong added to a claimed pung never does (both are always open).

⁵ **All four groups open, and the win itself claimed off a discard, not self-drawn** — the
mirror image of 門前清 (open melds: none, win: off a discard). Requiring every group open
avoids the ambiguity 門前清's own note flags: `decompose()` never marks a group as "claimed to
complete the win" vs. "held concealed all along," so the only shape this pattern can check
unambiguously is "no group came from `decompose()` at all."

⁶ **Exactly two, independent of the pair.** Stacks with Small Three Dragons (when the pair
happens to be the third dragon) and with 箭刻's own per-dragon count, same "nothing above
forbids it" precedent as 箭刻 stacking with Small/Big Three Dragons (§7 note ²). Mutually
exclusive with Big Three Dragons by the same physical-tile-count argument as Small vs. Big
there: three dragon pungs already commit 9 of the 12 physical dragon tiles, so a hand can
never have "two dragon pungs" resolve to anything but 2 or 3, never higher.

⁷ **Ladder: "exactly two" vs. "three or more," not additive.** A run's count of identical
chows can't be both `== 2` and `>= 3` at once, so Two and Three Identical Sequences are
mutually exclusive by construction — no separate subsumption check needed, same trick as
Voided Suit vs. Half/Full Flush (§7 note ¹). "Three or more" rather than "exactly three" for
the same reason as concealed pungs above: no fourth tier exists to catch an all-four-identical
hand.

⁸ **Step is two ranks, not one or three** — three chows in one suit at ranks `r`, `r+2`,
`r+4` (e.g. 123-345-567), not consecutive ranks. Four Step Sequences is the single shape this
allows within one suit's nine ranks: 123-345-567-789 (starts 0, 2, 4, 6), using all four of
the hand's groups. Because that shape's ranks also contain 三步高's own 3-run pattern twice
over ({0,2,4} and {2,4,6}), 三步高 explicitly excludes any suit that also satisfies 四步高 —
ladder rule, take the higher tier, same convention as note ⁷ above and Small/Big Three
Dragons/Four Winds (§7 note ²).

### Flower faan

`1` per flower matching the player's seat — 座位花 ("seat flower," a single matching tile,
not to be confused with 正花 in the Classic table above, which is a complete set of all four
flowers *or* all four seasons) — plus the `無花` entry above.
Config: `flowers_score`, `seven_flowers_instant_win` (3 faan), `eight_flowers_instant_win`
(limit).

**Implementation note (§7 has no `hand_sets` group for this subsection).** 座位花 and 正花
are both registered under `HandSet.CLASSIC` (same group as `無花`) since neither is listed
under `NEW_6`/`NEW_18` and CLASSIC is the always-present baseline group; 座位花 is additionally
gated by the `flowers_score` config flag specifically (independent of the `CLASSIC` toggle).
`seven_flowers_instant_win`/`eight_flowers_instant_win` are not faan patterns at all — an
instant win ends the hand on flower count alone, with no meld decomposition to score — so they
aren't in `patterns.py`'s registry; see that module's docstring for where they're expected to
land (engine.py's win-condition check, sub-task 8).

### Stacking and caps

- Faan **stack**: Full Flush (6) + All Pungs (3) = 9.
- **Seat Wind and Prevailing Wind stack on the same pung.** A dealer's seat wind is always East
  (§2); in the East round the prevailing wind is East too, so the dealer's own East pung earns
  both 門風 and 圈風 — 2 faan, not 1. Nothing above says these can't combine, and real HK
  scoring awards both.
- **Limit hands do not stack with anything** — not wind/dragon/flower faan, and not each
  other. A qualifying hand scores at the table's `faan_cap`, full stop; every other pattern
  that also matches (自摸, 門前清, 無花, ...) is ignored, not added on top. If a hand qualifies
  for more than one limit hand, take the highest, not the sum.
- `faan_cap` config: `10` (HK Mahjong Association) or `13` (common casual). Total is clamped.
- `min_faan` config: `0 | 1 | 3 | 5`, default **3**. **A hand below the minimum cannot be
  declared a win.** Changes bot strategy fundamentally — see [04-bots.md §4](04-bots.md).

## 8. Faan → points → payment

Two conversion tables, config-selectable.

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

**Rounding when `P` doesn't divide evenly.** Reachable at `faan = 0` (`P = 1`, legal only at
`min_faan = 0`) — none of the doc's worked examples hit this since every faan ≥ 1 value in
both tables is even. Round each share to the nearest whole point, ties up; balance by fixing
the winner's total (`P` for a discard win, `3 ×` the rounded loser share for self-draw) and
deriving the rest from it rather than rounding every seat independently, so payments always
sum to zero. Under `discard_payment = HALF`, round the discarder's own half first and let any
leftover from splitting the remaining half between the two bystanders fall back onto the
discarder — same party the 包 rules below already single out as the more responsible payer,
rather than a bystander.

**Robbing the kong (搶槓) payment shape.** Not specified separately above or in §7: it pays
exactly like a win on discard, with the seat whose kong was robbed standing in for the
discarder — one seat is responsible for the winning tile reaching the winner either way.

### Penalty / responsibility rules (包) — defer to v2

Applicable under `discarder_pays_half`.

| Rule | Chinese | Trigger |
| --- | --- | --- |
| 9-Piece Penalty | 九張包 | Discarder feeds a full-flush hand that already has 3 melds in one suit |
| 12-Piece Penalty | 十二張包自摸 | Same, allowing a 4th meld, winner then self-draws |
| Fifth-Tile Penalty | 五子包生 | Discarding a fresh tile with ≤5 wall tiles left, feeding the win |
| Great Dragons/Winds feeder | 大三元/大四喜包 | Discarder completes the third dragon or fourth wind pung |

## 9. Exhaustive draw (流局)

HK play has no dead wall: the wall is drawn down to nothing, kong replacements come off the
same live wall (§5), and the literal last drawable tile is 海底 (see §7 New 6, 海底撈月).
`wall_reserve` is configurable for tables that want to hold some tiles back (e.g. importing a
riichi-style dead wall), but **defaults to `0`** — the HK norm. Wall exhausted with
`wall_reserve` tiles remaining → no winner, no payment (config: `tenpai_payments`, off by
default). Dealer repeats or passes per `dealer_repeat_on_draw`.

Also config: `four_kong_abort`, `nine_terminals_abort` (九種九牌) — both off by default.

## 10. `RuleSet`

```python
@dataclass(frozen=True)
class RuleSet:
    # scoring
    min_faan: int = 3
    faan_cap: int = 10
    score_table: Literal["full_spicy", "half_spicy"] = "half_spicy"
    hand_sets: frozenset[str] = frozenset({"CLASSIC", "NEW_6", "NEW_18"})
    faan_overrides: dict[str, int] = field(default_factory=dict)
        # per-pattern faan overrides, keyed by the Chinese name in §7 (e.g. {"雞糊": 0} to
        # disable, {"清一色": 7}) — applied after hand_sets selection, before stacking/caps.
        # This is the knob for "same pattern, different table value" without toggling a
        # whole set; hand_sets stays the coarse on/off switch per §7 group.
    discard_payment: Literal["all", "half"] = "all"
    self_draw_multiplier: float = 1.5
    flowers_score: bool = True              # 座位花: +1 faan per flower matching seat, see §7
    seven_flowers_instant_win: bool = False # 3 faan, variant, see §7
    eight_flowers_instant_win: bool = False # limit hand, variant, see §7
    thirteen_orphans_wait_bonus: bool = False  # some tables double a single-tile wait, §11.10

    # flow
    game_length: Literal["EAST_ONLY", "EAST_SOUTH", "FULL"] = "EAST_ONLY"  # 一圈; see §2
    dealer_repeat_on_win: bool = True
    dealer_repeat_on_draw: bool = True
    wall_reserve: int = 0                   # HK default: no dead wall, see §9
    four_kong_abort: bool = False           # see §9
    nine_terminals_abort: bool = False      # 九種九牌, see §9
    tenpai_payments: bool = False           # pay tenpai players on exhaustive draw, see §9

    # variants
    flowers_enabled: bool = True
    multi_win: bool = False                 # 一炮多響 — deferred (see 99-deferred.md);
                                             # field reserved, always False in v1
    kong_rob_enabled: bool = True
    concealed_kong_robbable: bool = False   # only for 十三么, some tables
    pao_rules: bool = False                 # 包 responsibility, v2

    # fairness (see 02-protocol.md "Fairness")
    provable_fairness: bool = False         # gates hand_start.seed_commit / hand_end.fairness

    # timing (server-enforced)
    turn_seconds: int = 15                  # AWAIT_ACTION timeout
    claim_seconds: int = 5                  # AWAIT_CLAIMS window
    turn_timeout_strikes: int = 3           # timeouts before seat flips to AUTOPLAY,
                                             # see 00-architecture.md §8
```

`flowers_score`, `seven_flowers_instant_win`, `eight_flowers_instant_win` (§7),
`four_kong_abort`, `nine_terminals_abort`, `tenpai_payments` (§9), and
`thirteen_orphans_wait_bonus` (§11.10) were named in prose elsewhere in this doc but missing
from this dataclass; added here for consistency. `provable_fairness` is specified only in
[02-protocol.md](02-protocol.md) (gates `hand_start.seed_commit`/`hand_end.fairness`) but
lives on `RuleSet`, so it's listed here too. None of these have a documented default beyond
what's shown above; the implementation defaults them to the conservative/off position.

## 11. Edge cases

Write a named test for every one.

1. Flower drawn as a kong replacement → another replacement; can chain.
2. Winning on a flower replacement = 槓上開花.
3. Robbing an **added** kong (加槓); robbing a **concealed** kong only for 十三么 and only if `concealed_kong_robbable`.
4. Concealed kong that changes an already-tenpai hand's wait — legal in HK.
5. Four kongs on the table across different players → `four_kong_abort` if enabled.
6. Last-tile draw and last-discard win scoring, and their interaction with the wall reserve count after kongs shorten the wall.
7. Multi-win on one discard — deferred with `multi_win`, see
   [99-deferred.md](99-deferred.md); not required for v1 launch.
8. Mechanically complete hand below `min_faan` — win must be **disabled server-side**, not just hidden client-side. **M1/M2 boundary:** `mahjong_core/actions.py`'s `legal_actions` (M1) offers `DeclareWin`/`ClaimWin` on win *shape* alone (standard melds+pair, Seven Pairs, Thirteen Orphans) — the `min_faan` gate itself is M2 scope (05-roadmap.md §2, alongside the faan patterns it depends on), so this edge case isn't fully closed until engine.py wires a real faan check in front of these actions once `scoring/` exists. Tracked, not silently assumed away.
9. Seven Pairs vs. standard parse of the same 14 tiles → since `NEW_18` (and therefore Seven
   Pairs) is on by default (§7, §10), this collision is a default-path case, not an opt-in
   one — scoring must maximize over *all* valid decompositions, not the first found.
10. Thirteen Orphans 13-way wait vs. single wait (config: some tables double the latter).
11. Wall runs out **during** a flower-replacement cascade (edge case 1), not just before a
    normal draw: the seat's already-revealed flowers this cascade stay revealed, but the hand
    ends as an exhaustive draw right there instead of raising — checked before *every* draw in
    the cascade, not just the first.
