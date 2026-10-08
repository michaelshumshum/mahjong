"""League (docs/ml.md §11): the opponent pool for curriculum stage C2. `ml`-extra only.

Per episode (one hand) the env draws from `League.mix()`:

- `self_share`: the current policy in all four seats, every seat a `LEARNER`;
- `past_share`: `seat_learners` learner seats against a past snapshot in the other seats;
- `persona_share`: the same against a persona snapshot.

A snapshot plays `FROZEN` seats: its actions come from its own frozen `PolicyNet` and produce
no training samples. A share with nothing in its pool goes to self-play.

Past snapshots are taken every `snapshot_every` learner decisions (the first when the league
starts), at most `max_past` kept (oldest evicted). Persona snapshots are forks of the current
learner trained for `persona_updates` updates of 4-seat self-play on a perturbed reward
(`persona_rewards`; `ml.ppo.train_persona`), one per persona at every past snapshot, at most
`max_personas` kept. Heuristic bots never enter the pool.

Opponents are sampled by prioritised fictitious self-play: weight (1 − x)^`pfsp_power`, x the
learner's pairwise win share against that snapshot's seats — per hand, each (learner seat,
snapshot seat) pair scores 1 / ½ / 0 as the learner's payment is above / equal to / below the
snapshot seat's, so x is ½ at parity whatever the seating. Counts decay by `stat_decay` per update
and start from a ½ prior (one pseudo-game). To keep the rollout forward batched, only `active_past`
past and `active_personas` persona draws (with replacement) are playable at a time, redrawn every
`rotate_every` updates; a step runs one forward per distinct opponent present.

Learned-only Elo (§12): each past snapshot is anchored at the learner's rating when it was taken;
the learner's rating is the maximum-likelihood fit to its decayed pairwise scores against them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any

import numpy as np
import torch

from ml.policy_net import PolicyNet, PolicyNetConfig

__all__ = [
    "DEFAULT_PERSONAS",
    "PAST",
    "Entry",
    "League",
    "LeagueConfig",
    "Persona",
    "pairwise_scores",
    "persona_rewards",
]

PAST = "past"
_ELO_SCALE = 400.0
# a hand spans at most a handful of updates; an evicted model stays playable this long
_RETIRE_UPDATES = 64


@dataclass(frozen=True)
class Persona:
    """Reward multipliers on the seat's own hand payment: `win` when it wins, `deal_in` when it
    dealt in."""

    name: str
    win: float = 1.0
    deal_in: float = 1.0


DEFAULT_PERSONAS = (Persona("aggressive", win=1.3), Persona("defensive", deal_in=1.5))


def persona_rewards(rewards: np.ndarray, info: np.ndarray, persona: Persona) -> np.ndarray:
    """`rewards` (4,) of a finished hand, `info` its `INFO_FIELDS` row."""
    winner, discarder = int(info[0]), int(info[1])
    out = np.array(rewards, dtype=np.float32)
    if winner >= 0:
        out[winner] *= persona.win
        if discarder >= 0 and discarder != winner:
            out[discarder] *= persona.deal_in
    return out


def pairwise_scores(rewards: np.ndarray, learners: list[int], others: list[int]) -> float:
    """Sum over (learner seat, other seat) pairs of 1 / ½ / 0 by payment comparison."""
    total = 0.0
    for a in learners:
        for b in others:
            total += 1.0 if rewards[a] > rewards[b] else 0.5 if rewards[a] == rewards[b] else 0.0
    return total


@dataclass
class LeagueConfig:
    self_share: float = 0.5
    past_share: float = 0.35
    persona_share: float = 0.15
    seat_learners: int = 1
    snapshot_every: int = 50_000_000
    max_past: int = 32
    max_personas: int = 8
    active_past: int = 3
    active_personas: int = 1
    rotate_every: int = 16
    pfsp_power: float = 2.0
    stat_decay: float = 0.999
    persona_updates: int = 100
    personas: tuple[Persona, ...] = DEFAULT_PERSONAS

    def __post_init__(self) -> None:
        shares = (self.self_share, self.past_share, self.persona_share)
        if min(shares) < 0 or sum(shares) <= 0:
            raise ValueError(f"bad league shares {shares}")
        if not 1 <= self.seat_learners <= 3:
            raise ValueError(f"seat_learners must be 1..3, got {self.seat_learners}")
        if min(self.max_past, self.max_personas, self.active_past, self.active_personas) < 1:
            raise ValueError("max_past, max_personas, active_past, active_personas must be >= 1")
        names = [p.name for p in self.personas]
        if PAST in names or len(set(names)) != len(names):
            raise ValueError(f"persona names must be unique and not {PAST!r}: {names}")

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> LeagueConfig:
        raw = dict(raw)
        unknown = set(raw) - {f.name for f in fields(LeagueConfig)}
        if unknown:
            raise ValueError(f"unknown league keys: {sorted(unknown)}")
        if "personas" in raw:
            raw["personas"] = tuple(Persona(**p) for p in raw["personas"])
        return LeagueConfig(**raw)


@dataclass
class Entry:
    """One frozen snapshot. `score`/`games` are decayed pairwise counts (the PFSP and Elo input),
    `hands`/`wins` decayed learner seat-hands against it."""

    id: int
    kind: str
    decisions: int
    elo: float
    state: dict[str, torch.Tensor] = field(repr=False)
    score: float = 0.0
    games: float = 0.0
    hands: float = 0.0
    wins: float = 0.0

    @property
    def win_share(self) -> float:
        return (self.score + 0.5) / (self.games + 1.0)


def _expected(diff: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + 10.0 ** (-diff / _ELO_SCALE))


class League:
    """Pool, sampling, statistics and Elo. Frozen models live on `device`, gradients off."""

    def __init__(
        self, cfg: LeagueConfig, model_config: PolicyNetConfig, device: torch.device, seed: int
    ) -> None:
        self.cfg = cfg
        self.model_config = model_config
        self.device = device
        self.entries: list[Entry] = []
        self.next_id = 1
        self.next_snapshot: int | None = None
        self.elo = 0.0
        self.active: list[int] = []
        self.rotated_at: int | None = None
        self.rng = np.random.default_rng([seed, 0x1EA6])
        self._models: dict[int, PolicyNet] = {}
        # evicted, possibly still seated in a hand in flight: id -> (kind, model, update evicted)
        self._retired: dict[int, tuple[str, PolicyNet, int]] = {}

    def by_kind(self, past: bool) -> list[Entry]:
        return [e for e in self.entries if (e.kind == PAST) == past]

    def entry(self, oid: int) -> Entry | None:
        return next((e for e in self.entries if e.id == oid), None)

    def snapshot_due(self, decisions: int) -> bool:
        return self.next_snapshot is None or decisions >= self.next_snapshot

    def begin_snapshot(self, decisions: int, updates: int) -> None:
        self.next_snapshot = decisions + self.cfg.snapshot_every
        for oid, (_, _, at) in list(self._retired.items()):
            if updates - at > _RETIRE_UPDATES:
                del self._retired[oid]

    def add(self, kind: str, policy: PolicyNet, decisions: int, updates: int) -> Entry:
        state = {k: v.detach().cpu().clone() for k, v in policy.state_dict().items()}
        e = Entry(self.next_id, kind, decisions, self.elo, state)
        self.next_id += 1
        self.entries.append(e)
        self._models[e.id] = self._load(state)
        pool = self.by_kind(kind == PAST)
        cap = self.cfg.max_past if kind == PAST else self.cfg.max_personas
        for old in pool[: max(0, len(pool) - cap)]:
            self.entries.remove(old)
            self._retired[old.id] = (old.kind, self._models.pop(old.id), updates)
        self.rotated_at = None
        return e

    def _load(self, state: dict[str, torch.Tensor]) -> PolicyNet:
        model = PolicyNet(self.model_config)
        model.load_state_dict(state)
        return model.to(self.device).requires_grad_(False)

    def model(self, oid: int) -> PolicyNet:
        return self._models[oid] if oid in self._models else self._retired[oid][1]

    def kind(self, oid: int) -> str:
        e = self.entry(oid)
        return e.kind if e is not None else self._retired[oid][0]

    def weights(self, pool: list[Entry]) -> np.ndarray:
        w = np.array([(1.0 - e.win_share) ** self.cfg.pfsp_power for e in pool])
        return w / w.sum()

    def rotate(self, updates: int) -> bool:
        """Redraw the playable opponents if due (or after a snapshot); True when redrawn."""
        if self.rotated_at is not None and updates - self.rotated_at < self.cfg.rotate_every:
            return False
        self.rotated_at = updates
        active = []
        for past, n in ((True, self.cfg.active_past), (False, self.cfg.active_personas)):
            pool = self.by_kind(past)
            if pool:
                draws = self.rng.choice(len(pool), size=n, p=self.weights(pool))
                active += [pool[int(i)].id for i in draws]
        self.active = active
        return True

    def mix(self) -> tuple[tuple[float, int, int], ...]:
        """`EnvConfig.mix` over the active opponents; an empty share goes to self-play."""
        c = self.cfg
        groups: dict[bool, list[int]] = {True: [], False: []}
        for oid in self.active:
            e = self.entry(oid)
            if e is not None:
                groups[e.kind == PAST].append(oid)
        weights: dict[int, float] = {}
        self_w = c.self_share
        for past, share in ((True, c.past_share), (False, c.persona_share)):
            ids = groups[past]
            if not ids:
                self_w += share
            for oid in ids:
                weights[oid] = weights.get(oid, 0.0) + share / len(ids)
        out = [(self_w, 4, 0)] if self_w > 0 else []
        out += [(w, c.seat_learners, oid) for oid, w in sorted(weights.items())]
        return tuple(out)

    def observe(self, hands: list[tuple[int, np.ndarray, int]]) -> dict[str, float]:
        """`(opponent id, rewards (4,), learner seat bitmask)` per finished hand of one update:
        decays the counts, adds these hands, refits the Elo. Returns the batch's opponent-type
        mix (share of hands) and exhaustive-draw rate per type."""
        d = self.cfg.stat_decay
        for e in self.entries:
            e.score, e.games, e.hands, e.wins = (x * d for x in (e.score, e.games, e.hands, e.wins))
        counts = {"self": 0, "past": 0, "persona": 0}
        draws = dict.fromkeys(counts, 0)
        for oid, rewards, bits in hands:
            kind = "self" if oid == 0 else "past" if self.kind(oid) == PAST else "persona"
            draw = not np.any(rewards > 0)
            counts[kind] += 1
            draws[kind] += draw
            e = self.entry(oid) if oid else None
            if e is None:
                continue
            learners = [s for s in range(4) if bits >> s & 1]
            others = [s for s in range(4) if not bits >> s & 1]
            e.score += pairwise_scores(rewards, learners, others)
            e.games += len(learners) * len(others)
            e.hands += len(learners)
            e.wins += sum(bool(rewards[s] > 0) for s in learners)
        self.elo = self.fit_elo()
        n = sum(counts.values())
        out: dict[str, float] = {}
        for kind, c in counts.items():
            out[f"league_mix_{kind}"] = c / n if n else 0.0
            if c:
                out[f"league_draw_{kind}"] = draws[kind] / c
        return out

    def fit_elo(self) -> float:
        pool = [e for e in self.by_kind(True) if e.games > 0]
        if not pool:
            return self.elo
        anchors = np.array([e.elo for e in pool])
        games = np.array([e.games for e in pool]) + 1.0
        score = np.array([e.score for e in pool]) + 0.5
        lo, hi = anchors.min() - 4000.0, anchors.max() + 4000.0
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            if (games * _expected(mid - anchors)).sum() < score.sum():
                lo = mid
            else:
                hi = mid
        return float(0.5 * (lo + hi))

    def metrics(self) -> dict[str, Any]:
        return {
            "league_past": len(self.by_kind(True)),
            "league_personas": len(self.by_kind(False)),
            "league_elo": round(self.elo, 2),
            "league_active": list(self.active),
            "league_vs": {
                f"{e.kind}{e.id}": {
                    "x": round(e.win_share, 4),
                    "win": round(e.wins / e.hands, 4) if e.hands > 0 else None,
                    "hands": round(e.hands, 1),
                    "elo": round(e.elo, 1),
                    "decisions": e.decisions,
                }
                for e in self.entries
            },
        }

    def state_dict(self) -> dict[str, Any]:
        return {
            "entries": [asdict(e) for e in self.entries],
            "next_id": self.next_id,
            "next_snapshot": self.next_snapshot,
            "elo": self.elo,
            "active": list(self.active),
            "rotated_at": self.rotated_at,
            "rng": self.rng.bit_generator.state,
            "model_config": self.model_config.to_dict(),
        }

    def load_state_dict(self, state: dict[str, Any]) -> None:
        self.entries = [Entry(**e) for e in state["entries"]]
        self.next_id = state["next_id"]
        self.next_snapshot = state["next_snapshot"]
        self.elo = state["elo"]
        self.active = list(state["active"])
        self.rotated_at = state["rotated_at"]
        self.rng.bit_generator.state = state["rng"]
        self._models = {e.id: self._load(e.state) for e in self.entries}
        self._retired.clear()
