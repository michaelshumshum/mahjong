"""Gradient-boosted-trees baseline on hand-built safety features (docs/06-ml.md §6.2): does the
net earn its complexity over the same signals `bots/safety.py` reads?

    python -m ml.gbdt_baseline --data data/danger_v3_packed --ckpt runs/danger/ckpt_best.pt

Features are `bots/safety.py`'s signals re-derived vectorised from the packed arrays (live
copies, genbutsu, suji, meld/dragon read, tempo, wall) plus the tile's identity and the table
scalars a heuristic could use -- no board-wide structure, which is what the net adds. One row per
(row, opponent, candidate-discard tile), labelled legal-wait, trained on the train split with
validation early stopping, and scored on test candidates against the model with paired
game-bootstrap differences. Needs the `ml` extra.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

from ml.dataset import DangerData
from ml.encode import _NEVER, _PAD, _min_age, _rotate
from ml.evaluate import load_model
from ml.metrics import game_bootstrap, game_stats, metric_fns
from ml.splits import TEST, TRAIN, VAL

__all__ = ["FEATURE_NAMES", "candidate_features", "compare", "main"]

_OPPONENTS = 3
_TILES = 34
_WIND_EAST, _DRAGON_RED = 27, 31

FEATURE_NAMES = (
    "tile",
    "suit",
    "rank",
    "terminal_or_honor",
    "live",
    "own_count",
    "genbutsu",
    "suji",
    "opp_discards_of_tile",
    "discard_age",
    "opp_suit_discards",
    "opp_discard_count",
    "opp_meld_count",
    "opp_suit_melds",
    "opp_dragon_meld",
    "tempo",
    "opp_concealed",
    "opp_kongs",
    "opp_flowers",
    "opp_is_dealer",
    "opp_wind",
    "prevailing_wind",
    "tile_is_opp_wind",
    "tile_is_prevailing_wind",
    "wall_remaining",
    "others_discards_of_tile",
)

_TILE = np.arange(_TILES)
_SUIT = np.where(_TILE < 27, _TILE // 9, np.where(_TILE < _DRAGON_RED, 3, 4))
_RANK = np.where(_TILE < 27, _TILE % 9, -1)
_TERM = ((_RANK == 0) | (_RANK == 8) | (_TILE >= _WIND_EAST)).astype(np.float32)


def _suit_totals(counts: np.ndarray) -> np.ndarray:
    return np.stack([counts[:, _SUIT == s].sum(axis=1) for s in range(5)], axis=1)


def candidate_features(raw: dict[str, np.ndarray], opp: np.ndarray) -> np.ndarray:
    """`(B, 34, len(FEATURE_NAMES))` float32 features for one sample per element of `opp`."""
    b = len(opp)
    t = opp.astype(np.int64) + 1
    rot = (t[:, None] + np.arange(4)) % 4
    hand = raw["hand_counts"].astype(np.int64)
    melds = _rotate(raw["meld_counts"].astype(np.int64), rot)
    discards = _rotate(raw["discard_counts"].astype(np.int64), rot)
    seq = _rotate(raw["discard_seq"], rot)[:, 0]
    scalars = {
        k: _rotate(raw[k].astype(np.int64), rot)
        for k in ("concealed_counts", "concealed_kongs", "flowers")
    }

    obs_melds = melds[np.arange(b), (4 - t) % 4]
    seen = hand + melds.sum(axis=1) - obs_melds + discards.sum(axis=1)
    opp_discards, opp_melds = discards[:, 0], melds[:, 0]

    down = np.zeros_like(opp_discards) > 0
    up = down.copy()
    hit = opp_discards > 0
    down[:, 3:] = hit[:, :-3]
    up[:, :-3] = hit[:, 3:]
    has_lower, has_upper = (_RANK >= 3), ((_RANK <= 5) & (_RANK >= 0))
    suji = (has_lower | has_upper) & (~has_lower | down) & (~has_upper | up)

    per_suit_discards = _suit_totals(opp_discards)[:, _SUIT]
    per_suit_melds = (_suit_totals(opp_melds) // 3)[:, _SUIT]
    dragon_meld = (opp_melds[:, _DRAGON_RED:] >= 3).any(axis=1)

    valid = seq != _PAD
    n = valid.sum(axis=1)
    last = np.where(n > 0, seq[np.arange(b), np.maximum(n - 1, 0)], 0)
    earlier_terminal = (
        np.where(valid, _TERM[np.where(valid, seq, 0)], 0).sum(axis=1) - _TERM[last]
    ) / np.maximum(n - 1, 1)
    tempo = (n >= 4) & (earlier_terminal >= 0.7) & (_TERM[last] == 0)

    obs_wind = raw["seat_wind"].astype(np.int64)
    opp_wind = (obs_wind + t) % 4
    prevailing = raw["prevailing_wind"].astype(np.int64)
    winds = _WIND_EAST + np.arange(4)

    def col(v: np.ndarray) -> np.ndarray:
        return np.broadcast_to(np.asarray(v, dtype=np.float32).reshape(b, -1), (b, _TILES))

    ages = _min_age(seq)
    columns = [
        np.broadcast_to(_TILE, (b, _TILES)),
        np.broadcast_to(_SUIT, (b, _TILES)),
        np.broadcast_to(_RANK, (b, _TILES)),
        np.broadcast_to(_TERM, (b, _TILES)),
        np.clip(4 - seen, 0, 4),
        hand,
        hit,
        suji,
        opp_discards,
        np.where(ages == _NEVER, -1, ages),
        per_suit_discards,
        col(n),
        col(opp_melds.sum(axis=1) // 3),
        per_suit_melds,
        col(dragon_meld),
        col(tempo),
        col(scalars["concealed_counts"][:, 0]),
        col(scalars["concealed_kongs"][:, 0]),
        col(scalars["flowers"][:, 0]),
        col(raw["dealer_idx"].astype(np.int64) == t),
        col(opp_wind),
        col(prevailing),
        np.isin(np.broadcast_to(_TILE, (b, _TILES)), winds[opp_wind][:, None]),
        np.isin(np.broadcast_to(_TILE, (b, _TILES)), winds[prevailing][:, None]),
        col(raw["wall_remaining"]),
        discards[:, 1:].sum(axis=1),
    ]
    return np.stack([c.astype(np.float32) for c in columns], axis=-1)


def _gather(
    data: DangerData, rows: np.ndarray, samples: np.ndarray, model: Any = None, chunk: int = 2048
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Candidate-tile features, legal-wait labels, game seed and (when `model` is given) model
    legal-wait probabilities for `samples`."""
    import torch

    xs, ys, gs, ps = [], [], [], []
    seeds = np.asarray(data.raw["game_seed"])[rows]
    for i in range(0, len(samples), chunk):
        idx = samples[i : i + chunk]
        row_idx = rows[idx // _OPPONENTS]
        opp = idx % _OPPONENTS
        raw = {k: np.asarray(v[row_idx]) for k, v in data.raw.items() if k != "split"}
        cand = raw["hand_counts"] > 0
        xs.append(candidate_features(raw, opp)[cand])
        ys.append((raw["opponent_expected_faan"][np.arange(len(idx)), opp] > 0)[cand])
        gs.append(np.broadcast_to(seeds[idx // _OPPONENTS][:, None], cand.shape)[cand])
        if model is not None:
            tiles, scalars, _ = data.batch(rows, idx)
            with torch.no_grad():
                ps.append(torch.sigmoid(model(tiles, scalars).legal_wait).numpy()[cand])
    return (
        np.concatenate(xs),
        np.concatenate(ys),
        np.concatenate(gs),
        np.concatenate(ps) if ps else np.empty(0),
    )


def compare(
    data: DangerData,
    model: Any,
    *,
    train_samples: int = 2_000_000,
    test_samples: int = 300_000,
    n_boot: int = 500,
    seed: int = 0,
    num_boost_round: int = 400,
) -> dict[str, Any]:
    """Train the booster on train-split candidates (validation early stopping), then score it and
    `model` on the same test candidates. Test samples are drawn at random over the split, so the
    interval resamples whichever games they fall in."""
    import lightgbm as lgb

    rng = np.random.default_rng(seed)

    def draw(split: int, n: int) -> tuple[np.ndarray, np.ndarray]:
        rows = data.rows_of(split)
        total = len(rows) * _OPPONENTS
        return rows, np.sort(rng.choice(total, min(n, total), replace=False))

    x_tr, y_tr, _, _ = _gather(data, *draw(TRAIN, train_samples))
    x_va, y_va, _, _ = _gather(data, *draw(VAL, max(train_samples // 10, 1)))
    booster = lgb.train(
        {
            "objective": "binary",
            "learning_rate": 0.05,
            "num_leaves": 63,
            "min_data_in_leaf": 200,
            "feature_fraction": 0.9,
            "verbosity": -1,
            "seed": seed,
        },
        lgb.Dataset(x_tr, y_tr, feature_name=list(FEATURE_NAMES), categorical_feature=["tile"]),
        num_boost_round=num_boost_round,
        valid_sets=[lgb.Dataset(x_va, y_va)],
        callbacks=[lgb.early_stopping(30, verbose=False)],
    )

    x_te, y_te, g_te, p_model = _gather(data, *draw(TEST, test_samples), model=model)
    games, gi = np.unique(g_te, return_inverse=True)
    stats = {
        "gbdt": game_stats(booster.predict(x_te).astype(np.float64), y_te, gi, len(games)),
        "model": game_stats(p_model.astype(np.float64), y_te, gi, len(games)),
    }
    result: dict[str, Any] = {
        "n_train_candidates": len(y_tr),
        "n_test_candidates": len(y_te),
        "n_test_games": len(games),
        "best_iteration": booster.best_iteration,
        "importance": dict(zip(FEATURE_NAMES, booster.feature_importance("gain").tolist())),
    }
    for name, st in stats.items():
        result[name] = {
            m: game_bootstrap({"s": st}, lambda s, fn=fn: fn(s["s"]), n_boot)
            for m, fn in metric_fns.items()
        }
    result["model_minus_gbdt"] = {
        m: game_bootstrap(stats, lambda s, fn=fn: fn(s["model"]) - fn(s["gbdt"]), n_boot)
        for m, fn in metric_fns.items()
    }
    return result


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m ml.gbdt_baseline", description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--ckpt", type=Path, required=True)
    parser.add_argument("--train-samples", type=int, default=2_000_000)
    parser.add_argument("--test-samples", type=int, default=300_000)
    parser.add_argument("--n-boot", type=int, default=500)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    result = compare(
        DangerData(args.data),
        load_model(args.ckpt),
        train_samples=args.train_samples,
        test_samples=args.test_samples,
        n_boot=args.n_boot,
    )
    text = json.dumps(result, indent=2)
    if args.out:
        args.out.write_text(text)
    print(text)


if __name__ == "__main__":
    main(sys.argv[1:])
