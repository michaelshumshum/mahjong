"""Seeded self-play decision points and action masks for bot/ML policy tests."""

import random
from collections.abc import Iterator

from bots.random import random_action
from mahjong_core.config import RuleSet
from mahjong_core.engine import new_game, reduce, start_next_hand
from mahjong_core.ml import N_ACTIONS
from mahjong_core.state import GameState, Phase
from mahjong_core.tiles import TileType

_STEP_CAP = 2000


def decision_points(seed: int, ruleset: RuleSet) -> Iterator[tuple[GameState, int]]:
    """A seeded random-policy self-play game, yielding every `(state, seat)` with a live
    decision."""
    rng = random.Random(seed)
    state = new_game(ruleset, seed)
    steps = 0
    while state.phase != Phase.GAME_OVER:
        steps += 1
        assert steps <= _STEP_CAP, f"seed={seed}: exceeded {_STEP_CAP} steps"

        if state.phase == Phase.HAND_OVER:
            state, _ = start_next_hand(state)
            continue

        if state.phase in (Phase.AWAIT_CLAIMS, Phase.AWAIT_KONG_ROB):
            assert state.claim_window is not None
            pending = [
                o.seat
                for o in state.claim_window.offers
                if o.seat not in state.claim_window.responses
            ]
            seat = rng.choice(pending)
        else:
            seat = state.turn

        yield state, seat
        action = random_action(state, seat, rng)
        state, _ = reduce(state, action)


def discard_mask(types: list[TileType], *, extra: list[int] | None = None) -> list[bool]:
    """Legal mask with a discard of each type in `types`, plus raw action ids in `extra`."""
    mask = [False] * N_ACTIONS
    for t in set(types):
        mask[int(t)] = True
    for aid in extra or ():
        mask[aid] = True
    return mask
