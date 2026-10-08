"""PPO rollout env (docs/ml.md §7, §9, §10): `HandEnv`s whose surfaced decisions come back as
packed encoder-v2 rows, with non-learning seats played inside the env. `ml`-extra only.

Each episode seats `EnvConfig.learners` learning seats (drawn from the episode seed) and fills the
rest with an in-env opponent (`OPPONENTS`). A surfaced decision is one packed `uint8` row
(`ROW_FIELDS`): the acting seat's policy raw row, its oracle raw row, its current shanten (the
shaping potential), the episode's `min_faan`, the seat's role, and — on an `aux_rate` subsample of
learner decisions — the expensive auxiliary labels (opponent waits/faan, shanten/ukeire after each
discard). The policy row is built by `encode_v2.policy_raw`, the parity-tested leak guard; oracle
fields only ever feed the critic and the annealed oracle input.

Roles: `LEARNER` rows are trained on; `FROZEN` rows are surfaced for the caller to act with some
other policy and are never trained on (the league, `ml.league`); in-env opponents never surface.
With `EnvConfig.mix` each episode draws its seating and opponent id from a weighted table instead
(the league's opponent mix); every row of the episode carries that id. With
`EnvConfig.alt_rulesets` an episode plays another `RULESET_PRESETS` entry with that probability;
its rows' `ruleset` is then 1 + its index in `PRESET_IDS` (0 = `EnvConfig.ruleset`).

`VecTrainEnv` steps in-process, `SubprocVecTrainEnv` splits the envs over worker processes with
shared-memory buffers (as `ml.vec_env`). Both give identical arrays for the same seeds and actions.
"""

from __future__ import annotations

import itertools
import random
import traceback
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from multiprocessing.connection import Connection
from typing import Any, Self

import numpy as np

from bots.arena import _tenpai_can_reach_min_faan
from bots.labels import is_tenpai, seat_hand34
from mahjong_core.config import DEFAULT_RULESET, RuleSet
from mahjong_core.ml import N_ACTIONS
from mahjong_core.presets import RULESET_PRESETS
from mahjong_core.shanten import shanten
from mahjong_core.state import GameState, HandOutcome, Phase
from ml.encode_v2 import ORACLE_FIELDS, PAD, POLICY_FIELDS, oracle_raw, policy_raw
from ml.env import HandEnv
from ml.generate_aux import _label_row, _unseen, shanten_labels
from ml.mp import mp_context
from ml.vec_env import episode_seed

__all__ = [
    "AUX_LABEL_FIELDS",
    "FROZEN",
    "INFO_FIELDS",
    "LEARNER",
    "OPPONENTS",
    "PRESET_IDS",
    "ROW_BYTES",
    "ROW_FIELDS",
    "EnvConfig",
    "SubprocVecTrainEnv",
    "TrainEnv",
    "VecTrainEnv",
    "opponent_ids",
    "tsumogiri",
    "unpack_rows",
    "with_min_faan",
]

LEARNER = 0
FROZEN = 1
_PASS = 102
_TILES = 34

AUX_LABEL_FIELDS: dict[str, tuple[int, ...]] = {
    "opp_tenpai": (3,),
    "opp_wait": (3, _TILES),
    "opp_faan": (3, _TILES),
    "shanten": (_TILES,),
    "ukeire": (_TILES,),
}
ROW_FIELDS: dict[str, tuple[int, ...]] = {
    **POLICY_FIELDS,
    **ORACLE_FIELDS,
    "cur_shanten": (),  # shanten + 1, so -1 (complete) fits uint8
    "min_faan": (),
    "role": (),
    "aux": (),
    "teacher": (),  # §10 contingency teacher action, PAD unless enabled
    "ruleset": (),
    "opponent": (2,),  # league opponent id, little-endian; 0 = none
    **AUX_LABEL_FIELDS,
}
_OFFSETS: dict[str, tuple[int, int, tuple[int, ...]]] = {}
_at = 0
for _name, _shape in ROW_FIELDS.items():
    _n = int(np.prod(_shape)) if _shape else 1
    _OFFSETS[_name] = (_at, _at + _n, _shape)
    _at += _n
ROW_BYTES = _at

# per finished episode: winner, discarder (-1 if none), then seat bitmasks
INFO_FIELDS = ("winner", "discarder", "learners", "tenpai_at_draw", "sub_min_tenpai")

PRESET_IDS: tuple[str, ...] = tuple(RULESET_PRESETS)


