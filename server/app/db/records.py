"""Persisting/reading `GameRecord` (finished game) and `HandRecord` (standalone hand) rows. `engine_version` is always stamped from
`mahjong_core.engine.ENGINE_VERSION`, never caller-supplied, so a record can't be mislabeled.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GameRecord, HandRecord
from mahjong_core.actions import Action, action_to_dict
from mahjong_core.engine import ENGINE_VERSION, game_outcome
from mahjong_core.state import GameState, Phase

__all__ = [
    "count_games_since",
    "get_game_record",
    "get_hand_record",
    "hand_record_columns",
    "is_replayable",
    "save_game_record",
    "save_hand_record",
]


async def save_game_record(
    session: AsyncSession,
    state: GameState,
    actions: Sequence[Action],
    *,
    players: Sequence[str | None] | None = None,
) -> GameRecord:
    """Persist a finished game; `state.phase` must be `Phase.GAME_OVER` -- there's no mid-game
    durability story to record a snapshot against instead."""
    if state.phase != Phase.GAME_OVER:
        raise ValueError(f"save_game_record requires Phase.GAME_OVER, got {state.phase}")

    resolved_players = list(players) if players is not None else [None, None, None, None]
    if len(resolved_players) != 4:
        raise ValueError(f"players must have exactly 4 entries, got {len(resolved_players)}")

    record = GameRecord(
        engine_version=ENGINE_VERSION,
        ruleset=state.ruleset.to_dict(),
        seed=state.game_seed,
        action_log=[action_to_dict(a) for a in actions],
        players=resolved_players,
        result=game_outcome(state).to_dict(),
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


async def get_game_record(session: AsyncSession, record_id: int) -> GameRecord | None:
    return await session.get(GameRecord, record_id)


async def count_games_since(session: AsyncSession, since: dt.datetime) -> int:
    """Finished games recorded at or after `since` (`GET /status`)."""
    count = await session.scalar(
        select(func.count()).select_from(GameRecord).where(GameRecord.created_at >= since)
    )
    return count or 0


def is_replayable(record: GameRecord | HandRecord, current_version: str = ENGINE_VERSION) -> bool:
    """Exact `engine_version` equality -- no semver/range comparison, no migration path."""
    return record.engine_version == current_version


def hand_record_columns(
    state: GameState,
    actions: Sequence[Action],
    *,
    players: Sequence[str | None] | None = None,
) -> dict[str, Any]:
    """`HandRecord` column values for a hand started by `engine.new_hand(state.ruleset,
    state.game_seed, dealer=state.dealer, prevailing=state.prevailing)` and played to
    `HAND_OVER` by `actions`."""
    if state.phase != Phase.HAND_OVER or state.hand_result is None:
        raise ValueError(f"hand record requires Phase.HAND_OVER, got {state.phase}")
    resolved_players = list(players) if players is not None else [None, None, None, None]
    if len(resolved_players) != 4:
        raise ValueError(f"players must have exactly 4 entries, got {len(resolved_players)}")
    hr = state.hand_result
    return {
        "engine_version": ENGINE_VERSION,
        "ruleset": state.ruleset.to_dict(),
        "seed": state.game_seed,
        "dealer": state.dealer,
        "prevailing": int(state.prevailing),
        "action_log": [action_to_dict(a) for a in actions],
        "players": resolved_players,
        "result": {
            "outcome": str(hr.outcome),
            "winner": hr.winner,
            "faan": hr.faan,
            "points": hr.points,
            "payments": [hr.payments.get(i, 0) for i in range(4)],
            "final_scores": [s.score for s in state.seats],
        },
    }


async def save_hand_record(
    session: AsyncSession,
    state: GameState,
    actions: Sequence[Action],
    *,
    players: Sequence[str | None] | None = None,
) -> HandRecord:
    record = HandRecord(**hand_record_columns(state, actions, players=players))
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


async def get_hand_record(session: AsyncSession, record_id: int) -> HandRecord | None:
    return await session.get(HandRecord, record_id)
