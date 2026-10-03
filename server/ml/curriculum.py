"""Cold-start curriculum (docs/06-ml.md §10): C0 -> C0b -> C1, then C2 (the R3 league, a stub).

Each stage fixes the env seating (learning seats, in-env opponent) and linearly anneals, over
`anneal_decisions` from the stage's start, the oracle the policy sees (next-`k` draws, keep
probability) and the shaping β; `min_faan` steps up at fractions of the same anneal. A stage
advances once its anneal is complete and the rolling statistics over the last `window` learner
hands played since then meet every threshold it sets.

The §10 contingency (clone `FaanBot` with a decaying anchor) is built but off by default: unless
`contingency.enabled`, `teacher()` is always `None`, so the env never runs `FaanBot`.
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any

from ml.encode_v2 import ORACLE_MAX_DRAWS
from ml.ppo import HandStat, StageParams

__all__ = ["DEFAULT_STAGES", "Contingency", "Curriculum", "StageSpec"]


@dataclass(frozen=True)
class StageSpec:
    """`min_faan` is `[(value, from_fraction), ...]` over the anneal; thresholds left `None` are
    not checked. `implemented=False` marks a stage this milestone can't run (C2)."""

    name: str
    learners: int = 1
    opponent: str = "tsumogiri"
    min_faan: tuple[tuple[int, float], ...] = ((0, 0.0),)
    oracle_k: tuple[int, int] = (ORACLE_MAX_DRAWS, ORACLE_MAX_DRAWS)
    keep_prob: tuple[float, float] = (1.0, 1.0)
    beta: tuple[float, float] = (1.0, 1.0)
    anneal_decisions: int = 0
    min_decisions: int = 0
    win_rate: float | None = None
    blind_win_rate: float | None = None
    sub_min_tenpai_max: float | None = None
    min_tenpai_draws: int = 200
    implemented: bool = True

    @staticmethod
    def from_dict(d: dict[str, Any]) -> StageSpec:
        d = dict(d)
        if "min_faan" in d:
            d["min_faan"] = tuple((int(v), float(f)) for v, f in d["min_faan"])
        for key in ("oracle_k", "keep_prob", "beta"):
            if key in d:
                d[key] = tuple(d[key])
        return StageSpec(**d)


DEFAULT_STAGES: tuple[StageSpec, ...] = (
    StageSpec(name="C0", win_rate=0.40),
    StageSpec(
        name="C0b",
        oracle_k=(ORACLE_MAX_DRAWS, 0),
        beta=(1.0, 0.5),
        anneal_decisions=20_000_000,
        blind_win_rate=0.25,
    ),
    StageSpec(
        name="C1",
        learners=4,
        min_faan=((0, 0.0), (1, 0.5), (3, 1.0)),
        oracle_k=(0, 0),
        keep_prob=(1.0, 0.0),
        beta=(0.5, 0.0),
        anneal_decisions=200_000_000,
        win_rate=0.18,
        sub_min_tenpai_max=0.32,
    ),
    StageSpec(name="C2", learners=4, min_faan=((3, 0.0),), implemented=False),
)


def _lerp(pair: tuple[float, float], u: float) -> float:
    return pair[0] + (pair[1] - pair[0]) * u


@dataclass
class Contingency:
    """If `enabled`, and stage `stage` has run `after_decisions` with rolling win rate below
    `below_win_rate`, clone `teacher`'s actions with a coefficient decaying from `clone_coef` to 0
    over `anchor_decisions`. The checkpoint at coefficient 0 is the anchor-zero baseline the
    final agent must beat (paired CI > 0)."""

    enabled: bool = False
    teacher: str = "FaanBot"
    stage: str = "C1"
    after_decisions: int = 1_000_000_000
    below_win_rate: float = 0.10
    clone_coef: float = 1.0
    anchor_decisions: int = 500_000_000
    started_at: int | None = None
    anchor_zero_saved: bool = False