def unpack_rows(rows: np.ndarray, fields: tuple[str, ...] | None = None) -> dict[str, np.ndarray]:
    """`(B, ROW_BYTES)` packed rows -> named `uint8` views, shaped as `ROW_FIELDS`."""
    out = {}
    for name in fields or tuple(ROW_FIELDS):
        lo, hi, shape = _OFFSETS[name]
        out[name] = rows[:, lo:hi].reshape(len(rows), *shape)
    return out


def opponent_ids(u: dict[str, np.ndarray]) -> np.ndarray:
    """Per row, the episode's league opponent id from unpacked rows."""
    opp = u["opponent"].astype(np.int64)
    return opp[:, 0] | opp[:, 1] << 8


def tsumogiri(state: GameState, seat: int, mask: np.ndarray) -> int:
    """Discard the tile just drawn (the last concealed tile); pass every claim, never win."""
    if state.phase == Phase.AWAIT_ACTION and state.turn == seat:
        t = state.seats[seat].concealed[-1] // 4
        if mask[t]:
            return int(t)
        return int(np.flatnonzero(mask[:_TILES])[0])
    return _PASS


Opponent = Callable[[GameState, int, np.ndarray], int]
OPPONENTS: dict[str, Opponent] = {"tsumogiri": tsumogiri}


def _faanbot_teacher() -> Callable[[GameState, int, np.ndarray], int]:
    """§10 contingency only: `FaanBot`'s action from the seat's own `SeatView`."""
    import asyncio

    from app.views import seat_view
    from bots.faanbot import FaanBot

    bot = FaanBot()

    def act(state: GameState, seat: int, mask: np.ndarray) -> int:
        return asyncio.run(bot.act(seat_view(state, seat), mask.tolist(), float("inf")))

    return act


_TEACHERS: dict[str, Callable[[], Callable[[GameState, int, np.ndarray], int]]] = {
    "FaanBot": _faanbot_teacher
}


@dataclass(frozen=True)
class EnvConfig:
    """`learners` seats per episode surface as `LEARNER`, `frozen` more as `FROZEN`, the rest
    play `opponent` in-env. `teacher` is the §10 contingency and stays `None` unless enabled.

    `mix`, if set, replaces `learners`/`frozen` per episode: `(weight, learners, opponent_id)`
    entries, the remaining seats `FROZEN`. `alt_rulesets`: `(preset, probability)` pairs; the rest
    of the time an episode plays `ruleset`."""

    ruleset: RuleSet = DEFAULT_RULESET
    learners: int = 4
    frozen: int = 0
    opponent: str = "tsumogiri"
    aux_rate: float = 0.0
    teacher: str | None = None
    mix: tuple[tuple[float, int, int], ...] = ()
    alt_rulesets: tuple[tuple[str, float], ...] = ()

    def __post_init__(self) -> None:
        if not 1 <= self.learners <= 4 or self.learners + self.frozen > 4 or self.frozen < 0:
            raise ValueError(f"bad seating: learners={self.learners}, frozen={self.frozen}")
        if self.learners + self.frozen < 4 and self.opponent not in OPPONENTS:
            raise ValueError(f"unknown opponent {self.opponent!r}; choices: {sorted(OPPONENTS)}")
        if self.teacher is not None and self.teacher not in _TEACHERS:
            raise ValueError(f"unknown teacher {self.teacher!r}")
        for weight, learners, opp in self.mix:
            if weight < 0 or not 1 <= learners <= 4 or not 0 <= opp < 1 << 16:
                raise ValueError(f"bad mix entry {(weight, learners, opp)}")
            if (learners < 4) != (opp > 0):
                raise ValueError(f"mix entry {(weight, learners, opp)}: frozen seats need an id")
        if self.mix and sum(w for w, _, _ in self.mix) <= 0:
            raise ValueError("mix weights sum to 0")
        for name, prob in self.alt_rulesets:
            if name not in RULESET_PRESETS or prob < 0:
                raise ValueError(f"bad alt ruleset {(name, prob)}")
        if sum(p for _, p in self.alt_rulesets) > 1:
            raise ValueError("alt_rulesets probabilities sum past 1")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["ruleset"] = self.ruleset.to_dict()
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> EnvConfig:
        return EnvConfig(
            **{
                **d,
                "ruleset": RuleSet.from_dict(d["ruleset"]),
                "mix": tuple(tuple(e) for e in d.get("mix", ())),
                "alt_rulesets": tuple(tuple(e) for e in d.get("alt_rulesets", ())),
            }
        )


