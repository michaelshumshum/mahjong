"""Shared self-play game loop: plays a full game via the real `Bot` protocol and keeps the
action log, for anywhere a real `GameRecord` is wanted or a non-`RandomBot` tier needs exercising
end to end.

Distinct from `tests/test_selfplay.py`'s soak test, which drives `bots.random.random_action`
directly and keeps no log -- that test only needs to prove the engine terminates cleanly, and
building a real `SeatView`/mask per decision would make its hot loop heavier for no benefit.

This loop holds the real `GameState`, so it does the decode step `Bot.act` itself can't:
`seat_view`/`legal_mask` in, `Bot.act` returns an id, `decode_action` turns it into the concrete
`Action` `reduce` and the action log both need.
"""

from __future__ import annotations

import random
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GameRecord
from app.db.records import save_game_record
from app.views import seat_view
from bots.base import Bot
from bots.random import RandomBot
from mahjong_core.actions import Action
from mahjong_core.config import RuleSet
from mahjong_core.engine import new_game, reduce, start_next_hand
from mahjong_core.ml import decode_action, legal_mask
from mahjong_core.state import GameState, Phase

__all__ = ["play_and_record_game", "play_game"]

_STEP_CAP = 8000  # matches tests/test_selfplay.py's cap -- see that module for the bound's origin
_NO_DEADLINE = float("inf")  # self-play has no wall-clock budget; heuristic bots ignore it anyway


async def play_game(
    seed: int,
    ruleset: RuleSet,
    bots: Sequence[Bot] | None = None,
    *,
    step_cap: int = _STEP_CAP,
) -> tuple[GameState, list[Action]]:
    """Plays one complete game to `Phase.GAME_OVER`. Returns `(final_state, actions)`, the action
    log that reproduces `final_state` from `new_game(ruleset, seed)` via `reduce` --
    `start_next_hand` transitions aren't `Action`s, so they're reconstructed from replay, not
    logged.

    `bots` defaults to four `RandomBot`s sharing one seeded `Random` stream, so `(ruleset, seed)`
    alone reproduces the game.
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

        view = seat_view(state, seat)
        mask = legal_mask(state, seat)
        aid = await seats[seat].act(view, mask, _NO_DEADLINE)
        action = decode_action(aid, state, seat)
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
    """Plays one bot-only game and persists it. `players` defaults to labeling every seat by its
    bot's class name."""
    state, actions = await play_game(seed, ruleset, bots)
    resolved_players = players
    if resolved_players is None:
        resolved_players = (
            [f"bot:{type(b).__name__}" for b in bots] if bots is not None else ["bot:RandomBot"] * 4
        )
    return await save_game_record(session, state, actions, players=resolved_players)
