"""`GameState` builders and invariants shared by engine/table tests."""

import dataclasses

from mahjong_core.state import GameState


def with_seat(state: GameState, seat: int, **overrides: object) -> GameState:
    seats = list(state.seats)
    seats[seat] = dataclasses.replace(seats[seat], **overrides)  # type: ignore[arg-type]
    return dataclasses.replace(state, seats=tuple(seats))  # type: ignore[arg-type]


def total_tiles(state: GameState) -> int:
    """Every non-flower tile in hands, melds, discards and wall, plus every seat's flowers."""
    seat_tiles = sum(
        len(seat.concealed) + sum(len(m.tiles) for m in seat.melds) + len(seat.discards)
        for seat in state.seats
    )
    seat_flowers = sum(len(seat.flowers) for seat in state.seats)
    return seat_tiles + len(state.wall.tiles) + seat_flowers
