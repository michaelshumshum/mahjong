"""`bots.arena` (docs/04-bots.md §8): a fast, small smoke test that the harness runs end to end
and produces sane output. The full N-duplicate-set validation run (T1 vs T0, enough sets for the
paired-difference CI to mean something) is manual/report-only per this sub-task's scope -- not
CI-gated here, matching this repo's `-m slow` convention for expensive runs.
"""

from __future__ import annotations

import pytest

from bots.arena import (
    _ARENA_RULESET,
    BotStats,
    GameRecord,
    HandRecord,
    _collect_stats,
    _make_bot,
    _mean_ci95,
    _paired_differences,
    _run_duplicate_set,
    main,
)
from mahjong_core.state import HandOutcome, WinType


def test_make_bot_rejects_unknown_name() -> None:
    with pytest.raises(ValueError, match="unknown bot"):
        _make_bot("NotABot", seed=0)


@pytest.fixture(scope="module")
def sample_duplicate_set() -> tuple[GameRecord, ...]:
    """One real duplicate set, shared by every structural test below -- each is itself 4 full
    games, so computing it once keeps this "fast smoke test" file actually fast."""
    return _run_duplicate_set(
        seed=1, ruleset=_ARENA_RULESET, name_a="EfficiencyBot", name_b="RandomBot"
    )


def test_duplicate_set_has_four_rotations_each_with_exactly_one_a_seat(
    sample_duplicate_set: tuple[GameRecord, ...],
) -> None:
    records = sample_duplicate_set
    assert len(records) == 4
    for rotation, record in enumerate(records):
        assert record.roles.count("A") == 1
        assert record.roles.count("B") == 3
        assert record.roles[rotation] == "A"
        assert record.seed == 1
        assert len(record.hands) >= 1
        assert len(record.final_scores) == 4


def test_duplicate_set_is_reproducible(sample_duplicate_set: tuple[GameRecord, ...]) -> None:
    """Same seed, same bots -> bit-for-bit identical records (server/AGENTS.md's determinism
    rule, extended to bot-internal RNG -- see bots/arena.py's module docstring)."""
    again = _run_duplicate_set(
        seed=1, ruleset=_ARENA_RULESET, name_a="EfficiencyBot", name_b="RandomBot"
    )
    assert sample_duplicate_set == again


def test_paired_differences_and_ci_on_synthetic_data() -> None:
    # Two duplicate sets' worth of hand-crafted per-rotation scores, bypassing real gameplay,
    # to pin the arithmetic itself: seat 0 always "A", always scores +30 while the other three
    # always score -10 each -> per-rotation diff = 30 - (-10) = 40 for every rotation/set.
    def _record(rotation: int) -> GameRecord:
        roles = ["B", "B", "B", "B"]
        roles[rotation] = "A"
        scores = [-10, -10, -10, -10]
        scores[rotation] = 30
        return GameRecord(
            seed=0,
            roles=(roles[0], roles[1], roles[2], roles[3]),
            hands=(),
            final_scores=(scores[0], scores[1], scores[2], scores[3]),
        )

    duplicate_set = tuple(_record(r) for r in range(4))
    diffs = _paired_differences([duplicate_set, duplicate_set])
    assert diffs == pytest.approx([40.0, 40.0])
    mean, lo, hi = _mean_ci95(diffs)
    assert mean == pytest.approx(40.0)
    # zero variance across the two identical sets -> a degenerate (zero-width) CI at the mean.
    assert lo == pytest.approx(40.0)
    assert hi == pytest.approx(40.0)


def test_mean_ci95_single_sample_is_degenerate() -> None:
    mean, lo, hi = _mean_ci95([5.0])
    assert mean == lo == hi == 5.0


def test_bot_stats_summary_ranges_are_sane() -> None:
    stats = BotStats()
    stats.add_hand(
        0,
        HandRecord(
            hand_no=1,
            outcome=HandOutcome.WIN,
            winner=0,
            win_type=WinType.SELF_DRAW,
            discarder=None,
            faan=3,
            payments=(9, -3, -3, -3),
            turns=10,
        ),
    )
    stats.add_hand(
        0,
        HandRecord(
            hand_no=2,
            outcome=HandOutcome.EXHAUSTIVE_DRAW,
            winner=None,
            win_type=None,
            discarder=None,
            faan=0,
            payments=(0, 0, 0, 0),
            turns=17,
            tenpai_seats=(0, 2),
            sub_minimum_tenpai_seats=(0,),
        ),
    )
    summary = stats.summary()
    assert summary["hands_played"] == 2
    assert summary["win_rate"] == pytest.approx(0.5)
    assert summary["avg_winning_faan"] == pytest.approx(3.0)
    assert summary["avg_turns_to_win"] == pytest.approx(10.0)
    assert summary["tenpai_at_draw_rate"] == pytest.approx(1.0)
    assert summary["tenpai_rate_on_sub_minimum_hand"] == pytest.approx(1.0)
    for key in (
        "win_rate",
        "deal_in_rate",
        "tenpai_at_draw_rate",
        "tenpai_rate_on_sub_minimum_hand",
    ):
        assert 0.0 <= summary[key] <= 1.0


def test_collect_stats_pools_across_rotations(sample_duplicate_set: tuple[GameRecord, ...]) -> None:
    stats_a, stats_b = _collect_stats([sample_duplicate_set])
    # A occupied exactly one seat per rotation (4 rotations, 4 hands/rotation for EAST_ONLY).
    assert stats_a.hands_played == 4 * 4
    assert stats_b.hands_played == 4 * 4 * 3
    for stats in (stats_a, stats_b):
        summary = stats.summary()
        assert 0.0 <= summary["win_rate"] <= 1.0
        assert 0.0 <= summary["deal_in_rate"] <= 1.0


def test_main_smoke_end_to_end(capsys: pytest.CaptureFixture[str]) -> None:
    """The real CLI entry point, tiny N, no --parallel -- proves argparse, the duplicate-set
    loop, aggregation and the report all wire together."""
    main(["--a", "EfficiencyBot", "--b", "RandomBot", "--games", "2", "--seed", "100"])
    out = capsys.readouterr().out
    assert "EfficiencyBot (A) vs RandomBot (B)" in out
    assert "paired difference" in out
    assert "95% CI" in out


def test_main_smoke_with_parallel_matches_serial(capsys: pytest.CaptureFixture[str]) -> None:
    main(
        [
            "--a",
            "EfficiencyBot",
            "--b",
            "RandomBot",
            "--games",
            "1",
            "--seed",
            "100",
            "--parallel",
            "2",
        ]
    )
    parallel_out = capsys.readouterr().out
    main(
        [
            "--a",
            "EfficiencyBot",
            "--b",
            "RandomBot",
            "--games",
            "1",
            "--seed",
            "100",
            "--parallel",
            "1",
        ]
    )
    serial_out = capsys.readouterr().out
    assert parallel_out == serial_out


def test_never_deadlocks_within_step_cap() -> None:
    """Same bounded-ruleset guarantee `tests/test_selfplay.py` checks, exercised through the
    arena's own instrumented loop rather than `bots/selfplay.py`'s."""
    records = _run_duplicate_set(
        seed=42, ruleset=_ARENA_RULESET, name_a="EfficiencyBot", name_b="EfficiencyBot"
    )
    for record in records:
        assert record.hands
        assert record.hands[-1].hand_no >= 1
