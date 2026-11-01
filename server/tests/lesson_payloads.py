"""Checks on a puzzle's lesson JSON (docs/protocol.md §6), shared by the generated bundle's tests
and `GET /lessons/random`'s."""

from collections.abc import Mapping
from typing import Any

from pydantic import TypeAdapter

from app.protocol import ServerMessage, StateSync
from mahjong_core.engine import ENGINE_VERSION

PUZZLE_FIELDS = frozenset(
    {
        *("id", "lesson_kind", "kind", "track", "band", "text", "n", "theme"),
        *("engine_version", "snapshot", "key"),
    }
)

_server_message: TypeAdapter[object] = TypeAdapter(ServerMessage)


def assert_seat_zero_snapshot(snapshot: Mapping[str, Any]) -> StateSync:
    frame = _server_message.validate_python(snapshot)
    assert isinstance(frame, StateSync)
    assert frame.d.seat == 0
    assert frame.d.hands is None
    assert frame.d.ruleset_preset == "hk_classic"
    return frame


def assert_puzzle_payload(payload: Mapping[str, Any]) -> None:
    """Every field a `Lesson` has, under this engine, with a seat-0 snapshot."""
    assert payload.keys() == PUZZLE_FIELDS
    assert payload["lesson_kind"] == "puzzle"
    assert payload["engine_version"] == ENGINE_VERSION
    assert_seat_zero_snapshot(payload["snapshot"])
