"""Shared self-play game loop (docs/05-roadmap.md §1 `bots/`; docs/06-ml.md §2's M1 gate:
`GameRecord` persistence, bot-only included).

`tests/test_selfplay.py`'s soak test plays games without keeping their action log -- it only
needs to prove the engine terminates cleanly and every invariant holds, and logging 10,000
games' worth of actions would make that hot loop heavier for no benefit there. This module is
the version that keeps the log, used anywhere an actual `GameRecord` is wanted (see
`app/db/records.py`).
"""

from __future__ import annotations

import random
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GameRecord
from app.db.records import save_game_record
from bots.base import Bot
from bots.random import RandomBot
from mahjong_core.actions import Action
from mahjong_core.config import RuleSet
from mahjong_core.engine import new_game, reduce, start_next_hand
from mahjong_core.state import GameState, Phase

__all__ = ["play_and_record_game", "play_game"]

_STEP_CAP = 8000  # matches tests/test_selfplay.py's cap -- see that module for the bound's origin


def play_game(
    seed: int,
    ruleset: RuleSet,
    bots: Sequence[Bot] | None = None,
    *,
    step_cap: int = _STEP_CAP,
) -> tuple[GameState, list[Action]]:
    """Play one complete game to `Phase.GAME_OVER`. Returns `(final_state, actions)` -- the
    ordered `Action` log that reproduces `final_state` from `new_game(ruleset, seed)` via
    `reduce` (docs/00-architecture.md §3: "replays as `(game_seed, actions)`"), the shape
    `docs/06-ml.md §2`'s `GameRecord.actions` needs. `start_next_hand` transitions are never
    `Action`s (engine.py) so they aren't logged -- replaying the log reconstructs them
    automatically off `Phase.HAND_OVER`, deterministically, the same way live play does.

    `bots` defaults to four `RandomBot`s sharing one seeded `Random` stream, mirroring
    `tests/test_selfplay.py`'s own setup so `(ruleset, seed)` alone reproduces the game.
    """
    rng = random.Random(seed)
    seats: Sequence[Bot] = bots if bots is not None else [RandomBot(rng=rng) for _ in range(4)]
    if len(seats) != 4:
        raise ValueError(f"bots must have exactly 4 entries, got {len(seats)}")

    state = new_game(ruleset, seed)
    actions: list[Action] = []
    steps = 0
    while state.phase != Phase.GAME_OVER:
        steps += 1
        if steps > step_cap:
            raise RuntimeError(f"seed={seed}: exceeded {step_cap} steps -- possible deadlock")

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

        action = seats[seat].act(state, seat)
        actions.append(action)
        state, _ = reduce(state, action)

    return state, actions


async def play_and_record_game(
    session: AsyncSession,
    seed: int,
    ruleset: RuleSet,
    bots: Sequence[Bot] | None = None,
    *,
    players: Sequence[str | None] | None = None,
) -> GameRecord:
    """Play one bot-only game and persist it -- the actual self-play-to-`GameRecord` path
    (docs/05-roadmap.md §2's M1 gate: "persist `GameRecord` ... bot-only included"). `players`
    defaults to labeling every seat by its bot's class name."""
    state, actions = play_game(seed, ruleset, bots)
    resolved_players = players
    if resolved_players is None:
        resolved_players = (
            [f"bot:{type(b).__name__}" for b in bots] if bots is not None else ["bot:RandomBot"] * 4
        )
    return await save_game_record(session, state, actions, players=resolved_players)
