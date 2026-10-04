"""`ml/eval_policy.py`: paired-duplicate candidate-vs-heuristic hands with replayable records
(docs/ml.md §12)."""

from __future__ import annotations

import dataclasses

import pytest

np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")

from mahjong_core.config import DEFAULT_RULESET
from mahjong_core.engine import ENGINE_VERSION
from mahjong_core.state import Phase
from ml.env import replay_hand
from ml.eval_policy import bootstrap_ci, evaluate, load_candidate
from ml.policy_net import PolicyNet, PolicyNetConfig
from ml.ppo import PPOConfig, train_ppo

_RULESET = dataclasses.replace(DEFAULT_RULESET, min_faan=0)


def _model():
    torch.manual_seed(0)
    return PolicyNet(PolicyNetConfig(channels=8, blocks=1))


def test_duplicate_sets_rotate_the_candidate_and_records_replay():
    report, records = evaluate([5, 6], _RULESET, "EfficiencyBot", model=_model())
    assert report["sets"] == 2 and len(records) == 8
    assert report["candidate"]["hands_played"] == 8
    assert report["opponents"]["hands_played"] == 24
    for key in ("tenpai_rate_on_sub_minimum_hand", "win_rate", "deal_in_rate"):
        assert key in report["candidate"]
    assert 0.0 <= report["exhaustive_draw_rate"] <= 1.0
    lo, hi = report["paired_diff_ci95"]
    assert lo <= report["paired_diff_mean"] <= hi
    for i, rec in enumerate(records):
        assert rec["engine_version"] == ENGINE_VERSION
        assert rec["players"].count("candidate") == 1
        assert rec["players"].index("candidate") == i % 4
        state = replay_hand(rec)
        assert state.phase == Phase.HAND_OVER
        assert [s.score for s in state.seats] == rec["result"]["final_scores"]
    seeds = {r["seed"] for r in records}
    assert seeds == {5, 6}


def test_refuses_an_omniscient_opponent():
    with pytest.raises(ValueError, match="unknown opponent"):
        evaluate([5], _RULESET, "ORACLE", model=_model())


def test_same_seeds_same_report():
    a, _ = evaluate([3], _RULESET, "EfficiencyBot", model=_model())
    b, _ = evaluate([3], _RULESET, "EfficiencyBot", model=_model())
    assert a == b


def test_bootstrap_ci_brackets_the_mean():
    x = np.random.default_rng(0).standard_t(3, size=300)
    lo, hi = bootstrap_ci(x)
    assert lo < x.mean() < hi


def test_loads_a_ppo_checkpoint(tmp_path):
    cfg = PPOConfig(
        out=str(tmp_path / "run"),
        envs=2,
        workers=0,
        batch_size=32,
        minibatch=32,
        channels=8,
        blocks=1,
        stage={"min_faan": 0},
    )
    out = train_ppo(cfg, max_updates=1)
    model = load_candidate(str(out / "ckpt_last.pt"))
    report, _ = evaluate([1], _RULESET, "EfficiencyBot", model=model)
    assert report["candidate"]["hands_played"] == 4
