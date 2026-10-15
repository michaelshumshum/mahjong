"""`encode_seat_view(seat_view(state, seat))`, flattened, computed straight from `GameState` into a
preallocated buffer (docs/ml.md §7). Skips `seat_view`'s legal-action scan and the per-field
numpy round trips. `tests/test_ml_fast_encode.py` pins it bit-equal to the reference path: that
parity test is the leak guard, since this module reads `GameState` directly.

Reads, per seat, exactly what `SeatView` exposes: own concealed tiles, every seat's melds
(`ml.raw.visible_meld_counts34`), discards, concealed counts.
"""

from __future__ import annotations

import numpy as np

from app.views import seat_view
from mahjong_core.config import RuleSet
from mahjong_core.state import GameState, Phase
from mahjong_core.tiles import COPIES_PER_TYPE, N_TILE_TYPES
from ml.encode import (
    N_RULESET_FEATURES,
    N_THERMOMETER,
    PHASE_INDEX,
    encode_ruleset,
    encode_seat_view,
)

__all__ = ["OBS_DIM", "encode_reference", "encode_state"]

_N_ROWS = 1 + 4 + 4  # own hand, 4 seats' melds, 4 seats' discards
_N_TILE_PLANES = _N_ROWS * N_THERMOMETER * N_TILE_TYPES
_OFF_CONCEALED = _N_TILE_PLANES
_OFF_CONTEXT = _OFF_CONCEALED + 4
_N_CONTEXT = 4 + 4 + 4 + 4 + len(Phase)
_OFF_WALL = _OFF_CONTEXT + _N_CONTEXT
_OFF_RULESET = _OFF_WALL + 1
OBS_DIM = _OFF_RULESET + N_RULESET_FEATURES

_LEVELS = np.arange(N_THERMOMETER).reshape(1, N_THERMOMETER, 1)
_ruleset_cache: tuple[RuleSet | None, np.ndarray | None] = (None, None)


def _ruleset_vec(ruleset: RuleSet) -> np.ndarray:
    global _ruleset_cache
    cached, vec = _ruleset_cache
    if cached is not ruleset or vec is None:
        vec = encode_ruleset(ruleset)
        _ruleset_cache = (ruleset, vec)
    return vec


def encode_state(state: GameState, seat: int, out: np.ndarray | None = None) -> np.ndarray:
    if out is None:
        out = np.empty(OBS_DIM, dtype=np.float32)
    seats = state.seats
    idx: list[int] = []
    own = seats[seat]
    for t in own.concealed:
        idx.append(t // COPIES_PER_TYPE)
    for rel in range(4):
        abs_seat = (seat + rel) % 4
        s = seats[abs_seat]
        meld_base = (1 + rel) * N_TILE_TYPES
        own_melds = abs_seat == seat
        for meld in s.melds:
            tiles = meld.tiles[:3] if meld.is_kong else meld.tiles
            for t in tiles:
                idx.append(meld_base + t // COPIES_PER_TYPE)
                if own_melds:
                    idx.append(t // COPIES_PER_TYPE)
        disc_base = (5 + rel) * N_TILE_TYPES
        for t in s.discards:
            idx.append(disc_base + t // COPIES_PER_TYPE)
        out[_OFF_CONCEALED + rel] = len(s.concealed)

    counts = np.bincount(idx, minlength=_N_ROWS * N_TILE_TYPES).reshape(_N_ROWS, 1, N_TILE_TYPES)
    out[:_N_TILE_PLANES] = (counts > _LEVELS).ravel()

    ctx = out[_OFF_CONTEXT:_OFF_WALL]
    ctx[:] = 0.0
    ctx[(state.turn - seat) % 4] = 1.0
    ctx[4 + (state.dealer - seat) % 4] = 1.0
    ctx[8 + int(state.prevailing)] = 1.0
    ctx[12 + (seat - state.dealer) % 4] = 1.0
    ctx[16 + PHASE_INDEX[state.phase]] = 1.0
    out[_OFF_WALL] = len(state.wall.tiles)
    out[_OFF_RULESET:] = _ruleset_vec(state.ruleset)
    return out


def encode_reference(state: GameState, seat: int, out: np.ndarray | None = None) -> np.ndarray:
    """The parity target: `encode_seat_view(seat_view(state, seat))` flattened."""
    enc = encode_seat_view(seat_view(state, seat))
    parts = (
        enc.hand,
        enc.melds,
        enc.discards,
        enc.concealed_counts,
        enc.context,
        enc.wall_remaining,
        enc.ruleset,
    )
    if out is None:
        out = np.empty(OBS_DIM, dtype=np.float32)
    i = 0
    for p in parts:
        n = p.size
        out[i : i + n] = p.ravel()
        i += n
    assert i == OBS_DIM
    return out
