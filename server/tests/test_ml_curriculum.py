"""`ml/curriculum.py`: stage schedules, advancement on rolling statistics, and the off-by-default
§10 contingency (docs/06-ml.md §10)."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("torch")

from ml.curriculum import Curriculum
from ml.encode_v2 import PAD
from ml.ppo import HandStat, build_schedule, main_config
from ml.train_env import EnvConfig, TrainEnv, unpack_rows


def _hands(n, win_rate, *, blind=False, tenpai=0.0, sub_min=0.0, seed=0):
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        won = rng.random() < win_rate
        t = not won and rng.random() < tenpai
        out.append(
            HandStat(
                won=won,
                dealt_in=False,
                blind=blind,
                draw=not won,
                tenpai_at_draw=t,
                sub_min_tenpai=t and rng.random() < sub_min,
                points=1.0 if won else 0.0,
                min_faan=0,
            )
        )
    return out


def _at(cur: Curriculum, name: str) -> Curriculum:
    cur.index = [s.name for s in cur.stages].index(name)
    return cur


def test_c0b_anneals_draws_and_beta():
    cur = _at(Curriculum(), "C0b")
    span = cur.stage.anneal_decisions
    p0, mid, end = cur.params(0), cur.params(span // 2), cur.params(span * 2)
    assert (p0.oracle_k, p0.beta, p0.keep_prob, p0.learners) == (13, 1.0, 1.0, 1)
    assert mid.oracle_k in (6, 7) and mid.beta == pytest.approx(0.75)
    assert (end.oracle_k, end.beta, end.min_faan) == (0, 0.5, 0)


def test_c1_reaches_blind_and_unshaped_before_min_faan_3():
    cur = _at(Curriculum(), "C1")
    span = cur.stage.anneal_decisions
    seen = []
    for d in range(0, span + 1, span // 20):
        p = cur.params(d)
        assert p.learners == 4 and p.oracle_k == 0
        if p.min_faan == 3:
            assert p.keep_prob == 0.0 and p.beta == 0.0
        seen.append(p.min_faan)
    assert seen[0] == 0 and 1 in seen and seen[-1] == 3
    assert seen == sorted(seen)


def test_advancement_uses_rolling_stats_after_the_anneal():
    cur = Curriculum(window=1000)
    cur.observe(_hands(1000, 0.5))  # before the first advance() call: anneal not yet marked
    assert cur.advance(10) is None
    cur.observe(_hands(1000, 0.38))
    assert cur.advance(20) is None
    cur.observe(_hands(1000, 0.43, seed=1))
    assert cur.advance(30) == "C0b"
    assert len(cur.recent) == 0 and cur.stage_start == 30

    span = cur.stage.anneal_decisions
    cur.observe(_hands(1000, 0.9, blind=True))
    assert cur.advance(30 + span // 2) is None  # mid-anneal hands don't count
    assert cur.advance(30 + span) is None
    cur.observe(_hands(1000, 0.3, blind=True, seed=2))
    assert cur.advance(30 + span + 1) == "C1"


def test_c1_exit_needs_win_rate_and_sub_min_tenpai_then_completes():
    cur = _at(Curriculum(window=1000), "C1")
    end = cur.stage.anneal_decisions
    cur.advance(end)
    cur.observe(_hands(1000, 0.2, tenpai=0.6, sub_min=0.5))
    assert cur.advance(end + 1) is None
    cur.observe(_hands(1000, 0.2, tenpai=0.6, sub_min=0.2, seed=3))
    assert cur.advance(end + 2) == "C2"
    assert cur.complete()
    with pytest.raises(NotImplementedError):
        cur.params(end + 3)


def test_contingency_is_off_by_default_even_when_c1_stalls():
    cur = _at(Curriculum(window=100), "C1")
    late = cur.contingency.after_decisions + cur.stage.anneal_decisions
    cur.advance(late)
    cur.observe(_hands(100, 0.01))
    cur.advance(late + 1)
    assert cur.teacher() is None
    assert cur.clone_coef(late + 2) == 0.0
    assert cur.snapshot_due(late + 2) is None


def test_contingency_when_enabled_clones_with_a_decaying_anchor():
    cur = Curriculum.from_config(
        {
            "start": "C1",
            "window": 100,
            "contingency": {"enabled": True, "after_decisions": 10, "anchor_decisions": 100},
        }
    )
    end = cur.stage.anneal_decisions
    cur.advance(end)
    cur.observe(_hands(100, 0.05))
    cur.advance(end + 20)
    start = cur.contingency.started_at
    assert start == end + 20
    assert cur.teacher() == "FaanBot"
    assert cur.clone_coef(start + 50) == pytest.approx(0.5)
    assert cur.snapshot_due(start + 50) is None
    assert cur.snapshot_due(start + 100) == "anchor_zero"
    assert cur.snapshot_due(start + 101) is None
    assert cur.teacher() is None and cur.clone_coef(start + 200) == 0.0


def test_state_round_trip():
    cur = Curriculum(window=50)
    cur.advance(5)
    cur.observe(_hands(30, 0.5))
    other = Curriculum(window=50)
    other.load_state_dict(cur.state_dict())
    assert other.state_dict() == cur.state_dict()
    assert other.rolling() == cur.rolling()


def test_c0_config_loads_with_two_threads_and_the_curriculum():
    cfg = main_config(Path("ml/configs/rl_ppo_c0.yaml"))
    assert cfg.threads == 2 and cfg.workers <= 6
    schedule = build_schedule(cfg)
    assert isinstance(schedule, Curriculum)
    assert schedule.stage.name == "C0" and not schedule.contingency.enabled
    p = schedule.params(0)
    assert (p.learners, p.opponent, p.min_faan, p.oracle_k, p.keep_prob) == (
        1,
        "tsumogiri",
        0,
        13,
        1.0,
    )


def test_teacher_env_labels_only_when_enabled():
    rng = random.Random(0)
    for teacher in (None, "FaanBot"):
        env = TrainEnv(EnvConfig(learners=1, teacher=teacher))
        env.reset(4)
        for _ in range(3):
            label = int(unpack_rows(env.row[None])["teacher"][0])
            if teacher is None:
                assert label == PAD
            else:
                assert env.mask[label]
            if env.step(rng.choice(np.flatnonzero(env.mask).tolist()))[0]:
                break
