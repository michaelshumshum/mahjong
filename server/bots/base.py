"""`Bot` protocol (docs/bots.md §1): `act(view, mask, deadline) -> int`. A bot sees only
`seat_view`/mask, never `GameState` -- decoding the id to a real `Action` is always the caller's
job, since `mahjong_core` must never import `app.views` and only the caller holds `GameState`.

Protocol, not ABC: no shared state/helper worth inheriting across tiers.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.views import SeatView

__all__ = ["GAME_STEP_CAP", "NO_DEADLINE", "Bot"]

NO_DEADLINE = float("inf")
"""`deadline` for offline harnesses (self-play, arena, dataset generation): no wall-clock budget."""

GAME_STEP_CAP = 8000
"""Step cap for an offline full-game harness; a trip is a hard failure (deadlock), never a silent
early exit. Generous vs. the observed max of ~450 steps for a 4-hand `EAST_ONLY` game."""


@runtime_checkable
class Bot(Protocol):
    """`deadline` is advisory -- caller applies a safe default (tsumogiri/pass) if nothing lands
    in time; a bot need not check it itself. Returns one legal `aid` (`mask[aid]` true); never
    called with an all-false mask.
    """

    async def act(self, view: SeatView, mask: list[bool], deadline: float) -> int: ...