def _roles(cfg: EnvConfig, seed: int) -> tuple[list[int], int]:
    """Per seat `LEARNER`, `FROZEN`, or -1 (in-env opponent); and the episode's opponent id."""
    learners, frozen, opp = cfg.learners, cfg.frozen, 0
    if cfg.mix:
        rng = random.Random(f"mix:{seed}")
        _, learners, opp = rng.choices(cfg.mix, weights=[w for w, _, _ in cfg.mix])[0]
        frozen = 4 - learners
    seats = random.Random(f"seats:{seed}").sample(range(4), learners + frozen)
    roles = [-1] * 4
    for i, s in enumerate(seats):
        roles[s] = LEARNER if i < learners else FROZEN
    return roles, opp


def _episode_ruleset(cfg: EnvConfig, seed: int) -> tuple[RuleSet, int]:
    if not cfg.alt_rulesets:
        return cfg.ruleset, 0
    u = random.Random(f"ruleset:{seed}").random()
    for name, prob in cfg.alt_rulesets:
        if u < prob:
            return RULESET_PRESETS[name], 1 + PRESET_IDS.index(name)
        u -= prob
    return cfg.ruleset, 0


def _bits(seats: list[int]) -> int:
    return sum(1 << s for s in seats)


class TrainEnv:
    """One `HandEnv` with in-env opponents. `reset(seed)` and `step(aid)` leave the next surfaced
    decision in `seat`, `mask` and `row`; `step` returns `(done, rewards, info)` for the episode it
    finished (if any) before auto-resetting via `next_seed`."""

    def __init__(self, cfg: EnvConfig) -> None:
        self.cfg = cfg
        self.pending_cfg: EnvConfig | None = None
        self.env = HandEnv(cfg.ruleset, encode=False)
        self.row = np.zeros(ROW_BYTES, dtype=np.uint8)
        self.seat = -1
        self.mask = np.zeros(N_ACTIONS, dtype=bool)
        self.roles = [-1] * 4
        self.opponent_id = 0
        self.ruleset_id = 0
        self._aux_rng = random.Random()
        self._opponent: Opponent | None = None
        self._teacher: Callable[[GameState, int, np.ndarray], int] | None = None
        self._apply_cfg(cfg)

    def _apply_cfg(self, cfg: EnvConfig) -> None:
        self.cfg = cfg
        self.env.ruleset = cfg.ruleset
        self._opponent = OPPONENTS.get(cfg.opponent)
        self._teacher = _TEACHERS[cfg.teacher]() if cfg.teacher is not None else None

    def reset(self, seed: int) -> bool:
        """Start episode `seed`; False if it ended before any surfaced decision."""
        if self.pending_cfg is not None:
            self._apply_cfg(self.pending_cfg)
            self.pending_cfg = None
        self.roles, self.opponent_id = _roles(self.cfg, seed)
        self.env.ruleset, self.ruleset_id = _episode_ruleset(self.cfg, seed)
        self._aux_rng = random.Random(f"aux:{seed}")
        seat, _, mask = self.env.reset(seed)
        done = self._advance(seat, mask)
        if not done:
            self._fill_row()
        return not done

    def step(self, aid: int) -> tuple[bool, np.ndarray, list[int]]:
        seat, _, mask, done, _ = self.env.step(aid)
        if not done:
            done = self._advance(seat, mask)
        if done:
            return True, self.env.rewards(), self._info()
        self._fill_row()
        return False, np.zeros(4, dtype=np.float32), []

    def _advance(self, seat: int, mask: np.ndarray) -> bool:
        while self.roles[seat] < 0:
            assert self._opponent is not None and self.env.state is not None
            seat, _, mask, done, _ = self.env.step(self._opponent(self.env.state, seat, mask))
            if done:
                return True
        self.seat, self.mask = seat, mask
        return False

    def _info(self) -> list[int]:
        state = self.env.state
        assert state is not None and state.hand_result is not None
        result = state.hand_result
        learners = [s for s in range(4) if self.roles[s] == LEARNER]
        tenpai, sub_min = [], []
        if result.outcome == HandOutcome.EXHAUSTIVE_DRAW:
            for s in learners:
                if is_tenpai(state, s):
                    tenpai.append(s)
                    if not _tenpai_can_reach_min_faan(state, s):
                        sub_min.append(s)
        won = result.outcome == HandOutcome.WIN and result.winner is not None
        winner = result.winner if won and result.winner is not None else -1
        discarder = result.discarder if won and result.discarder is not None else -1
        return [winner, discarder, _bits(learners), _bits(tenpai), _bits(sub_min)]

    def _fill_row(self) -> None:
        state, seat, row = self.env.state, self.seat, self.row
        assert state is not None
        role = self.roles[seat]
        values: dict[str, Any] = {**policy_raw(state, seat), **oracle_raw(state, seat)}
        seat_state = state.seats[seat]
        sh = shanten(
            seat_hand34(seat_state),
            closed=not seat_state.melds,
            hand_sets=state.ruleset.hand_sets,
        )
        values["cur_shanten"] = sh + 1
        values["min_faan"] = state.ruleset.min_faan
        values["role"] = role
        values["ruleset"] = self.ruleset_id
        values["opponent"] = (self.opponent_id & 0xFF, self.opponent_id >> 8)
        aux = role == LEARNER and self._aux_rng.random() < self.cfg.aux_rate
        values["aux"] = int(aux)
        values["teacher"] = (
            self._teacher(state, seat, self.mask) if self._teacher is not None else PAD
        )
        if aux:
            values.update(_label_row(state, seat))
            if state.phase == Phase.AWAIT_ACTION and state.turn == seat:
                sh_after, uk = shanten_labels(state, seat, _unseen(values))
            else:
                sh_after, uk = [PAD] * _TILES, [0] * _TILES
            values["shanten"], values["ukeire"] = sh_after, uk
        else:
            for name, shape in AUX_LABEL_FIELDS.items():
                values[name] = np.zeros(shape, dtype=np.uint8)
            values["shanten"] = np.full(_TILES, PAD, dtype=np.uint8)
        for name, (lo, hi, _) in _OFFSETS.items():
            row[lo:hi] = np.asarray(values[name]).ravel()


