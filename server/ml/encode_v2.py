"""Encoder v2 for the RL policy (docs/ml.md §8): policy input and, kept separate, oracle input.

Two stages. A *raw* row is a dict of small uint8 arrays (counts, discard order, context). It is
built either straight from `GameState` (`policy_raw`, the fast path) or from
`seat_view(state, seat)` (`policy_raw_from_view`, the reference); `tests/test_ml_encode_v2.py`
pins the two equal on every state and seat it sweeps, which is the leak guard.
`encode_policy_batch` then turns stacked raw rows into network tensors, so datasets store raw
rows and the encoding stays a training-time choice (§5).

Oracle rows (`oracle_raw`) read hidden state on purpose: opponents' concealed tiles and
concealed-kong types, wall composition, the next draws. They only ever feed `encode_oracle_batch`,
never the policy tensors.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from app.views import SeatView
from mahjong_core.config import RuleSet
from mahjong_core.scoring.patterns import seat_wind_for
from mahjong_core.state import GameState, Phase
from mahjong_core.tiles import Flower, TileType, tile_id_type
from ml.encode import (
    N_RULESET_FEATURES,
    N_THERMOMETER,
    N_TILE_TYPES,
    _min_age,
    _static_tile_channels,
    encode_ruleset,
)
from ml.raw import concealed_kong_counts, visible_meld_counts34

__all__ = [
    "MAX_DISCARDS",
    "N_ORACLE_CHANNELS",
    "N_POLICY_CHANNELS",
    "N_POLICY_SCALARS",
    "ORACLE_CHANNELS",
    "ORACLE_FIELDS",
    "ORACLE_MAX_DRAWS",
    "PAD",
    "POLICY_CHANNELS",
    "POLICY_FIELDS",
    "encode_oracle",
    "encode_oracle_batch",
    "encode_policy",
    "encode_policy_batch",
    "oracle_raw",
    "policy_raw",
    "policy_raw_from_view",
    "ruleset_features",
    "stack_rows",
]

PAD = 255
MAX_DISCARDS = 32
ORACLE_MAX_DRAWS = 13
_PHASES = tuple(Phase)
_COPIES = 4
_RECENCY = ((1, 2), (3, 5), (6, 10**6))  # age 0 is the last-discard plane

POLICY_FIELDS: dict[str, tuple[int, ...]] = {
    "concealed": (N_TILE_TYPES,),
    "melds": (4, N_TILE_TYPES),
    "discard_seq": (4, MAX_DISCARDS),
    "concealed_counts": (4,),
    "concealed_kongs": (4,),
    "flowers": (4,),
    "own_flowers": (8,),
    "seat_wind": (),
    "dealer": (),
    "prevailing": (),
    "turn": (),
    "phase": (),
    "wall_remaining": (),
    "claim_tile": (),
}
ORACLE_FIELDS: dict[str, tuple[int, ...]] = {
    "opp_concealed": (3, N_TILE_TYPES),
    "opp_concealed_kongs": (3, N_TILE_TYPES),
    "wall_counts": (N_TILE_TYPES,),
    "next_draws": (ORACLE_MAX_DRAWS,),
}

_POLICY_LAYOUT = (
    ("hand", N_THERMOMETER),  # own concealed + own melds, as encode_seat_view's `hand`
    ("melds", 4 * N_THERMOMETER),
    ("discards", 4 * N_THERMOMETER),
    ("last_discard", 4),
    ("recency", 4 * len(_RECENCY)),
    ("claimable", 1),
    ("suji", 3),
    ("unseen", 1),
    ("static", 6),
    ("markers", 3),  # dragons, prevailing wind, own seat wind
    ("concealed", N_THERMOMETER),
)
_ORACLE_LAYOUT = (
    ("opp_concealed", 3 * N_THERMOMETER),
    ("opp_concealed_kongs", 3),
    ("wall", N_THERMOMETER),
    ("next_draws", ORACLE_MAX_DRAWS),
)


def _slices(layout: tuple[tuple[str, int], ...]) -> dict[str, slice]:
    out, at = {}, 0
    for name, n in layout:
        out[name] = slice(at, at + n)
        at += n
    return out


POLICY_CHANNELS = _slices(_POLICY_LAYOUT)
ORACLE_CHANNELS = _slices(_ORACLE_LAYOUT)
N_POLICY_CHANNELS = sum(n for _, n in _POLICY_LAYOUT)
N_ORACLE_CHANNELS = sum(n for _, n in _ORACLE_LAYOUT)
# concealed(4) turn(4) dealer(4) prevailing(4) seat wind(4) phase(7) wall(1) flowers(4)
# concealed kongs(4) own seat flowers / flower set / season set(3) + ruleset
N_POLICY_SCALARS = 4 + 4 + 4 + 4 + 4 + len(_PHASES) + 1 + 4 + 4 + 3 + N_RULESET_FEATURES

_PHASE_INDEX = {p: i for i, p in enumerate(_PHASES)}
_STATIC = _static_tile_channels()
_RANK = np.array([t % 9 if t < 27 else -1 for t in range(N_TILE_TYPES)])
_HAS_LOWER = _RANK >= 3
_HAS_UPPER = (_RANK >= 0) & (_RANK <= 5)
_LEVELS = np.arange(N_THERMOMETER)[:, None]
_EYE35 = np.eye(N_TILE_TYPES + 1, dtype=np.int64)[:, :N_TILE_TYPES]
_EYE4 = np.eye(4, dtype=np.float32)
_EYE_PHASE = np.eye(len(_PHASES), dtype=np.float32)
_DRAGONS = (np.arange(N_TILE_TYPES) >= int(TileType.DRAGON_RED)).astype(np.float32)
_ruleset_cache: tuple[RuleSet | None, np.ndarray | None] = (None, None)


def ruleset_features(ruleset: RuleSet) -> np.ndarray:
    """`encode_ruleset`, scaled as `encode_batch` scales it."""
    global _ruleset_cache
    cached, vec = _ruleset_cache
    if cached is not ruleset or vec is None:
        vec = encode_ruleset(ruleset)
        vec[0] /= 10.0
        vec[1] /= 100.0
        vec[5:] /= 10.0
        _ruleset_cache = (ruleset, vec)
    return vec


def _seq_row(types: Sequence[int]) -> list[int]:
    if len(types) > MAX_DISCARDS:
        raise ValueError(f"discard pool of {len(types)} exceeds MAX_DISCARDS={MAX_DISCARDS}")
    return [*types, *([PAD] * (MAX_DISCARDS - len(types)))]


def _flower_hot(flowers: Sequence[Flower]) -> list[int]:
    row = [0] * 8
    for f in flowers:
        row[int(f)] = 1
    return row


def _finish(d: dict[str, object]) -> dict[str, np.ndarray]:
    return {k: np.asarray(d[k], dtype=np.uint8) for k in POLICY_FIELDS}


def policy_raw(state: GameState, seat: int) -> dict[str, np.ndarray]:
    """`seat`'s raw policy row read straight from `GameState`: only what `SeatView` exposes."""
    seats = state.seats
    concealed = [0] * N_TILE_TYPES
    for t in seats[seat].concealed:
        concealed[t // _COPIES] += 1
    melds, seqs, counts, kongs, flowers = [], [], [], [], []
    for rel in range(4):
        s = seats[(seat + rel) % 4]
        row = [0] * N_TILE_TYPES
        n_kongs = 0
        for meld in s.melds:
            if meld.concealed:
                n_kongs += 1
            for t in meld.tiles[:3] if meld.is_kong else meld.tiles:
                row[t // _COPIES] += 1
        melds.append(row)
        seqs.append(_seq_row([t // _COPIES for t in s.discards]))
        counts.append(len(s.concealed))
        kongs.append(n_kongs)
        flowers.append(len(s.flowers))
    window = state.claim_window
    claim = PAD
    if window is not None and any(o.seat == seat for o in window.offers):
        claim = window.tile // _COPIES
    return _finish(
        {
            "concealed": concealed,
            "melds": melds,
            "discard_seq": seqs,
            "concealed_counts": counts,
            "concealed_kongs": kongs,
            "flowers": flowers,
            "own_flowers": _flower_hot(seats[seat].flowers),
            "seat_wind": (seat - state.dealer) % 4,
            "dealer": (state.dealer - seat) % 4,
            "prevailing": int(state.prevailing),
            "turn": (state.turn - seat) % 4,
            "phase": _PHASE_INDEX[state.phase],
            "wall_remaining": len(state.wall.tiles),
            "claim_tile": claim,
        }
    )


def policy_raw_from_view(view: SeatView) -> dict[str, np.ndarray]:
    """The parity reference: the same row built only from a `SeatView`."""
    if view.seat is None:
        raise ValueError("policy_raw_from_view needs a seated view, not a spectator's")
    seat = view.seat
    order = [(seat + rel) % 4 for rel in range(4)]
    concealed = [0] * N_TILE_TYPES
    for t in view.own_hand:
        concealed[int(tile_id_type(t))] += 1
    kongs = concealed_kong_counts(view)
    claim = PAD
    if view.claim_options:
        if view.phase == Phase.AWAIT_KONG_ROB:
            claim = int(view.melds[view.turn][-1].tile_type)
        else:
            claim = int(tile_id_type(view.discard_pools[view.turn][-1]))
    return _finish(
        {
            "concealed": concealed,
            "melds": [visible_meld_counts34(view, s) for s in order],
            "discard_seq": [
                _seq_row([int(tile_id_type(t)) for t in view.discard_pools[s]]) for s in order
            ],
            "concealed_counts": [view.concealed_counts[s] for s in order],
            "concealed_kongs": [kongs[s] for s in order],
            "flowers": [len(view.flowers[s]) for s in order],
            "own_flowers": _flower_hot(view.flowers[seat]),
            "seat_wind": int(seat_wind_for(seat, view.dealer)),
            "dealer": order.index(view.dealer),
            "prevailing": int(view.prevailing),
            "turn": order.index(view.turn),
            "phase": _PHASE_INDEX[view.phase],
            "wall_remaining": view.wall_remaining,
            "claim_tile": claim,
        }
    )


def oracle_raw(state: GameState, seat: int) -> dict[str, np.ndarray]:
    """Hidden information relative to `seat`, opponents in relative order (next, across,
    previous). Next draws are the front of the live wall; a flower there is `PAD`."""
    opp_concealed, opp_kongs = [], []
    for rel in (1, 2, 3):
        s = state.seats[(seat + rel) % 4]
        row = [0] * N_TILE_TYPES
        for t in s.concealed:
            row[t // _COPIES] += 1
        opp_concealed.append(row)
        krow = [0] * N_TILE_TYPES
        for meld in s.melds:
            if meld.concealed:
                krow[int(meld.tile_type)] += 1
        opp_kongs.append(krow)
    wall = [0] * N_TILE_TYPES
    tiles = state.wall.tiles
    for t in tiles:
        if not isinstance(t, Flower):
            wall[t // _COPIES] += 1
    draws = [PAD] * ORACLE_MAX_DRAWS
    for i, t in enumerate(tiles[:ORACLE_MAX_DRAWS]):
        if not isinstance(t, Flower):
            draws[i] = t // _COPIES
    return {
        "opp_concealed": np.asarray(opp_concealed, dtype=np.uint8),
        "opp_concealed_kongs": np.asarray(opp_kongs, dtype=np.uint8),
        "wall_counts": np.asarray(wall, dtype=np.uint8),
        "next_draws": np.asarray(draws, dtype=np.uint8),
    }


def stack_rows(rows: Sequence[dict[str, np.ndarray]]) -> dict[str, np.ndarray]:
    return {k: np.stack([r[k] for r in rows]) for k in rows[0]}


def _thermo(counts: np.ndarray) -> np.ndarray:
    """(..., 34) counts -> (..., N_THERMOMETER, 34), plane k lit where count > k."""
    return (counts[..., None, :] > _LEVELS).astype(np.float32)


def _one_hot_tiles(tile: np.ndarray) -> np.ndarray:
    """(...,) tile types, `PAD` for none -> (..., 34)."""
    return _EYE35[np.minimum(tile.astype(np.int64), N_TILE_TYPES)].astype(np.float32)


def encode_policy_batch(
    raw: dict[str, np.ndarray], ruleset_vec: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Stacked policy rows -> `tiles (B, N_POLICY_CHANNELS, 34)`, `scalars (B, N_POLICY_SCALARS)`.
    `ruleset_vec` is `ruleset_features(...)`, `(R,)` or `(B, R)`."""
    conc = raw["concealed"].astype(np.int64)
    b = len(conc)
    melds = raw["melds"].astype(np.int64)
    seq = raw["discard_seq"]
    seq_i = np.minimum(seq.astype(np.int64), N_TILE_TYPES)
    disc = _EYE35[seq_i].sum(axis=2)  # (B, 4, 34)
    hand = conc + melds[:, 0]

    n = (seq != PAD).sum(axis=2)
    last = np.take_along_axis(seq_i, np.maximum(n - 1, 0)[..., None], axis=2)[..., 0]
    last = np.where(n > 0, last, N_TILE_TYPES)
    ages = _min_age(seq.reshape(b * 4, -1)).reshape(b, 4, N_TILE_TYPES)
    recency = np.stack([(ages >= lo) & (ages <= hi) for lo, hi in _RECENCY], axis=2)

    discarded = disc[:, 1:] > 0
    down = np.zeros_like(discarded)
    down[..., 3:] = discarded[..., :-3]
    up = np.zeros_like(discarded)
    up[..., :-3] = discarded[..., 3:]
    suji = (_HAS_LOWER | _HAS_UPPER) & (~_HAS_LOWER | down) & (~_HAS_UPPER | up)

    seen = hand + melds[:, 1:].sum(axis=1) + disc.sum(axis=1)
    unseen = np.clip(4 - seen, 0, 4) / 4.0

    seat_wind = raw["seat_wind"].astype(np.int64)
    prevailing = raw["prevailing"].astype(np.int64)
    markers = np.stack(
        [
            np.broadcast_to(_DRAGONS, (b, N_TILE_TYPES)),
            _one_hot_tiles(int(TileType.WIND_EAST) + prevailing),
            _one_hot_tiles(int(TileType.WIND_EAST) + seat_wind),
        ],
        axis=1,
    )
    tiles = np.concatenate(
        [
            _thermo(hand),
            _thermo(melds).reshape(b, -1, N_TILE_TYPES),
            _thermo(disc).reshape(b, -1, N_TILE_TYPES),
            _EYE35[last].astype(np.float32),
            recency.reshape(b, -1, N_TILE_TYPES).astype(np.float32),
            _one_hot_tiles(raw["claim_tile"])[:, None],
            suji.astype(np.float32),
            unseen[:, None].astype(np.float32),
            np.broadcast_to(_STATIC, (b, *_STATIC.shape)),
            markers,
            _thermo(conc),
        ],
        axis=1,
    )

    own = raw["own_flowers"].astype(np.float32)
    seat_flowers = np.take_along_axis(own, seat_wind[:, None], 1) + np.take_along_axis(
        own, seat_wind[:, None] + 4, 1
    )
    ruleset = np.broadcast_to(np.asarray(ruleset_vec, dtype=np.float32), (b, N_RULESET_FEATURES))
    scalars = np.concatenate(
        [
            raw["concealed_counts"] / 13.0,
            _EYE4[raw["turn"]],
            _EYE4[raw["dealer"]],
            _EYE4[prevailing],
            _EYE4[seat_wind],
            _EYE_PHASE[raw["phase"]],
            raw["wall_remaining"][:, None] / 100.0,
            raw["flowers"] / 8.0,
            raw["concealed_kongs"] / 4.0,
            seat_flowers / 2.0,
            own[:, :4].sum(1, keepdims=True) / 4.0,
            own[:, 4:].sum(1, keepdims=True) / 4.0,
            ruleset,
        ],
        axis=1,
    ).astype(np.float32)
    return tiles, scalars


def encode_oracle_batch(oracle: dict[str, np.ndarray], k: int = ORACLE_MAX_DRAWS) -> np.ndarray:
    """Stacked oracle rows -> `(B, N_ORACLE_CHANNELS, 34)`. Draw planes `k..` are zero, so the
    layout is fixed while the curriculum anneals `k` (§10)."""
    if not 0 <= k <= ORACLE_MAX_DRAWS:
        raise ValueError(f"k must be in 0..{ORACLE_MAX_DRAWS}, got {k}")
    opp = oracle["opp_concealed"].astype(np.int64)
    b = len(opp)
    draws = _one_hot_tiles(oracle["next_draws"])
    draws[:, k:] = 0.0
    return np.concatenate(
        [
            _thermo(opp).reshape(b, -1, N_TILE_TYPES),
            (oracle["opp_concealed_kongs"] > 0).astype(np.float32),
            _thermo(oracle["wall_counts"].astype(np.int64)),
            draws,
        ],
        axis=1,
    )


def encode_policy(state: GameState, seat: int) -> tuple[np.ndarray, np.ndarray]:
    """One sample: `tiles (N_POLICY_CHANNELS, 34)`, `scalars (N_POLICY_SCALARS,)`."""
    row = policy_raw(state, seat)
    tiles, scalars = encode_policy_batch(
        {k: v[None] for k, v in row.items()}, ruleset_features(state.ruleset)
    )
    return tiles[0], scalars[0]


def encode_oracle(state: GameState, seat: int, k: int = ORACLE_MAX_DRAWS) -> np.ndarray:
    row = oracle_raw(state, seat)
    return encode_oracle_batch({key: v[None] for key, v in row.items()}, k)[0]