@dataclass
class Curriculum:
    stages: tuple[StageSpec, ...] = DEFAULT_STAGES
    window: int = 4000
    contingency: Contingency = field(default_factory=Contingency)
    index: int = 0
    stage_start: int = 0
    annealed_at: int | None = None
    recent: deque[HandStat] = field(default_factory=deque)

    def __post_init__(self) -> None:
        self.recent = deque(self.recent, maxlen=self.window)

    @staticmethod
    def from_config(raw: dict[str, Any]) -> Curriculum:
        raw = dict(raw)
        stages = DEFAULT_STAGES
        if "stages" in raw:
            overrides = {s["name"]: s for s in raw.pop("stages")}
            stages = tuple(
                StageSpec.from_dict({**asdict(s), **overrides.pop(s.name, {})})
                for s in DEFAULT_STAGES
            )
            if overrides:
                raise ValueError(f"unknown stages: {sorted(overrides)}")
        start = raw.pop("start", stages[0].name)
        contingency = Contingency(**raw.pop("contingency", {}))
        window = int(raw.pop("window", 4000))
        if raw:
            raise ValueError(f"unknown curriculum keys: {sorted(raw)}")
        index = [s.name for s in stages].index(start)
        return Curriculum(stages, window, contingency, index)

    @property
    def stage(self) -> StageSpec:
        return self.stages[self.index]

    def progress(self, decisions: int) -> float:
        span = self.stage.anneal_decisions
        return 1.0 if span <= 0 else min(1.0, (decisions - self.stage_start) / span)

    def params(self, decisions: int) -> StageParams:
        s = self.stage
        if not s.implemented:
            raise NotImplementedError(f"stage {s.name} is not part of R2 (league, R3)")
        u = self.progress(decisions)
        min_faan = s.min_faan[0][0]
        for value, at in s.min_faan:
            if u >= at:
                min_faan = value
        return StageParams(
            name=s.name,
            min_faan=min_faan,
            learners=s.learners,
            opponent=s.opponent,
            oracle_k=round(_lerp((float(s.oracle_k[0]), float(s.oracle_k[1])), u)),
            keep_prob=_lerp(s.keep_prob, u),
            beta=_lerp(s.beta, u),
        )

    def observe(self, stats: list[HandStat]) -> None:
        if self.annealed_at is not None:
            self.recent.extend(stats)

    def rolling(self) -> dict[str, float]:
        hands = list(self.recent)
        out: dict[str, float] = {"hands": len(hands)}
        if hands:
            out["win_rate"] = sum(h.won for h in hands) / len(hands)
            out["deal_in_rate"] = sum(h.dealt_in for h in hands) / len(hands)
            out["draw_rate"] = sum(h.draw for h in hands) / len(hands)
        blind = [h for h in hands if h.blind]
        if blind:
            out["blind_win_rate"] = sum(h.won for h in blind) / len(blind)
        tenpai = [h for h in hands if h.tenpai_at_draw]
        out["tenpai_draws"] = len(tenpai)
        if tenpai:
            out["sub_min_tenpai_rate"] = sum(h.sub_min_tenpai for h in tenpai) / len(tenpai)
        return out

    def ready(self, decisions: int) -> bool:
        s = self.stage
        if self.annealed_at is None or len(self.recent) < self.window:
            return False
        if decisions - self.stage_start < s.min_decisions:
            return False
        r = self.rolling()
        if s.win_rate is not None and r.get("win_rate", 0.0) < s.win_rate:
            return False
        if s.blind_win_rate is not None and r.get("blind_win_rate", 0.0) < s.blind_win_rate:
            return False
        return s.sub_min_tenpai_max is None or (
            r["tenpai_draws"] >= s.min_tenpai_draws
            and r.get("sub_min_tenpai_rate", 1.0) <= s.sub_min_tenpai_max
        )

    def advance(self, decisions: int) -> str | None:
        """Call after `observe`; returns the new stage's name when it moves on."""
        self._check_contingency(decisions)
        if self.annealed_at is None and self.progress(decisions) >= 1.0:
            self.annealed_at = decisions
            self.recent.clear()
        if not self.ready(decisions):
            return None
        self.index += 1
        self.stage_start = decisions
        self.annealed_at = None
        self.recent.clear()
        return self.stage.name

    def complete(self) -> bool:
        return not self.stage.implemented

    def _check_contingency(self, decisions: int) -> None:
        c = self.contingency
        if not c.enabled or c.started_at is not None or self.stage.name != c.stage:
            return
        if decisions - self.stage_start < c.after_decisions or len(self.recent) < self.window:
            return
        if self.rolling().get("win_rate", 0.0) < c.below_win_rate:
            c.started_at = decisions

    def clone_coef(self, decisions: int) -> float:
        c = self.contingency
        if not c.enabled or c.started_at is None:
            return 0.0
        return c.clone_coef * max(0.0, 1.0 - (decisions - c.started_at) / c.anchor_decisions)

    def teacher(self) -> str | None:
        c = self.contingency
        if not c.enabled or c.started_at is None or c.anchor_zero_saved:
            return None
        return c.teacher

    def snapshot_due(self, decisions: int) -> str | None:
        """`"anchor_zero"` once, when the contingency's clone coefficient first reaches 0."""
        c = self.contingency
        if c.started_at is None or c.anchor_zero_saved or self.clone_coef(decisions) > 0:
            return None
        c.anchor_zero_saved = True
        return "anchor_zero"

    def metrics(self) -> dict[str, float]:
        out = {f"rolling_{k}": v for k, v in self.rolling().items()}
        out["stage_index"] = self.index
        out["annealed"] = float(self.annealed_at is not None)
        if self.contingency.started_at is not None:
            out["contingency_started_at"] = self.contingency.started_at
        return out

    def state_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "stage_start": self.stage_start,
            "annealed_at": self.annealed_at,
            "recent": [asdict(h) for h in self.recent],
            "contingency": asdict(self.contingency),
        }

    def load_state_dict(self, state: dict[str, Any]) -> None:
        self.index = state["index"]
        self.stage_start = state["stage_start"]
        self.annealed_at = state["annealed_at"]
        self.recent = deque((HandStat(**h) for h in state["recent"]), maxlen=self.window)
        self.contingency = Contingency(**state["contingency"])
