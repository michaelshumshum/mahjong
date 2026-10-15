"""REST request/response models for `app/main.py`'s routes (docs/protocol.md §10). Hand-typed on
the client in `web/src/lib/net/lobby.ts`, not codegen'd."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from app.table_types import WireSeatStatus
from mahjong_core.presets import DEFAULT_PRESET_ID

__all__ = [
    "CreateTableRequest",
    "CreateTableResponse",
    "SeatSummary",
    "TableList",
    "TableSummaryOut",
]


class SeatSummary(BaseModel):
    status: WireSeatStatus
    name: str | None


class TableSummaryOut(BaseModel):
    id: str
    status: Literal["open", "in_progress"]
    hand_no: int
    seats: list[SeatSummary]


class TableList(BaseModel):
    tables: list[TableSummaryOut]


class CreateTableRequest(BaseModel):
    # `mahjong_core.presets.RULESET_PRESETS` key, or "custom" to take `rules` below instead.
    ruleset: str = DEFAULT_PRESET_ID
    # `RuleSet.from_dict`-shaped; only read when `ruleset == "custom"`.
    rules: dict[str, Any] | None = None
    practice: bool = False
    # practice mode's per-seat difficulty picker: {1: "T1", 2: "T4", 3: "ORACLE"}-shaped, seat 0
    # excluded (the human seat) -- only meaningful when practice=True, see _resolve_seat_bot_tiers.
    bot_tiers: dict[int, str] | None = None


class CreateTableResponse(BaseModel):
    table_id: str
    # same shape as state_sync.ruleset/ruleset_preset
    ruleset_preset: str | None
    ruleset: dict[str, Any]
