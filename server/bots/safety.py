"""Defence/safety model for T2 `FaanBot` (docs/04-bots.md §5) -- read that section before
touching this module.

Hand-tuned, not trained: a logistic-regression model needs a labelled self-play corpus that
doesn't exist yet (docs/06-ml.md §3). Weights are checked per-signal for *direction*
(`tests/test_safety.py`), not calibrated accuracy. Training one is flagged as real follow-up
work, not silently skipped.

No `is_safe(tile) -> bool`: every signal is a multiplier into `deal_in_probability`, a float in
`[0, 1]` -- `no_chance` is the only hard zero. Genbutsu/suji only ever scale the estimate down,
never to exactly zero (HK has no furiten).
"""

from __future__ import annotations

from collections.abc import Sequence
from statistics import fmean

from app.views import SeatView
from bots.features import is_terminal_or_honor, seen34
from mahjong_core.tiles import TileId, TileType, tile_id_type

__all__ = [
    "deal_in_probability",
    "expected_cost",
    "is_genbutsu",
    "no_chance",
    "opponent_threat_level",
    "tile_risk",
]

_HONOR_START = 27
_RANKS_PER_SUIT = 9
_DRAGON_TYPES = frozenset(
    {int(TileType.DRAGON_RED), int(TileType.DRAGON_GREEN), int(TileType.DRAGON_WHITE)}
)

_BASE_RATE = 0.06
"""Flat prior P(deal-in) before any signal adjusts it -- not calibrated to a real rate (no
corpus yet); sized so multipliers stay in a believable 0-0.3 range without saturating."""

_ONE_CHANCE_FACTOR = 0.4
"""Soft half of one-chance/no-chance: exactly one copy left. Not a hard constraint (that's
`no_chance`), just a real reduction since only one hidden copy can support the wait."""

_GENBUTSU_FACTOR = 0.35
"""Weakest-guarantee, highest-volume signal -- largest reduction here short of `no_chance`,
never 0 (HK has no furiten)."""

_SUJI_FACTOR = 0.75
"""Smaller reduction than genbutsu -- suji's force in riichi comes entirely from furiten, which
HK doesn't have."""

_MELD_SUIT_DANGER = 1.4
"""2+ melds in one suit plausibly means Half/Full Flush -- same-suit tiles get a danger bump."""

_DRAGON_PUNG_DANGER = 1.5
"""A dragon pung on the table makes the next dragon expensive."""

_TEMPO_THREAT_FACTOR = 1.3
"""A middle-tile discard right after a terminal/honor string often marks a hand that just
reached tenpai."""

_WALL_PRESSURE_TIERS: tuple[tuple[int, float], ...] = ((20, 1.5), (40, 1.2))
"""`(remaining_at_or_below, multiplier)`, checked in order; falls through to 1.0 with plenty of
wall left."""

_ASSUMED_DEALIN_FAAN = 5.0
"""Baseline assumed faan if this discard deals in -- arbitrary but documented (halfway between
min_faan=3 and a half-flush-plus-dragon hand), scaled by `_meld_danger_multiplier`. A relative
cost unit for ranking candidates, never a real point estimate."""


def no_chance(tile_type: int, seen: Sequence[int]) -> bool:
    """Hard-constraint half of one-chance/no-chance: every copy of `tile_type` is already
    accounted for, so no one can complete a wait needing it. Tile-count fact, not psychology --
    unlike every other signal here, allowed to force probability to exactly 0."""
    return seen[tile_type] >= 4


def is_genbutsu(view: SeatView, opponent_seat: int, tile_type: int) -> bool:
    """Whether `tile_type` sits in `opponent_seat`'s own discard pool -- weak evidence in HK,
    never a guarantee."""
    return any(int(tile_id_type(t)) == tile_type for t in view.discard_pools[opponent_seat])


def _is_suji(view: SeatView, opponent_seat: int, tile_type: int) -> bool:
    """`tile_type` is a suji of a tile `opponent_seat` already discarded (same suit, 3 ranks
    apart); honors are never suji."""
    if tile_type >= _HONOR_START:
        return False
    suit, rank = divmod(tile_type, _RANKS_PER_SUIT)
    for offset in (-3, 3):
        other_rank = rank + offset
        if 0 <= other_rank < _RANKS_PER_SUIT:
            other_type = suit * _RANKS_PER_SUIT + other_rank
            if is_genbutsu(view, opponent_seat, other_type):
                return True
    return False


