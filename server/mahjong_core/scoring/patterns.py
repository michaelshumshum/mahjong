"""Faan pattern detectors (docs/01-rules-spec.md §7; docs/05-roadmap.md §1, §2).

Scope (first sub-task, first slice of M2): the detector framework -- `ScoringContext`, the
`Pattern` registration shape, and `score_hand`, the per-decomposition scorer -- plus the first
batch of patterns: the structural/suit-shape Classic patterns (All Sequences, All Pungs,
Voided Suit, Half Flush, Full Flush) and the single-flag situational Classic patterns (No
Flowers, Self-Draw, Fully Concealed, Seat Wind, Prevailing Wind, Dragon pung). These were
picked as the starting batch because together they exercise every field `ScoringContext` needs
(seat wind, prevailing wind, self-draw, flowers, concealed-vs-open) without requiring
decomposition-maximisation (faan.py, later) or wall-timing context (New Six's 海底/槓上開花/
搶槓, a later sub-task).

Scope (second sub-task): the "count across the whole hand" aggregate Classic/New-6 patterns --
Small/Big Three Dragons, Small/Big Four Winds, Mixed Terminals. No `DetectorFn`/`Pattern`
shape change was needed for these: a detector already receives the *entire* candidate `hand`
(every group plus the pair, see `_groups_and_pair`), not one meld at a time -- sub-task 1's own
箭刻 detector already sums dragon pungs across the whole hand this same way. "Small vs Big"
and stacking-with-sub-task-1-patterns judgment calls are recorded in 01-rules-spec.md §7's
footnotes next to the patterns they affect, not here.

Seven Pairs and New 18's stacking patterns are later batches -- see the sub-task breakdown in
the M2 planning report this change shipped with.

Scope (third sub-task): the limit hands (§7's "Limit" rows) -- Thirteen Orphans, All Honors,
All Terminals, Nine Gates, Heavenly Hand, and Earthly Hand. All six sit in the *Classic* §7
table (there's no separate "Limit" `hand_set`), so `HandSet.CLASSIC` gates every one of them,
same as sub-task 1/2's patterns.

Scope (fourth sub-task): all eight `HandSet.NEW_18` patterns -- Seven Pairs, Three Concealed
Pungs, All Revealed, Two Dragon Pungs, Two/Three Identical Sequences, Three/Four Step
Sequences. Seven Pairs is a raw-hand shape check like Thirteen Orphans (see "Raw-hand access"
above) and is *not* a limit hand here -- §7 gives it a plain 4 faan, unlike Thirteen Orphans in
the same shape family. The other seven operate on `hand` like sub-task 2/3's aggregate
checks, but Two/Three Identical Sequences and Three/Four Step Sequences need something new:
comparing groups *against each other* (same run twice, or three/four runs evenly spaced),
not just counting how many groups match one fixed category (a tile type, concealed-ness).
Two small helpers, `_chow_run_counts` and `_chow_start_ranks_by_suit`, carry that comparison;
see their docstrings and the "step" footnote added to 01-rules-spec.md §7 for the shape they
each resolve.

**What a detector operates on.** `hand` is one candidate full decomposition of the winning
14 tiles: the seat's already-formed melds (`SeatState.melds` -- claimed chows/pungs/kongs, or
a self-declared concealed/added kong) plus one candidate parse of the remaining concealed
tiles from `melds.decompose` (always exactly one `PAIR` plus four 3-or-4-tile groups for the
patterns in this batch; Seven Pairs/Thirteen Orphans hands don't decompose this way at all).
Maximising faan across every such candidate (when `decompose` returns more than one split) is
faan.py's job, not this module's -- `score_hand` here just scores the one candidate it's given.

**Raw-hand access, for shapes `decompose()` never produces.** Thirteen Orphans (and Nine
Gates, which needs an exact tile-count check rather than a meld shape) don't operate on
`hand` at all -- `decompose()` returns `()` for a Thirteen Orphans hand, so a detector gated on
`_groups_and_pair` would never see it. Rather than changing every detector's signature,
`ScoringContext` grows one more field, `concealed_tiles`: the winning seat's concealed tile
ids at the moment of the win (mirrors `SeatState.concealed`; all 14 for a fully concealed
hand, fewer once melds are claimed). This fits the same "everything beyond the melds
themselves, built once per win, reused across every decomposition candidate" contract the
rest of `ScoringContext` already documents -- unlike `hand`, the raw tile identities don't
change across candidates, so it belongs on the context, not as a new `score_hand`/`DetectorFn`
parameter. All Honors and All Terminals don't need this: every group and the pair still comes
through `hand` under a normal decomposition (no chows possible with only honors/terminals
involved), so they're whole-hand-over-a-decomposition checks like sub-task 2's patterns.

**Limit hands don't stack (§7 "Stacking and caps").** A qualifying hand takes the single
highest-faan limit pattern instead of also adding wind/dragon/flower faan on top; if more than
one limit pattern applies, take the highest of those. `score_hand` doesn't implement that
rule -- same divide as every other cap/stacking rule, `faan.py`'s job -- it just needs the
patterns tagged so `faan.py` can find them: every limit pattern below sets `is_limit=True`
(the field sub-task 1 added to `Pattern` but nothing used yet) and `faan=LIMIT_FAAN`, a
placeholder since `Pattern.faan` is typed `int` but a limit hand's real value is "the table's
`faan_cap`," not a fixed number `patterns.py` knows.

**Heavenly/Earthly Hand timing is a stub.** Both need "is this the very first decision point
of the hand" context that doesn't exist yet -- real turn/discard-count tracking is
engine-integration (sub-task 8). `ScoringContext` grows two booleans, `won_before_any_discard`
and `won_on_dealer_first_discard`, default `False`, for engine.py to set once that wiring
exists; the detectors themselves are correct today; only the field's producer is a stub.

**Concealed vs. open, without a redundant context field.** A meld is "open" (exposed via a
claim) iff `meld.from_seat is not None` -- `melds.py`'s `Meld.__post_init__` already forbids
`from_seat` on `PAIR`/`CONCEALED_KONG`, and `decompose()` never sets it, so this single check
correctly covers every meld kind without `ScoringContext` needing its own concealed/open flag
that could drift out of sync with the melds it describes.

Scope (fifth sub-task): the four remaining New Six win-timing patterns -- Win on Last Wall
Tile (海底撈月), Win on Last Discard (河底撈魚), Win on Kong Replacement (槓上開花), Robbing the
Kong (搶槓) -- plus flower faan (座位花, and 正花, a Classic-table pattern missed in sub-task 1's
"situational" batch, folded in here since it's flower-shaped and this batch is already
re-reading §7's flower material end to end).

**Win-timing context is a stub, same as Heavenly/Earthly Hand's (third sub-task).**
`ScoringContext` grows three more booleans, all defaulting `False`: `is_last_tile` (the wall
was exhausted on the draw or discard that produced this win -- covers both 海底 self-draws and
河底 claimed discards, distinguished the same way 自摸/門前清 already are, by `ctx.self_drawn`),
`is_kong_replacement` (this win's tile came from a kong replacement draw, 槓上開花), and
`is_robbing_kong` (this win claimed a tile another seat just added to an exposed kong -- or,
per §11.3, a concealed kong under `concealed_kong_robbable` -- 搶槓). Real wall-remaining-count
and kong-replacement tracking is engine-integration (sub-task 8, same as `won_before_any_discard`/
`won_on_dealer_first_discard`) -- nothing in `wall.py`/`state.py` yet exposes "tiles left" or
"this draw was a replacement" to the scoring layer. The detectors below are correct against
these flags today; only their producer is a stub.

**海底撈月 and 槓上開花 are mutually exclusive by construction.** A kong replacement can
physically be the wall's last drawable tile (each kong replacement shrinks the live wall by
one, `wall.py`); §11 edge case 6 flags this exact interaction as needing a resolved rule.
`_detect_win_on_last_wall_tile` excludes `ctx.is_kong_replacement` so the more specific pattern
(you won *because* of the kong) takes it instead of also double-counting the generic
last-tile pattern -- same ladder convention as Small/Big Three Dragons and the step-sequence
patterns. See the footnote added to 01-rules-spec.md §7.

**Flower faan.** 座位花 ("each," like 箭刻/一般高: up to 2 per seat, the numbered flower and
the numbered season matching `ctx.seat_wind`) is gated by a new `ScoringContext.flowers_score`
field mirroring `RuleSet.flowers_score` (config.py) -- a policy toggle, not a per-win fact, but
`ScoringContext` has no other way to reach `RuleSet` and every other field on this dataclass is
already "whatever this batch's detectors need," so it fits the same contract rather than
threading a whole `RuleSet` through for one bool. Defaults `True`, matching `RuleSet`'s own
default, so a caller that doesn't set it keeps today's behavior. 正花 (all four flowers *or*
all four seasons held at once) needs no new context field -- it only reads `ctx.flowers`, same
as `_detect_no_flowers` already does.

**What doesn't fit here.** Two §7 New-6/flower entries are deliberately *not* registered as
`Pattern`s:

- **Chicken Hand (雞糊)**, "zero other faan" (§7 note ¹): this can't be a `DetectorFn` at all
  under the current contract -- a detector only ever sees one `hand`/`ctx` pair and reports
  whether *its own* pattern applies, but Chicken Hand's condition is "every other registered
  pattern reported zero," which requires already knowing the outcome of the very
  `score_hand` loop it would need to run inside of. That's `faan.py`'s job (a later sub-task):
  run `score_hand`, and if the result is empty (and `min_faan == 0`, per the note), award
  Chicken Hand's floor faan.
- **Flower instant-win** (`seven_flowers_instant_win`/`eight_flowers_instant_win`,
  config.py, unconsumed since it was added): not a hand-shape pattern at all -- it wins the
  hand immediately on flower count alone, with no meld decomposition, cutting the hand short
  before a normal win would even be checked. `score_hand`/`Pattern` here only ever score an
  already-complete, already-decomposed winning hand; there's nothing for a detector to
  decompose for an instant win, and "cut the hand short" is turn-state-machine control flow
  (engine.py), not a faan value to add to a `dict[str, int]`. Flagged for sub-task 8
  (engine integration) to implement as its own win-condition check, alongside whatever
  `faan.py` (sub-task 6) needs to award its fixed faan value.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

from mahjong_core.config import HandSet
from mahjong_core.melds import KONG_KINDS, Meld, MeldKind
from mahjong_core.state import Wind
from mahjong_core.tiles import Flower, TileId, TileType, tile_id_type

_DRAGON_TYPES = frozenset({TileType.DRAGON_RED, TileType.DRAGON_GREEN, TileType.DRAGON_WHITE})
_WIND_TYPES = frozenset(
    {TileType.WIND_EAST, TileType.WIND_SOUTH, TileType.WIND_WEST, TileType.WIND_NORTH}
)
_PUNG_OR_KONG = frozenset({MeldKind.PUNG, *KONG_KINDS})

_ORPHAN_TYPES = frozenset(
    {
        TileType.MAN_1,
        TileType.MAN_9,
        TileType.PIN_1,
        TileType.PIN_9,
        TileType.SOU_1,
        TileType.SOU_9,
        TileType.WIND_EAST,
        TileType.WIND_SOUTH,
        TileType.WIND_WEST,
        TileType.WIND_NORTH,
        TileType.DRAGON_RED,
        TileType.DRAGON_GREEN,
        TileType.DRAGON_WHITE,
    }
)
"""Mirrors `actions.py`'s `_ORPHAN_TYPES`/`_is_thirteen_orphans` (win-legality's shape check)
-- kept as a separate copy rather than an import so this module doesn't take a dependency on
the state-machine layer (`actions.py` pulls in `state.GameState`) for one frozenset. Any
change to what counts as an orphan type must be made in both places; `test_scoring.py` cross-
checks the two against each other so they can't silently drift.
"""

_NINE_GATES_BASE_COUNTS = (3, 1, 1, 1, 1, 1, 1, 1, 3)
"""九蓮寶燈's fixed 13-tile skeleton within one suit, ranks 1..9: three of the 1, one each of
2-8, three of the 9. The winning hand is this plus exactly one more tile of the same suit
(any rank 1-9) -- 14 tiles total, still one suit, no honors."""


def seat_wind_for(seat: int, dealer: int) -> Wind:
    """A seat's wind for the hand currently being dealt by `dealer` (01-rules-spec.md §2: the
    dealer is always East for their own deal, and seat wind rotates with the deal, not with
    fixed table position). `(seat - dealer) % 4` lands on the same East/South/West/North
    numbering `Wind`/the seat frame already use everywhere else in this codebase.
    """
    if not 0 <= seat < 4 or not 0 <= dealer < 4:
        raise ValueError(f"seat and dealer must be 0..3, got seat={seat} dealer={dealer}")
    return Wind((seat - dealer) % 4)


@dataclass(frozen=True)
class ScoringContext:
    """Everything a pattern detector needs beyond the winning hand's melds themselves
    (docs/01-rules-spec.md §7). One instance per win; faan.py (later) builds it once and
    reuses it across every decomposition candidate for that win.

    Deliberately minimal for this batch -- only the fields this batch's detectors actually
    read. Later batches (New Six's win-timing patterns, thirteen orphans' wait bonus, ...)
    extend this as they need to; adding unread fields now would be dead code with no test
    behind it.

    Third sub-task adds three fields (see the module docstring's "Raw-hand access" and
    "Heavenly/Earthly Hand timing" notes): `concealed_tiles` for shapes `decompose()` can't
    produce, and two win-timing stubs, both permanently `False` until engine-integration
    (sub-task 8) wires real discard-count tracking through:

    - `won_before_any_discard` (天糊, Heavenly Hand): the winning hand was already complete on
      the initial deal, before any seat has discarded. Only the dealer can ever have this be
      true -- no one else holds a complete hand before the first discard.
    - `won_on_dealer_first_discard` (地糊, Earthly Hand): the winning seat claimed win off the
      dealer's first discard of the hand.

    Fifth sub-task adds four more fields (see the module docstring's "Win-timing context is a
    stub" and "Flower faan" notes): three more win-timing stubs, permanently `False` until
    engine-integration (sub-task 8) wires real wall/kong tracking through --

    - `is_last_tile` (海底撈月/河底撈魚): the wall was exhausted on the draw or discard that
      produced this win. Covers both the self-draw and claimed-discard cases; `self_drawn`
      tells the detectors which one they're looking at, the same way it already disambiguates
      自摸 from 門前清.
    - `is_kong_replacement` (槓上開花): this win's tile came from a kong-replacement draw.
    - `is_robbing_kong` (搶槓): this win claimed a tile another seat just added to an exposed
      kong (or, per 01-rules-spec.md §11.3, a concealed kong under `concealed_kong_robbable`).

    -- and one policy passthrough, not a per-win stub:

    - `flowers_score` (座位花): mirrors `RuleSet.flowers_score` (config.py). Defaults `True`
      like the `RuleSet` field it mirrors, so an existing caller that never sets it keeps
      getting 座位花 scored, same as before this field existed.

    All default so every earlier caller/test keeps working unchanged.
    """

    seat_wind: Wind
    prevailing_wind: Wind
    self_drawn: bool
    flowers: tuple[Flower, ...]
    concealed_tiles: tuple[TileId, ...] = ()
    won_before_any_discard: bool = False
    won_on_dealer_first_discard: bool = False
    is_last_tile: bool = False
    is_kong_replacement: bool = False
    is_robbing_kong: bool = False
    flowers_score: bool = True


DetectorFn = Callable[[tuple[Meld, ...], ScoringContext], int]
"""A detector returns how many times its pattern applies to `hand` (0 if it doesn't apply at
all) -- almost always 0 or 1, but "each"-style patterns like dragon pung can return up to 3.
`Pattern.faan` is the *per-occurrence* value, so `faan.py` (later) computes a pattern's
contribution as `occurrences * (faan_overrides.get(name) or faan)`, matching how
`RuleSet.faan_overrides` (config.py) is documented to apply: a per-pattern value swap, not a
per-occurrence one.
"""


@dataclass(frozen=True)
class Pattern:
    """One faan pattern's registration: identity, which `hand_sets` group gates it (§7), its
    base per-occurrence faan value, and its detector. `name` is the Chinese name from §7's
    tables -- the same key `RuleSet.faan_overrides` (config.py) is documented to use.
    """

    name: str
    hand_set: HandSet
    faan: int
    detect: DetectorFn
    is_limit: bool = False


def _groups_and_pair(hand: tuple[Meld, ...]) -> tuple[tuple[Meld, ...], Meld] | None:
    """Split `hand` into its four non-pair groups and its pair. `None` if `hand` isn't shaped
    that way (exactly one `PAIR` meld) -- the shape every detector in this batch requires;
    returning `None` rather than raising lets a detector just treat it as "pattern doesn't
    apply" for hand shapes it doesn't understand (Seven Pairs, Thirteen Orphans), rather than
    every detector needing its own guard.
    """
    pairs = [m for m in hand if m.kind == MeldKind.PAIR]
    if len(pairs) != 1:
        return None
    groups = tuple(m for m in hand if m.kind != MeldKind.PAIR)
    return groups, pairs[0]


def _is_open(meld: Meld) -> bool:
    return meld.from_seat is not None


def _suits_used(groups: tuple[Meld, ...], pair: Meld) -> tuple[set[int], bool]:
    """`(suits, honors_present)` -- `suits` holds which of m=0/p=1/s=2 appear anywhere in the
    hand; `honors_present` whether any wind/dragon tile does."""
    suits: set[int] = set()
    honors = False
    for meld in (*groups, pair):
        v = int(meld.tile_type)
        if v < 27:
            suits.add(v // 9)
        else:
            honors = True
    return suits, honors


def _detect_all_sequences(hand: tuple[Meld, ...], _ctx: ScoringContext) -> int:
    split = _groups_and_pair(hand)
    if split is None:
        return 0
    groups, _pair = split
    return 1 if all(m.kind == MeldKind.CHOW for m in groups) else 0


def _detect_all_pungs(hand: tuple[Meld, ...], _ctx: ScoringContext) -> int:
    split = _groups_and_pair(hand)
    if split is None:
        return 0
    groups, _pair = split
    return 1 if all(m.kind in _PUNG_OR_KONG for m in groups) else 0


def _detect_voided_suit(hand: tuple[Meld, ...], _ctx: ScoringContext) -> int:
    """缺一門: tiles from exactly two of the three numbered suits, the third completely
    absent. Deliberately *not* "at most two suits" -- a hand using only one suit (or zero,
    all-honor) is Half/Full Flush/All Honors territory, stronger patterns that would otherwise
    silently double up with this one every time they fire. Requiring exactly two suits present
    is what keeps this pattern and Full/Half Flush mutually exclusive by construction, with no
    special-cased subsumption check needed -- see the same note added to
    01-rules-spec.md §7.
    """
    split = _groups_and_pair(hand)
    if split is None:
        return 0
    groups, pair = split
    suits, _honors = _suits_used(groups, pair)
    return 1 if len(suits) == 2 else 0


def _detect_half_flush(hand: tuple[Meld, ...], _ctx: ScoringContext) -> int:
    split = _groups_and_pair(hand)
    if split is None:
        return 0
    groups, pair = split
    suits, honors = _suits_used(groups, pair)
    return 1 if len(suits) == 1 and honors else 0


def _detect_full_flush(hand: tuple[Meld, ...], _ctx: ScoringContext) -> int:
    split = _groups_and_pair(hand)
    if split is None:
        return 0
    groups, pair = split
    suits, honors = _suits_used(groups, pair)
    return 1 if len(suits) == 1 and not honors else 0


def _detect_no_flowers(_hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    return 1 if not ctx.flowers else 0


def _detect_self_draw(_hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    return 1 if ctx.self_drawn else 0


def _detect_fully_concealed(hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    """門前清: win *on a discard* (not self-draw -- that's the separate 自摸 pattern, and
    this ruleset's §7 entry defines the two as not stacking) with no open melds. The winning
    tile itself never counts as "open" here: whether claimed off a discard or drawn, it's part
    of the concealed-tiles decomposition (`decompose()` never sets `from_seat`), matching real
    HK play where winning off a discard doesn't itself break concealment.
    """
    if ctx.self_drawn:
        return 0
    return 1 if not any(_is_open(m) for m in hand) else 0


def _detect_seat_wind(hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    split = _groups_and_pair(hand)
    if split is None:
        return 0
    groups, _pair = split
    want = TileType(27 + int(ctx.seat_wind))
    return 1 if any(m.kind in _PUNG_OR_KONG and m.tile_type == want for m in groups) else 0


def _detect_prevailing_wind(hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    """圈風. Deliberately independent of `_detect_seat_wind`: when a dealer's seat wind equals
    the prevailing wind (round East, dealer's own hand), both patterns fire on the same pung
    and stack -- 2 faan, not 1. Nothing in §7 says these can't combine, and real HK scoring
    awards both; see the note added to 01-rules-spec.md §7.
    """
    split = _groups_and_pair(hand)
    if split is None:
        return 0
    groups, _pair = split
    want = TileType(27 + int(ctx.prevailing_wind))
    return 1 if any(m.kind in _PUNG_OR_KONG and m.tile_type == want for m in groups) else 0


def _detect_dragon_pung(hand: tuple[Meld, ...], _ctx: ScoringContext) -> int:
    """箭刻 / 番牌, "each" -- returns how many of the (up to three) dragon pungs/kongs are
    present, so the caller's `occurrences * faan` naturally gives 1 faan per dragon. Whether
    two or three of these should instead resolve to Small/Big Three Dragons is faan.py's
    concern (those are separate, higher-value patterns registered in a later sub-task) -- this
    detector only ever reports the base per-dragon count.
    """
    split = _groups_and_pair(hand)
    if split is None:
        return 0
    groups, _pair = split
    return sum(1 for m in groups if m.kind in _PUNG_OR_KONG and m.tile_type in _DRAGON_TYPES)


def _detect_small_three_dragons(hand: tuple[Meld, ...], _ctx: ScoringContext) -> int:
    """小三元: a dragon pair plus pungs/kongs of the other two dragons. Mutually exclusive
    with Big Three Dragons by construction (01-rules-spec.md §7 note ²) -- no need to check
    the pair's dragon differs from the two pungs' dragons, physical tile counts (max 4 per
    type) already rule out an overlap."""
    split = _groups_and_pair(hand)
    if split is None:
        return 0
    groups, pair = split
    dragon_pungs = sum(
        1 for m in groups if m.kind in _PUNG_OR_KONG and m.tile_type in _DRAGON_TYPES
    )
    return 1 if dragon_pungs == 2 and pair.tile_type in _DRAGON_TYPES else 0


def _detect_big_three_dragons(hand: tuple[Meld, ...], _ctx: ScoringContext) -> int:
    """大三元: pungs/kongs of all three dragons."""
    split = _groups_and_pair(hand)
    if split is None:
        return 0
    groups, _pair = split
    dragon_pungs = sum(
        1 for m in groups if m.kind in _PUNG_OR_KONG and m.tile_type in _DRAGON_TYPES
    )
    return 1 if dragon_pungs == 3 else 0


def _detect_small_four_winds(hand: tuple[Meld, ...], _ctx: ScoringContext) -> int:
    """小四喜: a wind pair plus pungs/kongs of the other three winds."""
    split = _groups_and_pair(hand)
    if split is None:
        return 0
    groups, pair = split
    wind_pungs = sum(1 for m in groups if m.kind in _PUNG_OR_KONG and m.tile_type in _WIND_TYPES)
    return 1 if wind_pungs == 3 and pair.tile_type in _WIND_TYPES else 0


def _detect_big_four_winds(hand: tuple[Meld, ...], _ctx: ScoringContext) -> int:
    """大四喜: pungs/kongs of all four winds."""
    split = _groups_and_pair(hand)
    if split is None:
        return 0
    groups, _pair = split
    wind_pungs = sum(1 for m in groups if m.kind in _PUNG_OR_KONG and m.tile_type in _WIND_TYPES)
    return 1 if wind_pungs == 4 else 0


def _is_terminal(tile_type: TileType) -> bool:
    v = int(tile_type)
    return v < 27 and v % 9 in (0, 8)


def _is_honor(tile_type: TileType) -> bool:
    return int(tile_type) >= 27


def _detect_mixed_terminals(hand: tuple[Meld, ...], _ctx: ScoringContext) -> int:
    """混么九: every group and the pair is a terminal or an honor, with at least one of each
    present (01-rules-spec.md §7 note ²). Excluding chows outright (rather than relying on
    `Meld.tile_type`, which is a chow's *lowest* tile and would wrongly call 1-2-3 "terminal")
    is required here -- a chow's other tiles are never terminal or honor regardless of its
    lowest one."""
    split = _groups_and_pair(hand)
    if split is None:
        return 0
    groups, pair = split
    if any(m.kind == MeldKind.CHOW for m in groups):
        return 0
    all_melds = (*groups, pair)
    if not all(_is_terminal(m.tile_type) or _is_honor(m.tile_type) for m in all_melds):
        return 0
    has_terminal = any(_is_terminal(m.tile_type) for m in all_melds)
    has_honor = any(_is_honor(m.tile_type) for m in all_melds)
    return 1 if has_terminal and has_honor else 0


def _detect_all_honors(hand: tuple[Meld, ...], _ctx: ScoringContext) -> int:
    """字一色: every group and the pair is an honor tile. No chow-exclusion needed (contrast
    `_detect_mixed_terminals`/`_detect_all_terminals`): honors never form chows, so any chow
    present already fails `_is_honor` on its (necessarily suited) `tile_type`."""
    split = _groups_and_pair(hand)
    if split is None:
        return 0
    groups, pair = split
    return 1 if all(_is_honor(m.tile_type) for m in (*groups, pair)) else 0


def _detect_all_terminals(hand: tuple[Meld, ...], _ctx: ScoringContext) -> int:
    """清么九: every group and the pair is a terminal (1 or 9), no honors. Chows must be
    excluded explicitly, same reason as `_detect_mixed_terminals` -- a 1-2-3 chow's
    `tile_type` (its lowest tile) reads as terminal even though 2 and 3 aren't."""
    split = _groups_and_pair(hand)
    if split is None:
        return 0
    groups, pair = split
    if any(m.kind == MeldKind.CHOW for m in groups):
        return 0
    return 1 if all(_is_terminal(m.tile_type) for m in (*groups, pair)) else 0


def _detect_nine_gates(hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    """九蓮寶燈: one suit, fully concealed, 1112345678999 plus one more tile of that suit
    (any rank 1-9) -- see `_NINE_GATES_BASE_COUNTS`. Reads `ctx.concealed_tiles` directly
    (see the module docstring's "Raw-hand access" note) rather than `hand`: this is an exact
    tile-count check, not a meld-shape one, and requiring `len(...) == 14` is what excludes an
    open hand (Nine Gates has no claimed-meld variant) without a separate open-meld check.

    **Must still reject a non-empty `hand`.** `ctx.concealed_tiles` is fixed for the whole win
    (`score_winning_hand` sets it once, the same on every candidate it scores -- see that
    function's docstring), so without this guard the pattern would fire on *every* candidate
    scored during decomposition maximisation whenever the raw 14 tiles happen to satisfy this
    shape, not just the one raw candidate (`melds` alone, no `decompose()` split attached) it's
    meant for -- stacking onto an unrelated standard decomposition's own patterns. `hand` is
    non-empty for any candidate with a real meld/decompose split attached; the correct raw
    candidate is always `()` here since this shape requires a fully concealed hand (no exposed
    melds possible), so `if hand: return 0` isolates the check to exactly that one candidate.
    """
    if hand:
        return 0
    tiles = ctx.concealed_tiles
    if len(tiles) != 14:
        return 0
    types = [tile_id_type(t) for t in tiles]
    if any(_is_honor(t) for t in types):
        return 0
    suits = {int(t) // 9 for t in types}
    if len(suits) != 1:
        return 0
    base = suits.pop() * 9
    counts = [0] * 9
    for t in types:
        counts[int(t) - base] += 1
    return 1 if all(c >= b for c, b in zip(counts, _NINE_GATES_BASE_COUNTS, strict=True)) else 0


def _detect_thirteen_orphans(hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    """十三么: all 13 terminal/honor types present at least once among 14 concealed tiles
    (the 14th is necessarily a duplicate of one of them). Mirrors `actions.py`'s
    `_is_thirteen_orphans` -- see `_ORPHAN_TYPES`'s docstring for why this is a copy, not an
    import, and how the two are kept from drifting apart. Reads `ctx.concealed_tiles` for the
    same reason as Nine Gates: `decompose()` never produces a `hand` for this shape at all.
    `if hand: return 0` isolates this to the one raw candidate it's meant for -- see
    `_detect_nine_gates`'s docstring for why."""
    if hand:
        return 0
    tiles = ctx.concealed_tiles
    if len(tiles) != 14:
        return 0
    return 1 if {tile_id_type(t) for t in tiles} == _ORPHAN_TYPES else 0


def _detect_heavenly_hand(_hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    """天糊: dealer wins on the initial deal, before any discard. `ctx.seat_wind == Wind.EAST`
    is redundant with `won_before_any_discard` in practice (only the dealer can ever have a
    complete hand before the first discard, see that field's docstring) but is checked
    explicitly anyway so this detector doesn't rely on that invariant holding elsewhere."""
    return 1 if ctx.won_before_any_discard and ctx.seat_wind == Wind.EAST else 0


def _detect_earthly_hand(_hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    """地糊: non-dealer wins by claiming the dealer's first discard. `not ctx.self_drawn` is
    redundant with `won_on_dealer_first_discard` (a claimed win is never a self-draw) but,
    same as Heavenly Hand above, checked explicitly rather than assumed."""
    if not ctx.won_on_dealer_first_discard or ctx.self_drawn:
        return 0
    return 1 if ctx.seat_wind != Wind.EAST else 0


def _detect_win_on_last_wall_tile(_hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    """海底撈月: self-draw win on the wall's last drawable tile. Excludes
    `ctx.is_kong_replacement` so this stays mutually exclusive with 槓上開花 when a kong
    replacement happens to also be that last tile -- see the module docstring's ladder note
    and the footnote added to 01-rules-spec.md §7. `ctx.is_last_tile`/`.is_kong_replacement`
    are stub fields, always `False` until sub-task 8 -- see the module docstring."""
    if not ctx.is_last_tile or not ctx.self_drawn or ctx.is_kong_replacement:
        return 0
    return 1


def _detect_win_on_last_discard(_hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    """河底撈魚: win claimed off the wall's last discard (the discard made right after the
    wall's last tile was drawn, with nothing left to draw after it). `not ctx.self_drawn` is
    the discard-vs-self-draw disambiguation `is_last_tile`'s docstring describes;
    `not ctx.is_robbing_kong` keeps this from double-firing alongside 搶槓 on the same claim,
    even though the two shouldn't realistically coincide (a robbed kong isn't a discard)."""
    if not ctx.is_last_tile or ctx.self_drawn or ctx.is_robbing_kong:
        return 0
    return 1


def _detect_win_on_kong_replacement(_hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    """槓上開花: self-draw win on a kong-replacement tile. `ctx.self_drawn` is redundant with
    `ctx.is_kong_replacement` in practice (a replacement draw is always a draw, never a claim)
    but checked explicitly anyway, same convention as Heavenly/Earthly Hand above."""
    return 1 if ctx.is_kong_replacement and ctx.self_drawn else 0


def _detect_robbing_the_kong(_hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    """搶槓: win by claiming a tile another seat just added to a kong. `not ctx.self_drawn` is
    redundant with `ctx.is_robbing_kong` (a robbed win is always a claim, never a self-draw)
    but checked explicitly, same convention as the rest of this batch."""
    return 1 if ctx.is_robbing_kong and not ctx.self_drawn else 0


_SEASON_OFFSET = 4


def _seat_flower_types(seat_wind: Wind) -> frozenset[Flower]:
    """The flower and season that match `seat_wind` (§7 "Flower faan": flower/season number N
    matches the seat currently holding wind N -- East=1, South=2, West=3, North=4, 0-indexed
    here to match `Wind`/`Flower`)."""
    return frozenset({Flower(int(seat_wind)), Flower(int(seat_wind) + _SEASON_OFFSET)})


def _detect_seat_flower(_hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    """座位花, "each" like 箭刻/一般高: up to 2 (the seat-matching flower and the
    seat-matching season). Gated by `ctx.flowers_score`, mirroring `RuleSet.flowers_score`
    (config.py) -- see the module docstring's "Flower faan" note."""
    if not ctx.flowers_score:
        return 0
    want = _seat_flower_types(ctx.seat_wind)
    return sum(1 for f in ctx.flowers if f in want)


_FULL_FLOWER_SET = frozenset({Flower.FLOWER_1, Flower.FLOWER_2, Flower.FLOWER_3, Flower.FLOWER_4})
_FULL_SEASON_SET = frozenset({Flower.SEASON_1, Flower.SEASON_2, Flower.SEASON_3, Flower.SEASON_4})


def _detect_flower_set(_hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    """正花 (Classic table, missed in sub-task 1's situational batch -- see the module
    docstring): holding all four flowers, or all four seasons, at once. "Each," not
    "either/or" -- physically rare but not impossible to hold both complete sets in one hand
    (kong-replacement chains can draw arbitrarily many flowers), so this can report 2, same
    "each" convention as every other aggregate detector in this module."""
    held = frozenset(ctx.flowers)
    return int(_FULL_FLOWER_SET <= held) + int(_FULL_SEASON_SET <= held)


def _detect_seven_pairs(hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    """七對子: 14 concealed tiles as 7 *distinct* pairs. Mirrors `actions.py`'s
    `_is_seven_pairs` (win-legality's shape check) for the same reason `_ORPHAN_TYPES` mirrors
    rather than imports it -- see that frozenset's docstring; `test_scoring.py` cross-checks
    the two so they can't drift. Unlike Thirteen Orphans, §7 gives this a plain 4 faan, not a
    limit hand -- `is_limit=False` below. `decompose()` never produces a `hand` for this shape
    (seven pairs isn't four groups plus a pair), so this reads `ctx.concealed_tiles` directly,
    same as Thirteen Orphans/Nine Gates. `if hand: return 0` isolates this to the one raw
    candidate it's meant for -- see `_detect_nine_gates`'s docstring for why this matters here
    in particular: unlike Thirteen Orphans/Nine Gates, this isn't a limit pattern, so it isn't
    shielded from double-counting by the limit-hand non-stacking collapse (`faan.py`'s
    `_score_candidate`) -- a hand whose 14 tiles happen to also parse as a real standard
    decomposition would otherwise add 七對子's faan on top of that unrelated decomposition's
    own patterns on every candidate scored, not just the seven-pairs interpretation itself."""
    if hand:
        return 0
    tiles = ctx.concealed_tiles
    if len(tiles) != 14:
        return 0
    counts = Counter(tile_id_type(t) for t in tiles)
    return 1 if len(counts) == 7 and all(c == 2 for c in counts.values()) else 0


def _detect_three_concealed_pungs(hand: tuple[Meld, ...], _ctx: ScoringContext) -> int:
    """三暗刻: at least three concealed pungs/kongs. "At least," not "exactly" -- a fourth
    concealed pung has no separate, higher-value pattern in this ruleset's tables to catch it
    (contrast Small/Big Three Dragons' exact counts, each with its own named tier), so folding
    a rare four-concealed-pung hand into this one is correct rather than a gap. A `PUNG` meld
    is concealed iff `from_seat is None` -- decompose() only ever emits pungs that way (self-
    drawn, never claimed); a claimed pung always carries a `from_seat`. `CONCEALED_KONG` always
    has `from_seat is None` by construction (`Meld.__post_init__` forbids it otherwise) and
    counts as a concealed pung here, matching standard practice that a self-declared kong
    doesn't break concealment. `EXPOSED_KONG`/`ADDED_KONG` are always open (claimed, or
    upgrading a claimed pung) and never qualify."""
    split = _groups_and_pair(hand)
    if split is None:
        return 0
    groups, _pair = split
    concealed_pungs = sum(
        1
        for m in groups
        if m.kind in (MeldKind.PUNG, MeldKind.CONCEALED_KONG) and m.from_seat is None
    )
    return 1 if concealed_pungs >= 3 else 0


def _detect_all_revealed(hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    """全求人: every one of the four groups is open (claimed from another seat) and the win
    itself is claimed off a discard, not self-drawn -- "entirely obtained from others," the
    mirror image of `_detect_fully_concealed`'s "no open melds, win on discard." Requiring all
    four groups open is what keeps this unambiguous despite `decompose()` never tagging a
    group as claimed-to-win vs self-formed (see `_detect_fully_concealed`'s note that the
    winning tile is never itself "open"): if every group already carries a `from_seat`, none
    of them came from `decompose()` at all (`decompose()` never sets `from_seat`), so there's
    no risk of a self-formed concealed group being mistaken for an open one, or vice versa.
    `self_drawn` still needs its own check -- a hand can have four pre-claimed groups and then
    self-draw the tile that completes the pair, which isn't "from others.\""""
    if ctx.self_drawn:
        return 0
    split = _groups_and_pair(hand)
    if split is None:
        return 0
    groups, _pair = split
    return 1 if all(_is_open(m) for m in groups) else 0


def _detect_two_dragon_pungs(hand: tuple[Meld, ...], _ctx: ScoringContext) -> int:
    """雙箭: pungs/kongs of exactly two dragon types, independent of what the pair is. This
    reads the same `dragon_pungs` count as Small Three Dragons but doesn't require a dragon
    pair -- so it fires both when the pair is the third dragon (stacking with Small Three
    Dragons, same "everything stacks unless §7 says otherwise" precedent as 箭刻 stacking with
    Small/Big Three Dragons) and when it isn't (a shape Small Three Dragons can't reach at
    all). "Exactly two," not "at least two," keeps this mutually exclusive with Big Three
    Dragons by the same physical-tile-count argument as Small vs. Big (three dragon pungs
    commit 9 of the 12 physical dragon tiles, leaving no room for a fourth pung of a type
    already exhausted) -- see the footnote added to 01-rules-spec.md §7."""
    split = _groups_and_pair(hand)
    if split is None:
        return 0
    groups, _pair = split
    dragon_pungs = sum(
        1 for m in groups if m.kind in _PUNG_OR_KONG and m.tile_type in _DRAGON_TYPES
    )
    return 1 if dragon_pungs == 2 else 0


def _chow_run_counts(groups: tuple[Meld, ...]) -> dict[TileType, int]:
    """How many `CHOW` melds in `groups` share the exact same three ranks (same `tile_type`,
    a chow's lowest tile) -- the building block Two/Three Identical Sequences both need. This
    is a genuinely different shape than every earlier detector in this module: those look at
    one meld at a time or count a single fixed category (a tile type, concealed-ness) across
    the hand; identical sequences need groups compared *against each other*, so the comparison
    has to happen in its own pass before either detector can just check a count."""
    counts: dict[TileType, int] = {}
    for m in groups:
        if m.kind == MeldKind.CHOW:
            counts[m.tile_type] = counts.get(m.tile_type, 0) + 1
    return counts


def _detect_two_identical_sequences(hand: tuple[Meld, ...], _ctx: ScoringContext) -> int:
    """一般高, "each" like 箭刻: how many distinct runs appear as *exactly* two identical
    chows. With only four groups in a hand, two different double-chows (e.g. 123m x2 and
    456p x2) is the only way this fires more than once. "Exactly two" (not "at least two") is
    what keeps this mutually exclusive with 三般高 by construction -- a run's count can't be
    both `== 2` and `>= 3` at once, no separate subsumption check needed, same trick as
    Voided Suit vs Half/Full Flush."""
    split = _groups_and_pair(hand)
    if split is None:
        return 0
    groups, _pair = split
    return sum(1 for c in _chow_run_counts(groups).values() if c == 2)


def _detect_three_identical_sequences(hand: tuple[Meld, ...], _ctx: ScoringContext) -> int:
    """三般高: a run appearing three (or, physically possible with four matching copies of one
    suit's three ranks, four) times. "At least three," not "exactly three" -- same reasoning
    as `_detect_three_concealed_pungs`: there's no separate, higher-value "Four Identical
    Sequences" tier in this ruleset's tables, so a hand with all four groups identical folds
    into this one rather than scoring nothing."""
    split = _groups_and_pair(hand)
    if split is None:
        return 0
    groups, _pair = split
    return 1 if any(c >= 3 for c in _chow_run_counts(groups).values()) else 0


def _chow_start_ranks_by_suit(groups: tuple[Meld, ...]) -> dict[int, set[int]]:
    """Which ranks (0-8) start a `CHOW` in `groups`, grouped by suit (0=man/1=pin/2=sou) --
    the building block Three/Four Step Sequences need to find an evenly-spaced run of chows,
    the same "compare groups against each other" shape `_chow_run_counts` uses for identical
    sequences, but keyed by rank-with-suit instead of exact run identity."""
    result: dict[int, set[int]] = {}
    for m in groups:
        if m.kind != MeldKind.CHOW:
            continue
        suit, rank = divmod(int(m.tile_type), 9)
        result.setdefault(suit, set()).add(rank)
    return result


def _has_step_run(ranks: set[int], length: int) -> bool:
    """Whether `ranks` (one suit's distinct chow-starting ranks) contains `length` runs each
    starting two ranks above the previous (01-rules-spec.md §7 footnote: 三步高/四步高's step is
    2, e.g. 123-345-567, not 1 or 3) -- `max_start` is the highest starting rank that still
    leaves room for `length` such runs within ranks 0-8."""
    max_start = 6 - 2 * (length - 1)
    return any(all((s + 2 * i) in ranks for i in range(length)) for s in range(max_start + 1))


def _detect_four_step_sequences(hand: tuple[Meld, ...], _ctx: ScoringContext) -> int:
    """四步高: four chows in one suit, starting ranks spaced two apart. The only shape that
    fits within one suit's nine ranks is 1-2-3 / 3-4-5 / 5-6-7 / 7-8-9 (starts 0,2,4,6) --
    using every one of the hand's four groups, so this hand has no room left for a pair drawn
    from the same suit's chows; that's fine, the pair is unconstrained."""
    split = _groups_and_pair(hand)
    if split is None:
        return 0
    groups, _pair = split
    by_suit = _chow_start_ranks_by_suit(groups)
    return 1 if any(_has_step_run(ranks, 4) for ranks in by_suit.values()) else 0


def _detect_three_step_sequences(hand: tuple[Meld, ...], _ctx: ScoringContext) -> int:
    """三步高: three chows in one suit, starting ranks spaced two apart. Excludes a suit that
    also satisfies Four Step Sequences (`not _has_step_run(ranks, 4)`) -- ladder rule, take the
    higher tier, same convention as Two/Three Identical Sequences above and Small/Big Three
    Dragons in the second sub-task: a 0,2,4,6 four-step hand's ranks contain the 3-step
    sub-sequences {0,2,4} and {2,4,6} too, so without this exclusion both patterns would fire
    on the same four groups. See the footnote added to 01-rules-spec.md §7."""
    split = _groups_and_pair(hand)
    if split is None:
        return 0
    groups, _pair = split
    by_suit = _chow_start_ranks_by_suit(groups)
    return (
        1
        if any(
            _has_step_run(ranks, 3) and not _has_step_run(ranks, 4) for ranks in by_suit.values()
        )
        else 0
    )


LIMIT_FAAN = 13
"""Placeholder per-occurrence value for `is_limit` patterns. §7 gives limit hands no faan
number at all -- "take the highest [limit pattern]," scored at the table's `faan_cap` (10 or
13), not stacked faan-by-faan -- so there's no single correct `int` here. `13` (the highest
configurable `faan_cap`) is a conservative stand-in `score_hand`'s `dict[str, int]` can carry
until `faan.py` exists; once it does, it's expected to special-case `is_limit` and replace
this with the real payout rather than sum it in with everything else. See the module
docstring's "Limit hands don't stack" note.
"""


PATTERNS: tuple[Pattern, ...] = (
    Pattern("平糊", HandSet.CLASSIC, 1, _detect_all_sequences),
    Pattern("對對糊", HandSet.CLASSIC, 3, _detect_all_pungs),
    Pattern("缺一門", HandSet.CLASSIC, 2, _detect_voided_suit),
    Pattern("混一色", HandSet.CLASSIC, 3, _detect_half_flush),
    Pattern("清一色", HandSet.CLASSIC, 6, _detect_full_flush),
    Pattern("無花", HandSet.CLASSIC, 1, _detect_no_flowers),
    Pattern("自摸", HandSet.CLASSIC, 1, _detect_self_draw),
    Pattern("門前清", HandSet.CLASSIC, 1, _detect_fully_concealed),
    Pattern("門風", HandSet.CLASSIC, 1, _detect_seat_wind),
    Pattern("圈風", HandSet.CLASSIC, 1, _detect_prevailing_wind),
    Pattern("箭刻", HandSet.CLASSIC, 1, _detect_dragon_pung),
    Pattern("小三元", HandSet.CLASSIC, 3, _detect_small_three_dragons),
    Pattern("大三元", HandSet.CLASSIC, 7, _detect_big_three_dragons),
    Pattern("小四喜", HandSet.CLASSIC, 5, _detect_small_four_winds),
    Pattern("大四喜", HandSet.CLASSIC, 8, _detect_big_four_winds),
    Pattern("混么九", HandSet.NEW_6, 3, _detect_mixed_terminals),
    Pattern("海底撈月", HandSet.NEW_6, 1, _detect_win_on_last_wall_tile),
    Pattern("河底撈魚", HandSet.NEW_6, 1, _detect_win_on_last_discard),
    Pattern("槓上開花", HandSet.NEW_6, 1, _detect_win_on_kong_replacement),
    Pattern("搶槓", HandSet.NEW_6, 1, _detect_robbing_the_kong),
    Pattern("座位花", HandSet.CLASSIC, 1, _detect_seat_flower),
    Pattern("正花", HandSet.CLASSIC, 3, _detect_flower_set),
    Pattern("字一色", HandSet.CLASSIC, LIMIT_FAAN, _detect_all_honors, is_limit=True),
    Pattern("清么九", HandSet.CLASSIC, LIMIT_FAAN, _detect_all_terminals, is_limit=True),
    Pattern("九蓮寶燈", HandSet.CLASSIC, LIMIT_FAAN, _detect_nine_gates, is_limit=True),
    Pattern("十三么", HandSet.CLASSIC, LIMIT_FAAN, _detect_thirteen_orphans, is_limit=True),
    Pattern("天糊", HandSet.CLASSIC, LIMIT_FAAN, _detect_heavenly_hand, is_limit=True),
    Pattern("地糊", HandSet.CLASSIC, LIMIT_FAAN, _detect_earthly_hand, is_limit=True),
    Pattern("七對子", HandSet.NEW_18, 4, _detect_seven_pairs),
    Pattern("三暗刻", HandSet.NEW_18, 2, _detect_three_concealed_pungs),
    Pattern("全求人", HandSet.NEW_18, 2, _detect_all_revealed),
    Pattern("雙箭", HandSet.NEW_18, 2, _detect_two_dragon_pungs),
    Pattern("一般高", HandSet.NEW_18, 1, _detect_two_identical_sequences),
    Pattern("三般高", HandSet.NEW_18, 6, _detect_three_identical_sequences),
    Pattern("三步高", HandSet.NEW_18, 2, _detect_three_step_sequences),
    Pattern("四步高", HandSet.NEW_18, 6, _detect_four_step_sequences),
)


def score_hand(hand: tuple[Meld, ...], context: ScoringContext) -> dict[str, int]:
    """Run every registered pattern against one candidate `hand` (see the module docstring for
    what shape that is), returning `{pattern_name: faan_awarded}` for patterns that matched at
    all. Faan simply sums here with no cap and no `hand_sets`/`faan_overrides` filtering --
    real stacking-with-caps, the `min_faan` gate, and maximising across every decomposition
    candidate for a win are faan.py's job (a later sub-task); this is the per-decomposition
    building block it will call once per candidate.
    """
    result: dict[str, int] = {}
    for pattern in PATTERNS:
        occurrences = pattern.detect(hand, context)
        if occurrences:
            result[pattern.name] = occurrences * pattern.faan
    return result
