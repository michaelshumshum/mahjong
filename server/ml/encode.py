"""`SeatView` + `RuleSet` -> fixed-shape numpy feature planes for a network (docs/06-ml.md §6.2,
docs/99-deferred.md "Feature-plane encoding"). `ml`-extra only -- numpy is not a base dependency
(server/AGENTS.md: "mahjong_core is stdlib-only... no numpy, no torch in base deps"), so nothing
outside `server/ml/` may import this module.

Reads only entitled `SeatView` fields -- own_hand, melds, discard_pools, concealed_counts
(app/views.py's `Entitlement` contract) -- the same fields a live, non-oracle bot or client
actually receives. `view.hands` (the `"ORACLE"` tier's omniscient extra, docs/04-bots.md §10) is
deliberately never read here: a network trained on oracle-only input wouldn't generalize to the
redacted view it's served at inference.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.views import SeatView
from bots.features import own_hand34
from mahjong_core.config import HandSet, RuleSet
from mahjong_core.scoring.patterns import PATTERNS, seat_wind_for
from mahjong_core.state import Phase
from mahjong_core.tiles import new_count_array, tile_id_type
from ml.raw import visible_meld_counts34

__all__ = [
    "N_PATTERNS",
    "N_RULESET_FEATURES",
    "N_THERMOMETER",
    "N_TILE_TYPES",
    "EncodedSeatView",
    "encode_ruleset",
    "encode_seat_view",
]

N_TILE_TYPES = 34
N_THERMOMETER = 4  # tile count 1..4 -> four "count > k" planes (Suphx/Mortal convention)
_HAND_SETS = (HandSet.CLASSIC, HandSet.NEW_6, HandSet.NEW_18)
N_PATTERNS = len(PATTERNS)
_PHASES = tuple(Phase)
# min_faan, wall_reserve (2 scalars) + hand_sets bitmask + one effective-faan slot per pattern
N_RULESET_FEATURES = 2 + len(_HAND_SETS) + N_PATTERNS


def _relative_seats(seat: int) -> tuple[int, int, int, int]:
    """(self, next, across, previous) as absolute seat indices, so a view's own encoding always
    puts itself at relative position 0 regardless of which physical seat it sits in."""
    return (seat, (seat + 1) % 4, (seat + 2) % 4, (seat + 3) % 4)


def _thermometer(counts: list[int]) -> np.ndarray:
    """(N_THERMOMETER, 34): plane k is 1.0 wherever a tile type's count is > k."""
    arr = np.asarray(counts, dtype=np.float32)
    return np.stack([(arr > k).astype(np.float32) for k in range(N_THERMOMETER)])


def _discard_counts(pool: tuple[int, ...]) -> list[int]:
    counts = new_count_array()
    for t in pool:
        counts[int(tile_id_type(t))] += 1
    return counts


def _one_hot(index: int, size: int) -> np.ndarray:
    v = np.zeros(size, dtype=np.float32)
    v[index] = 1.0
    return v


@dataclass(frozen=True)
class EncodedSeatView:
    """Fixed-shape arrays for one `SeatView`; every per-seat axis is in relative-seat order
    (index 0 = this view's own seat, per `_relative_seats`).

    hand:              (N_THERMOMETER, 34) -- this seat's own concealed+meld tiles. The only
                        seat this view is ever entitled to full tile identities for.
    melds:              (4, N_THERMOMETER, 34) -- public exposed melds, per relative seat.
    discards:           (4, N_THERMOMETER, 34) -- public discard pools, per relative seat.
    concealed_counts:   (4,) -- `SeatView.concealed_counts`, reordered to relative seats.
    context:            (4 + 4 + 4 + 4 + 7,) -- turn / dealer / prevailing-wind / own-seat-wind /
                        phase, each a one-hot block, concatenated in that order.
    wall_remaining:     (1,) -- `SeatView.wall_remaining`, tiles left in the live wall.
    ruleset:            (N_RULESET_FEATURES,) -- see `encode_ruleset`.
    """

    hand: np.ndarray
    melds: np.ndarray
    discards: np.ndarray
    concealed_counts: np.ndarray
    context: np.ndarray
    wall_remaining: np.ndarray
    ruleset: np.ndarray


def encode_seat_view(view: SeatView) -> EncodedSeatView:
    if view.seat is None:
        raise ValueError("encode_seat_view needs a seated view, not a spectator's")
    order = _relative_seats(view.seat)

    hand = _thermometer(own_hand34(view))
    melds = np.stack([_thermometer(visible_meld_counts34(view, s)) for s in order])
    discards = np.stack([_thermometer(_discard_counts(view.discard_pools[s])) for s in order])
    concealed_counts = np.asarray([view.concealed_counts[s] for s in order], dtype=np.float32)

    context = np.concatenate(
        [
            _one_hot(order.index(view.turn), 4),
            _one_hot(order.index(view.dealer), 4),
            _one_hot(int(view.prevailing), 4),
            _one_hot(int(seat_wind_for(view.seat, view.dealer)), 4),
            _one_hot(_PHASES.index(view.phase), len(_PHASES)),
        ]
    )
    wall_remaining = np.asarray([view.wall_remaining], dtype=np.float32)

    return EncodedSeatView(
        hand=hand,
        melds=melds,
        discards=discards,
        concealed_counts=concealed_counts,
        context=context,
        wall_remaining=wall_remaining,
        ruleset=encode_ruleset(view.ruleset),
    )


def encode_ruleset(ruleset: RuleSet) -> np.ndarray:
    """The `RuleSet` fields that change correct play (docs/06-ml.md §6.2,
    docs/99-deferred.md "Feature-plane encoding") -- not the full `RuleSet.to_dict()`. Timing/
    connection/fairness fields (`turn_seconds`, `provable_fairness`, etc.) have no bearing on
    hand-value decisions and are deliberately not encoded.

    Layout: [min_faan, wall_reserve, *hand_sets bitmask (CLASSIC, NEW_6, NEW_18),
    *effective faan for every `PATTERNS` entry in registry order -- `faan_overrides[name]` if
    that pattern is overridden, else the pattern's own base `faan`].
    """
    scalars = np.asarray([ruleset.min_faan, ruleset.wall_reserve], dtype=np.float32)
    hand_sets = np.asarray(
        [1.0 if hs in ruleset.hand_sets else 0.0 for hs in _HAND_SETS], dtype=np.float32
    )
    effective_faan = np.asarray(
        [ruleset.faan_overrides.get(p.name, p.faan) for p in PATTERNS], dtype=np.float32
    )
    return np.concatenate([scalars, hand_sets, effective_faan])
