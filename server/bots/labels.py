"""Ground-truth per-opponent danger labels from a live `GameState` (docs/ml.md §5's danger
model and §8's auxiliary heads -- exact, not estimated). `bots/arena.py`'s tenpai/winning-tile stats already computed most of this for its
own metrics; those helpers live here now and `arena.py` imports them back, rather than this
module reimplementing them.

Deliberately never touches `app.views._omniscient_seat_view` -- that function is structurally
pinned to exactly one call site (`tests/test_oracle_containment.py`'s AST sweep, which scans this
package). Labels come straight from `GameState`/`SeatState`, which self-play/arena code already
holds directly; there's no need for an omniscient `SeatView` detour to get them.
"""

from __future__ import annotations

from dataclasses import dataclass

from mahjong_core.actions import build_scoring_context, hand_is_winning_shape
from mahjong_core.config import HandSet
from mahjong_core.melds import Meld
from mahjong_core.scoring.faan import score_winning_hand
from mahjong_core.shanten import shanten
from mahjong_core.state import GameState, SeatState
from mahjong_core.tiles import TileId, TileType, new_count_array, tile_id_type, tile_ids_for_type

__all__ = [
    "OpponentDangerLabel",
    "danger_labels_for_opponents",
    "discard_counts34",
    "expected_faan_if_won",
    "is_tenpai",
    "meld_counts34",
    "seat_hand34",
    "unused_tile_id_for_type",
    "winning_tile_types",
]


def seat_hand34(seat_state: SeatState) -> list[int]:
    """34-array contract straight from `SeatState` -- no `SeatView` involved. A kong contributes
    3 tiles, matching `mahjong_core.shanten`'s convention."""
    counts = new_count_array()
    for t in seat_state.concealed:
        counts[int(tile_id_type(t))] += 1
    meld_counts = meld_counts34(seat_state.melds)
    for i in range(34):
        counts[i] += meld_counts[i]
    return counts


def meld_counts34(melds: tuple[Meld, ...]) -> list[int]:
    """34-count array from a public meld tuple alone (no concealed tiles) -- a kong contributes 3
    tiles, matching `mahjong_core.shanten`'s convention. Split out from `seat_hand34` so a caller
    that only has another seat's public melds (never their concealed tiles) can still get a
    count array without touching anything it isn't entitled to."""
    counts = new_count_array()
    for meld in melds:
        tiles = meld.tiles[:3] if meld.is_kong else meld.tiles
        for t in tiles:
            counts[int(tile_id_type(t))] += 1
    return counts


def discard_counts34(discards: tuple[TileId, ...]) -> list[int]:
    """34-count array from a discard pool -- always public."""
    counts = new_count_array()
    for t in discards:
        counts[int(tile_id_type(t))] += 1
    return counts


def winning_tile_types(
    hand34: list[int], *, closed: bool, hand_sets: frozenset[HandSet]
) -> list[int]:
    """Every tile type that would bring `hand34` (already tenpai) to agari, under `hand_sets`
    (docs/bots.md §8 -- a hand that's only tenpai via a shape `hand_sets` excludes, e.g. Seven
    Pairs under `hk_strict`, must not be reported as a real wait)."""
    out = []
    for t in range(34):
        if hand34[t] >= 4:
            continue
        candidate = list(hand34)
        candidate[t] += 1
        if shanten(candidate, closed=closed, hand_sets=hand_sets) == -1:
            out.append(t)
    return out


def _used_physical_ids(seat_state: SeatState) -> set[int]:
    used = {int(t) for t in seat_state.concealed}
    for meld in seat_state.melds:
        used.update(int(t) for t in meld.tiles)
    return used


def unused_tile_id_for_type(tile_type_value: int, seat_state: SeatState) -> TileId:
    """A real physical id of `tile_type_value` this seat doesn't already hold. Raises if all 4
    copies are already theirs -- never true for a type `winning_tile_types` reported, by
    construction (it skips `hand34[t] >= 4`); `expected_faan_if_won` checks itself before calling
    this for a type that hasn't been through that filter."""
    used = _used_physical_ids(seat_state)
    for tid in tile_ids_for_type(TileType(tile_type_value)):
        if int(tid) not in used:
            return tid
    raise AssertionError("no unused physical tile for a hypothetical win check")


def is_tenpai(state: GameState, seat: int) -> bool:
    """Whether `seat`'s real hand is one tile from a structurally-complete shape -- shanten==0,
    ruleset-aware (`hand_sets` gates Seven Pairs, docs/bots.md §8)."""
    seat_state = state.seats[seat]
    hand34 = seat_hand34(seat_state)
    closed = not seat_state.melds
    return shanten(hand34, closed=closed, hand_sets=state.ruleset.hand_sets) == 0


def expected_faan_if_won(state: GameState, seat: int, tile_type: int, *, discarder: int) -> float:
    """The real faan `seat` would score by winning on `tile_type` right now, or `0.0` if their
    real hand provably can't -- either not a complete shape, or a complete shape that doesn't
    clear `state.ruleset.min_faan` (a sub-minimum structural win is not a deal-in,
    docs/bots.md §4). Mirrors `bots/safety.py`'s `_exact_deal_in_faan` but reads straight from
    `GameState` instead of an omniscient `SeatView` -- see this module's docstring for why."""
    seat_state = state.seats[seat]
    if len({tile_type * 4 + offset for offset in range(4)} & _used_physical_ids(seat_state)) == 4:
        return 0.0  # all 4 physical copies already theirs -- a 5th can't exist
    tile_id = unused_tile_id_for_type(tile_type, seat_state)
    candidate = (*seat_state.concealed, tile_id)
    if not hand_is_winning_shape(SeatState(concealed=candidate, melds=seat_state.melds)):
        return 0.0
    ctx = build_scoring_context(state, seat, self_drawn=False, discarder=discarder)
    result = score_winning_hand(candidate, seat_state.melds, ctx, state.ruleset)
    return float(result.total_faan) if result.clears_min_faan else 0.0


@dataclass(frozen=True)
class OpponentDangerLabel:
    """Ground truth for one seat at one `GameState` snapshot -- docs/ml.md §5's three label
    heads: `P(tenpai)`, `P(wait on t)` per tile type, expected faan if dealt into."""

    is_tenpai: bool
    winning_tiles: tuple[int, ...]
    expected_faan_by_tile_type: tuple[float, ...]
    """Length 34, indexed by `TileType` value -- `0.0` for every non-winning type."""


def danger_labels_for_opponents(state: GameState, seat: int) -> dict[int, OpponentDangerLabel]:
    """`OpponentDangerLabel` for the three seats other than `seat`, as `seat` would compute them
    right before deciding what to discard (`discarder=seat`, matching how `bots/safety.py`'s
    `tile_risk` frames the same question at inference)."""
    labels: dict[int, OpponentDangerLabel] = {}
    for opponent in range(4):
        if opponent == seat:
            continue
        if not is_tenpai(state, opponent):
            labels[opponent] = OpponentDangerLabel(False, (), (0.0,) * 34)
            continue
        opponent_state = state.seats[opponent]
        hand34 = seat_hand34(opponent_state)
        closed = not opponent_state.melds
        winners = tuple(
            winning_tile_types(hand34, closed=closed, hand_sets=state.ruleset.hand_sets)
        )
        faan = tuple(
            expected_faan_if_won(state, opponent, t, discarder=seat) if t in winners else 0.0
            for t in range(34)
        )
        labels[opponent] = OpponentDangerLabel(True, winners, faan)
    return labels
