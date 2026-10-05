"""Whole-engine trajectory pin: the guard for behaviour-neutral engine speed-ups
(docs/ml.md §7). Each case plays seeded games through `reduce`/`start_next_hand` and hashes
every action, every event, every hand result and the final `GameState`. The digests were
generated before any speed-up landed, so a mismatch means an optimisation changed behaviour.

Regenerate only for an intended behaviour change (which also bumps `ENGINE_VERSION`):

    uv run python -m tests.test_engine_trajectory_pin
"""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Callable
from dataclasses import fields, is_dataclass, replace
from enum import Enum
from typing import Any

import pytest

from mahjong_core.actions import Action, ActionKind, Discard, legal_actions
from mahjong_core.config import DEFAULT_RULESET, GameLength, RuleSet
from mahjong_core.engine import new_hand, prevailing_winds, reduce, start_next_hand
from mahjong_core.presets import RULESET_PRESETS
from mahjong_core.shanten import shanten
from mahjong_core.state import GameState, Phase, new_game
from mahjong_core.tiles import count_array_from_types, tile_id_type

_STEP_CAP = 20_000

_BOUNDED = {"dealer_repeat_on_win": False, "dealer_repeat_on_draw": False}

_RULESETS: dict[str, RuleSet] = {
    "classic": replace(DEFAULT_RULESET, **_BOUNDED),
    "casual": replace(RULESET_PRESETS["hk_casual"], **_BOUNDED),
    "strict": replace(RULESET_PRESETS["hk_strict"], **_BOUNDED),
    "zero_es": replace(DEFAULT_RULESET, min_faan=0, game_length=GameLength.EAST_SOUTH, **_BOUNDED),
    "exotic": replace(
        DEFAULT_RULESET,
        min_faan=0,
        wall_reserve=14,
        four_kong_abort=True,
        nine_terminals_abort=True,
        tenpai_payments=True,
        seven_flowers_instant_win=True,
        eight_flowers_instant_win=True,
        thirteen_orphans_wait_bonus=True,
        concealed_kong_robbable=True,
        **_BOUNDED,
    ),
    "no_flowers": replace(DEFAULT_RULESET, min_faan=1, flowers_enabled=False, **_BOUNDED),
}

_WIN_KINDS = {ActionKind.DECLARE_WIN, ActionKind.CLAIM_WIN}
_KONG_KINDS = {
    ActionKind.CLAIM_KONG,
    ActionKind.DECLARE_CONCEALED_KONG,
    ActionKind.DECLARE_ADDED_KONG,
}
_TAKE_P = {ActionKind.CLAIM_PUNG: 0.5, ActionKind.CLAIM_CHOW: 0.3}


def _uniform(state: GameState, seat: int, acts: tuple[Action, ...], rng: random.Random) -> Action:
    return rng.choice(acts)


def _greedy(state: GameState, seat: int, acts: tuple[Action, ...], rng: random.Random) -> Action:
    """claims, kongs and min-shanten discards, so wins and scoring paths actually get exercised."""
    for kinds, p in ((_WIN_KINDS, 0.95), (_KONG_KINDS, 0.7)):
        hits = [a for a in acts if a.kind in kinds]
        if hits and rng.random() < p:
            return rng.choice(hits)
    for kind, p in _TAKE_P.items():
        hits = [a for a in acts if a.kind == kind]
        if hits and rng.random() < p:
            return rng.choice(hits)
    discards = [a for a in acts if isinstance(a, Discard)]
    if not discards or rng.random() < 0.1:
        return rng.choice(acts)
    me = state.seats[seat]
    counts = count_array_from_types(tile_id_type(t) for t in me.concealed)
    closed = not me.melds

    def after(d: Discard) -> int:
        tt = int(tile_id_type(d.tile_id))
        counts[tt] -= 1
        s = shanten(counts, closed=closed, hand_sets=state.ruleset.hand_sets)
        counts[tt] += 1
        return s

    scored = [(after(d), d) for d in discards]
    best = min(s for s, _ in scored)
    return rng.choice([d for s, d in scored if s == best])


_POLICIES: dict[str, Callable[[GameState, int, tuple[Action, ...], random.Random], Action]] = {
    "uniform": _uniform,
    "greedy": _greedy,
}


def _canon(obj: Any) -> Any:
    if is_dataclass(obj) and not isinstance(obj, type):
        return [type(obj).__name__, {f.name: _canon(getattr(obj, f.name)) for f in fields(obj)}]
    if isinstance(obj, Enum):
        return f"{type(obj).__name__}.{obj.name}"
    if isinstance(obj, (set, frozenset)):
        return sorted((_canon(x) for x in obj), key=json.dumps)
    if isinstance(obj, dict):
        items = [[_canon(k), _canon(v)] for k, v in obj.items()]
        return sorted(items, key=json.dumps)
    if isinstance(obj, (list, tuple)):
        return [_canon(x) for x in obj]
    if isinstance(obj, bytes):
        return obj.hex()
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    raise TypeError(f"no canonical form for {type(obj).__name__}")


def _feed(digest: Any, obj: Any) -> None:
    digest.update(json.dumps(_canon(obj), separators=(",", ":")).encode())
    digest.update(b"\n")


