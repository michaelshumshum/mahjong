"""Score a hand built outside a game: the faan guide's hand checker (`POST /score`,
docs/protocol.md §10).

The hand is complete at 14 tiles, with no kongs; the last tile is the winning tile. Only the
context a player can set by hand is taken: self-draw vs discard, fully concealed or not, seat
and prevailing wind, flowers. Win-timing patterns (海底撈月, 槓上開花, 天糊, ...) never score
here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from mahjong_core.actions import _is_winning_shape
from mahjong_core.config import RuleSet
from mahjong_core.melds import MeldKind, decompose
from mahjong_core.scoring.faan import FaanResult, score_winning_hand, seven_pairs_enabled
from mahjong_core.scoring.patterns import ScoringContext
from mahjong_core.scoring.payout import points
from mahjong_core.state import Wind
from mahjong_core.tiles import COPIES_PER_TYPE, Flower, TileId, TileType, tile_ids_for_type

HAND_SIZE = 14

# any other seat: scoring reads only whether a meld was claimed, never from whom
_CLAIMED_FROM = 1


@dataclass(frozen=True)
class HandCheck:
    """`winning` is the structural shape check; `result`/`points` are `None` when it fails."""

    winning: bool
    result: FaanResult | None
    points: int | None


def _tile_ids(tiles: Sequence[TileType]) -> list[TileId]:
    used: dict[TileType, int] = {}
    ids = []
    for tile in tiles:
        n = used.get(tile, 0)
        if n >= COPIES_PER_TYPE:
            raise ValueError(f"more than {COPIES_PER_TYPE} copies of {tile.name}")
        used[tile] = n + 1
        ids.append(tile_ids_for_type(tile)[n])
    return ids


def _score_with_one_claimed(
    concealed: list[TileId], ctx: ScoringContext, ruleset: RuleSet
) -> FaanResult:
    """Best score with one set claimed from another seat: which set isn't given, so every one
    but the winning tile's is tried, as `score_winning_hand` maximises over decompositions."""
    best: FaanResult | None = None
    for split in decompose(concealed):
        for meld in split:
            if meld.kind == MeldKind.PAIR or ctx.winning_tile in meld.tiles:
                continue
            rest = [t for t in concealed if t not in meld.tiles]
            claimed = replace(meld, from_seat=_CLAIMED_FROM)
            result = score_winning_hand(rest, (claimed,), ctx, ruleset)
            if best is None or result.total_faan > best.total_faan:
                best = result
    assert best is not None, "a standard shape always decomposes into four sets and a pair"
    return best


def check_hand(
    tiles: Sequence[TileType],
    flowers: Sequence[Flower],
    *,
    self_drawn: bool,
    seat_wind: Wind,
    prevailing_wind: Wind,
    ruleset: RuleSet,
    fully_concealed: bool = True,
) -> HandCheck:
    """`fully_concealed=False` takes one set as claimed, so only a standard shape can win.
    Raises `ValueError` on a hand no real deal could produce: not 14 tiles, a fifth copy, or a
    repeated flower."""
    if len(tiles) != HAND_SIZE:
        raise ValueError(f"a hand to check is {HAND_SIZE} tiles, got {len(tiles)}")
    if len(set(flowers)) != len(flowers):
        raise ValueError("each flower is a single tile")
    concealed = _tile_ids(tiles)
    if not _is_winning_shape(
        concealed, closed=fully_concealed, seven_pairs=seven_pairs_enabled(ruleset)
    ):
        return HandCheck(winning=False, result=None, points=None)
    ctx = ScoringContext(
        seat_wind=seat_wind,
        prevailing_wind=prevailing_wind,
        self_drawn=self_drawn,
        # no flower tiles are dealt with flowers off, so 無花 always scores, as in a real game
        flowers=tuple(flowers) if ruleset.flowers_enabled else (),
        flowers_score=ruleset.flowers_score,
        winning_tile=concealed[-1],
    )
    result = (
        score_winning_hand(concealed, (), ctx, ruleset)
        if fully_concealed
        else _score_with_one_claimed(concealed, ctx, ruleset)
    )
    return HandCheck(winning=True, result=result, points=points(result.total_faan, ruleset))
