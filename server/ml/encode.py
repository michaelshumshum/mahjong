"""`SeatView` + `RuleSet` -> fixed-shape numpy feature planes for a network (docs/06-ml.md §5). `ml`-extra only -- numpy is not a base dependency
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
from mahjong_core.tiles import TileType, new_count_array, tile_id_type
from ml.raw import visible_meld_counts34

__all__ = [
    "N_PATTERNS",
    "N_RULESET_FEATURES",
    "N_SCALARS",
    "N_THERMOMETER",
    "N_TILE_CHANNELS",
    "N_TILE_TYPES",
    "EncodedSeatView",
    "encode_batch",
    "encode_ruleset",
    "encode_seat_view",
    "rows_to_arrays",
]

N_TILE_TYPES = 34
N_THERMOMETER = 4  # tile count 1..4 -> four "count > k" planes (Suphx/Mortal convention)
_HAND_SETS = (HandSet.CLASSIC, HandSet.NEW_6, HandSet.NEW_18)
N_PATTERNS = len(PATTERNS)
_PHASES = tuple(Phase)
# min_faan, wall_reserve (2 scalars) + hand_sets bitmask + one effective-faan slot per pattern
N_RULESET_FEATURES = 2 + len(_HAND_SETS) + N_PATTERNS

_PAD = 255
_AGE_BUCKETS = ((0, 0), (1, 2), (3, 5), (6, 10**6))
_NEVER = 10**7
# hand + 4 seats' melds + 4 seats' discards (thermometer) + target/others discard-age buckets
# + copies unseen + static tile properties + wind/dragon markers + target-suji
N_TILE_CHANNELS = N_THERMOMETER * (1 + 4 + 4) + 2 * len(_AGE_BUCKETS) + 1 + (4 + 1 + 1) + 4 + 1
# opponent slot(3) + target-wind(4) + dealer(4) + prevailing(4) + wall(1) + concealed/kongs/
# flowers/discard-count per seat(16) + ruleset
N_SCALARS = 3 + 4 + 4 + 4 + 1 + 16 + N_RULESET_FEATURES


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
    """The `RuleSet` fields that change correct play (docs/06-ml.md §5) -- not the full `RuleSet.to_dict()`. Timing/
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


def _static_tile_channels() -> np.ndarray:
    """(6, 34): suit one-hot (man, pin, sou, honor), rank/8 (0 for honors), terminal flag."""
    out = np.zeros((6, N_TILE_TYPES), dtype=np.float32)
    for t in range(N_TILE_TYPES):
        if t >= int(TileType.WIND_EAST):
            out[3, t] = 1.0
            continue
        suit, rank = divmod(t, 9)
        out[suit, t] = 1.0
        out[4, t] = rank / 8
        out[5, t] = float(rank in (0, 8))
    return out


_STATIC = _static_tile_channels()
_SUIT_RANK = np.array([t % 9 if t < 27 else -1 for t in range(N_TILE_TYPES)])
_HAS_LOWER = (_SUIT_RANK >= 3) & (_SUIT_RANK >= 0)
_HAS_UPPER = (_SUIT_RANK <= 5) & (_SUIT_RANK >= 0)


def _thermo(counts: np.ndarray) -> np.ndarray:
    """(..., 34) counts -> (..., N_THERMOMETER, 34) planes, plane k lit where count > k."""
    return (counts[..., None, :] > np.arange(N_THERMOMETER)[:, None]).astype(np.float32)


def _rotate(a: np.ndarray, rot: np.ndarray) -> np.ndarray:
    idx = rot.reshape(rot.shape + (1,) * (a.ndim - 2))
    return np.take_along_axis(a, idx, axis=1)


def _min_age(seq: np.ndarray) -> np.ndarray:
    """(B, L) discard order, `_PAD`-padded -> (B, 34) turns since each tile type was last
    discarded by that seat (0 = its most recent discard), `_NEVER` if never."""
    b, length = seq.shape
    valid = seq != _PAD
    n = valid.sum(axis=1)
    ages = np.full((b, N_TILE_TYPES), _NEVER, dtype=np.int64)
    rows = np.arange(b)
    for k in range(length):  # later discards overwrite earlier ones, so the minimum age wins
        m = valid[:, k]
        ages[rows[m], seq[m, k]] = n[m] - 1 - k
    return ages


def _age_buckets(ages: np.ndarray) -> np.ndarray:
    return np.stack([((ages >= lo) & (ages <= hi)) for lo, hi in _AGE_BUCKETS], axis=1).astype(
        np.float32
    )


def _marker(tile: np.ndarray) -> np.ndarray:
    out = np.zeros((len(tile), N_TILE_TYPES), dtype=np.float32)
    out[np.arange(len(tile)), tile] = 1.0
    return out


