"""Faan pattern detectors (docs/01-rules-spec.md §7; docs/05-roadmap.md §1, §2).

Scope (this sub-task, first slice of M2): the detector framework -- `ScoringContext`, the
`Pattern` registration shape, and `score_hand`, the per-decomposition scorer -- plus the first
batch of patterns: the structural/suit-shape Classic patterns (All Sequences, All Pungs,
Voided Suit, Half Flush, Full Flush) and the single-flag situational Classic patterns (No
Flowers, Self-Draw, Fully Concealed, Seat Wind, Prevailing Wind, Dragon pung). These were
picked as the starting batch because together they exercise every field `ScoringContext` needs
(seat wind, prevailing wind, self-draw, flowers, concealed-vs-open) without requiring
decomposition-maximisation (faan.py, later) or wall-timing context (New Six's 海底/槓上開花/
搶槓, a later sub-task). Seven Pairs, Thirteen Orphans, the three/four-dragon and
wind "small/big" patterns, New 18's stacking patterns, and every limit hand are later batches
-- see the sub-task breakdown in the M2 planning report this change shipped with.

**What a detector operates on.** `hand` is one candidate full decomposition of the winning
14 tiles: the seat's already-formed melds (`SeatState.melds` -- claimed chows/pungs/kongs, or
a self-declared concealed/added kong) plus one candidate parse of the remaining concealed
tiles from `melds.decompose` (always exactly one `PAIR` plus four 3-or-4-tile groups for the
patterns in this batch; Seven Pairs/Thirteen Orphans hands don't decompose this way at all --
a future sub-task's detectors for those patterns won't take this `hand` shape). Maximising
faan across every such candidate (when `decompose` returns more than one split) is faan.py's
job, not this module's -- `score_hand` here just scores the one candidate it's given.

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
from mahjong_core.tiles import Flower, TileType

_DRAGON_TYPES = frozenset({TileType.DRAGON_RED, TileType.DRAGON_GREEN, TileType.DRAGON_WHITE})
_WIND_TYPES = frozenset(
    {TileType.WIND_EAST, TileType.WIND_SOUTH, TileType.WIND_WEST, TileType.WIND_NORTH}
)
_PUNG_OR_KONG = frozenset({MeldKind.PUNG, *KONG_KINDS})


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
    """

    seat_wind: Wind
    prevailing_wind: Wind
    self_drawn: bool
    flowers: tuple[Flower, ...]


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
