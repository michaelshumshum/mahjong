"""`engine.drawn_tile` / `engine.newest_discard` against the event stream a client folds them
from (`web/src/lib/net/reducer.ts`): the drawn tile is the turn seat's last `Drawn`/
`KongReplacementDrawn` (or the dealer's 14th, as `deal` holds it apart), the newest discard
the last `Discarded` with no `MeldFormed` or new hand since. They back `state_sync`'s
`drawn_tile`/`last_discard` (docs/protocol.md §3), so a resync lands where the stream did."""

from __future__ import annotations

import random

from bots.random import random_action
from mahjong_core.actions import ActionKind, legal_actions
from mahjong_core.config import RuleSet
from mahjong_core.engine import (
    drawn_tile,
    new_game,
    newest_discard,
    reduce,
    start_next_hand,
)
from mahjong_core.events import Discarded, Drawn, Event, KongReplacementDrawn, MeldFormed
from mahjong_core.state import GameState, Phase
from mahjong_core.tiles import TileId

_RULESET = RuleSet(dealer_repeat_on_win=False, dealer_repeat_on_draw=False)
_SEEDS = range(40)
_STEP_CAP = 3000
_KONGS = (ActionKind.DECLARE_CONCEALED_KONG, ActionKind.DECLARE_ADDED_KONG, ActionKind.CLAIM_KONG)
_CLAIMS = (ActionKind.CLAIM_CHOW, ActionKind.CLAIM_PUNG)


class _Stream:
    """What a client knows from the frames alone."""

    def __init__(self, state: GameState) -> None:
        self.new_hand(state)

    def new_hand(self, state: GameState) -> None:
        dealer = state.dealer
        self.drawn: tuple[int, TileId] | None = (dealer, state.seats[dealer].concealed[-1])
        self.discard: tuple[int, TileId] | None = None

    def apply(self, events: list[Event]) -> None:
        for event in events:
            if isinstance(event, (Drawn, KongReplacementDrawn)):
                self.drawn = (event.seat, event.tile_id)
            elif isinstance(event, Discarded):
                self.drawn = None
                self.discard = (event.seat, event.tile_id)
            elif isinstance(event, MeldFormed):
                self.drawn = None
                self.discard = None


def _action(state: GameState, seat: int, rng: random.Random):
    """Random play that takes every kong and claim it can, so replacement draws and claimed
    turns come up."""
    actions = legal_actions(state, seat)
    for kinds in (_KONGS, _CLAIMS):
        picks = [a for a in actions if a.kind in kinds]
        if picks:
            return rng.choice(picks)
    return random_action(state, seat, rng)


def _check(state: GameState, stream: _Stream, seen: set[str]) -> None:
    if state.phase == Phase.AWAIT_ACTION:
        held = stream.drawn
        want = held[1] if held is not None and held[0] == state.turn else None
        assert drawn_tile(state) == want
        seen.add("drawn" if want is not None else "claimed")
        if state.last_draw_was_kong_replacement and want is not None:
            seen.add("kong_replacement")
    else:
        assert drawn_tile(state) is None
    if state.phase in (Phase.AWAIT_ACTION, Phase.AWAIT_CLAIMS, Phase.AWAIT_KONG_ROB):
        assert newest_discard(state) == stream.discard
        seen.add(f"discard:{state.phase.value}:{stream.discard is not None}")
    if state.phase == Phase.HAND_OVER:
        assert newest_discard(state) is None


def test_held_tiles_match_the_event_stream() -> None:
    seen: set[str] = set()
    for seed in _SEEDS:
        rng = random.Random(seed)
        state = new_game(_RULESET, seed)
        stream = _Stream(state)
        for _ in range(_STEP_CAP):
            _check(state, stream, seen)
            if state.phase == Phase.GAME_OVER:
                break
            if state.phase == Phase.HAND_OVER:
                state, _ = start_next_hand(state)
                if state.phase != Phase.GAME_OVER:
                    stream.new_hand(state)
                continue
            window = state.claim_window
            if window is not None:
                seat = rng.choice([o.seat for o in window.offers if o.seat not in window.responses])
            else:
                seat = state.turn
            state, events = reduce(state, _action(state, seat, rng))
            stream.apply(events)
        else:
            raise AssertionError(f"seed {seed}: no GAME_OVER within {_STEP_CAP} steps")
    assert {
        "drawn",
        "claimed",
        "kong_replacement",
        "discard:AWAIT_ACTION:True",
        "discard:AWAIT_ACTION:False",
        "discard:AWAIT_CLAIMS:True",
    } <= seen