def encode_batch(
    raw: dict[str, np.ndarray], opp: np.ndarray, ruleset_vec: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Danger-model input for one (row, opponent) sample per element of `opp` (0..2 = the
    observer's next/across/previous seat). Rows are `ml.pack` fields (or `rows_to_arrays` of
    `ml.raw.raw_row`s); seats are rotated so the target opponent is position 0, then the seats
    after it. Returns `tiles (B, N_TILE_CHANNELS, 34)` and `scalars (B, N_SCALARS)`.

    Channel `hand` is the observer's own tiles; `unseen` counts the copies of a tile the observer
    can't see (a kong shows 3 of its 4 tiles in `meld_counts`, so it overstates unseen by one).
    """
    b = len(opp)
    t = opp.astype(np.int64) + 1
    rot = (t[:, None] + np.arange(4)) % 4

    hand = raw["hand_counts"].astype(np.int64)
    melds = _rotate(raw["meld_counts"].astype(np.int64), rot)
    discards = _rotate(raw["discard_counts"].astype(np.int64), rot)
    seq = _rotate(raw["discard_seq"], rot)

    target_age = _min_age(seq[:, 0])
    other_age = np.minimum.reduce([_min_age(seq[:, p]) for p in (1, 2, 3)])

    # the observer's own melds are already inside `hand`; the observer sits at position 4 - t
    obs_melds = melds[np.arange(b), (4 - t) % 4]
    seen = hand + melds.sum(axis=1) - obs_melds + discards.sum(axis=1)
    unseen = np.clip(4 - seen, 0, 4)[:, None, :] / 4.0

    target_discarded = discards[:, 0] > 0
    down = np.zeros_like(target_discarded)
    down[:, 3:] = target_discarded[:, :-3]
    up = np.zeros_like(target_discarded)
    up[:, :-3] = target_discarded[:, 3:]
    suji = ((_HAS_LOWER | _HAS_UPPER) & (~_HAS_LOWER | down) & (~_HAS_UPPER | up))[:, None, :]

    obs_wind = raw["seat_wind"].astype(np.int64)
    target_wind = (obs_wind + t) % 4
    markers = np.stack(
        [
            np.broadcast_to(
                (np.arange(N_TILE_TYPES) >= int(TileType.DRAGON_RED)).astype(np.float32),
                (b, N_TILE_TYPES),
            ),
            _marker(int(TileType.WIND_EAST) + raw["prevailing_wind"].astype(np.int64)),
            _marker(int(TileType.WIND_EAST) + target_wind),
            _marker(int(TileType.WIND_EAST) + obs_wind),
        ],
        axis=1,
    )

    tiles = np.concatenate(
        [
            _thermo(hand),
            _thermo(melds).reshape(b, -1, N_TILE_TYPES),
            _thermo(discards).reshape(b, -1, N_TILE_TYPES),
            _age_buckets(target_age),
            _age_buckets(other_age),
            unseen.astype(np.float32),
            np.broadcast_to(_STATIC, (b, *_STATIC.shape)),
            markers,
            suji.astype(np.float32),
        ],
        axis=1,
    )

    eye4 = np.eye(4, dtype=np.float32)
    n_discards = (seq != _PAD).sum(axis=2)
    ruleset = ruleset_vec.astype(np.float32).copy()
    ruleset[0] /= 10.0
    ruleset[1] /= 100.0
    ruleset[2 + len(_HAND_SETS) :] /= 10.0
    scalars = np.concatenate(
        [
            np.eye(3, dtype=np.float32)[opp],
            eye4[target_wind],
            eye4[(raw["dealer_idx"].astype(np.int64) - t) % 4],
            eye4[raw["prevailing_wind"].astype(np.int64)],
            raw["wall_remaining"].astype(np.float32)[:, None] / 100.0,
            _rotate(raw["concealed_counts"], rot) / 13.0,
            _rotate(raw["concealed_kongs"], rot) / 4.0,
            _rotate(raw["flowers"], rot) / 8.0,
            n_discards / 24.0,
            np.broadcast_to(ruleset, (b, N_RULESET_FEATURES)),
        ],
        axis=1,
    ).astype(np.float32)
    return tiles, scalars


def rows_to_arrays(rows: list[dict[str, object]], max_discards: int = 32) -> dict[str, np.ndarray]:
    """`ml.raw.raw_row` dicts -> the batched uint8 arrays `encode_batch` reads, laid out the
    same way as `ml.pack`."""
    out: dict[str, np.ndarray] = {}
    for key in (
        "hand_counts",
        "meld_counts",
        "discard_counts",
        "concealed_counts",
        "concealed_kongs",
        "flowers",
        "dealer_idx",
        "prevailing_wind",
        "seat_wind",
        "wall_remaining",
    ):
        out[key] = np.asarray([r[key] for r in rows], dtype=np.uint8)
    seq = np.full((len(rows), 4, max_discards), _PAD, dtype=np.uint8)
    for i, r in enumerate(rows):
        for p, pool in enumerate(r["discard_seq"]):  # type: ignore[attr-defined]
            seq[i, p, : len(pool)] = pool
    out["discard_seq"] = seq
    return out