@dataclass(frozen=True)
class _Buffers:
    """seat (K,) int32; mask (K, N_ACTIONS) bool; rows (K, ROW_BYTES) uint8; done (K,) bool;
    rewards (K, 4) float32; info (K, len(INFO_FIELDS)) int8."""

    seat: np.ndarray
    mask: np.ndarray
    rows: np.ndarray
    done: np.ndarray
    rewards: np.ndarray
    info: np.ndarray

    @staticmethod
    def allocate(n: int) -> _Buffers:
        return _Buffers(
            seat=np.zeros(n, dtype=np.int32),
            mask=np.zeros((n, N_ACTIONS), dtype=bool),
            rows=np.zeros((n, ROW_BYTES), dtype=np.uint8),
            done=np.zeros(n, dtype=bool),
            rewards=np.zeros((n, 4), dtype=np.float32),
            info=np.zeros((n, len(INFO_FIELDS)), dtype=np.int8),
        )

    def part(self, lo: int, hi: int) -> _Buffers:
        return _Buffers(**{k: getattr(self, k)[lo:hi] for k in self.__dataclass_fields__})


class VecTrainEnv:
    """`reset()` / `step(actions)` fill and return the buffers: `seat, mask, rows` describe each
    env's next surfaced decision; where `done[i]`, `rewards[i]`/`info[i]` belong to the episode that
    just ended. `configure(cfg)` takes effect at each env's next episode."""

    def __init__(
        self,
        n_envs: int,
        base_seed: int,
        cfg: EnvConfig,
        *,
        first_index: int = 0,
        buffers: _Buffers | None = None,
    ) -> None:
        self.num_envs = n_envs
        self.base_seed = base_seed
        self.envs = [TrainEnv(cfg) for _ in range(n_envs)]
        self._first = first_index
        self._episodes = [0] * n_envs
        self.buf = buffers or _Buffers.allocate(n_envs)

    def configure(self, cfg: EnvConfig) -> None:
        for env in self.envs:
            env.pending_cfg = cfg

    def reset(self) -> _Buffers:
        self._episodes = [0] * self.num_envs
        self.buf.done[:] = False
        self.buf.rewards[:] = 0.0
        self.buf.info[:] = 0
        for i in range(self.num_envs):
            self._reset_one(i)
        return self.buf

    def step(self, actions: np.ndarray) -> _Buffers:
        buf = self.buf
        for i, env in enumerate(self.envs):
            done, rewards, info = env.step(int(actions[i]))
            buf.done[i] = done
            buf.rewards[i] = rewards
            if done:
                buf.info[i] = info
                self._reset_one(i)
            else:
                self._publish(i)
        return buf

    def _reset_one(self, i: int) -> None:
        env = self.envs[i]
        while True:
            seed = episode_seed(self.base_seed, self._first + i, self._episodes[i])
            self._episodes[i] += 1
            if env.reset(seed):
                break
        self._publish(i)

    def _publish(self, i: int) -> None:
        env, buf = self.envs[i], self.buf
        buf.seat[i] = env.seat
        buf.mask[i] = env.mask
        buf.rows[i] = env.row


