"""`Bot` -- the minimal interface every bot tier (docs/04-bots.md) implements.

**Scoping note: takes `GameState`, not `SeatView`.** `server/AGENTS.md` says `seat_view()`/
`redact_event()` are the only paths to seat-visible state, "bots included" -- but `seat_view()`
doesn't exist yet (00-architecture.md §5's `SeatView` is M3 scope, docs/05-roadmap.md §2). Bots
are pure `mahjong_core` consumers today, with no `app/room.py` to wire real per-seat redaction
through, so this takes the full `GameState` plus the acting `seat`. That's a real, tracked scope
gap, not a design choice to keep: once `app/views.py` lands, bots must be migrated to consume
`SeatView` instead, so a bot can never see another seat's concealed tiles or the live wall order.
Until then, nothing in `mahjong_core` prevents it -- `RandomBot` doesn't look past `legal_actions`
so it isn't exploiting the gap today, but a future bot tier easily could by accident.

**Still open as of M3 sub-task 6 (disconnect/bot-handover) -- a deliberate call, not an
oversight.** `app/room.py`'s bot-handover path needs a `SeatView`-based, `ProcessPoolExecutor`-
picklable entry point (D12), and now has one: `bots/worker.py`'s `compute_action(view, seed)`.
This `Bot.act(state, seat)` interface itself is untouched -- `04-bots.md`'s own target shape for
it is a different, async, `mask`/`deadline`-based signature landing in M4 with T1/T2, so
migrating this interface's `GameState` param to `SeatView` now would just be replaced again next
milestone. See `bots/worker.py`'s module docstring for the full reasoning.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from mahjong_core.actions import Action
from mahjong_core.state import GameState

__all__ = ["Bot"]


class Bot(ABC):
    """Given the full table state and the seat it's acting for, return one `Action` from
    `actions.legal_actions(state, seat)`. Never called when that set is empty."""

    @abstractmethod
    def act(self, state: GameState, seat: int) -> Action:
        raise NotImplementedError
