"""`HandRecord` persistence (docs/ml.md §2): standalone hands from `engine.new_hand`, stored in
`hand_records`, replayed from `(ruleset, seed, dealer, prevailing, action_log)`. SQLite, as
`test_game_record.py`."""

from __future__ import annotations

import random

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.records import (
    get_hand_record,
    hand_record_columns,
    is_replayable,
    save_hand_record,
)
from mahjong_core.actions import Action, action_from_dict
from mahjong_core.config import RuleSet
from mahjong_core.engine import ENGINE_VERSION, new_game, new_hand, reduce
from mahjong_core.ml import decode_action, legal_mask
from mahjong_core.state import GameState, Phase, Wind


def _play_hand(state: GameState, seed: int) -> tuple[GameState, list[Action]]:
    rng = random.Random(seed)
    actions: list[Action] = []
    while state.phase not in (Phase.HAND_OVER, Phase.GAME_OVER):
        if state.claim_window is not None:
            responded = state.claim_window.responses
            seat = next(o.seat for o in state.claim_window.offers if o.seat not in responded)
        else:
            seat = state.turn
        mask = legal_mask(state, seat)
        aid = rng.choice([i for i, ok in enumerate(mask) if ok])
        action = decode_action(aid, state, seat)
        actions.append(action)
        state, _ = reduce(state, action)
    return state, actions


async def test_save_hand_record_round_trips_and_replays(session: AsyncSession) -> None:
    ruleset = RuleSet()
    start = new_hand(ruleset, 7, dealer=2, prevailing=Wind.EAST)
    final, actions = _play_hand(start, seed=3)

    saved = await save_hand_record(session, final, actions, players=["a", None, "b", None])
    loaded = await get_hand_record(session, saved.id)
    assert loaded is not None and is_replayable(loaded)
    assert (loaded.engine_version, loaded.seed, loaded.dealer, loaded.prevailing) == (
        ENGINE_VERSION,
        7,
        2,
        int(Wind.EAST),
    )
    assert loaded.players == ["a", None, "b", None]
    assert sum(loaded.result["payments"]) == 0

    state = new_hand(
        RuleSet.from_dict(loaded.ruleset),
        loaded.seed,
        dealer=loaded.dealer,
        prevailing=Wind(loaded.prevailing),
    )
    for data in loaded.action_log:
        state, _ = reduce(state, action_from_dict(data))
    assert state == final


def test_hand_record_requires_hand_over() -> None:
    with pytest.raises(ValueError, match="HAND_OVER"):
        hand_record_columns(new_game(RuleSet(), 1), [])


def test_hand_record_rejects_wrong_player_count() -> None:
    final, actions = _play_hand(new_game(RuleSet(), 4), seed=1)
    with pytest.raises(ValueError, match="4 entries"):
        hand_record_columns(final, actions, players=["a"])
