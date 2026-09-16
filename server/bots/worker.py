"""Process-pool worker for disconnect/bot-handover (docs/00-architecture.md §3 D12,
docs/05-roadmap.md M3 sub-task 6).

**Deliberately separate from `Bot.act(state, seat)` (`bots/base.py`), not a migration of it.**
`bots/base.py`'s own docstring already tracks the `GameState`-vs-`SeatView` gap as real; this
module closes it for the one path that actually needs it today rather than retrofitting the
whole tier interface. Two reasons:

1. `04-bots.md`'s own target `Bot` interface is a *different* shape again -- async,
   `mask`/`deadline`-based, returning an action id from the 109-action space (`06-ml.md`) -- and
   ships in M4 alongside T1/T2. Migrating `Bot.act`'s `GameState` param to `SeatView` now, only
   to replace the whole signature again next milestone, is churn with no lasting value.
   `bots/selfplay.py`/`bots/arena.py` and their tests keep the full-`GameState` tier interface
   unchanged; only this sub-task's own new code path uses `SeatView`.
2. `app/room.py`'s bot-handover path crosses a real boundary (`ProcessPoolExecutor`, D12) that
   `GameState` was never meant to cross: `game_seed` must never leave the room's own process
   (00-architecture.md §3, D2), and a worker process is exactly the kind of "different
   recipient" `seat_view()` exists to gate. `SeatView` is already the documented D12 payload
   shape (`(room_id, window_id, state_version, seat_view)`), and it's already picklable (frozen
   dataclasses of ints/enums/tuples) -- ferrying a `GameState` instead would leak `game_seed`
   and the live wall order into a worker for no reason, and would start violating D2 the moment
   a real (not `RandomBot`-equivalent) tier looked at more than `legal_actions`.

`compute_action` is the actual unit submitted to the pool: uniform-random over
`view.legal_actions`, the same T0 policy as `RandomBot` (`bots/random.py`), reimplemented
against `SeatView` rather than calling `RandomBot.act` so this module has zero import-time
dependency on `mahjong_core.state.GameState` -- the whole point of running in a worker process
is to not need the rest of the room's live state.
"""

from __future__ import annotations

import random

from app.views import SeatView
from mahjong_core.actions import Action

__all__ = ["compute_action"]


def compute_action(view: SeatView, seed: int) -> Action:
    """Pick uniformly among `view.legal_actions`, seeded per-call from the tag the room
    submitted this job against (`app/room.py`'s `BotJobTag`) rather than an unseeded
    `random.Random()` -- server/AGENTS.md: "a failing game is reproducible from (ruleset, seed,
    actions)". Never called with an empty `legal_actions` -- same contract `Bot.act` documents.
    """
    return random.Random(seed).choice(view.legal_actions)
