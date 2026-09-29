"""The shipped deal-in heuristic as an offline baseline for the danger model (docs/06-ml.md §6.2):

    python -m ml.heuristic_baseline --data data/danger_v3_packed --ckpt runs/danger/ckpt_best.pt

`bots/safety.py`'s `deal_in_probability` needs a live `SeatView`, which the packed arrays are not,
so games are replayed deterministically from `(seed, ruleset, roster)` with `play_and_label`'s
`row_hook`, scoring every (opponent, tile) as each row is emitted. Each replay is checked
against the packed rows (hand, labels), so a drift in bots, engine or labels fails loudly
instead of silently scoring the wrong positions. The heuristic is Platt-calibrated on validation
games before its log-loss is compared with the model's, on test games.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from app.views import seat_view
from bots.safety import deal_in_probability
from mahjong_core.config import RuleSet
from mahjong_core.state import GameState
from ml.dataset import DangerData
from ml.evaluate import legal_wait_probs, load_model
from ml.generate_dataset import _make_bots, _mp_context, _shuffled_roster, play_and_label
from ml.metrics import apply_platt, fit_platt, game_bootstrap, game_stats, metric_fns
from ml.splits import TEST, VAL

__all__ = ["compare", "main", "replay_scores", "score_games"]


def replay_scores(
    seed: int, ruleset: RuleSet, bot_names: Sequence[str]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """One game replayed: heuristic `(rows, 3, 34)` scores plus the regenerated `hand_counts`
    and `opponent_expected_faan`, for checking against the packed rows."""
    scores: list[list[list[float]]] = []

    def hook(state: GameState, seat: int, row: dict[str, object]) -> None:
        view = seat_view(state, seat)
        opponents: Any = row["opponent_seats"]
        scores.append([[deal_in_probability(view, o, t) for t in range(34)] for o in opponents])

    roster = _shuffled_roster(bot_names, seed)
    rows = asyncio.run(play_and_label(seed, ruleset, _make_bots(roster, seed), roster, hook))
    return (
        np.asarray(scores, dtype=np.float32),
        np.asarray([r["hand_counts"] for r in rows], dtype=np.uint8),
        np.asarray([r["opponent_expected_faan"] for r in rows], dtype=np.uint8),
    )


def _replay_job(args: tuple[int, dict[str, Any], list[str]]) -> tuple[int, Any]:
    seed, ruleset, bot_names = args
    return seed, replay_scores(seed, RuleSet.from_dict(ruleset), bot_names)


def game_rows(data: DangerData, seeds: Sequence[int]) -> dict[int, np.ndarray]:
    """Packed row indices per game seed, in the order the game emitted them."""
    all_seeds = np.asarray(data.raw["game_seed"])
    order = np.argsort(all_seeds, kind="stable")
    sorted_seeds = all_seeds[order]
    out = {}
    for seed in seeds:
        lo, hi = np.searchsorted(sorted_seeds, [seed, seed + 1])
        out[int(seed)] = order[lo:hi]
    return out


def score_games(
    data: DangerData, seeds: Sequence[int], *, workers: int = 4
) -> dict[int, np.ndarray]:
    """Heuristic scores `(rows, 3, 34)` per game seed, each replay verified against the packed
    rows; raises `ValueError` on any mismatch."""
    ruleset = data.meta["manifest"]["ruleset"]
    roster = list(data.meta["manifest"]["bot_roster"])
    packed = game_rows(data, seeds)
    jobs = [(int(s), ruleset, roster) for s in seeds]
    out: dict[int, np.ndarray] = {}
    with ProcessPoolExecutor(max_workers=workers, mp_context=_mp_context()) as pool:
        for seed, (scores, hands, faan) in pool.map(_replay_job, jobs):
            rows = packed[seed]
            same = (
                len(rows) == len(scores)
                and np.array_equal(np.asarray(data.raw["hand_counts"][rows]), hands)
                and np.array_equal(np.asarray(data.raw["opponent_expected_faan"][rows]), faan)
            )
            if not same:
                raise ValueError(f"game {seed}: replay does not match the packed rows")
            out[seed] = scores
    return out


def _candidates(
    data: DangerData, rows: np.ndarray, game_of_row: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Flat candidate-discard mask over `(rows, 3, 34)`, legal-wait labels and game indices."""
    cand = np.asarray(data.raw["hand_counts"][rows]) > 0
    cand = np.broadcast_to(cand[:, None, :], (len(rows), 3, 34))
    y = np.asarray(data.raw["opponent_expected_faan"][rows]) > 0
    g = np.broadcast_to(game_of_row[:, None, None], cand.shape)
    return cand.ravel(), y.ravel(), g.ravel()


