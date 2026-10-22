"""REST request/response models for `app/main.py`'s routes (docs/protocol.md §10). Hand-typed on
the client in `web/src/lib/net/lobby.ts`, not codegen'd."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.table_types import WireSeatStatus
from mahjong_core.hand_check import HAND_SIZE
from mahjong_core.presets import DEFAULT_PRESET_ID
from mahjong_core.scoring.faan import validate_faan_overrides
from mahjong_core.tiles import N_FLOWERS

__all__ = [
    "BotLatencyOut",
    "CreateTableRequest",
    "CreateTableResponse",
    "LoadPointOut",
    "ScoreHandRequest",
    "ScoreHandResponse",
    "SeatSummary",
    "ServerStatus",
    "StatusResponse",
    "TableList",
    "TableSummaryOut",
]

# /healthz's and /status's "status"
type ServerStatus = Literal["ok", "degraded", "draining"]


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
    # left out of GET /tables; joinable by id/url only
    private: bool = False

    @field_validator("rules")
    @classmethod
    def _check_faan_overrides(cls, rules: dict[str, Any] | None) -> dict[str, Any] | None:
        # the one rules field rejected rather than folded into resolve_ruleset's fallback: the
        # table keeps and echoes it on every state_sync
        if rules is not None and "faan_overrides" in rules:
            validate_faan_overrides(rules["faan_overrides"])
        return rules


class CreateTableResponse(BaseModel):
    table_id: str
    # same shape as state_sync.ruleset/ruleset_preset
    ruleset_preset: str | None
    ruleset: dict[str, Any]


class BotLatencyOut(BaseModel):
    p50_ms: float
    p95_ms: float


class LoadPointOut(BaseModel):
    ts: int
    players: int
    tables: int
    bot_p95_ms: float | None
    loop_lag_ms: float


class StatusResponse(BaseModel):
    status: ServerStatus
    uptime_seconds: int
    players_online: int
    spectators: int
    tables_playing: int
    tables_waiting: int
    # live tables / MAX_TABLES; None when unlimited
    capacity_pct: int | None
    # None without a database
    games_finished_24h: int | None
    # None with no bot decision in the last 5 minutes
    bot_decision_ms: BotLatencyOut | None
    loop_lag_ms: float
    history: list[LoadPointOut]


class ScoreHandRequest(BaseModel):
    # same ruleset choice as CreateTableRequest, resolved the same way
    ruleset: str = DEFAULT_PRESET_ID
    rules: dict[str, Any] | None = None
    # concealed tile codes ('1m'..'z7'); the last one is the winning tile
    tiles: list[str] = Field(max_length=HAND_SIZE)
    # 'f1'..'f8'
    flowers: list[str] = Field(default=[], max_length=N_FLOWERS)
    self_drawn: bool = False
    # False: one set was claimed from another seat (which one is maximised over)
    fully_concealed: bool = True
    # mahjong_core.state.Wind: 0 = East .. 3 = North
    seat_wind: int = Field(default=0, ge=0, le=3)
    prevailing_wind: int = Field(default=0, ge=0, le=3)


class ScoreHandResponse(BaseModel):
    winning: bool
    # the rest is None/empty when the tiles aren't a winning shape
    total_faan: int | None
    breakdown: dict[str, int]
    clears_min_faan: bool | None
    points: int | None
    # the resolved ruleset's, so the client can explain a hand below the minimum
    min_faan: int
