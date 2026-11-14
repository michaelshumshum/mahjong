"""Seat count and range check. Import-free so `wall`, `melds` and `state` can all depend on it
(`state` imports both of those, so it can't own the constant itself)."""

N_SEATS = 4


def validate_seat(seat: int) -> None:
    if not 0 <= seat < N_SEATS:
        raise ValueError(f"seat must be 0..{N_SEATS - 1}, got {seat}")