def _flat_rows(
    packed: dict[int, np.ndarray], scores: dict[int, np.ndarray]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    seeds = sorted(scores)
    rows = np.concatenate([packed[s] for s in seeds])
    heur = np.concatenate([scores[s] for s in seeds])
    game_of_row = np.concatenate([np.full(len(packed[s]), i) for i, s in enumerate(seeds)])
    return rows, heur, game_of_row


def compare(
    data: DangerData,
    model: Any,
    *,
    calib_games: int = 100,
    test_games: int = 200,
    workers: int = 4,
    n_boot: int = 500,
) -> dict[str, Any]:
    """Legal-wait metrics at candidate-discard tiles for the raw heuristic, the Platt-calibrated
    heuristic and the model, over the first `test_games` test games; the calibration is fit on
    the first `calib_games` validation games. Includes paired model-minus-calibrated differences."""
    seeds = np.asarray(data.raw["game_seed"])
    split = np.asarray(data.raw["split"])
    val_seeds = sorted(set(seeds[split == VAL].tolist()))[:calib_games]
    test_seeds = sorted(set(seeds[split == TEST].tolist()))[:test_games]

    val_scores = score_games(data, val_seeds, workers=workers)
    rows, heur, g = _flat_rows(game_rows(data, val_seeds), val_scores)
    mask, y, _ = _candidates(data, rows, g)
    a, b = fit_platt(heur.ravel()[mask], y[mask])

    test_scores = score_games(data, test_seeds, workers=workers)
    rows, heur, g = _flat_rows(game_rows(data, test_seeds), test_scores)
    mask, y, gi = _candidates(data, rows, g)
    scorers = {
        "heuristic_raw": heur.ravel()[mask],
        "heuristic_platt": apply_platt(heur.ravel()[mask], a, b),
        "model": legal_wait_probs(model, data, rows).ravel()[mask],
    }
    stats = {
        name: game_stats(p.astype(np.float64), y[mask], gi[mask], len(test_seeds))
        for name, p in scorers.items()
    }
    result: dict[str, Any] = {
        "platt": [a, b],
        "n_val_games": len(val_seeds),
        "n_test_games": len(test_seeds),
        "n_candidates": int(mask.sum()),
        "base_rate": float(y[mask].mean()),
    }
    for name, st in stats.items():
        result[name] = {
            m: game_bootstrap({"s": st}, lambda s, fn=fn: fn(s["s"]), n_boot)
            for m, fn in metric_fns.items()
        }
    result["model_minus_heuristic_platt"] = {
        m: game_bootstrap(
            {"a": stats["model"], "b": stats["heuristic_platt"]},
            lambda s, fn=fn: fn(s["a"]) - fn(s["b"]),
            n_boot,
        )
        for m, fn in metric_fns.items()
    }
    return result


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m ml.heuristic_baseline", description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--ckpt", type=Path, required=True)
    parser.add_argument("--calib-games", type=int, default=100)
    parser.add_argument("--test-games", type=int, default=200)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--n-boot", type=int, default=500)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    result = compare(
        DangerData(args.data),
        load_model(args.ckpt),
        calib_games=args.calib_games,
        test_games=args.test_games,
        workers=args.workers,
        n_boot=args.n_boot,
    )
    text = json.dumps(result, indent=2)
    if args.out:
        args.out.write_text(text)
    print(text)


if __name__ == "__main__":
    main(sys.argv[1:])
