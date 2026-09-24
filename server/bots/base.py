"""`Bot` protocol (docs/04-bots.md §1): `act(view, mask, deadline) -> int`. A bot sees only
`seat_view`/mask, never `GameState` -- decoding the id to a real `Action` is always the caller's
job, since `mahjong_core` must never import `app.views` and only the caller holds `GameState`.

Protocol, not ABC: no shared state/helper worth inheriting across tiers.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.views import SeatView

__all__ = ["Bot"]


@runtime_checkable
class Bot(Protocol):
    """`deadline` is advisory -- caller applies a safe default (tsumogiri/pass) if nothing lands
    in time; a bot need not check it itself. Returns one legal `aid` (`mask[aid]` true); never
    called with an all-false mask.
    """

    async def act(self, view: SeatView, mask: list[bool], deadline: float) -> int: ...
