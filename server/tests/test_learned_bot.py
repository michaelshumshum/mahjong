"""`bots/learned.py`'s `LearnedBot` (`T4`, Expert; docs/bots.md §2, docs/ml.md §14 R4): the shipped
weights' provenance, legal play on the public view only, and a torch-free serving path. Base deps
only; the torch parity test on the shipped weights is `tests/test_ml_learned_parity.py`."""

from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from pathlib import Path

import pytest

import bots.learned
from app.views import _omniscient_seat_view, seat_view
from bots.arena import BOT_REGISTRY, OMNISCIENT_BOTS
from bots.learned import DEFAULT_WEIGHTS, LearnedBot, policy_meta, weights_problem
from bots.tiers import BOT_TIERS
from bots.worker import compute_action
from mahjong_core.engine import ENGINE_VERSION
from ml.env import HandEnv
from ml.export import EXPORT_VERSION
from tests.latency import check_latency

_SERVER_ROOT = Path(__file__).resolve().parents[1]


def _decisions(n_hands: int, seed0: int = 0) -> list[tuple[object, int, list[bool]]]:
    """`(state, seat, mask)` for every decision of `n_hands` hands played by `LearnedBot`."""
    bot = LearnedBot()
    out = []
    for seed in range(seed0, seed0 + n_hands):
        env = HandEnv(encode=False)
        seat, _, mask = env.reset(seed)
        while not env.done:
            assert env.state is not None
            m = mask.tolist()
            out.append((env.state, seat, m))
            aid = asyncio.run(bot.act(seat_view(env.state, seat), m, 0.0))
            assert m[aid]
            seat, _, mask, _, _ = env.step(aid)
    return out


def test_shipped_weights_record_their_source() -> None:
    meta = policy_meta()
    assert meta is not None
    assert meta["source"] == "ckpt_L274.3M.pt"
    assert meta["decisions"] == 274_239_759
    assert meta["algorithm"] == "ppo"
    assert meta["export_version"] == EXPORT_VERSION
    # the ruleset encoding is engine-versioned (docs/ml.md §9): a bump needs a re-export
    assert meta["engine_version"] == ENGINE_VERSION
    assert DEFAULT_WEIGHTS.stat().st_size < 4_000_000


def test_weights_problem_passes_the_shipped_file_and_names_a_broken_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """the api's startup check (app/main.py, docs/bots.md §2): missing, corrupt, truncated, or
    exported for another engine."""
    assert weights_problem() is None
    assert "FileNotFoundError" in str(weights_problem(tmp_path / "missing.npz"))
    (tmp_path / "corrupt.npz").write_bytes(b"not an npz")
    assert "ValueError" in str(weights_problem(tmp_path / "corrupt.npz"))
    blob = DEFAULT_WEIGHTS.read_bytes()
    (tmp_path / "truncated.npz").write_bytes(blob[: len(blob) // 2])
    assert "BadZipFile" in str(weights_problem(tmp_path / "truncated.npz"))
    monkeypatch.setattr(bots.learned, "ENGINE_VERSION", "0.0.0")
    assert "engine_version" in str(weights_problem())


def test_plays_legal_actions_on_the_public_view() -> None:
    decisions = _decisions(2)
    assert len(decisions) > 50
    # claim decisions occur, not only discards
    assert any(any(m[102:]) and sum(m) > 1 for _, _, m in decisions)


def test_refuses_an_omniscient_view() -> None:
    env = HandEnv(encode=False)
    seat, _, mask = env.reset(0)
    assert env.state is not None
    with pytest.raises(ValueError, match="omniscient"):
        asyncio.run(LearnedBot().act(_omniscient_seat_view(env.state, seat), mask.tolist(), 0.0))


def test_registered_as_t4_and_in_the_arena() -> None:
    assert "T4" in BOT_TIERS
    assert "LearnedBot" in BOT_REGISTRY
    assert "LearnedBot" not in OMNISCIENT_BOTS
    assert isinstance(BOT_REGISTRY["LearnedBot"](0), LearnedBot)


def test_worker_t4_matches_the_bot() -> None:
    env = HandEnv(encode=False)
    seat, _, mask = env.reset(3)
    assert env.state is not None
    view = seat_view(env.state, seat)
    m = mask.tolist()
    expected = asyncio.run(LearnedBot().act(view, m, 0.0))
    assert compute_action(view, m, 0, "T4", 0.0) == expected


def test_serving_never_imports_torch() -> None:
    """Fresh interpreter: the live path loads numpy and the four sanctioned `ml` modules only
    (`ml/__init__.py`)."""
    code = (
        "import asyncio, sys\n"
        "from app.views import seat_view\n"
        "from bots.worker import compute_action\n"
        "from mahjong_core.engine import new_game\n"
        "from mahjong_core.ml import legal_mask\n"
        "from mahjong_core.config import DEFAULT_RULESET\n"
        "state = new_game(DEFAULT_RULESET, 0)\n"
        "seat = state.turn\n"
        "compute_action(seat_view(state, seat), legal_mask(state, seat), 0, 'T4', 0.0)\n"
        "ml = sorted(m for m in sys.modules if m == 'ml' or m.startswith('ml.'))\n"
        "print(','.join(ml)); print('torch' in sys.modules)\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=_SERVER_ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    assert out[0].split(",") == ["ml", "ml.encode", "ml.encode_v2", "ml.export", "ml.raw"]
    assert out[1] == "False"


@pytest.mark.slow
@pytest.mark.latency
def test_single_decision_latency() -> None:
    """docs/ml.md §14 R4's "bot load not regressed": a `T4` decision through `compute_action` costs
    less than a `T2` one at p99 (`seat_view` excluded: the table builds it for every tier). The
    absolute 5 ms is `make bench-latency` (`tests/latency.py`)."""
    decisions = _decisions(5, seed0=100)[:400]
    views = [(seat_view(s, seat), m) for s, seat, m in decisions]  # type: ignore[arg-type]
    for view, m in views[:20]:
        compute_action(view, m, 0, "T4", 0.0)
        compute_action(view, m, 0, "T2", 0.0)
    t4, t2 = [], []
    for view, m in views:
        start = time.perf_counter()
        compute_action(view, m, 0, "T4", 0.0)
        mid = time.perf_counter()
        compute_action(view, m, 0, "T2", 0.0)
        t4.append(mid - start)
        t2.append(time.perf_counter() - mid)
    check_latency("T4 decision", t4, "T2", t2)
