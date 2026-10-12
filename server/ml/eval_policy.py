"""R2 evaluation: paired-duplicate hands, candidate × 1 vs a heuristic bot × 3 (docs/ml.md §12,
docs/bots.md §7). `ml`-extra only.

    python -m ml.eval_policy --ckpt runs/ppo_c0/ckpt_last.pt --sets 200 --seed 1000000 \
        [--opponent EfficiencyBot] [--min-faan 3] [--parallel 6] [--records eval.jsonl]
    python -m ml.eval_policy --candidate-bot FaanBot --opponent ORACLE ...   # calibration
    python -m ml.eval_policy --candidate-bot LearnedBot --opponent FaanBot ...  # shipped T4
    python -m ml.eval_policy --candidate-bot ORACLE --opponent LearnedBot ...   # Impossible gate

A duplicate set is one `HandEnv` episode seed (`hand_start` picks dealer and prevailing wind)
played four times, the candidate in each seat in turn. The candidate (`PolicyBot`) acts only on
`seat_view(...)` through `policy_raw_from_view`: no oracle input exists on this path. Every
`BOT_REGISTRY` seat, opponent or `--candidate-bot`, is served through `bots.arena._view_for`, the
arena's sanctioned omniscient call site (docs/bots.md §9), so an `OMNISCIENT_BOTS` name gets the
full view and every other seat a plain `seat_view`; a `PolicyBot` seat never does. Each played
hand is wrapped as a one-hand `bots.arena.GameRecord`, so `bots.arena`'s statistics, paired
differences (candidate − mean of the others, per set) and normal CI apply unchanged; a seeded
percentile bootstrap CI is added because payouts are heavy-tailed. Units are points per hand.
Every hand is exportable as `HandRecord` columns (`--records`, one JSON object per line).
"""

from __future__ import annotations

import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import argparse
import asyncio
import dataclasses
import functools
import json
import sys
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import torch

from app.views import SeatView, seat_view
from bots.arena import (
    BOT_REGISTRY,
    OMNISCIENT_BOTS,
    GameRecord,
    HandRecord,
    _collect_stats,
    _mean_ci95,
    _paired_differences,
    _roles_for_rotation,
    _tenpai_can_reach_min_faan,
    _view_for,
)
from bots.base import Bot
from bots.labels import is_tenpai
from mahjong_core.actions import Discard
from mahjong_core.config import RuleSet
from mahjong_core.presets import RULESET_PRESETS
from mahjong_core.state import HandOutcome
from ml.encode_v2 import encode_policy_batch, policy_raw_from_view, ruleset_features
from ml.env import HandEnv
from ml.policy_net import PolicyNet, PolicyNetConfig, masked_log_softmax

__all__ = ["PolicyBot", "bootstrap_ci", "evaluate", "load_candidate", "main", "play_set"]


class PolicyBot:
    """`Bot` over a `PolicyNet`: greedy, or sampled from `rng` when given."""

    def __init__(self, model: PolicyNet, rng: np.random.Generator | None = None) -> None:
        self.model = model.eval()
        self.rng = rng

    async def act(self, view: SeatView, mask: list[bool], deadline: float) -> int:
        del deadline
        row = policy_raw_from_view(view)
        tiles, scalars = encode_policy_batch(
            {k: v[None] for k, v in row.items()}, ruleset_features(view.ruleset)
        )
        legal = torch.tensor(mask)[None]
        with torch.no_grad():
            logits = self.model(
                torch.from_numpy(tiles), torch.from_numpy(scalars), aux=False
            ).logits
            logp = masked_log_softmax(logits, legal)[0].numpy()
        if self.rng is None:
            return int(np.argmax(logp))
        p = np.exp(logp - logp.max())
        return int(self.rng.choice(len(p), p=p / p.sum()))


def _opponent_choices() -> list[str]:
    return sorted(BOT_REGISTRY)


def _candidate_bot_choices() -> list[str]:
    return sorted(BOT_REGISTRY)


