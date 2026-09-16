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
"""

from __future__ import annotations

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

    All three default so every earlier caller/test keeps working unchanged.
    """

    seat_wind: Wind
    prevailing_wind: Wind
    self_drawn: bool
    flowers: tuple[Flower, ...]
    concealed_tiles: tuple[TileId, ...] = ()
    won_before_any_discard: bool = False
    won_on_dealer_first_discard: bool = False


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


def _detect_nine_gates(_hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    """九蓮寶燈: one suit, fully concealed, 1112345678999 plus one more tile of that suit
    (any rank 1-9) -- see `_NINE_GATES_BASE_COUNTS`. Reads `ctx.concealed_tiles` directly
    (see the module docstring's "Raw-hand access" note) rather than `hand`: this is an exact
    tile-count check, not a meld-shape one, and requiring `len(...) == 14` is what excludes an
    open hand (Nine Gates has no claimed-meld variant) without a separate open-meld check.
    """
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


def _detect_thirteen_orphans(_hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    """十三么: all 13 terminal/honor types present at least once among 14 concealed tiles
    (the 14th is necessarily a duplicate of one of them). Mirrors `actions.py`'s
    `_is_thirteen_orphans` -- see `_ORPHAN_TYPES`'s docstring for why this is a copy, not an
    import, and how the two are kept from drifting apart. Reads `ctx.concealed_tiles` for the
    same reason as Nine Gates: `decompose()` never produces a `hand` for this shape at all."""
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
    Pattern("字一色", HandSet.CLASSIC, LIMIT_FAAN, _detect_all_honors, is_limit=True),
    Pattern("清么九", HandSet.CLASSIC, LIMIT_FAAN, _detect_all_terminals, is_limit=True),
    Pattern("九蓮寶燈", HandSet.CLASSIC, LIMIT_FAAN, _detect_nine_gates, is_limit=True),
    Pattern("十三么", HandSet.CLASSIC, LIMIT_FAAN, _detect_thirteen_orphans, is_limit=True),
    Pattern("天糊", HandSet.CLASSIC, LIMIT_FAAN, _detect_heavenly_hand, is_limit=True),
    Pattern("地糊", HandSet.CLASSIC, LIMIT_FAAN, _detect_earthly_hand, is_limit=True),
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
