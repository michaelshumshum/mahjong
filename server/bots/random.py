"""`RandomBot` -- T0, uniform over legal actions (docs/04-bots.md §2). Exists to stress the
engine's state machine and to serve as the arena's incumbent baseline (§8), not to play well.

**Two distinct things live here, deliberately not one.** `random_action(state, seat, rng)` is
the raw, `GameState`-based self-play generator: fast, synchronous, no `SeatView`/mask/action-id
machinery, used by `bots/selfplay.py` and by the handful of test modules
(`tests/test_ml.py`, `tests/test_redaction.py`, `tests/test_room.py`) that just need "a policy
that plays legally" to drive a self-play sweep for *other* code under test. `RandomBot` is the
actual `bots.base.Bot`-protocol implementation (`docs/04-bots.md §1`'s
`async def act(view, mask, deadline) -> int`), the T0 tier the arena harness compares candidates
against. They implement the same uniform-random policy over two genuinely different contracts
(one already has concrete `Action`s to choose from; the other only ever sees an opaque
109-slot mask), so one is not a thin wrapper around the other.
"""

from __future__ import annotations

import random

from app.views import SeatView
from mahjong_core.actions import Action, legal_actions
from mahjong_core.state import GameState

__all__ = ["RandomBot", "random_action"]


def random_action(state: GameState, seat: int, rng: random.Random | None = None) -> Action:
    """Uniform-random among `legal_actions(state, seat)`. `rng` is caller-supplied so self-play
    runs stay seeded/deterministic (`server/AGENTS.md`: "a failing game is reproducible from
    (ruleset, seed, actions)") -- it defaults to an unseeded `Random()` only for ad-hoc
    interactive use, never for tests."""
    actions = legal_actions(state, seat)
    r = rng if rng is not None else random.Random()
    return r.choice(actions)


class RandomBot:
    """`docs/04-bots.md §1`'s `Bot` protocol, T0 tier: pick uniformly among the ids `mask`
    marks legal. Never decodes to a concrete `Action` itself -- per `bots/base.py`'s
    `legal_mask`/`decode_action` resolution note, that's the caller's job once it has both the
    action id and the real `GameState` a worker process never receives (see `bots/worker.py`).
    """

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng if rng is not None else random.Random()

    async def act(self, view: SeatView, mask: list[bool], deadline: float) -> int:
        del view, deadline  # unused: uniform over whatever the mask marks legal
        legal_ids = [aid for aid, ok in enumerate(mask) if ok]
        if not legal_ids:
            raise ValueError("RandomBot.act called with an all-false mask")
        return self._rng.choice(legal_ids)