def load_candidate(path: str) -> PolicyNet:
    """A `ml.ppo` checkpoint (`learner.policy`) or an R1 `rl_aux` one (`model`)."""
    ckpt = torch.load(path, weights_only=False, map_location="cpu")
    state = ckpt["learner"]["policy"] if "learner" in ckpt else ckpt["model"]
    model = PolicyNet(PolicyNetConfig(**ckpt["model_config"]))
    model.load_state_dict(state)
    return model


def _hand(env: HandEnv) -> HandRecord:
    state = env.state
    assert state is not None and state.hand_result is not None
    result = state.hand_result
    tenpai: list[int] = []
    sub_min: list[int] = []
    if result.outcome == HandOutcome.EXHAUSTIVE_DRAW:
        for s in range(4):
            if is_tenpai(state, s):
                tenpai.append(s)
                if not _tenpai_can_reach_min_faan(state, s):
                    sub_min.append(s)
    won = result.outcome == HandOutcome.WIN
    return HandRecord(
        hand_no=state.hand_no,
        outcome=result.outcome,
        winner=result.winner if won else None,
        win_type=result.win_type if won else None,
        discarder=result.discarder if won else None,
        faan=result.faan,
        payments=tuple(result.payments.get(s, 0) for s in range(4)),  # type: ignore[arg-type]
        turns=sum(isinstance(a, Discard) for a in env.actions),
        tenpai_seats=tuple(tenpai),
        sub_minimum_tenpai_seats=tuple(sub_min),
    )


def _view(state: Any, seat: int, bot: Bot, name: str | None) -> SeatView:
    if name is None or isinstance(bot, PolicyBot):
        return seat_view(state, seat)
    return _view_for(state, seat, name)


async def _play(
    seed: int,
    ruleset: RuleSet,
    bots: Sequence[Bot],
    names: Sequence[str | None] | None = None,
) -> tuple[HandRecord, dict[str, Any]]:
    """`names` routes each named non-`PolicyBot` seat through `_view_for`; a `None` name, a
    `PolicyBot` or no `names` at all gets `seat_view`."""
    env = HandEnv(ruleset, encode=False)
    seat, _, mask = env.reset(seed)
    while not env.done:
        assert env.state is not None
        name = names[seat] if names is not None else None
        view = _view(env.state, seat, bots[seat], name)
        aid = await bots[seat].act(view, mask.tolist(), float("inf"))
        seat, _, mask, _, _ = env.step(aid)
    return _hand(env), env.record()


_WORKER: dict[str, Any] = {}


def _init_worker(ckpt: str | None) -> None:
    torch.set_num_threads(1)
    if ckpt is not None:
        _WORKER["model"] = load_candidate(ckpt)


def play_set(
    seed: int,
    ruleset: RuleSet,
    opponent: str,
    model: PolicyNet | None = None,
    candidate: str = "candidate",
    candidate_bot: str | None = None,
) -> tuple[tuple[GameRecord, ...], list[dict[str, Any]]]:
    """One duplicate set: four `GameRecord`s (one hand each) and their `HandRecord` columns.
    `candidate_bot` seats a `BOT_REGISTRY` bot as the candidate instead of the policy."""
    net = None if candidate_bot else model if model is not None else _WORKER["model"]

    async def run() -> tuple[tuple[GameRecord, ...], list[dict[str, Any]]]:
        games, records = [], []
        for rotation in range(4):
            bots: list[Bot] = [BOT_REGISTRY[opponent](seed * 4 + i) for i in range(4)]
            if candidate_bot is None:
                assert net is not None
                bots[rotation] = PolicyBot(net)
            else:
                bots[rotation] = BOT_REGISTRY[candidate_bot](seed * 4 + rotation)
            names: list[str | None] = [opponent] * 4
            names[rotation] = candidate_bot  # None for the policy: plain `seat_view`
            hand, record = await _play(seed, ruleset, bots, names)
            players = [opponent] * 4
            players[rotation] = candidate
            record["players"] = players
            games.append(
                GameRecord(
                    seed=seed,
                    roles=_roles_for_rotation(rotation),
                    hands=(hand,),
                    final_scores=hand.payments,
                )
            )
            records.append(record)
        return tuple(games), records

    return asyncio.run(run())


