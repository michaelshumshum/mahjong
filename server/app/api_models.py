"""REST request/response models for `app/main.py`'s routes (docs/protocol.md §10). Hand-typed on
the client in `web/src/lib/net/lobby.ts`, not codegen'd, except `RandomLessonResponse`: a lesson
file, typed by the generated `lessons.d.ts`."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)

from app.accounts.learn import MAX_LEARN_COUNT
from app.db.models import GameMode, SeatKind
from app.lessons.model import Band, LessonKind, PuzzleKind, Track
from app.names import MAX_RAW_NAME_LENGTH
from app.protocol import StateSync
from app.table_types import WireSeatStatus
from mahjong_core.hand_check import HAND_SIZE
from mahjong_core.presets import DEFAULT_PRESET_ID
from mahjong_core.scoring.faan import validate_faan_overrides
from mahjong_core.tiles import N_FLOWERS

__all__ = [
    "BotLatencyOut",
    "CreateTableRequest",
    "CreateTableResponse",
    "EndlessScoreIn",
    "EndlessScoreOut",
    "ExportGame",
    "ExportIdentity",
    "ExportResponse",
    "ExportUser",
    "LearnImport",
    "LearnImportResponse",
    "LearnResponse",
    "LessonProgressIn",
    "LessonProgressOut",
    "LoadPointOut",
    "MePatch",
    "MeResponse",
    "MyGame",
    "MyGameSeat",
    "MyGamesResponse",
    "PrefsPatch",
    "RandomLessonResponse",
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


class MeResponse(BaseModel):
    """`GET /me`: the signed-in account (docs/protocol.md §10 "Accounts")."""

    id: uuid.UUID
    display_name: str
    created_at: dt.datetime
    # null = no consent to training on this user's games
    training_consent_at: dt.datetime | None
    consent_version: str | None


class PrefsPatch(BaseModel):
    """Synced settings in `users.prefs`; only these keys are stored. null removes one."""

    model_config = ConfigDict(extra="forbid")

    # the endless puzzles' band
    learn_band: Band | None = None
    # the first practice hand's coach marks were finished or skipped
    coach_marks_done: StrictBool | None = None


class MePatch(BaseModel):
    """`PATCH /me`. Omitted fields are unchanged."""

    model_config = ConfigDict(extra="forbid")

    # trimmed and capped like a guest name; empty is 422
    display_name: str | None = Field(default=None, max_length=MAX_RAW_NAME_LENGTH)
    # true records consent with the current wording's version; false withdraws it
    training_consent: bool | None = None
    # merged key by key into users.prefs
    prefs: PrefsPatch | None = None


LearnCount = Annotated[int, Field(ge=0, le=MAX_LEARN_COUNT)]


class LessonProgressIn(BaseModel):
    """One lesson's progress (web `LessonProgress`): `PUT /me/learn/{lesson_id}` and an upload
    entry."""

    model_config = ConfigDict(extra="forbid")

    solved: bool
    attempts: LearnCount
    solved_at: AwareDatetime | None = None
    # a tutorial's resume point
    step: LearnCount | None = None

    @model_validator(mode="after")
    def _consistent(self) -> LessonProgressIn:
        if self.solved and self.attempts < 1:
            raise ValueError("a solved lesson has an attempt")
        if self.solved_at is not None and not self.solved:
            raise ValueError("solved_at without solved")
        return self


class LessonProgressOut(BaseModel):
    solved: bool
    attempts: int
    solved_at: dt.datetime | None
    step: int | None
    # values came from a local upload, not a server-recorded answer
    imported: bool


class EndlessScoreIn(BaseModel):
    """One puzzle kind's endless score (web `EndlessScore`)."""

    model_config = ConfigDict(extra="forbid")

    streak: LearnCount
    best: LearnCount
    solved: LearnCount

    @model_validator(mode="after")
    def _consistent(self) -> EndlessScoreIn:
        if not self.streak <= self.best <= self.solved:
            raise ValueError("needs streak <= best <= solved")
        return self


class EndlessScoreOut(BaseModel):
    streak: int
    best: int
    solved: int
    imported: bool


class LearnResponse(BaseModel):
    """`GET /me/learn`: progress by lesson id, endless scores by `PuzzleKind`, synced prefs."""

    progress: dict[str, LessonProgressOut]
    endless: dict[str, EndlessScoreOut]
    prefs: dict[str, Any]


class LearnImport(BaseModel):
    """`POST /me/learn/import`: a device's guest progress. Entries stay untyped here so a bad
    one is dropped on its own (`LessonProgressIn`, `EndlessScoreIn`, `PrefsPatch` each)."""

    model_config = ConfigDict(extra="forbid")

    progress: dict[str, Any] = Field(default_factory=dict)
    endless: dict[str, Any] = Field(default_factory=dict)
    prefs: dict[str, Any] = Field(default_factory=dict)


class LearnImportResponse(LearnResponse):
    """The merged progress, plus how many uploaded entries failed validation."""

    dropped: int


class ExportUser(BaseModel):
    id: uuid.UUID
    display_name: str
    created_at: dt.datetime
    training_consent_at: dt.datetime | None
    consent_version: str | None
    disabled_at: dt.datetime | None
    # the last learn-progress upload
    learn_imported_at: dt.datetime | None


class ExportIdentity(BaseModel):
    provider: str
    subject: str
    email: str | None
    created_at: dt.datetime


class ExportGame(BaseModel):
    game_id: int
    created_at: dt.datetime
    mode: str | None
    seat: int
    hand_count: int | None
    final_score: int
    placement: int
    players: list[str | None]


class ExportResponse(BaseModel):
    """`GET /me/export`."""

    user: ExportUser
    identities: list[ExportIdentity]
    games: list[ExportGame]
    learn: LearnResponse


class MyGameSeat(BaseModel):
    """Another seat of one of the caller's games. Never carries a user id."""

    seat: int
    kind: SeatKind
    # games.players[seat] for a user or guest seat; null for a bot
    name: str | None
    # bots.tiers.BotTier as stored; a str so a retired tier still reads
    bot_tier: str | None


class MyGame(BaseModel):
    game_id: int
    # persist time = game end
    created_at: dt.datetime
    # null for games saved before modes were recorded
    mode: GameMode | None
    hand_count: int | None
    seat: int
    placement: int
    final_score: int
    others: list[MyGameSeat]


class MyGamesResponse(BaseModel):
    """`GET /me/games`, newest first; `next` is the `before` cursor of the next page."""

    games: list[MyGame]
    next: int | None


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


class RandomLessonResponse(BaseModel):
    """A generated puzzle file's `Lesson` (docs/protocol.md §6), the shape `lessons.d.ts` types
    on the web. Documents `GET /lessons/random`, which returns the payload unvalidated."""

    id: str
    lesson_kind: Literal[LessonKind.PUZZLE]
    kind: PuzzleKind
    track: Track
    band: Band
    text: str
    n: int
    engine_version: str
    snapshot: StateSync
    # app/lessons/grade.py's key for `kind`, dataclasses.asdict
    key: dict[str, Any]


class ScoreHandResponse(BaseModel):
    winning: bool
    # the rest is None/empty when the tiles aren't a winning shape
    total_faan: int | None
    breakdown: dict[str, int]
    clears_min_faan: bool | None
    points: int | None
    # the resolved ruleset's, so the client can explain a hand below the minimum
    min_faan: int