def _play(state: GameState, stop: Phase, policy: str, seed: int, digest: Any) -> GameState:
    rng = random.Random(f"pin:{policy}:{seed}")
    pick = _POLICIES[policy]
    for _ in range(_STEP_CAP):
        if state.phase == stop:
            _feed(digest, state)
            return state
        if state.phase == Phase.HAND_OVER:
            _feed(digest, state.hand_result)
            state, events = start_next_hand(state)
            _feed(digest, events)
            continue
        if state.phase in (Phase.AWAIT_CLAIMS, Phase.AWAIT_KONG_ROB):
            assert state.claim_window is not None
            window = state.claim_window
            seat = rng.choice([o.seat for o in window.offers if o.seat not in window.responses])
        else:
            seat = state.turn
        action = pick(state, seat, legal_actions(state, seat), rng)
        _feed(digest, action)
        state, events = reduce(state, action)
        _feed(digest, events)
    raise AssertionError(f"{policy} seed={seed}: exceeded {_STEP_CAP} steps")


def _case_digest(ruleset_name: str, policy: str, mode: str, seeds: range) -> str:
    ruleset = _RULESETS[ruleset_name]
    digest = hashlib.sha256()
    for seed in seeds:
        if mode == "game":
            _play(new_game(ruleset, seed), Phase.GAME_OVER, policy, seed, digest)
            continue
        winds = prevailing_winds(ruleset)
        start = new_hand(ruleset, seed, dealer=seed % 4, prevailing=winds[seed % len(winds)])
        _play(start, Phase.HAND_OVER, policy, seed, digest)
    return digest.hexdigest()


def _cases() -> list[tuple[str, str, str, range]]:
    out: list[tuple[str, str, str, range]] = []
    for name in _RULESETS:
        for policy in _POLICIES:
            out.append((name, policy, "game", range(3)))
            out.append((name, policy, "hand", range(100, 140)))
    return out


_PINNED: dict[str, str] = {
    "classic/uniform/game": "9695ef3d39e9f695dde783b4982f15c0bb8be26684fa9a035c17df0b6b330df7",
    "classic/uniform/hand": "d5f6dacc9a1b2e6d1b59a6dfeded894cca7a80bce8f4666356ac8763159c3108",
    "classic/greedy/game": "f47a5ac4b825d145a8fa999a6b6a23a934bdd40335cb53efa14d4275c3cddd70",
    "classic/greedy/hand": "8946878c7185f0e7ee77e4f1e156901a18e32c9954f165511379fa2d56e70164",
    "casual/uniform/game": "9ed84e3952b8ec2ea614cc9c1bb12a0cc4d5a4c73b40858313197484fbd05330",
    "casual/uniform/hand": "b2d97d6940609a95320122f78c8a82476c290145bf3b16cf833579bcbaaee6a4",
    "casual/greedy/game": "d2a7cfd15fe9d9bfa03253dade810b6a27cc61c33d3859404981c39d4f247781",
    "casual/greedy/hand": "f88e6dafacdb35b6a71361b8b1eb6ed3dbad75fe7b1a7c5776ceab1bcb868f8e",
    "strict/uniform/game": "7de286c1b3e817b3cf68a02f34c63d102f25c35c17db8c5d2af48ee48fe88231",
    "strict/uniform/hand": "76b48ee25e23b2d457de86f1f2140cd835a8336cfa4ccfeb24202ec1100b2907",
    "strict/greedy/game": "ef799a7dc80c4ded839ae95f1ed6f305a5f6aac3540034cce433134bc423f6af",
    "strict/greedy/hand": "bff1cc93da8e5bf93b91765f0ad74deab12fb6ffcbe2f30fcf370240e6b8f9d5",
    "zero_es/uniform/game": "4a986c43cf245f0c0da2385bbc83c99cbda2eada1863467ba2888033b486070a",
    "zero_es/uniform/hand": "288fa1dca93acb3517b5c6af692feabaabc31042eefc57e1c0fe437447f38964",
    "zero_es/greedy/game": "f71097a604978c212c6f36ae9ffc7061126f6efc40d9246f425a74ab5504abb7",
    "zero_es/greedy/hand": "822425457e874f1815bc89327beb287dd6ccdc6fe775d3ca6cad20d7105ffa8c",
    "exotic/uniform/game": "e5689bece9ad5f8d86bff0e3027a99771b298203cdbef04b90c332047b7d217a",
    "exotic/uniform/hand": "dbca464acaba3818fde53c4743215f8bc90ce2999baaafd3db9ee949f5ec0557",
    "exotic/greedy/game": "f3da91f4c0efb0eb71f5bdb6f6ede85dc764740e4ced3923065416e8c1016cd0",
    "exotic/greedy/hand": "79f0e1a20df465382dfc18ef86695b3f64dcc5c76efbacfa06ae4a1aeddee6cb",
    "no_flowers/uniform/game": "5cba2623ddc735e01b4a089c3d28446506cd7ac2a04f8796d9a59290cd5d4cb4",
    "no_flowers/uniform/hand": "82b6e34476c6019feb89cdaa456d9687f7c85131b8577a2a205222e34886afcf",
    "no_flowers/greedy/game": "bbaee407c116794871d21abe2ef962a95313f8d6531f77a0b23f6f84de5875e6",
    "no_flowers/greedy/hand": "b15824f2b6c9f76663d57b95b12c90fddf7d4d70bdc2943c36fa4899bc406e82",
}


@pytest.mark.parametrize(
    ("ruleset_name", "policy", "mode", "seeds"),
    _cases(),
    ids=lambda v: v if isinstance(v, str) else f"{v.start}-{v.stop}",
)
def test_trajectory_digest_is_pinned(ruleset_name: str, policy: str, mode: str, seeds: range):
    key = f"{ruleset_name}/{policy}/{mode}"
    assert _case_digest(ruleset_name, policy, mode, seeds) == _PINNED[key]


if __name__ == "__main__":
    for name, policy, mode, seeds in _cases():
        print(f'    "{name}/{policy}/{mode}": "{_case_digest(name, policy, mode, seeds)}",')
