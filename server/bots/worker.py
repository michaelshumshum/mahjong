"""Process-pool worker for disconnect/bot-handover (docs/00-architecture.md §3 D12,
docs/05-roadmap.md M3 sub-task 6).

**Still deliberately separate from `Bot.act` (`bots/base.py`), now that both have converged on
`SeatView` -- updated reasoning, since M4's interface migration closed the gap this module's
docstring used to describe.** `Bot.act` is now `async def act(view, mask, deadline) -> int`
(`bots/base.py`), returning a bare id from the 109-action space, not a concrete `Action`. That
migration does *not* make `compute_action` redundant, because of what each side has access to:

1. **A worker process never receives `GameState`** (D2: `game_seed` must never leave the room's
   own process; `SeatView` is the documented D12 payload precisely so a worker never needs it).
   Turning a `Bot.act`-returned id back into a concrete `Action` needs `decode_action(aid,
   state, seat)` (`mahjong_core/ml.py`), which needs the real `GameState` -- so if this path
   called into `Bot.act` and got back an id, the *Room*, not the worker, would have to decode
   it after the result comes back, changing `app/room.py`'s result-handling shape (it currently
   just uses `view.legal_actions` directly, no decode step). That's a real change to the live
   handover path, out of scope for the sub-task that did the `Bot.act` migration -- see
   docs/04-bots.md's changelog note for the explicit call not to touch it without a reason tied
   to that migration itself.
2. `compute_action`'s policy (uniform-random) is exactly T0's, so there's nothing left to gain
   in *behaviour* from routing through `Bot.act` here -- only a decode-step relocation that
   `app/room.py` doesn't currently need. Should a *non-uniform* tier (T1+) ever need to run
   disconnect-handover for real, that's the point to revisit this, not before.

`compute_action` is the actual unit submitted to the pool: uniform-random over
`view.legal_actions`, the same T0 policy as `RandomBot` (`bots/random.py`), reimplemented
against `SeatView` rather than calling into `bots.random` so this module has zero import-time
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
