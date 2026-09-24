"""Persisting/reading `GameRecord` rows. `engine_version` is always stamped from
`mahjong_core.engine.ENGINE_VERSION`, never caller-supplied, so a record can't be mislabeled.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GameRecord
from mahjong_core.actions import Action, action_to_dict
from mahjong_core.engine import ENGINE_VERSION, game_outcome
from mahjong_core.state import GameState, Phase

__all__ = ["get_game_record", "is_replayable", "save_game_record"]


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


def is_replayable(record: GameRecord, current_version: str = ENGINE_VERSION) -> bool:
    """Exact `engine_version` equality -- no semver/range comparison, no migration path."""
    return record.engine_version == current_version
