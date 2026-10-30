"""`Table`'s outbound frames against the pure builders in `app/frames.py`. Seeded games
(`min_faan=0`, random play that wins and kongs whenever it can) run through a real `Table` with
four joined seats and a spectator; every frame each recipient gets is recorded with the state it
was built from.

- `test_frame_streams_are_pinned` hashes every recipient's stream (deadlines blanked: they read
  the clock), pinned before the builders moved out of `Table`, so a change to any frame's bytes,
  key order included, fails it.
- `test_frames_rebuild_from_state` rebuilds every frame from its state alone, with only what
  `Table` owns (deadlines, seat statuses, names, history, fairness) taken from the frame."""

from __future__ import annotations

import dataclasses
import hashlib
import itertools
import json
import random
from dataclasses import dataclass
from typing import Any

import pytest

import app.table as table_module
from app.frames import (
    claim_offer_frame,
    deal_frame,
    hand_start_frame,
    score_frame,
    state_sync_frame,
    turn_frame,
)
from app.lessons.model import MeldSetup, Position, SeatSetup
from app.lessons.position import build_position
from app.table import Table
from bots.random import random_action
from mahjong_core.actions import Action, ActionKind, legal_actions
from mahjong_core.config import GameLength, RuleSet
from mahjong_core.events import ClaimResolved, FlowerReplaced, HandEnded, MeldFormed
from mahjong_core.melds import MeldKind
from mahjong_core.state import GameState, Phase
from tests.table_frames import (
    Recorded,
    Sent,
    as_parsed,
    rebuilt_event_frames,
    record_engine,
    recorder,
    sent_event_frames,
)

_RULESET = RuleSet(
    min_faan=0,
    dealer_repeat_on_win=False,
    dealer_repeat_on_draw=False,
    game_length=GameLength.EAST_ONLY,
    hand_end_seconds=0,
    provable_fairness=True,
)

_SPECTATOR = "spectator"
_STEP_CAP = 5000


def robbable_kong() -> GameState:
    """Seat 0 to act with a 1m pung and the fourth 1m; seat 2 waits on 1m, so the added kong
    opens a kong-rob window. Random play never reaches one."""
    state = build_position(
        Position(
            seats=(
                SeatSetup(hand="1m2468246s567z", melds=(MeldSetup(MeldKind.PUNG, "111m", 1),)),
                SeatSetup(hand="1234z1234z13579s"),
                SeatSetup(hand="23456789m123p99p"),
                SeatSetup(hand="1234z13579s5678p"),
            ),
            seed=7,
        )
    )
    return dataclasses.replace(state, ruleset=_RULESET)


async def play_recorded(
    seed: int, monkeypatch: pytest.MonkeyPatch, start: GameState | None = None
) -> Recorded:
    """One full game through `Table`; every frame each recipient got, and every engine step.
    `start` replaces hand 1's deal before the table starts."""
    rec = Recorded()
    nonces = itertools.count()
    monkeypatch.setattr(table_module, "new_nonce", lambda: next(nonces).to_bytes(16, "big"))
    record_engine(rec, monkeypatch)

    table = Table(f"frames-{seed}", _RULESET, game_seed=seed, require_ready=True)
    table.register_spectator(_SPECTATOR, recorder(rec, table, _SPECTATOR))
    for seat in range(4):
        table.join(f"session-{seat}", recorder(rec, table, seat), seat=seat, name=f"P{seat}")
    if start is not None:
        table.state = start
    for seat in range(4):
        table.mark_ready(seat)

    rng = random.Random(seed)
    for _ in range(_STEP_CAP):
        state = table.state
        if state.phase == Phase.GAME_OVER:
            return rec
        if state.phase == Phase.HAND_OVER:
            await table.process_one()
            continue
        if state.phase in (Phase.AWAIT_CLAIMS, Phase.AWAIT_KONG_ROB):
            assert state.claim_window is not None
            window = state.claim_window
            seat = rng.choice([o.seat for o in window.offers if o.seat not in window.responses])
        else:
            seat = state.turn
        table.submit(seat, _greedy_action(state, seat, rng))
        await table.process_one()
    raise RuntimeError(f"seed {seed}: no GAME_OVER within {_STEP_CAP} steps")


_WINS = (ActionKind.DECLARE_WIN, ActionKind.CLAIM_WIN)
_KONGS = (ActionKind.DECLARE_CONCEALED_KONG, ActionKind.DECLARE_ADDED_KONG, ActionKind.CLAIM_KONG)


def _greedy_action(state: GameState, seat: int, rng: random.Random) -> Action:
    """Random play that always wins or kongs when it can: uniform play almost never wins."""
    actions = legal_actions(state, seat)
    for kinds in (_WINS, _KONGS):
        picks = [a for a in actions if a.kind in kinds]
        if picks:
            return picks[0]
    return random_action(state, seat, rng)


def _blank_deadline(wire: dict[str, Any]) -> dict[str, Any]:
    if wire.get("deadline_ts") is None:
        return wire
    return {k: ("<deadline>" if k == "deadline_ts" else v) for k, v in wire.items()}


