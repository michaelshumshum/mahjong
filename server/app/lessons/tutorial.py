"""Tutorial scripts -> seat 0's frame stream (ADR 0025 "Guided tutorial vs one-shot puzzle").

The script runs through the real `reduce()`, and each step's frames are what a live `Table`
would send seat 0 for the same actions: `redact_event` and the `app/frames.py` builders, in
`Table`'s order (an action's event frames, `score` after `hand_end`, a new window's
`claim_offer`, then `turn`). Only seat 0's stream exists, so nothing here can leak another
seat's tiles.

Flowers stay on (`LESSON_RULESET` is pinned) but are kept out of the script: every draw must
come off the stacked `wall_front`/`wall_back`, and a flower drawn anywhere fails the build.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.frames import (
    claim_offer_frame,
    event_frame,
    score_frame,
    state_sync_frame,
    to_envelope,
    turn_frame,
)
from app.lessons.model import Auto, Expect, Move, Narrate, Tutorial, TutorialStep
from app.lessons.position import build_position
from mahjong_core.actions import (
    Action,
    ClaimChow,
    ClaimKong,
    ClaimPung,
    DeclareAddedKong,
    DeclareConcealedKong,
    Discard,
    legal_actions,
)
from mahjong_core.engine import reduce
from mahjong_core.events import (
    ClaimResolved,
    Drawn,
    Event,
    FlowerReplaced,
    HandEnded,
    KongReplacementDrawn,
)
from mahjong_core.state import GameState
from mahjong_core.tiles import Tile, parse_tiles, tile_id_type

# the learner's seat; every `expect` is its decision
SEAT = 0
# the player keeps no clock: a deadline the wire requires reads 0, like `ts`
NO_CLOCK = 0


@dataclass(frozen=True)
class ScriptedStep:
    """`action` resolved from the step's `Move` (`None` for `narrate`); `snapshot` is seat 0's
    `state_sync` before it acts (`expect` only); `frames` follow the action, enveloped."""

    step: TutorialStep
    seat: int | None
    action: Action | None
    snapshot: dict[str, Any] | None
    frames: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class TutorialRun:
    """`start` is seat 0's opening `state_sync`. Frames carry a dense `seq` from 1; a snapshot
    carries the `seq` of the last frame before it, the stream it stands in for."""

    start: dict[str, Any]
    steps: tuple[ScriptedStep, ...]
    final: GameState


def _own_types(state: GameState, action: Action) -> list[Tile]:
    """The tiles a `Move` names for `action`: a claim's exclude the claimed discard."""
    if isinstance(action, Discard):
        return [tile_id_type(action.tile_id)]
    if isinstance(action, ClaimChow | ClaimPung | ClaimKong):
        assert state.claim_window is not None
        claimed = state.claim_window.tile
        return [tile_id_type(t) for t in action.meld.tiles if t != claimed]
    if isinstance(action, DeclareConcealedKong | DeclareAddedKong):
        return [tile_id_type(t) for t in action.meld.tiles]
    return []


def resolve_move(state: GameState, seat: int, move: Move) -> Action:
    """The legal action `move` names; the first of equals (two copies of a discard)."""
    want = sorted(parse_tiles(move.tiles))
    for action in legal_actions(state, seat):
        if action.kind == move.kind and sorted(_own_types(state, action)) == want:
            return action
    raise ValueError(f"seat {seat} cannot {move.kind} {move.tiles or ''}".rstrip())


class _Stream:
    def __init__(self) -> None:
        self.head = 0

    def snapshot(self, state: GameState) -> dict[str, Any]:
        return to_envelope(state_sync_frame(state, SEAT), seq=self.head, ts=0)

    def frame(self, wire: dict[str, Any]) -> dict[str, Any]:
        self.head += 1
        return to_envelope(wire, seq=self.head, ts=0)


def seat_frames(before: GameState, after: GameState, events: list[Event]) -> list[dict[str, Any]]:
    """Seat 0's frames for one `reduce()` from `before` to `after`, flat, as `Table` sends
    them: a no-claim `claim_resolved` only when seat 0 was offered the window."""
    window = before.claim_window
    offered = window is not None and any(o.seat == SEAT for o in window.offers)
    wires: list[dict[str, Any]] = []
    for event in events:
        if isinstance(event, ClaimResolved) and event.winning_seat is None and not offered:
            continue
        wires.append(event_frame(after, SEAT, event, hand_end_deadline_ts=NO_CLOCK))
        if isinstance(event, HandEnded):
            wires.append(score_frame(after))
    opened = after.claim_window
    if opened is not None and (window is None or window.window_id != opened.window_id):
        offer = claim_offer_frame(after, SEAT, deadline_ts=NO_CLOCK)
        if offer is not None:
            wires.append(offer)
    turn = turn_frame(after, SEAT, deadline_ts=NO_CLOCK)
    if turn is not None:
        wires.append(turn)
    return wires


@dataclass
class _Draws:
    front: int
    back: int

    def take(self, events: list[Event]) -> None:
        """Raises once a draw leaves the stacked wall, or on any flower."""
        self.front -= sum(isinstance(e, Drawn) for e in events)
        self.back -= sum(isinstance(e, KongReplacementDrawn) for e in events)
        if self.front < 0:
            raise ValueError("a draw went past the stacked wall_front")
        if self.back < 0:
            raise ValueError("a kong replacement went past the stacked wall_back")
        if any(isinstance(e, FlowerReplaced) for e in events):
            raise ValueError("a flower was drawn: keep flowers out of the scripted draws")


def run_tutorial(tutorial: Tutorial) -> TutorialRun:
    """Plays the script and checks it. Raises `ValueError` naming the step: a move not in that
    seat's legal actions, an `expect` when seat 0 has no decision, an `auto` for seat 0, a draw
    off the stacked wall or a flower, or a final phase other than `end_phase`."""
    state = build_position(tutorial.position)
    draws = _Draws(
        front=len(parse_tiles(tutorial.position.wall_front)),
        back=len(parse_tiles(tutorial.position.wall_back)),
    )
    stream = _Stream()
    start = stream.snapshot(state)
    steps: list[ScriptedStep] = []
    for n, step in enumerate(tutorial.steps):
        try:
            if isinstance(step, Narrate):
                steps.append(ScriptedStep(step, None, None, None, ()))
                continue
            snapshot = None
            if isinstance(step, Expect):
                seat = SEAT
                if not legal_actions(state, SEAT):
                    raise ValueError("expect: seat 0 has no decision here")
                snapshot = stream.snapshot(state)
            else:
                assert isinstance(step, Auto)
                seat = step.seat
                if seat == SEAT:
                    raise ValueError("auto: seat 0's actions are expect steps")
            action = resolve_move(state, seat, step.move)
            after, events = reduce(state, action)
            draws.take(events)
            frames = tuple(stream.frame(w) for w in seat_frames(state, after, events))
            steps.append(ScriptedStep(step, seat, action, snapshot, frames))
            state = after
        except ValueError as e:
            raise ValueError(f"{tutorial.id}: step {n}: {e}") from None
    if state.phase != tutorial.end_phase:
        raise ValueError(f"{tutorial.id}: ends in {state.phase}, not {tutorial.end_phase}")
    return TutorialRun(start=start, steps=tuple(steps), final=state)
