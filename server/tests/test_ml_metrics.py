"""Unit tests for `ml/metrics.py`. Needs numpy (the `ml` extra)."""

from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")

from ml.metrics import (
    add_stats,
    apply_platt,
    fit_platt,
    game_bootstrap,
    game_stats,
    metric_fns,
    reliability_sums,
    reliability_table,
)


def _exact_auc(p: np.ndarray, y: np.ndarray) -> float:
    pos, neg = p[y == 1], p[y == 0]
    diff = pos[:, None] - neg[None, :]
    return float(((diff > 0).sum() + 0.5 * (diff == 0).sum()) / (len(pos) * len(neg)))


def _stats(p, y, games):  # type: ignore[no-untyped-def]
    return game_stats(p, y, games, int(games.max()) + 1)


def test_auc_matches_exact_pairwise_auc() -> None:
    rng = np.random.default_rng(0)
    y = (rng.random(400) < 0.3).astype(np.uint8)
    p = np.clip(rng.random(400) * 0.6 + y * 0.25, 0.001, 0.999)
    stats = _stats(p, y, rng.integers(0, 10, 400))
    assert metric_fns["auc"](stats) == pytest.approx(_exact_auc(p, y), abs=1e-3)


def test_perfect_and_inverted_rankings() -> None:
    y = np.array([0, 0, 1, 1], dtype=np.uint8)
    g = np.zeros(4, dtype=np.int64)
    assert metric_fns["auc"](_stats(np.array([0.1, 0.2, 0.8, 0.9]), y, g)) == 1.0
    assert metric_fns["auc"](_stats(np.array([0.9, 0.8, 0.2, 0.1]), y, g)) == 0.0


def test_logloss_and_brier_match_the_direct_formulas() -> None:
    p = np.array([0.9, 0.2, 0.6, 0.4])
    y = np.array([1, 0, 1, 1], dtype=np.uint8)
    stats = _stats(p, y, np.array([0, 0, 1, 1]))
    expected = -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))
    assert metric_fns["logloss"](stats) == pytest.approx(expected)
    assert metric_fns["brier"](stats) == pytest.approx(np.mean((p - y) ** 2))


def test_stats_are_additive_across_chunks() -> None:
    rng = np.random.default_rng(1)
    p, y, g = rng.random(100), (rng.random(100) < 0.5).astype(np.uint8), rng.integers(0, 5, 100)
    whole = game_stats(p, y, g, 5)
    parts = add_stats(game_stats(p[:40], y[:40], g[:40], 5), game_stats(p[40:], y[40:], g[40:], 5))
    for k in whole:
        assert np.allclose(whole[k], parts[k])


def test_bootstrap_interval_brackets_the_point_and_paired_diff_is_zero_for_equal_scorers() -> None:
    rng = np.random.default_rng(2)
    n = 2000
    y = (rng.random(n) < 0.2).astype(np.uint8)
    p = np.clip(0.2 + 0.3 * (y - 0.2) + rng.normal(0, 0.1, n), 0.01, 0.99)
    stats = _stats(p, y, rng.integers(0, 40, n))
    point, lo, hi = game_bootstrap({"m": stats}, lambda s: metric_fns["auc"](s["m"]), 200)
    assert lo < point < hi and hi - lo < 0.1

    same = game_bootstrap(
        {"a": stats, "b": stats},
        lambda s: metric_fns["logloss"](s["a"]) - metric_fns["logloss"](s["b"]),
        50,
    )
    assert same == (0.0, 0.0, 0.0)


def test_platt_recovers_a_known_miscalibration() -> None:
    rng = np.random.default_rng(3)
    true_p = rng.random(50000) * 0.5
    y = (rng.random(50000) < true_p).astype(np.uint8)
    overconfident = np.clip(true_p * 1.8, 0.001, 0.999)
    a, b = fit_platt(overconfident, y)
    fixed = apply_platt(overconfident, a, b)
    assert abs(fixed.mean() - y.mean()) < 0.01
    assert abs(overconfident.mean() - y.mean()) > 0.05


def test_reliability_table_reports_observed_frequency_per_bin() -> None:
    p = np.array([0.001, 0.002, 0.6, 0.65])
    y = np.array([0, 0, 1, 0])
    table = reliability_table(reliability_sums(p, y))
    assert [n for _, _, n in table] == [2, 2]
    assert table[0][1] == 0.0 and table[1][1] == 0.5
    assert table[1][0] == pytest.approx(0.625)
