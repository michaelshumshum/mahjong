"""Offline metrics for wait/danger scores (docs/06-ml.md §5): AUC, log-loss and Brier with
game-level bootstrap confidence intervals.

Rows within a game are correlated, so resampling is over games, never samples. Each game is
reduced once to sufficient statistics (score histograms, loss sums) so a bootstrap replicate is a
weighted sum over games instead of a pass over tens of millions of samples. AUC is computed from
logit-binned histograms; bins are 0.01 wide in logit space, so binning error is negligible.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

__all__ = [
    "add_stats",
    "auc_from_hist",
    "game_bootstrap",
    "game_stats",
    "logit",
    "metric_fns",
    "reliability_sums",
    "reliability_table",
]

_EPS = 1e-6
_LO, _HI, _STEP = -14.0, 8.0, 0.01
_EDGES = np.arange(_LO, _HI + _STEP, _STEP)
N_BINS = len(_EDGES) - 1

Stats = dict[str, np.ndarray]


def logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, _EPS, 1 - _EPS)
    return np.log(p / (1 - p))


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def game_stats(p: np.ndarray, y: np.ndarray, game_idx: np.ndarray, n_games: int) -> Stats:
    """Per-game sufficient statistics of scores `p` against binary labels `y`; `game_idx` maps
    each sample to `0..n_games-1`."""
    y = y.astype(bool)
    bins = np.clip(np.digitize(logit(p), _EDGES) - 1, 0, N_BINS - 1)
    flat = game_idx.astype(np.int64) * N_BINS + bins

    def hist(mask: np.ndarray) -> np.ndarray:
        return np.bincount(flat[mask], minlength=n_games * N_BINS).reshape(n_games, N_BINS)

    pc = np.clip(p, _EPS, 1 - _EPS)
    loss = -np.where(y, np.log(pc), np.log1p(-pc))
    return {
        "pos": hist(y).astype(np.float64),
        "neg": hist(~y).astype(np.float64),
        "loss": np.bincount(game_idx, weights=loss, minlength=n_games),
        "sq": np.bincount(game_idx, weights=(pc - y) ** 2, minlength=n_games),
        "n": np.bincount(game_idx, minlength=n_games).astype(np.float64),
    }


def add_stats(a: Stats, b: Stats) -> Stats:
    return {k: a[k] + b[k] for k in a}


def auc_from_hist(pos: np.ndarray, neg: np.ndarray) -> float:
    total_pos, total_neg = pos.sum(), neg.sum()
    if total_pos == 0 or total_neg == 0:
        return float("nan")
    below = np.cumsum(neg) - neg
    return float((pos * (below + 0.5 * neg)).sum() / (total_pos * total_neg))


metric_fns: dict[str, Callable[[Stats], float]] = {
    "auc": lambda s: auc_from_hist(s["pos"].sum(0), s["neg"].sum(0)),
    "logloss": lambda s: float(s["loss"].sum() / s["n"].sum()),
    "brier": lambda s: float(s["sq"].sum() / s["n"].sum()),
}


def game_bootstrap(
    stats: dict[str, Stats],
    fn: Callable[[dict[str, Stats]], float],
    n_boot: int = 500,
    seed: int = 0,
) -> tuple[float, float, float]:
    """`fn` of the pooled statistics, and its 95% percentile interval over game resamples. All
    named scorers share each resample, so `fn` may be a paired difference."""
    n_games = len(next(iter(next(iter(stats.values())).values())))
    point = fn({k: {n: v.sum(0, keepdims=True) for n, v in s.items()} for k, s in stats.items()})
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(n_boot):
        w = rng.multinomial(n_games, np.full(n_games, 1.0 / n_games)).astype(np.float64)
        draws.append(fn({k: {n: (w @ v)[None] for n, v in s.items()} for k, s in stats.items()}))
    lo, hi = np.nanpercentile(draws, [2.5, 97.5])
    return point, float(lo), float(hi)


_REL_EDGES = np.array([0, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0000001])


def reliability_sums(p: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Additive `(bins, 3)` array of sum(score), sum(label), count over fixed probability bins."""
    idx = np.digitize(p, _REL_EDGES) - 1
    n_bins = len(_REL_EDGES) - 1
    return np.stack(
        [
            np.bincount(idx, weights=p, minlength=n_bins),
            np.bincount(idx, weights=y.astype(np.float64), minlength=n_bins),
            np.bincount(idx, minlength=n_bins).astype(np.float64),
        ],
        axis=1,
    )


def reliability_table(sums: np.ndarray) -> list[tuple[float, float, int]]:
    """(mean score, observed frequency, count) per non-empty bin."""
    return [(a / n, b / n, int(n)) for a, b, n in sums if n > 0]
