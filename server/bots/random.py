"""`RandomBot` -- picks uniformly among `legal_actions`. No strategy: it exists to stress the
engine's state machine (docs/05-roadmap.md §2's self-play soak gate), not to play well.
"""

from __future__ import annotations

import random

from bots.base import Bot
from mahjong_core.actions import Action, legal_actions
from mahjong_core.state import GameState

__all__ = ["RandomBot"]


class RandomBot(Bot):
    """`rng` is caller-supplied so self-play runs stay seeded/deterministic
    (`server/AGENTS.md`: "a failing game is reproducible from (ruleset, seed, actions)") --
    it defaults to an unseeded `Random()` only for ad-hoc interactive use, never for tests."""

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng if rng is not None else random.Random()

    def act(self, state: GameState, seat: int) -> Action:
        actions = legal_actions(state, seat)
        return self._rng.choice(actions)