def _opponent_suit_meld_counts(view: SeatView, opponent_seat: int) -> dict[int, int]:
    counts: dict[int, int] = {}
    for meld in view.melds[opponent_seat]:
        v = int(meld.tile_type)
        if v < _HONOR_START:
            counts[v // _RANKS_PER_SUIT] = counts.get(v // _RANKS_PER_SUIT, 0) + 1
    return counts


def _opponent_dragon_pung_count(view: SeatView, opponent_seat: int) -> int:
    return sum(1 for m in view.melds[opponent_seat] if int(m.tile_type) in _DRAGON_TYPES)


def _meld_danger_multiplier(view: SeatView, opponent_seat: int, tile_type: int) -> float:
    """Visible melds narrowing likely hand shape, applied as a multiplier on tiles that shape
    would want -- never standalone."""
    multiplier = 1.0
    if tile_type < _HONOR_START:
        suit = tile_type // _RANKS_PER_SUIT
        suit_melds = _opponent_suit_meld_counts(view, opponent_seat)
        if suit_melds.get(suit, 0) >= 2:
            multiplier *= _MELD_SUIT_DANGER
    if tile_type in _DRAGON_TYPES and _opponent_dragon_pung_count(view, opponent_seat) >= 1:
        multiplier *= _DRAGON_PUNG_DANGER
    return multiplier


def _tempo_multiplier(pool: Sequence[TileId]) -> float:
    """Sudden middle-tile discard after a terminal/honor string. Needs >= 3 prior discards to
    call a tempo change at all."""
    if len(pool) < 4:
        return 1.0
    *earlier, most_recent = pool
    earlier_terminal_ratio = fmean(is_terminal_or_honor(int(tile_id_type(t))) for t in earlier)
    recent_is_middle = not is_terminal_or_honor(int(tile_id_type(most_recent)))
    if recent_is_middle and earlier_terminal_ratio >= 0.7:
        return _TEMPO_THREAT_FACTOR
    return 1.0


def wall_pressure_multiplier(wall_remaining: int) -> float:
    for threshold, multiplier in _WALL_PRESSURE_TIERS:
        if wall_remaining <= threshold:
            return multiplier
    return 1.0


def deal_in_probability(view: SeatView, opponent_seat: int, tile_type: int) -> float:
    """`P(deal_in | tile)` against one opponent, all signals folded into one `[0, 1]` estimate
    (`no_chance` the only hard override). Genbutsu/suji are mutually exclusive -- suji only
    checked when genbutsu doesn't already apply, since genbutsu is the stronger read."""
    seen = seen34(view)
    if no_chance(tile_type, seen):
        return 0.0

    p = _BASE_RATE
    live = 4 - seen[tile_type]
    if live == 1:
        p *= _ONE_CHANCE_FACTOR

    if is_genbutsu(view, opponent_seat, tile_type):
        p *= _GENBUTSU_FACTOR
    elif _is_suji(view, opponent_seat, tile_type):
        p *= _SUJI_FACTOR

    p *= _meld_danger_multiplier(view, opponent_seat, tile_type)
    p *= _tempo_multiplier(view.discard_pools[opponent_seat])
    return min(p, 1.0)


def expected_cost(view: SeatView, opponent_seat: int, tile_type: int) -> float:
    """Assumed faan lost if this deals in -- a relative cost unit, scaled by meld reads and wall
    pressure (raises stakes, not probability)."""
    cost = _ASSUMED_DEALIN_FAAN
    cost *= _meld_danger_multiplier(view, opponent_seat, tile_type)
    cost *= wall_pressure_multiplier(view.wall_remaining)
    return cost


def tile_risk(view: SeatView, tile_type: int) -> float:
    """`P(deal_in) * expected_cost`, summed across opponents -- summing instead of the stricter
    `1 - prod(1-p_i)` is deliberate: at `_BASE_RATE`'s small magnitude they're nearly identical,
    and summing keeps each opponent's contribution separately testable."""
    if view.seat is None:
        raise ValueError("tile_risk needs a seated view, not a spectator's")
    total = 0.0
    for opponent in range(4):
        if opponent == view.seat:
            continue
        total += deal_in_probability(view, opponent, tile_type) * expected_cost(
            view, opponent, tile_type
        )
    return total


def opponent_threat_level(view: SeatView, opponent_seat: int) -> float:
    """Coarse "how worried should T2 be" score for `bots/faanbot.py`'s fold logic -- combines
    meld count and the tempo signal into a threshold-compared scalar, not a probability."""
    melds = len(view.melds[opponent_seat])
    tempo_bump = _tempo_multiplier(view.discard_pools[opponent_seat]) - 1.0
    return melds * 0.3 + tempo_bump
