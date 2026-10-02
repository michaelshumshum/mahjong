"""Auxiliary-head pipeline (docs/06-ml.md §8): `ml.generate_aux` labels, `ml.aux_data` packing and
targets, `ml.train`'s `rl_aux` dispatch and `ml.aux_eval`. Uses `EfficiencyBot` states for speed."""

from __future__ import annotations

from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")

from app.views import seat_view
from mahjong_core.presets import DEFAULT_PRESET_ID, RULESET_PRESETS
from ml import train as ml_train
from ml.aux_data import AuxData, danger_raw, pack_aux
from ml.aux_eval import evaluate_aux_model, load_policy
from ml.danger_model import DangerNet, DangerNetConfig
from ml.encode_v2 import PAD, policy_raw, stack_rows
from ml.env import HandEnv
from ml.generate_aux import main as generate_main
from ml.generate_aux import record_game
from ml.raw import raw_row

_BOTS = ["EfficiencyBot"] * 4
_RULESET = RULESET_PRESETS[DEFAULT_PRESET_ID]


@pytest.fixture(scope="module")
def packed(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("aux")
    generate_main(
        [
            "--out",
            str(root / "raw"),
            "--games",
            "16",
            "--bots",
            ",".join(_BOTS),
            "--shard-games",
            "10",
            "--max-hands",
            "1",
            "--parallel",
            "2",
        ]
    )
    pack_aux(root / "raw", root / "packed")
    return root / "packed"


def test_record_game_labels_are_consistent() -> None:
    rows = record_game(3, _RULESET, _BOTS, max_hands=3)
    assert rows["win"].any()
    n = len(rows["seat"])
    assert n > 0 and all(len(v) == n for v in rows.values())
    own = rows["own_turn"] > 0
    held = rows["concealed"] > 0
    sh = rows["shanten"]
    assert ((sh != PAD) == (held & own[:, None])).all()
    assert (sh[sh != PAD] <= 8).all()
    assert (rows["ukeire"][sh == PAD] == 0).all()
    assert ((rows["opp_wait"].sum(2) > 0) == (rows["opp_tenpai"] > 0)).all()
    assert (rows["opp_faan"][rows["opp_wait"] == 0] == 0).all()
    for hand in np.unique(rows["hand_no"]):
        h = rows["hand_no"] == hand
        winners = set(rows["seat"][h & (rows["win"] > 0)].tolist())
        assert len(winners) <= 1
        assert not (rows["win"][h] & rows["deal_in"][h]).any()
        assert (rows["payment"][h & (rows["win"] > 0)] > 0).all()


def test_danger_raw_is_the_v3_row_layout() -> None:
    env = HandEnv(encode=False)
    env.reset(5)
    rng = np.random.default_rng(0)
    states, seats = [], []
    while not env.done:
        assert env.state is not None
        states.append(env.state)
        seats.append(env._seat)
        env.step(int(rng.choice(np.flatnonzero(env._mask_array()))))
    raw = stack_rows([policy_raw(s, seat) for s, seat in zip(states, seats, strict=True)])
    converted = danger_raw(raw)
    for i, (s, seat) in enumerate(zip(states, seats, strict=True)):
        ref = raw_row(seat_view(s, seat))
        for k, v in converted.items():
            if k == "discard_seq":
                pools = [list(p) for p in ref[k]]
                got = [[t for t in row if t != PAD] for row in v[i].tolist()]
                assert got == pools
            else:
                assert np.array_equal(v[i], np.asarray(ref[k])), k


def test_hidden_targets_match_public_slot_counts(packed: Path) -> None:
    data = AuxData(packed)
    assert data.meta["games"] == 16
    rows = np.arange(data.meta["rows"])
    inputs, t, _ = data.arrays(rows, oracle=True)
    assert inputs["tiles"].shape[0] == inputs["oracle"].shape[0] == len(rows)
    assert np.array_equal(t["hidden"].sum(axis=2), t["slots"])
    assert set(np.unique(data.raw["split"]).tolist()) <= {0, 1, 2}


def test_train_dispatch_and_eval(packed: Path, tmp_path: Path) -> None:
    algorithm, _ = ml_train.load_config(Path("ml/configs/rl_aux.yaml"))
    assert algorithm == "rl_aux"
    config = tmp_path / "c.yaml"
    config.write_text(
        "algorithm: rl_aux\nchannels: 16\nblocks: 1\nbatch_size: 32\nsteps: 4\nwarmup: 1\n"
        "eval_every: 2\neval_samples: 64\nsave_every: 2\nlog_every: 2\nthreads: 1\n"
    )
    out = tmp_path / "run"
    ml_train.main(["--config", str(config), "--data", str(packed), "--out", str(out)])
    assert (out / "ckpt_best.pt").exists() and (out / "ckpt_last.pt").exists()
    lines = (out / "metrics.jsonl").read_text().splitlines()
    assert any("val_hidden" in line for line in lines)

    model = load_policy(out / "ckpt_best.pt")
    data = AuxData(packed)
    danger = DangerNet(DangerNetConfig(channels=16, blocks=1)).eval()
    result = evaluate_aux_model(model, data, np.arange(data.meta["rows"]), danger=danger, n_boot=20)
    for key in (
        "policy_legal_wait_auc",
        "danger_legal_wait_auc",
        "legal_wait_auc_policy_minus_danger",
        "hidden_nll_model",
        "hidden_nll_uniform",
        "win_auc",
    ):
        assert key in result, key
    point, lo, hi = result["hidden_nll_gain"]
    assert lo <= point <= hi
