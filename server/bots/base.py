"""`Bot` -- the minimal interface every bot tier (docs/04-bots.md §1) implements. Migrated (M4,
alongside T1/T2 per `bots/worker.py`'s M3-era note) from the earlier `act(state, seat) -> Action`
placeholder to the real target shape:

```python
class Bot(Protocol):
    async def act(self, view: SeatView, mask: list[bool], deadline: float) -> int: ...
```

A bot never sees `GameState` -- only its own `seat_view(state, seat)` (`app/views.py`) plus a
legal-action `mask` over the fixed 109-id space (`mahjong_core/ml.py`, docs/06-ml.md §1). It
returns one legal id; decoding that back into a concrete `Action` needs `decode_action(aid,
state, seat)`, which needs the real `GameState` -- so decoding is always the *caller's* job
(the self-play harness, the arena harness, or -- for the live disconnect-handover path -- the
Room actor), never the bot's. `async` because a real tier (T2, learned policy) may eventually
await a model call; the heuristic tiers here are synchronous under the hood and just return
immediately.

**Resolved: `legal_mask(state)`, not `legal_mask(view)`.** docs/06-ml.md §1's `legal_mask`
signature stayed `(state: GameState, seat: int) -> list[bool]` through M2, and this module's own
predecessor flagged the `04-bots.md §1` pseudocode's `legal_mask(view)` call as an open question.
It's resolved now, in favour of the state-based signature staying exactly as-is:
`mahjong_core` must never import `app.views` (layering only runs one way -- `app` depends on
`mahjong_core`, never the reverse; `SeatView` living in `app/` at all is because it's a
per-recipient wire concern, not a game rule, per that module's own docstring). So `legal_mask`
can't take a `SeatView` without breaking that. Instead: whoever drives a bot (self-play, the
arena, the Room) computes `mask = mahjong_core.ml.legal_mask(state, seat)` from the real
`GameState` it already holds, and hands `(view, mask, deadline)` to `Bot.act` together --
docs/04-bots.md §1's own prose already says this ("`mask` is `legal_mask(view) ->
list[bool]`... the engine-produced legal-action mask"), so this is a phrasing fix there, not a
behaviour change here.

**Protocol, not an ABC.** docs/04-bots.md §1 spells it as a `Protocol`, and there's no shared
state or helper method across tiers worth inheriting (T1/T2's shared shanten/ukeire machinery
lives in `mahjong_core.shanten`, called by each bot, not on a common base class) -- structural
typing is all `Bot`-typed parameters (the arena's registry, `bots/selfplay.py`'s `bots`
sequence) actually need.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.views import SeatView

__all__ = ["Bot"]


@runtime_checkable
class Bot(Protocol):
    """`view` is this seat's own redacted snapshot; `mask` is a length-109 legal-action mask
    (`mahjong_core.ml.legal_mask`, computed by the caller against real `GameState`); `deadline`
    is a `time.monotonic()`-comparable epoch, purely advisory -- a bot is not required to check
    it itself (docs/04-bots.md §1's scheduling section: the caller enforces it by applying a
    safe default if nothing lands in time, exactly like a stale/missing human claim response).
    Returns one action id `aid` with `mask[aid]` true. Never called with an all-false mask.
    """

    async def act(self, view: SeatView, mask: list[bool], deadline: float) -> int: ...
