"""Faan pattern detectors: `ScoringContext`, the `Pattern` registration shape, and
`score_hand`, the per-decomposition scorer.

`hand` is one candidate full decomposition of the winning 14 tiles: the seat's already-formed
melds plus one candidate parse of the remaining concealed tiles from `melds.decompose` (one
`PAIR` plus four 3-or-4-tile groups, for hands that decompose this way). Maximising faan
across every candidate split is faan.py's job -- `score_hand` here just scores the one
candidate it's given.

Raw-hand access: Thirteen Orphans and Nine Gates don't decompose into `hand` at all, so
`ScoringContext.concealed_tiles` carries the winning seat's raw concealed tile ids for
detectors that need them directly, instead of changing every detector's signature.

Limit hands don't stack (§7 "Stacking and caps"): a qualifying hand takes the single
highest-faan limit pattern instead of also adding wind/dragon/flower faan on top.
`score_hand` doesn't implement that rule -- it just tags patterns with `is_limit=True` and
`faan=LIMIT_FAAN` (a placeholder; the real value is `ruleset.faan_cap`) for `faan.py` to apply.

Heavenly/Earthly Hand and the four win-timing patterns (海底撈月/河底撈魚/槓上開花/搶槓) read
`ScoringContext` booleans (`won_before_any_discard`, `won_on_dealer_first_discard`,
`is_last_tile`, `is_kong_replacement`, `is_robbing_kong`) that default `False` -- the
detectors here are correct against them today; wiring the real values off engine state is
engine.py's job. 海底撈月 and 槓上開花 are mutually exclusive by construction:
`_detect_win_on_last_wall_tile` excludes `ctx.is_kong_replacement` so the more specific
pattern wins instead of double-counting the generic last-tile one.

A meld is "open" iff `meld.from_seat is not None` -- `Meld.__post_init__` already forbids
`from_seat` on `PAIR`/`CONCEALED_KONG`, so this single check covers concealed-vs-open without
`ScoringContext` needing its own flag.

Flower faan: 座位花 (up to 2 per seat: the numbered flower and season matching
`ctx.seat_wind`) is gated by `ScoringContext.flowers_score` (mirrors `RuleSet.flowers_score`,
default `True`); 正花 (all four flowers or all four seasons held at once) only reads
`ctx.flowers`.

Chicken Hand (雞糊) and the flower instant-win variants are deliberately not `Pattern`s here.
Chicken Hand's condition ("every other pattern scored zero") needs the whole `score_hand` loop
to have already run first, which is `faan.py`'s job. The flower instant-win ends the hand
immediately on flower count alone with no meld decomposition at all -- that's turn-state-machine
control flow (engine.py), not a faan value to add to a `dict[str, int]`.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

from mahjong_core.config import HandSet
from mahjong_core.melds import KONG_KINDS, Meld, MeldKind
from mahjong_core.state import Wind
from mahjong_core.tiles import (
    DRAGON_TYPES,
    N_SUITED_TYPES,
    ORPHAN_TYPES,
    RANKS_PER_SUIT,
    WIND_TYPES,
    Flower,
    TileId,
    TileType,
    tile_id_type,
)

_PUNG_OR_KONG = frozenset({MeldKind.PUNG, *KONG_KINDS})

_NINE_GATES_BASE_COUNTS = (3, 1, 1, 1, 1, 1, 1, 1, 3)
"""九蓮寶燈's fixed 13-tile skeleton within one suit, ranks 1..9: three of the 1, one each of
2-8, three of the 9. The winning hand is this plus exactly one more tile of the same suit
(any rank 1-9) -- 14 tiles total, still one suit, no honors."""


def seat_wind_for(seat: int, dealer: int) -> Wind:
    """A seat's wind for the hand currently being dealt by `dealer` -- the dealer is always
    East for their own deal, and seat wind rotates with the deal, not fixed table position.
    """
    if not 0 <= seat < 4 or not 0 <= dealer < 4:
        raise ValueError(f"seat and dealer must be 0..3, got seat={seat} dealer={dealer}")
    return Wind((seat - dealer) % 4)


@dataclass(frozen=True)
class ScoringContext:
    """Everything a pattern detector needs beyond the winning hand's melds themselves. One
    instance per win; faan.py builds it once and reuses it across every decomposition
    candidate for that win.

    `concealed_tiles`: raw concealed tile ids, for shapes `decompose()` can't produce
    (Thirteen Orphans, Nine Gates).

    `won_before_any_discard` (天糊): hand was already complete on the initial deal, before any
    discard -- only the dealer can ever have this be true.
    `won_on_dealer_first_discard` (地糊): winning seat claimed the dealer's first discard.
    `is_last_tile` (海底撈月/河底撈魚): wall was exhausted on the draw/discard that produced
    this win -- `self_drawn` disambiguates which.
    `is_kong_replacement` (槓上開花): this win's tile came from a kong-replacement draw.
    `is_chained_kong_replacement` (連槓開花): the kong replacement itself followed a kong
    declared on a kong-replacement draw.
    `is_robbing_kong` (搶槓): this win claimed a tile another seat just added to a kong.
    `flowers_score` (座位花): mirrors `RuleSet.flowers_score`, default `True`.
    `winning_tile`: the tile that completed the hand, for off-discard wins -- a pung it
    completes is open, not concealed (三暗刻/四暗刻).

    The win-timing fields all default `False` -- real values come from engine.py; the
    detectors below are already correct against them.
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
    is_chained_kong_replacement: bool = False
    is_robbing_kong: bool = False
    flowers_score: bool = True
    winning_tile: TileId | None = None