def stream_digest(sent: list[Sent]) -> str:
    h = hashlib.sha256()
    for s in sent:
        h.update(json.dumps(_blank_deadline(s.wire)).encode())
        h.update(b"\n")
    return h.hexdigest()[:16]


def coverage(rec: Recorded) -> set[str]:
    """What a set of games exercised: meld kinds, claim kinds won, flowers, hand outcomes."""
    seen: set[str] = set()
    for step in rec.reduced:
        for event in step.events:
            if isinstance(event, MeldFormed):
                seen.add(event.meld.kind.value)
            elif isinstance(event, ClaimResolved) and event.winning_seat is not None:
                seen.add(f"{event.claim_kind.value}:{event.action_kind}")
            elif isinstance(event, FlowerReplaced):
                seen.add("flower")
            elif isinstance(event, HandEnded):
                seen.add(f"{event.outcome.value}:{event.win_type}")
    return seen


@dataclass(frozen=True)
class Game:
    seed: int
    covers: frozenset[str]
    # recipient -> stream digest
    digests: dict[int | str, str]
    rigged: bool = False


# seeds picked for what they cover; together, every frame shape
_GAMES = {
    "self-draw": Game(
        seed=28,
        covers=frozenset(
            {"chow", "pung", "exposed_kong", "concealed_kong", "flower", "win:self_draw"}
        ),
        digests={
            0: "0a13d37fb187df14",
            1: "2def300b3f74f079",
            2: "25c2c86b74b5905d",
            3: "1f602adc16e8ffbc",
            _SPECTATOR: "da09165487da9dc7",
        },
    ),
    "discard-win": Game(
        seed=30,
        covers=frozenset({"discard:claim_win", "win:discard", "exhaustive_draw:None"}),
        digests={
            0: "06e5f1edefda4228",
            1: "2b0eadaad283422d",
            2: "3ea041ea13a072f5",
            3: "f8457dc9b05e59fd",
            _SPECTATOR: "f33e4f4051db1d99",
        },
    ),
    "kong-rob": Game(
        seed=7,
        covers=frozenset({"added_kong", "kong_rob:claim_win", "win:kong_rob"}),
        digests={
            0: "bf5e42e68d257de4",
            1: "256cfa26aa10b3c5",
            2: "58e7bf2ab9390665",
            3: "ab22d8d1ac2e3aae",
            _SPECTATOR: "562fd7846500c908",
        },
        rigged=True,
    ),
}


def test_games_cover_every_frame_shape() -> None:
    covered = frozenset().union(*(g.covers for g in _GAMES.values()))
    meld_kinds = {k.value for k in MeldKind if k != MeldKind.PAIR}
    wins = {f"win:{w}" for w in ("self_draw", "discard", "kong_rob")}
    assert covered >= meld_kinds | wins | {"flower", "exhaustive_draw:None"}


@pytest.mark.parametrize("name", _GAMES)
async def test_frame_streams_are_pinned(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    game = _GAMES[name]
    rec = await play_recorded(game.seed, monkeypatch, robbable_kong() if game.rigged else None)
    assert coverage(rec) >= game.covers
    assert {key: stream_digest(sent) for key, sent in rec.sent.items()} == game.digests


# what `Table` adds to a `state_sync` from its clock, seat bindings and history
_SYNC_OWNED = frozenset(
    {
        "seat_status",
        "names",
        "deadline_ts",
        "host_seat",
        "hand_history",
        "bot_levels",
        "seed_commit",
    }
)


def _rebuilt(sent: Sent, recipient: int | None) -> dict[str, Any] | None:
    """`sent` rebuilt from its state; `None` for a frame with no builder (`seat_state`, events)."""
    wire, state = sent.wire, sent.state
    match wire["t"]:
        case "turn":
            return turn_frame(state, recipient, deadline_ts=wire["deadline_ts"])
        case "claim_offer":
            assert recipient is not None
            return claim_offer_frame(state, recipient, deadline_ts=wire["deadline_ts"])
        case "deal":
            assert recipient is not None
            return deal_frame(state, recipient)
        case "hand_start":
            return hand_start_frame(state, seats=wire["seats"], seed_commit=wire.get("seed_commit"))
        case "score":
            return score_frame(state)
        case "state_sync":
            sync = state_sync_frame(state, recipient, seed_commit=wire.get("seed_commit"))
            return {k: (wire[k] if k in _SYNC_OWNED else v) for k, v in sync.items()}
        case _:
            return None


@pytest.mark.parametrize("name", _GAMES)
async def test_frames_rebuild_from_state(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    game = _GAMES[name]
    rec = await play_recorded(game.seed, monkeypatch, robbable_kong() if game.rigged else None)
    for key, sent in rec.sent.items():
        recipient = None if key == _SPECTATOR else key
        assert isinstance(recipient, int | None)
        for s in sent:
            rebuilt = _rebuilt(s, recipient)
            if rebuilt is not None:
                assert as_parsed(rebuilt) == s.wire, (key, s.wire["t"])
        assert sent_event_frames(sent) == rebuilt_event_frames(rec, recipient), key
