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
    "classic/uniform/game": "04acc29313e6aaa047147036b236c7fa0f6522ca50a93e0d58505f5037ef2413",
    "classic/uniform/hand": "b1946eda25d98339e5e31fecf8b693ed054e09b671eba8962795c0bd5fae0403",
    "classic/greedy/game": "564ef61aabcdbce1768f3e9221fea6363e53dced7deef8a975f1ddf03ccdd9e9",
    "classic/greedy/hand": "fd6961ac00e061ecc503580b0e8ca84587c8072f6a16679115df02c0a76cf031",
    "casual/uniform/game": "646b1c790fef5f4ceec2cd904f9329e8b37035b0472f7a50dca5fbbdd85fe61f",
    "casual/uniform/hand": "e17b1d82d39b54ec88f4b192cf1daeabbfa2f3013273b775b6bc6b70cabadf83",
    "casual/greedy/game": "829b5b74a4c2d5eabefcba006d837e39ccb49b44ec9951ac2a2593edc9559254",
    "casual/greedy/hand": "9ce3b60310dd94f912856ec015e08fd16df8b023697d97645e4140c5ab037813",
    "strict/uniform/game": "e979d1ddc6bc0dfbdb6696cf0ee1fc2f37fe67202b14c116b960780641573233",
    "strict/uniform/hand": "185fc647a0656104fb5061f4abe51f938e7ef812e623c65de67c2fb97ba44ec3",
    "strict/greedy/game": "2a1c1a69083af4fa62aad745e25d7589b6cd54ac4f2f51b82d872ba764ad7b7f",
    "strict/greedy/hand": "25626f5f3c1111f7ea28bf499deb28ce5862f6562d04a5059614aa44c1cd58a5",
    "zero_es/uniform/game": "6413757b4b95e83c68c7c0e9c4679c7e59186c18c8d13699f63ec73d2ed75a7e",
    "zero_es/uniform/hand": "b981b4079c519acafd98d2d6dac94a5b7563f3d8d13c873b0985215d64dac7f6",
    "zero_es/greedy/game": "3ba501e01940a9a11d01f7b3d630c3d882e17a68a7733210be9100c7bacec59d",
    "zero_es/greedy/hand": "1459bc0234e95ff3cc24a57153ef1bac60ce42d6971a42757ef9f00c8382aacc",
    "exotic/uniform/game": "233dfa34cf802ed7cc1283fcb23d866fc626423a3e784ceb991fd0bc5d063fee",
    "exotic/uniform/hand": "6ce904d20de892523de2883e862e0de745b9fb00fc4e1931c835784e992ea99c",
    "exotic/greedy/game": "b15b3f9b1d7c8df9ac4b1c865437503f25d1af36afcf90e89f58a0f0227ad76d",
    "exotic/greedy/hand": "97d078303be87d4024a02e9c166e7a77accde3c249a1c75d4b1e9e0d803c5df9",
    "no_flowers/uniform/game": "9a4ee7c22c20d0d522e661cb34ee988624c8cecae89ea4433db94fdd033b4d1e",
    "no_flowers/uniform/hand": "dded4b0f97cd3d880804911e7353307519d28d49f6d63c2571a843a59a48c03e",
    "no_flowers/greedy/game": "de0dc8998d440359cc4c5ae62a318c17aaf5191246b88d9f0524e457be55abde",
    "no_flowers/greedy/hand": "c80c8b950f407db7a0336d7cbeb9095d895d983582c278d4f587679eeccc15d6",
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