DetectorFn = Callable[[tuple[Meld, ...], ScoringContext], int]
"""A detector returns how many times its pattern applies to `hand` (0 if it doesn't apply at
all) -- almost always 0 or 1, but "each"-style patterns like dragon pung can return up to 3.
`Pattern.faan` is the per-occurrence value; `faan.py` computes a pattern's contribution as
`occurrences * (faan_overrides.get(name) or faan)`.
"""


@dataclass(frozen=True)
class Pattern:
    """One faan pattern's registration: identity, which `hand_sets` group gates it, its base
    per-occurrence faan value, and its detector. `name` is also the key `RuleSet.faan_overrides`
    uses.
    """

    name: str
    hand_set: HandSet
    faan: int
    detect: DetectorFn
    is_limit: bool = False


def _groups_and_pair(hand: tuple[Meld, ...]) -> tuple[tuple[Meld, ...], Meld] | None:
    """Split `hand` into its four non-pair groups and its pair. `None` if `hand` isn't shaped
    that way (exactly one `PAIR` meld) -- lets a detector just treat that as "pattern doesn't
    apply" for shapes it doesn't understand (Seven Pairs, Thirteen Orphans).
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
        if v < N_SUITED_TYPES:
            suits.add(v // RANKS_PER_SUIT)
        else:
            honors = True
    return suits, honors


def _suit_profile(hand: tuple[Meld, ...], ctx: ScoringContext) -> tuple[set[int], bool] | None:
    """`_suits_used` for a standard decomposition, or the same read off the raw tiles for a
    Seven Pairs hand, so flush patterns stack with 七對子. `None` for any other shape."""
    split = _groups_and_pair(hand)
    if split is not None:
        return _suits_used(*split)
    if not _detect_seven_pairs(hand, ctx):
        return None
    suits: set[int] = set()
    honors = False
    for t in ctx.concealed_tiles:
        v = int(tile_id_type(t))
        if v < N_SUITED_TYPES:
            suits.add(v // RANKS_PER_SUIT)
        else:
            honors = True
    return suits, honors


def _detect_all_sequences(hand: tuple[Meld, ...], _ctx: ScoringContext) -> int:
    """平糊: four chows and any pair."""
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


def _detect_half_flush(hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    profile = _suit_profile(hand, ctx)
    if profile is None:
        return 0
    suits, honors = profile
    return 1 if len(suits) == 1 and honors else 0


def _detect_full_flush(hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    profile = _suit_profile(hand, ctx)
    if profile is None:
        return 0
    suits, honors = profile
    return 1 if len(suits) == 1 and not honors else 0


def _detect_no_flowers(_hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    return 1 if not ctx.flowers else 0


def _detect_self_draw(_hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    return 1 if ctx.self_drawn else 0


def _detect_fully_concealed(hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    """門前清: no claimed melds and no concealed kong, on a self-draw or a discard win. Seven
    Pairs never earns it (and 四暗刻 replaces it, `_SUPERSEDES`)."""
    if _detect_seven_pairs(hand, ctx):
        return 0
    return 0 if any(_is_open(m) or m.kind == MeldKind.CONCEALED_KONG for m in hand) else 1


def _detect_seat_wind(hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    split = _groups_and_pair(hand)
    if split is None:
        return 0
    groups, _pair = split
    want = TileType(TileType.WIND_EAST + int(ctx.seat_wind))
    return 1 if any(m.kind in _PUNG_OR_KONG and m.tile_type == want for m in groups) else 0


def _detect_prevailing_wind(hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    """圈風. Deliberately independent of `_detect_seat_wind`: when a dealer's seat wind equals
    the prevailing wind, both patterns fire on the same pung and stack -- 2 faan, not 1.
    """
    split = _groups_and_pair(hand)
    if split is None:
        return 0
    groups, _pair = split
    want = TileType(TileType.WIND_EAST + int(ctx.prevailing_wind))
    return 1 if any(m.kind in _PUNG_OR_KONG and m.tile_type == want for m in groups) else 0


def _detect_dragon_pung(hand: tuple[Meld, ...], _ctx: ScoringContext) -> int:
    """箭刻 / 番牌, "each" -- returns how many of the (up to three) dragon pungs/kongs are
    present, so the caller's `occurrences * faan` naturally gives 1 faan per dragon. Whether
    two or three of these should instead resolve to Small/Big Three Dragons is faan.py's
    concern; this detector only reports the base per-dragon count.
    """
    split = _groups_and_pair(hand)
    if split is None:
        return 0
    groups, _pair = split
    return sum(1 for m in groups if m.kind in _PUNG_OR_KONG and m.tile_type in DRAGON_TYPES)


def _detect_small_three_dragons(hand: tuple[Meld, ...], _ctx: ScoringContext) -> int:
    """小三元: a dragon pair plus pungs/kongs of the other two dragons. Mutually exclusive
    with Big Three Dragons by construction -- physical tile counts (max 4 per type) already
    rule out the pair's dragon overlapping the two pungs' dragons."""
    split = _groups_and_pair(hand)
    if split is None:
        return 0
    groups, pair = split
    dragon_pungs = sum(1 for m in groups if m.kind in _PUNG_OR_KONG and m.tile_type in DRAGON_TYPES)
    return 1 if dragon_pungs == 2 and pair.tile_type in DRAGON_TYPES else 0


def _detect_big_three_dragons(hand: tuple[Meld, ...], _ctx: ScoringContext) -> int:
    """大三元: pungs/kongs of all three dragons."""
    split = _groups_and_pair(hand)
    if split is None:
        return 0
    groups, _pair = split
    dragon_pungs = sum(1 for m in groups if m.kind in _PUNG_OR_KONG and m.tile_type in DRAGON_TYPES)
    return 1 if dragon_pungs == 3 else 0


def _detect_small_four_winds(hand: tuple[Meld, ...], _ctx: ScoringContext) -> int:
    """小四喜: a wind pair plus pungs/kongs of the other three winds."""
    split = _groups_and_pair(hand)
    if split is None:
        return 0
    groups, pair = split
    wind_pungs = sum(1 for m in groups if m.kind in _PUNG_OR_KONG and m.tile_type in WIND_TYPES)
    return 1 if wind_pungs == 3 and pair.tile_type in WIND_TYPES else 0


def _detect_big_four_winds(hand: tuple[Meld, ...], _ctx: ScoringContext) -> int:
    """大四喜: pungs/kongs of all four winds."""
    split = _groups_and_pair(hand)
    if split is None:
        return 0
    groups, _pair = split
    wind_pungs = sum(1 for m in groups if m.kind in _PUNG_OR_KONG and m.tile_type in WIND_TYPES)
    return 1 if wind_pungs == 4 else 0


def _is_terminal(tile_type: TileType) -> bool:
    v = int(tile_type)
    return v < N_SUITED_TYPES and v % RANKS_PER_SUIT in (0, 8)


def _is_honor(tile_type: TileType) -> bool:
    return int(tile_type) >= N_SUITED_TYPES


def _detect_mixed_terminals(hand: tuple[Meld, ...], _ctx: ScoringContext) -> int:
    """花么九: every group and the pair is a terminal or an honor, with at least one of each
    present. Excludes chows outright -- `Meld.tile_type` is a chow's lowest tile and would
    wrongly call 1-2-3 "terminal"."""
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


def _detect_all_honors(hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    """字一色: every group and the pair is an honor tile. No chow-exclusion needed (contrast
    `_detect_mixed_terminals`/`_detect_all_terminals`): honors never form chows, so any chow
    present already fails `_is_honor` on its (necessarily suited) `tile_type`."""
    split = _groups_and_pair(hand)
    if split is None:
        profile = _suit_profile(hand, ctx)
        return 1 if profile is not None and not profile[0] else 0
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
    """九蓮寶燈: one suit, fully concealed, 1112345678999 plus one more tile of that suit (any
    rank 1-9) -- see `_NINE_GATES_BASE_COUNTS`. Reads `ctx.concealed_tiles` directly rather
    than `hand`: exact tile-count check, not meld-shape.

    `if hand: return 0` matters here: `ctx.concealed_tiles` is fixed across every candidate
    scored for one win, so without this guard the pattern would fire on every candidate during
    decomposition maximisation, not just the raw (fully-concealed) one it's meant for --
    stacking its faan onto an unrelated standard decomposition.
    """
    if hand:
        return 0
    tiles = ctx.concealed_tiles
    if len(tiles) != 14:
        return 0
    types = [tile_id_type(t) for t in tiles]
    if any(_is_honor(t) for t in types):
        return 0
    suits = {int(t) // RANKS_PER_SUIT for t in types}
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
    `_is_thirteen_orphans` -- see `ORPHAN_TYPES`'s docstring. Reads `ctx.concealed_tiles` and
    guards `if hand: return 0`, same reason as `_detect_nine_gates`."""
    if hand:
        return 0
    tiles = ctx.concealed_tiles
    if len(tiles) != 14:
        return 0
    return 1 if {tile_id_type(t) for t in tiles} == ORPHAN_TYPES else 0


