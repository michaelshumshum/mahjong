"""Table-level exceptions and wire error payloads. Each exception maps to one wire
`error{code}` (`app/ws.py`)."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

__all__ = [
    "TABLE_CLOSED_ERROR",
    "ErrorCode",
    "NotHostError",
    "SeatAuthError",
    "SeatNotBoundError",
    "SeatTakenError",
    "TableAlreadyStartedError",
    "TableFullError",
]


class ErrorCode(StrEnum):
    """Every wire `error{code}` the server sends. Ack failures (`ack{error}`) are a separate,
    untyped vocabulary."""

    BAD_FRAME = "bad_frame"
    ALREADY_JOINED = "already_joined"
    NO_SUCH_SEAT = "no_such_seat"
    SEAT_TAKEN = "seat_taken"
    BAD_SECRET = "bad_secret"
    NOT_JOINED = "not_joined"
    TABLE_CLOSED = "table_closed"


# error payload for every socket on (or later connecting to) an abandoned table; the client stops
# reconnecting on this code
TABLE_CLOSED_ERROR: Final = {
    "code": ErrorCode.TABLE_CLOSED,
    "message": "table closed: every player left",
}


class SeatTakenError(Exception):
    """Raised by `Table.join(seat=...)` when the requested seat is already bound
    (wire `error{code:'seat_taken'}`)."""

    def __init__(self, seat: int) -> None:
        super().__init__(f"seat {seat} is already taken")
        self.seat = seat


class TableFullError(Exception):
    """Raised by `Table.join(seat=None)` when every seat is bound (wire
    `error{code:'table_full'}`)."""


class SeatNotBoundError(Exception):
    """Raised by `Table.reconnect(seat, ...)` when nothing has ever `join`ed this seat -- no
    `SeatBinding` to reclaim (wire `error{code:'no_such_seat'}`). Distinct from `SeatTakenError`:
    that fires on `join` finding a seat already bound; this fires on `hello` finding one never
    bound."""

    def __init__(self, seat: int) -> None:
        super().__init__(f"seat {seat} has never been joined")
        self.seat = seat


class SeatAuthError(Exception):
    """Raised by `Table.reconnect(seat, ..., secret=...)` when the presented `secret` doesn't
    match `SeatBinding.reconnect_secret` (wire `error{code:'bad_secret'}`), including a missing
    one."""

    def __init__(self, seat: int) -> None:
        super().__init__(f"seat {seat} secret mismatch")
        self.seat = seat


class NotHostError(Exception):
    """Raised by `Table.start_with_bots(seat)` when `seat` isn't `self.host_seat` (wire
    `error{code:'not_host'}`). Host is whichever seat's `join` was this table's first."""

    def __init__(self, seat: int) -> None:
        super().__init__(f"seat {seat} is not the host")
        self.seat = seat


class TableAlreadyStartedError(Exception):
    """Raised by `Table.start_with_bots(seat)` once `self.started` (wire
    `error{code:'already_started'}`)."""
