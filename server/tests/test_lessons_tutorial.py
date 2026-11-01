"""Tutorial scripts (`app/lessons/tutorial.py`, ADR 0025): the catalog's scripts run and
validate, a broken script is rejected at build time, and every step's frames are what a live
`Table` sends seat 0 for the same actions."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from pydantic import TypeAdapter

from app.lessons.catalog import TUTORIALS
from app.lessons.catalog.tutorials import BASICS_TUTORIAL
from app.lessons.model import Auto, Expect, Move, Narrate, Tutorial
from app.lessons.position import build_position
from app.lessons.tutorial import SEAT, run_tutorial
from app.protocol import ServerMessage, StateSync
from app.table import Table
from mahjong_core.actions import ActionKind, action_to_dict
from mahjong_core.state import WinType
from tests.table_frames import Recorded, as_parsed, recorder

_server_message: TypeAdapter[object] = TypeAdapter(ServerMessage)


def _with_steps(tutorial: Tutorial, *steps: Narrate | Expect | Auto) -> Tutorial:
    return dataclasses.replace(tutorial, steps=steps)


@pytest.mark.parametrize("tutorial", TUTORIALS, ids=lambda t: t.id)
def test_script_runs_to_its_end_phase(tutorial: Tutorial) -> None:
    run = run_tutorial(tutorial)
    assert run.final.phase == tutorial.end_phase
    for scripted in run.steps:
        if isinstance(scripted.step, Expect):
            assert scripted.seat == SEAT


@pytest.mark.parametrize("tutorial", TUTORIALS, ids=lambda t: t.id)
def test_frames_are_seat_zero_server_frames_with_a_dense_seq(tutorial: Tutorial) -> None:
    run = run_tutorial(tutorial)
    start = _server_message.validate_python(run.start)
    assert isinstance(start, StateSync) and start.d.seat == SEAT and start.seq == 0
    seqs = []
    for scripted in run.steps:
        if scripted.snapshot is not None:
            snapshot = _server_message.validate_python(scripted.snapshot)
            assert isinstance(snapshot, StateSync) and snapshot.seq == (seqs[-1] if seqs else 0)
        for frame in scripted.frames:
            _server_message.validate_python(frame)
            seqs.append(frame["seq"])
    assert seqs == list(range(1, len(seqs) + 1))


@pytest.mark.parametrize("tutorial", TUTORIALS, ids=lambda t: t.id)
def test_each_expect_snapshot_offers_the_expected_action(tutorial: Tutorial) -> None:
    for scripted in run_tutorial(tutorial).steps:
        if isinstance(scripted.step, Expect):
            assert scripted.snapshot is not None and scripted.action is not None
            legal = scripted.snapshot["d"]["legal_actions"]
            assert action_to_dict(scripted.action) in legal


def test_basics_teaches_discard_pung_chow_kong_then_self_draw() -> None:
    run = run_tutorial(BASICS_TUTORIAL)
    taught = [s.step.move.kind for s in run.steps if isinstance(s.step, Expect)]
    claims_and_win = [k for k in taught if k != ActionKind.DISCARD]
    assert taught[0] == ActionKind.DISCARD
    assert claims_and_win == [
        ActionKind.CLAIM_PUNG,
        ActionKind.CLAIM_CHOW,
        ActionKind.CLAIM_KONG,
        ActionKind.DECLARE_WIN,
    ]
    result = run.final.hand_result
    assert result is not None and result.winner == SEAT
    assert result.win_type == WinType.SELF_DRAW
    hand_end = run.steps[-2].frames[0]
    assert hand_end["t"] == "hand_end" and hand_end["d"]["revealed"]


def test_output_is_deterministic() -> None:
    assert run_tutorial(BASICS_TUTORIAL) == run_tutorial(BASICS_TUTORIAL)


def _first_expect(tutorial: Tutorial) -> int:
    return next(n for n, s in enumerate(tutorial.steps) if isinstance(s, Expect))


def test_an_illegal_scripted_action_is_rejected() -> None:
    n = _first_expect(BASICS_TUTORIAL)
    steps = list(BASICS_TUTORIAL.steps)
    steps[n] = Expect(Move(ActionKind.DISCARD, "1s"), "discardFirst")
    with pytest.raises(ValueError, match=rf"step {n}: seat 0 cannot discard 1s"):
        run_tutorial(_with_steps(BASICS_TUTORIAL, *steps))


def test_an_expect_on_another_seats_turn_is_rejected() -> None:
    n = _first_expect(BASICS_TUTORIAL)
    # seat 0's discard hands the turn to seat 1
    steps = [*BASICS_TUTORIAL.steps[: n + 1], Expect(Move(ActionKind.DISCARD, "1m"), "x")]
    with pytest.raises(ValueError, match=rf"step {n + 1}: expect: seat 0 has no decision"):
        run_tutorial(_with_steps(BASICS_TUTORIAL, *steps))


def test_an_auto_step_for_seat_zero_is_rejected() -> None:
    n = _first_expect(BASICS_TUTORIAL)
    steps = [*BASICS_TUTORIAL.steps[:n], Auto(SEAT, Move(ActionKind.DISCARD, "6z"))]
    with pytest.raises(ValueError, match=rf"step {n}: auto: seat 0's actions are expect"):
        run_tutorial(_with_steps(BASICS_TUTORIAL, *steps))


def test_a_flower_drawn_into_the_script_is_rejected() -> None:
    position = BASICS_TUTORIAL.position
    flowered = dataclasses.replace(position, wall_front="1f" + position.wall_front)
    with pytest.raises(ValueError, match="a flower was drawn"):
        run_tutorial(dataclasses.replace(BASICS_TUTORIAL, position=flowered))


def test_a_draw_past_the_stacked_wall_is_rejected() -> None:
    position = BASICS_TUTORIAL.position
    short = dataclasses.replace(position, wall_front=position.wall_front[:-2])
    with pytest.raises(ValueError, match="past the stacked wall_front"):
        run_tutorial(dataclasses.replace(BASICS_TUTORIAL, position=short))


def test_a_script_ending_in_another_phase_is_rejected() -> None:
    unfinished = _with_steps(BASICS_TUTORIAL, *BASICS_TUTORIAL.steps[:-3])
    with pytest.raises(ValueError, match="ends in"):
        run_tutorial(unfinished)


def _flat(frame: dict[str, Any]) -> dict[str, Any]:
    """An envelope as `Table` hands it to `send`, less the deadline `Table` reads off its
    clock."""
    flat = {"t": frame["t"]} | {k: v for k, v in frame["d"].items() if k != "deadline_ts"}
    return as_parsed(flat)


# what a live seat's state_sync carries from its Table: bindings, host, the clock
_TABLE_OWNED = frozenset({"t", "seat_status", "names", "host_seat", "deadline_ts"})


def _sync_fields(sync: dict[str, Any]) -> dict[str, Any]:
    fields = {k: v for k, v in sync.items() if k not in _TABLE_OWNED}
    if fields["claim_offer"] is not None:
        fields["claim_offer"] = _flat({"t": "claim_offer", "d": fields["claim_offer"]})
    return as_parsed(fields)


@pytest.mark.parametrize("tutorial", TUTORIALS, ids=lambda t: t.id)
async def test_frames_match_a_live_table(tutorial: Tutorial) -> None:
    run = run_tutorial(tutorial)
    rec = Recorded()
    table = Table(f"tutorial-{tutorial.id}", run.final.ruleset, game_seed=1)
    table.join("learner", recorder(rec, table, SEAT), seat=SEAT)
    table.state = build_position(tutorial.position)
    sent = rec.sent[SEAT]
    for scripted in run.steps:
        if scripted.action is None:
            continue
        if scripted.snapshot is not None:
            live = table.state_sync_wire(SEAT)
            assert _sync_fields(live) == _sync_fields(scripted.snapshot["d"])
        sent.clear()
        assert scripted.seat is not None
        table.submit(scripted.seat, scripted.action)
        await table.process_one()
        got = [{k: v for k, v in s.wire.items() if k != "deadline_ts"} for s in sent]
        assert got == [_flat(f) for f in scripted.frames], scripted.step
    assert table.state.phase == tutorial.end_phase