def _detect_heavenly_hand(_hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    """天糊: dealer wins on the initial deal, before any discard. `ctx.seat_wind == Wind.EAST`
    is redundant with `won_before_any_discard` in practice but checked explicitly anyway so
    this detector doesn't rely on that invariant holding elsewhere."""
    return 1 if ctx.won_before_any_discard and ctx.seat_wind == Wind.EAST else 0


def _detect_earthly_hand(_hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    """地糊: non-dealer wins by claiming the dealer's first discard. `not ctx.self_drawn` is
    redundant with `won_on_dealer_first_discard` but, same as Heavenly Hand, checked
    explicitly rather than assumed."""
    if not ctx.won_on_dealer_first_discard or ctx.self_drawn:
        return 0
    return 1 if ctx.seat_wind != Wind.EAST else 0


def _detect_win_on_last_wall_tile(_hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    """海底撈月: self-draw win on the wall's last drawable tile. Excludes
    `ctx.is_kong_replacement` so this stays mutually exclusive with 槓上開花 when a kong
    replacement happens to also be that last tile."""
    if not ctx.is_last_tile:
        return 0
    if ctx.self_drawn:
        return 0 if ctx.is_kong_replacement else 1
    return 0 if ctx.is_robbing_kong else 1


def _detect_win_on_kong_replacement(_hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    """槓上開花: self-draw win on a kong-replacement tile. `ctx.self_drawn` is redundant with
    `ctx.is_kong_replacement` but checked explicitly anyway, same convention as above."""
    return 1 if ctx.is_kong_replacement and ctx.self_drawn else 0


def _detect_chained_kong_win(_hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    """連槓開花: self-draw win on the replacement tile of a second consecutive kong."""
    return 1 if ctx.is_chained_kong_replacement and ctx.self_drawn else 0


def _detect_robbing_the_kong(_hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    """搶槓: win by claiming a tile another seat just added to a kong. `not ctx.self_drawn` is
    redundant with `ctx.is_robbing_kong` but checked explicitly, same convention as above."""
    return 1 if ctx.is_robbing_kong and not ctx.self_drawn else 0


_SEASON_OFFSET = 4


def _seat_flower_types(seat_wind: Wind) -> frozenset[Flower]:
    """The flower and season that match `seat_wind`: flower/season number N matches the seat
    currently holding wind N -- East=1, South=2, West=3, North=4, 0-indexed here."""
    return frozenset({Flower(int(seat_wind)), Flower(int(seat_wind) + _SEASON_OFFSET)})


_FULL_FLOWER_SET = frozenset({Flower.FLOWER_1, Flower.FLOWER_2, Flower.FLOWER_3, Flower.FLOWER_4})
_FULL_SEASON_SET = frozenset({Flower.SEASON_1, Flower.SEASON_2, Flower.SEASON_3, Flower.SEASON_4})


def _complete_flower_sets(ctx: ScoringContext) -> list[frozenset[Flower]]:
    held = frozenset(ctx.flowers)
    return [s for s in (_FULL_FLOWER_SET, _FULL_SEASON_SET) if s <= held]


def _detect_seat_flower(_hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    """正花, "each": up to 2 (the seat-matching flower and season), not counting one that
    belongs to a complete set -- 一台花 already pays for it. Gated by `ctx.flowers_score`,
    mirroring `RuleSet.flowers_score`."""
    if not ctx.flowers_score:
        return 0
    want = _seat_flower_types(ctx.seat_wind)
    in_sets = frozenset().union(*_complete_flower_sets(ctx))
    return sum(1 for f in ctx.flowers if f in want and f not in in_sets)


def _detect_flower_set(_hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    """一台花: all four flowers, or all four seasons, held at once. "Each," so 2 sets report 2."""
    return len(_complete_flower_sets(ctx))


def _detect_seven_pairs(hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    """七對子: 14 concealed tiles as 7 *distinct* pairs. Mirrors `actions.py`'s
    `_is_seven_pairs` -- see `ORPHAN_TYPES`'s docstring. Unlike Thirteen Orphans, §7 gives
    this a plain 4 faan, not a limit hand (`is_limit=False` below), so it isn't shielded from
    double-counting by the limit-hand collapse -- the `if hand: return 0` guard (see
    `_detect_nine_gates`) matters especially here since a hand that also parses as a real
    standard decomposition would otherwise stack this on top of it."""
    if hand:
        return 0
    tiles = ctx.concealed_tiles
    if len(tiles) != 14:
        return 0
    counts = Counter(tile_id_type(t) for t in tiles)
    return 1 if len(counts) == 7 and all(c == 2 for c in counts.values()) else 0


def _concealed_pung_count(hand: tuple[Meld, ...], ctx: ScoringContext) -> int | None:
    """Concealed pungs/kongs in a standard decomposition, `None` for other shapes.
    `CONCEALED_KONG` counts (a self-declared kong doesn't break concealment); exposed/added
    kongs never do. On an off-discard win, a pung of the winning tile's type is open --
    maximisation over decompositions covers the case where that tile sits in a chow or pair."""
    split = _groups_and_pair(hand)
    if split is None:
        return None
    groups, _pair = split
    completing = (
        tile_id_type(ctx.winning_tile)
        if ctx.winning_tile is not None and not ctx.self_drawn
        else None
    )
    return sum(
        1
        for m in groups
        if m.from_seat is None
        and (
            m.kind == MeldKind.CONCEALED_KONG
            or (m.kind == MeldKind.PUNG and m.tile_type != completing)
        )
    )


def _detect_four_concealed_pungs(hand: tuple[Meld, ...], ctx: ScoringContext) -> int:
    """四暗刻 (坎坎糊): all four groups concealed pungs/kongs."""
    return 1 if _concealed_pung_count(hand, ctx) == 4 else 0


def _detect_four_kongs(hand: tuple[Meld, ...], _ctx: ScoringContext) -> int:
    """十八羅漢: all four groups are kongs."""
    split = _groups_and_pair(hand)
    if split is None:
        return 0
    groups, _pair = split
    return 1 if all(m.kind in KONG_KINDS for m in groups) else 0


LIMIT_FAAN = 13
LOW_LIMIT_FAAN = 10
"""`is_limit` patterns' own tier: 13 for most, 10 for 字一色/清么九/九蓮寶燈. `faan.py` pays
`min(tier, faan_cap)` and never sums a limit with anything else."""


PATTERNS: tuple[Pattern, ...] = (
    Pattern("平糊", HandSet.CLASSIC, 1, _detect_all_sequences),
    Pattern("對對糊", HandSet.CLASSIC, 3, _detect_all_pungs),
    Pattern("混一色", HandSet.CLASSIC, 3, _detect_half_flush),
    Pattern("清一色", HandSet.CLASSIC, 7, _detect_full_flush),
    Pattern("無花", HandSet.CLASSIC, 1, _detect_no_flowers),
    Pattern("自摸", HandSet.CLASSIC, 1, _detect_self_draw),
    Pattern("門前清", HandSet.CLASSIC, 1, _detect_fully_concealed),
    Pattern("門風", HandSet.CLASSIC, 1, _detect_seat_wind),
    Pattern("圈風", HandSet.CLASSIC, 1, _detect_prevailing_wind),
    Pattern("箭刻", HandSet.CLASSIC, 1, _detect_dragon_pung),
    Pattern("小三元", HandSet.CLASSIC, 5, _detect_small_three_dragons),
    Pattern("大三元", HandSet.CLASSIC, 8, _detect_big_three_dragons),
    Pattern("小四喜", HandSet.CLASSIC, 6, _detect_small_four_winds),
    Pattern("大四喜", HandSet.CLASSIC, LIMIT_FAAN, _detect_big_four_winds, is_limit=True),
    Pattern("十八羅漢", HandSet.CLASSIC, LIMIT_FAAN, _detect_four_kongs, is_limit=True),
    Pattern("花么九", HandSet.CLASSIC, 4, _detect_mixed_terminals),
    Pattern("海底撈月", HandSet.NEW_6, 1, _detect_win_on_last_wall_tile),
    Pattern("槓上開花", HandSet.NEW_6, 1, _detect_win_on_kong_replacement),
    Pattern("搶槓", HandSet.NEW_6, 1, _detect_robbing_the_kong),
    Pattern("連槓開花", HandSet.NEW_6, 8, _detect_chained_kong_win),
    Pattern("正花", HandSet.CLASSIC, 1, _detect_seat_flower),
    Pattern("一台花", HandSet.CLASSIC, 2, _detect_flower_set),
    Pattern("字一色", HandSet.CLASSIC, LOW_LIMIT_FAAN, _detect_all_honors, is_limit=True),
    Pattern("清么九", HandSet.CLASSIC, LOW_LIMIT_FAAN, _detect_all_terminals, is_limit=True),
    Pattern("九蓮寶燈", HandSet.CLASSIC, LOW_LIMIT_FAAN, _detect_nine_gates, is_limit=True),
    Pattern("十三么", HandSet.CLASSIC, LIMIT_FAAN, _detect_thirteen_orphans, is_limit=True),
    Pattern("天糊", HandSet.CLASSIC, LIMIT_FAAN, _detect_heavenly_hand, is_limit=True),
    Pattern("地糊", HandSet.CLASSIC, LIMIT_FAAN, _detect_earthly_hand, is_limit=True),
    Pattern("四暗刻", HandSet.CLASSIC, 8, _detect_four_concealed_pungs),
    Pattern("七對子", HandSet.NEW_18, 4, _detect_seven_pairs),
)


_SUPERSEDES: dict[str, frozenset[str]] = {
    "小三元": frozenset({"箭刻"}),
    "大三元": frozenset({"箭刻"}),
    "四暗刻": frozenset({"對對糊", "門前清"}),
    "花么九": frozenset({"對對糊"}),
    "連槓開花": frozenset({"槓上開花", "自摸"}),
}
"""Patterns whose faan already includes the listed ones, so those are dropped when both match
-- real tables quote 小三元 5 and 大三元 8 as totals, not on top of 箭刻."""


def apply_supersedes(result: dict[str, int]) -> dict[str, int]:
    """`result` minus every pattern an also-present pattern's inclusive total already covers."""
    out = dict(result)
    for name, superseded in _SUPERSEDES.items():
        if name in result:
            for gone in superseded:
                out.pop(gone, None)
    return out


def score_hand(
    hand: tuple[Meld, ...], context: ScoringContext, *, supersede: bool = True
) -> dict[str, int]:
    """Run every registered pattern against one candidate `hand`, returning
    `{pattern_name: faan_awarded}` for patterns that matched. Faan simply sums here with no
    cap and no `hand_sets`/`faan_overrides` filtering -- stacking-with-caps, the `min_faan`
    gate, and maximising across every decomposition candidate are faan.py's job.
    """
    result: dict[str, int] = {}
    for pattern in PATTERNS:
        occurrences = pattern.detect(hand, context)
        if occurrences:
            result[pattern.name] = occurrences * pattern.faan
    return apply_supersedes(result) if supersede else result
