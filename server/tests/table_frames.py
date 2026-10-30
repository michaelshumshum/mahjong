"""Record what a live `Table` sends each recipient, beside the engine steps behind it, and
rebuild the event frames from those steps with `app.frames` (`tests/test_frames.py`,
`tests/test_lessons_tutorial.py`)."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest

import app.table as table_module
from app.frames import event_frame
from app.table import Table
from mahjong_core.events import ClaimResolved, Event
from mahjong_core.state import GameState

# frames backed by an engine `Event`
EVENT_FRAMES = frozenset(
    {
        "draw",
        "flower_replace",
        "discard",
        "meld",
        "claim_resolved",
        "kong_replace",
        "hand_end",
        "game_end",
    }
)


@dataclass(frozen=True)
class Sent:
    """A frame as the client parses it, and `Table.state` when it went out."""

    wire: dict[str, Any]
    state: GameState


@dataclass(frozen=True)
class Reduced:
    before: GameState
    after: GameState
    events: tuple[Event, ...]


@dataclass
class Recorded:
    sent: dict[int | str, list[Sent]] = field(default_factory=dict)
    reduced: list[Reduced] = field(default_factory=list)


def as_parsed(wire: dict[str, Any]) -> dict[str, Any]:
    """Int keys become strings, as on the wire."""
    parsed: dict[str, Any] = json.loads(json.dumps(wire))
    return parsed


def recorder(rec: Recorded, table: Table, key: int | str) -> Callable[[int, dict[str, Any]], None]:
    """A `send` callback for a seat binding or spectator that records into `rec.sent[key]`."""
    sent = rec.sent.setdefault(key, [])

    def send(seq: int, wire: dict[str, Any]) -> None:
        del seq
        sent.append(Sent(as_parsed(wire), table.state))

    return send


def record_engine(rec: Recorded, monkeypatch: pytest.MonkeyPatch) -> None:
    """Log every `reduce`/`start_next_hand` call `app.table` makes into `rec.reduced`."""
    real_reduce, real_next_hand = table_module.reduce, table_module.start_next_hand

    def reduce(state: GameState, action: Any) -> tuple[GameState, list[Event]]:
        after, events = real_reduce(state, action)
        rec.reduced.append(Reduced(state, after, tuple(events)))
        return after, events

    def start_next_hand(state: GameState) -> tuple[GameState, list[Event]]:
        after, events = real_next_hand(state)
        rec.reduced.append(Reduced(state, after, tuple(events)))
        return after, events

    monkeypatch.setattr(table_module, "reduce", reduce)
    monkeypatch.setattr(table_module, "start_next_hand", start_next_hand)


def _without(wire: dict[str, Any], keys: frozenset[str]) -> dict[str, Any]:
    return {k: v for k, v in wire.items() if k not in keys}


# what `Table` adds to `hand_end` from its own clock and nonce
_HAND_END_OWNED = frozenset({"deadline_ts", "fairness"})


def sent_event_frames(sent: list[Sent]) -> list[dict[str, Any]]:
    return [_without(s.wire, _HAND_END_OWNED) for s in sent if s.wire["t"] in EVENT_FRAMES]


def rebuilt_event_frames(rec: Recorded, recipient: int | None) -> list[dict[str, Any]]:
    """Every event frame `recipient` should get, rebuilt from the logged engine steps: a
    no-claim `claim_resolved` only reaches the seats its window offered (architecture.md §4)."""
    frames = []
    for step in rec.reduced:
        window = step.before.claim_window
        offered = {o.seat for o in window.offers} if window is not None else set()
        for event in step.events:
            private = isinstance(event, ClaimResolved) and event.winning_seat is None
            if private and recipient not in offered:
                continue
            wire = as_parsed(event_frame(step.after, recipient, event))
            frames.append(_without(wire, _HAND_END_OWNED))
    return frames