def _shared(ctx: Any, n: int) -> dict[str, Any]:
    return {
        "seat": ctx.RawArray("i", n),
        "mask": ctx.RawArray("b", n * N_ACTIONS),
        "rows": ctx.RawArray("B", n * ROW_BYTES),
        "done": ctx.RawArray("b", n),
        "rewards": ctx.RawArray("f", n * 4),
        "info": ctx.RawArray("b", n * len(INFO_FIELDS)),
        "actions": ctx.RawArray("i", n),
    }


def _views(raw: dict[str, Any], n: int) -> tuple[_Buffers, np.ndarray]:
    buf = _Buffers(
        seat=np.frombuffer(raw["seat"], dtype=np.int32),
        mask=np.frombuffer(raw["mask"], dtype=bool).reshape(n, N_ACTIONS),
        rows=np.frombuffer(raw["rows"], dtype=np.uint8).reshape(n, ROW_BYTES),
        done=np.frombuffer(raw["done"], dtype=bool),
        rewards=np.frombuffer(raw["rewards"], dtype=np.float32).reshape(n, 4),
        info=np.frombuffer(raw["info"], dtype=np.int8).reshape(n, len(INFO_FIELDS)),
    )
    return buf, np.frombuffer(raw["actions"], dtype=np.int32)


def _worker(
    conn: Connection,
    lo: int,
    hi: int,
    n: int,
    raw: dict[str, Any],
    base_seed: int,
    cfg: dict[str, Any],
) -> None:
    full, actions = _views(raw, n)
    venv = VecTrainEnv(
        hi - lo,
        base_seed,
        EnvConfig.from_dict(cfg),
        first_index=lo,
        buffers=full.part(lo, hi),
    )
    while True:
        cmd, arg = conn.recv()
        try:
            if cmd == "reset":
                venv.reset()
            elif cmd == "step":
                venv.step(actions[lo:hi])
            elif cmd == "configure":
                venv.configure(EnvConfig.from_dict(arg))
            else:
                return
            conn.send(("ok", None))
        except Exception:  # noqa: BLE001 -- re-raised in the parent with this traceback
            conn.send(("err", traceback.format_exc()))


class SubprocVecTrainEnv:
    """`VecTrainEnv`'s API over `n_workers` processes. Use as a context manager or `close()`."""

    def __init__(self, n_envs: int, base_seed: int, cfg: EnvConfig, *, n_workers: int) -> None:
        if not 1 <= n_workers <= n_envs:
            raise ValueError(f"n_workers must be in 1..{n_envs}, got {n_workers}")
        self.num_envs = n_envs
        ctx = mp_context()
        raw = _shared(ctx, n_envs)
        self.buf, self._actions = _views(raw, n_envs)
        bounds = np.linspace(0, n_envs, n_workers + 1).astype(int)
        self._conns: list[Connection] = []
        self._procs = []
        for lo, hi in itertools.pairwise(bounds):
            parent, child = ctx.Pipe()
            proc = ctx.Process(
                target=_worker,
                args=(child, int(lo), int(hi), n_envs, raw, base_seed, cfg.to_dict()),
                daemon=True,
            )
            proc.start()
            child.close()
            self._conns.append(parent)
            self._procs.append(proc)

    def configure(self, cfg: EnvConfig) -> None:
        self._broadcast("configure", cfg.to_dict())

    def reset(self) -> _Buffers:
        self._broadcast("reset")
        return self.buf

    def step(self, actions: np.ndarray) -> _Buffers:
        self._actions[:] = actions
        self._broadcast("step")
        return self.buf

    def close(self) -> None:
        for conn in self._conns:
            try:
                conn.send(("close", None))
            except (BrokenPipeError, OSError):
                pass
        for proc in self._procs:
            proc.join(timeout=5)
        self._conns = []
        self._procs = []

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _broadcast(self, cmd: str, arg: object = None) -> None:
        for conn in self._conns:
            conn.send((cmd, arg))
        errors = [p for status, p in (c.recv() for c in self._conns) if status == "err"]
        if errors:
            raise RuntimeError("train env worker failed:\n" + "\n".join(errors))


def with_min_faan(cfg: EnvConfig, min_faan: int) -> EnvConfig:
    return replace(cfg, ruleset=replace(cfg.ruleset, min_faan=min_faan))