def bootstrap_ci(values: Sequence[float], seed: int = 0, n: int = 10_000) -> tuple[float, float]:
    x = np.asarray(values, dtype=np.float64)
    means = np.random.default_rng(seed).choice(x, size=(n, len(x)), replace=True).mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(lo), float(hi)


def evaluate(
    seeds: Sequence[int],
    ruleset: RuleSet,
    opponent: str,
    *,
    ckpt: str | None = None,
    model: PolicyNet | None = None,
    parallel: int = 1,
    candidate_bot: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if opponent not in BOT_REGISTRY:
        raise ValueError(f"unknown opponent {opponent!r}; choices: {_opponent_choices()}")
    if candidate_bot is not None and candidate_bot not in _candidate_bot_choices():
        raise ValueError(
            f"unknown candidate bot {candidate_bot!r}; choices: {_candidate_bot_choices()}"
        )
    play = functools.partial(
        play_set, ruleset=ruleset, opponent=opponent, candidate_bot=candidate_bot
    )
    sets: list[tuple[GameRecord, ...]] = []
    records: list[dict[str, Any]] = []
    if parallel > 1:
        assert ckpt is not None or candidate_bot is not None, (
            "parallel evaluation loads the checkpoint in each worker"
        )
        with ProcessPoolExecutor(parallel, initializer=_init_worker, initargs=(ckpt,)) as pool:
            for games, recs in pool.map(play, seeds):
                sets.append(games)
                records += recs
    else:
        net = None
        if candidate_bot is None:
            net = model if model is not None else load_candidate(str(ckpt))
        for s in seeds:
            games, recs = play(s, model=net)
            sets.append(games)
            records += recs
    stats_a, stats_b = _collect_stats(sets)
    diffs = _paired_differences(sets)
    mean, lo, hi = _mean_ci95(diffs)
    hands = [g.hands[0] for games in sets for g in games]
    report = {
        "sets": len(sets),
        "opponent": opponent,
        "candidate_bot": candidate_bot,
        "candidate_omniscient": candidate_bot in OMNISCIENT_BOTS,
        "min_faan": ruleset.min_faan,
        "candidate": stats_a.summary(),
        "opponents": stats_b.summary(),
        "exhaustive_draw_rate": sum(h.outcome == HandOutcome.EXHAUSTIVE_DRAW for h in hands)
        / max(1, len(hands)),
        "paired_diff_mean": mean,
        "paired_diff_ci95": [lo, hi],
        "paired_diff_bootstrap_ci95": list(bootstrap_ci(diffs)) if len(diffs) > 1 else [mean, mean],
    }
    return report, records


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m ml.eval_policy", description=__doc__)
    who = parser.add_mutually_exclusive_group(required=True)
    who.add_argument("--ckpt")
    who.add_argument(
        "--candidate-bot",
        choices=_candidate_bot_choices(),
        help="a BOT_REGISTRY candidate instead (a heuristic, the shipped LearnedBot, or ORACLE)",
    )
    parser.add_argument("--sets", type=int, default=200)
    parser.add_argument("--seed", type=int, default=1_000_000, help="set i uses seed + i")
    parser.add_argument("--opponent", default="EfficiencyBot", choices=_opponent_choices())
    parser.add_argument("--ruleset", default="hk_classic", choices=sorted(RULESET_PRESETS))
    parser.add_argument("--min-faan", type=int, help="override the preset's min_faan")
    parser.add_argument("--parallel", type=int, default=1)
    parser.add_argument("--records", type=Path, help="write HandRecord columns as JSON lines")
    parser.add_argument("--out", type=Path, help="write the report as JSON")
    args = parser.parse_args(argv)
    torch.set_num_threads(1)
    ruleset = RULESET_PRESETS[args.ruleset]
    if args.min_faan is not None:
        ruleset = dataclasses.replace(ruleset, min_faan=args.min_faan)
    seeds = [args.seed + i for i in range(args.sets)]
    report, records = evaluate(
        seeds,
        ruleset,
        args.opponent,
        ckpt=args.ckpt,
        parallel=args.parallel,
        candidate_bot=args.candidate_bot,
    )
    report["ckpt"] = args.ckpt
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        args.out.write_text(text)
    if args.records:
        with args.records.open("w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")


if __name__ == "__main__":
    main(sys.argv[1:])
