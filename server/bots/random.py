"""`RandomBot` -- T0, uniform over legal actions (docs/bots.md §2): the arena's baseline, not
meant to play well.

`random_action(state, seat, rng)` is a separate, `GameState`-based helper used by self-play/tests
that just need "a policy that plays legally" -- not a wrapper around `RandomBot`, since it works
over concrete `Action`s rather than an opaque mask.
"""

from __future__ import annotations

import random

from app.views import SeatView
from mahjong_core.actions import Action, legal_actions
from mahjong_core.state import GameState

__all__ = ["RandomBot", "random_action"]


def random_action(state: GameState, seat: int, rng: random.Random | None = None) -> Action:
    """Uniform-random among `legal_actions(state, seat)`. `rng` is caller-supplied so self-play
    stays seeded/deterministic; unseeded only for ad-hoc interactive use."""
    actions = legal_actions(state, seat)
    r = rng if rng is not None else random.Random()
    return r.choice(actions)


class RandomBot:
    """T0 `Bot` tier: pick uniformly among the ids `mask` marks legal. Never decodes to a
    concrete `Action` itself -- that's the caller's job."""

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng if rng is not None else random.Random()

    async def act(self, view: SeatView, mask: list[bool], deadline: float) -> int:
        del view, deadline  # unused
        legal_ids = [aid for aid, ok in enumerate(mask) if ok]
        if not legal_ids:
            raise ValueError("RandomBot.act called with an all-false mask")
        return self._rng.choice(legal_ids)
