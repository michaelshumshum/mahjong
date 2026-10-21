"""RuleSet — every configurable HK mahjong rule.

Plain frozen dataclass, not pydantic: mahjong_core has no deps beyond stdlib, even though
app/protocol.py uses pydantic elsewhere.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .tiles import TOTAL_PHYSICAL_TILES


class ScoreTable(StrEnum):
    """Faan -> points conversion (§8)."""

    FULL_SPICY = "full_spicy"
    HALF_SPICY = "half_spicy"


class HandSet(StrEnum):
    """Faan-table groups, each toggleable (§7)."""

    CLASSIC = "CLASSIC"
    NEW_6 = "NEW_6"
    NEW_18 = "NEW_18"


class DiscardPayment(StrEnum):
    """Who pays on a discard win (§8)."""

    ALL = "all"
    HALF = "half"


class GameLength(StrEnum):
    """Rounds played before the game ends (§2)."""

    EAST_ONLY = "EAST_ONLY"
    EAST_SOUTH = "EAST_SOUTH"  # riichi-style convention, not the HK norm
    FULL = "FULL"


_VALID_MIN_FAAN = frozenset({0, 1, 3, 5})
_VALID_FAAN_CAP = frozenset({8, 10, 13})
MAX_FAAN_CAP = max(_VALID_FAAN_CAP)

_INT_FIELDS = (
    "min_faan",
    "faan_cap",
    "wall_reserve",
    "turn_seconds",
    "claim_seconds",
    "hand_end_seconds",
    "turn_timeout_strikes",
)
_REAL_FIELDS = ("self_draw_multiplier", "disconnect_grace_seconds")

_MAX_TIMER_SECONDS = 3600

# structural bounds, enforced on every RuleSet (tests and stored records included).
# lower ends stay at 0 on purpose: 0-second timers are the tests' time-control knob.
_CORE_BOUNDS: dict[str, tuple[float, float]] = {
    "wall_reserve": (0, TOTAL_PHYSICAL_TILES),
    "turn_seconds": (0, _MAX_TIMER_SECONDS),
    "claim_seconds": (0, _MAX_TIMER_SECONDS),
    "hand_end_seconds": (0, _MAX_TIMER_SECONDS),
    "turn_timeout_strikes": (1, 100),
    "disconnect_grace_seconds": (0, _MAX_TIMER_SECONDS),
    "self_draw_multiplier": (1, 10),
}

# inclusive bounds for a client-supplied custom ruleset (presets.resolve_ruleset).
# docs/rules.md §10; web/src/lib/net/ruleset.ts NUMERIC_RULE_BOUNDS mirrors the steppers.
CLIENT_RULE_BOUNDS: dict[str, tuple[float, float]] = {
    "wall_reserve": (0, 30),
    "turn_seconds": (5, 60),
    "claim_seconds": (2, 30),
    "hand_end_seconds": (3, 60),
    "turn_timeout_strikes": (1, 10),
    "disconnect_grace_seconds": (5, 60),
    "self_draw_multiplier": (1, 2),
}


def _check_range(name: str, value: float, bounds: tuple[float, float]) -> None:
    lo, hi = bounds
    if not lo <= value <= hi:
        raise ValueError(f"{name} must be in [{lo}, {hi}], got {value}")


@dataclass(frozen=True)
class RuleSet:
    min_faan: int = 3  # one of 0 | 1 | 3 | 5 (§7); below this a hand cannot win
    faan_cap: int = 10  # one of 8 | 10 (HKMA) | 13 (casual); total is clamped (§7)
    score_table: ScoreTable = ScoreTable.HALF_SPICY
    hand_sets: frozenset[HandSet] = field(
        default_factory=lambda: frozenset({HandSet.CLASSIC, HandSet.NEW_6})
    )
    faan_overrides: dict[str, int] = field(default_factory=dict)
    # per-pattern faan override keyed by Chinese name (e.g. {"雞糊": 0}), applied after
    # hand_sets selection, before stacking/caps. dataclass freezing is shallow — still mutable.
    discard_payment: DiscardPayment = DiscardPayment.ALL
    self_draw_multiplier: float = 1.5
    flowers_score: bool = True  # 正花: +1 faan per flower matching seat (§7)
    seven_flowers_instant_win: bool = False
    eight_flowers_instant_win: bool = False
    thirteen_orphans_wait_bonus: bool = False  # flower instant-win + wait doubling (§7, §11.10)

    # flow
    game_length: GameLength = GameLength.EAST_ONLY
    dealer_repeat_on_win: bool = True
    dealer_repeat_on_draw: bool = True
    wall_reserve: int = 0  # HK default: no dead wall (§9)
    four_kong_abort: bool = False
    nine_terminals_abort: bool = False
    tenpai_payments: bool = False  # pay tenpai players on exhaustive draw (§9)

    # variants
    flowers_enabled: bool = True
    multi_win: bool = False  # 一炮多響, reserved: docs/decisions/0007-multi-win-and-pao.md
    kong_rob_enabled: bool = True
    concealed_kong_robbable: bool = False  # only for 十三么 on some tables (§5, §11.3)
    pao_rules: bool = False  # 包 responsibility — deferred to v2 (§8)

    # fairness (docs/protocol.md "Fairness")
    provable_fairness: bool = False  # gates hand_start.seed_commit / hand_end.fairness

    # timing (server-enforced); defaults documented in docs/architecture.md §4, §8.
    turn_seconds: int = 15
    claim_seconds: int = 5
    hand_end_seconds: int = 10
    turn_timeout_strikes: int = 3
    disconnect_grace_seconds: float = 20.0

    def __post_init__(self) -> None:
        for name in _INT_FIELDS:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an int, got {value!r}")
        for name in _REAL_FIELDS:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be a number, got {value!r}")
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite, got {value!r}")
        for name, bounds in _CORE_BOUNDS.items():
            _check_range(name, getattr(self, name), bounds)
        if not isinstance(self.faan_overrides, Mapping):
            raise TypeError(f"faan_overrides must be a mapping, got {self.faan_overrides!r}")
        for pattern, faan in self.faan_overrides.items():
            if not isinstance(pattern, str) or isinstance(faan, bool) or not isinstance(faan, int):
                raise TypeError(f"faan_overrides must map str -> int, got {pattern!r}: {faan!r}")
            if faan < 0:
                raise ValueError(f"faan_overrides[{pattern!r}] must be >= 0, got {faan}")
        if self.min_faan not in _VALID_MIN_FAAN:
            raise ValueError(
                f"min_faan must be one of {sorted(_VALID_MIN_FAAN)}, got {self.min_faan}"
            )
        if self.faan_cap not in _VALID_FAAN_CAP:
            raise ValueError(
                f"faan_cap must be one of {sorted(_VALID_FAAN_CAP)}, got {self.faan_cap}"
            )
        if self.multi_win:
            raise ValueError(
                "multi_win is reserved and must be False in v1 (see docs/decisions/0007-multi-win-and-pao.md)"
            )

    def check_client_bounds(self) -> None:
        """Raise `ValueError` unless this ruleset is one a client may create a table with:
        `CLIENT_RULE_BOUNDS` plus faan overrides capped at `MAX_FAAN_CAP`. Not part of
        `__post_init__` so tests and stored records keep their 0-second timers."""
        for name, bounds in CLIENT_RULE_BOUNDS.items():
            _check_range(name, getattr(self, name), bounds)
        for pattern, faan in self.faan_overrides.items():
            if faan > MAX_FAAN_CAP:
                raise ValueError(
                    f"faan_overrides[{pattern!r}] must be <= {MAX_FAAN_CAP}, got {faan}"
                )

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe representation. Round-trips via `RuleSet.from_dict`."""
        return {
            "min_faan": self.min_faan,
            "faan_cap": self.faan_cap,
            "score_table": self.score_table.value,
            "hand_sets": sorted(hs.value for hs in self.hand_sets),
            "faan_overrides": dict(self.faan_overrides),
            "discard_payment": self.discard_payment.value,
            "self_draw_multiplier": self.self_draw_multiplier,
            "flowers_score": self.flowers_score,
            "seven_flowers_instant_win": self.seven_flowers_instant_win,
            "eight_flowers_instant_win": self.eight_flowers_instant_win,
            "thirteen_orphans_wait_bonus": self.thirteen_orphans_wait_bonus,
            "game_length": self.game_length.value,
            "dealer_repeat_on_win": self.dealer_repeat_on_win,
            "dealer_repeat_on_draw": self.dealer_repeat_on_draw,
            "wall_reserve": self.wall_reserve,
            "four_kong_abort": self.four_kong_abort,
            "nine_terminals_abort": self.nine_terminals_abort,
            "tenpai_payments": self.tenpai_payments,
            "flowers_enabled": self.flowers_enabled,
            "multi_win": self.multi_win,
            "kong_rob_enabled": self.kong_rob_enabled,
            "concealed_kong_robbable": self.concealed_kong_robbable,
            "pao_rules": self.pao_rules,
            "provable_fairness": self.provable_fairness,
            "turn_seconds": self.turn_seconds,
            "claim_seconds": self.claim_seconds,
            "hand_end_seconds": self.hand_end_seconds,
            "turn_timeout_strikes": self.turn_timeout_strikes,
            "disconnect_grace_seconds": self.disconnect_grace_seconds,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RuleSet:
        return cls(
            min_faan=data["min_faan"],
            faan_cap=data["faan_cap"],
            score_table=ScoreTable(data["score_table"]),
            hand_sets=frozenset(HandSet(v) for v in data["hand_sets"]),
            faan_overrides=dict(data["faan_overrides"]),
            discard_payment=DiscardPayment(data["discard_payment"]),
            self_draw_multiplier=data["self_draw_multiplier"],
            flowers_score=data["flowers_score"],
            seven_flowers_instant_win=data["seven_flowers_instant_win"],
            eight_flowers_instant_win=data["eight_flowers_instant_win"],
            thirteen_orphans_wait_bonus=data["thirteen_orphans_wait_bonus"],
            game_length=GameLength(data["game_length"]),
            dealer_repeat_on_win=data["dealer_repeat_on_win"],
            dealer_repeat_on_draw=data["dealer_repeat_on_draw"],
            wall_reserve=data["wall_reserve"],
            four_kong_abort=data["four_kong_abort"],
            nine_terminals_abort=data["nine_terminals_abort"],
            tenpai_payments=data["tenpai_payments"],
            flowers_enabled=data["flowers_enabled"],
            multi_win=data["multi_win"],
            kong_rob_enabled=data["kong_rob_enabled"],
            concealed_kong_robbable=data["concealed_kong_robbable"],
            pao_rules=data["pao_rules"],
            provable_fairness=data["provable_fairness"],
            turn_seconds=data["turn_seconds"],
            claim_seconds=data["claim_seconds"],
            hand_end_seconds=data["hand_end_seconds"],
            turn_timeout_strikes=data["turn_timeout_strikes"],
            disconnect_grace_seconds=data["disconnect_grace_seconds"],
        )


DEFAULT_RULESET = RuleSet()
