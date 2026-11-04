"""Seat display names: the guest `join.name` and an account's `users.display_name` share one cap
and normalizer (docs/protocol.md §2 `join.name`, docs/decisions/0028-user-account-schema.md)."""

from __future__ import annotations

from typing import Final

MAX_NAME_LENGTH: Final = 24


def normalize_name(raw: str | None, seat: int) -> str:
    """Trim whitespace, cap at `MAX_NAME_LENGTH` chars, fall back to `"Guest N"` (1-indexed)
    when empty or omitted -- a low-stakes guest field, so bad input is normalized, never
    rejected."""
    trimmed = (raw or "").strip()
    if not trimmed:
        return f"Guest {seat + 1}"
    return trimmed[:MAX_NAME_LENGTH]
