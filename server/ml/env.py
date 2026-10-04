"""Single-hand self-play env over `mahjong_core` (docs/ml.md §7). `ml`-extra only.

One episode is a fresh hand from `engine.new_hand(ruleset, env_seed, dealer, prevailing)`,
played to `HAND_OVER`; the caller drives all four seats. Dealer and prevailing wind are drawn
from `env_seed` (uniform over seats and `prevailing_winds(ruleset)`), so the policy sees every
seat-wind context, not just hand 1's. Decisions with exactly one legal action are auto-played
and never surface. A trajectory is a pure function of `(ruleset, env_seed, actions)`.

Observations are `encode_seat_view(seat_view(...))` flattened into one float32 vector of
`OBS_DIM`, computed by the fast encoder (`ml/fast_encode.py`) that is parity-tested against it.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from app.db.records import hand_record_columns
from mahjong_core.actions import Action, action_from_dict
from mahjong_core.config import DEFAULT_RULESET, RuleSet
from mahjong_core.engine import (
    ENGINE_VERSION,
    IllegalActionError,
    new_hand,
    prevailing_winds,
    reduce,
)
from mahjong_core.ml import N_ACTIONS, decode_action, legal_mask
from mahjong_core.state import GameState, Phase, Wind
from ml.fast_encode import OBS_DIM, encode_state

__all__ = [
    "N_ACTIONS",
    "OBS_DIM",
    "REWARD_SCALE",
    "HandEnv",
    "encode_obs",
    "hand_start",
    "replay_hand",
]

REWARD_SCALE = 32
_STEP_CAP = 2000  # one hand is a few hundred engine steps at most
_ENDED = (Phase.HAND_OVER, Phase.GAME_OVER)


def encode_obs(state: GameState, seat: int, out: np.ndarray | None = None) -> np.ndarray:
    """`seat`'s observation, `(OBS_DIM,)` float32: `ml.fast_encode.encode_state`, parity-tested
    against `encode_reference` (`seat_view` -> `encode_seat_view`)."""
    return encode_state(state, seat, out)


def hand_start(ruleset: RuleSet, seed: int) -> tuple[int, Wind]:
    """`(dealer, prevailing)` for episode `seed`."""
    rng = random.Random(f"start:{seed}")
    return rng.randrange(4), rng.choice(prevailing_winds(ruleset))


def _scores(state: GameState) -> tuple[int, int, int, int]:
    s = state.seats
    return (s[0].score, s[1].score, s[2].score, s[3].score)


class HandEnv:
    """`reset(seed) -> (seat, obs, mask)`; `step(aid) -> (seat, obs, mask, done, rewards)`.

    `seat` is the absolute seat to act next (-1 once done), `mask` a `(N_ACTIONS,)` bool array,
    `rewards` a `(4,)` float32 array: each seat's score delta for the hand / `REWARD_SCALE`,
    zero until `done`. With `encode=False`, `obs` is always `None` (engine-only benchmarking).
    """

    def __init__(self, ruleset: RuleSet = DEFAULT_RULESET, *, encode: bool = True) -> None:
        self.ruleset = ruleset
        self.encode = encode
        self.seed: int | None = None
        self.state: GameState | None = None
        self.actions: list[Action] = []
        self.done = True
        self.decisions = 0
        self._rng = random.Random()
        self._seat = -1
        self._mask: list[bool] = [False] * N_ACTIONS
        self._start_scores = (0, 0, 0, 0)

    def reset(self, seed: int) -> tuple[int, np.ndarray | None, np.ndarray]:
        self.seed = seed
        dealer, prevailing = hand_start(self.ruleset, seed)
        self.state = new_hand(self.ruleset, seed, dealer=dealer, prevailing=prevailing)
        self.actions = []
        self.done = False
        self.decisions = 0
        # str seed: a stream independent of any caller policy seeded with the bare int
        self._rng = random.Random(f"claims:{seed}")
        self._start_scores = _scores(self.state)
        self._advance()
        if self.done:
            raise RuntimeError(f"seed={seed}: hand ended before any decision")
        return self._seat, self._obs(), self._mask_array()

    def step(self, aid: int) -> tuple[int, np.ndarray | None, np.ndarray, bool, np.ndarray]:
        if self.done or self.state is None:
            raise RuntimeError("step() on a finished episode; call reset()")
        if not 0 <= aid < N_ACTIONS or not self._mask[aid]:
            raise IllegalActionError(f"action id {aid} is not legal for seat {self._seat}")
        self.decisions += 1
        self._apply(aid)
        self._advance()
        if self.done:
            return -1, self._obs(), np.zeros(N_ACTIONS, dtype=bool), True, self.rewards()
        return self._seat, self._obs(), self._mask_array(), False, np.zeros(4, dtype=np.float32)

    def rewards(self) -> np.ndarray:
        assert self.state is not None
        end = _scores(self.state)
        return np.asarray(
            [(end[i] - self._start_scores[i]) / REWARD_SCALE for i in range(4)], dtype=np.float32
        )

    def record(self, players: Sequence[str | None] | None = None) -> dict[str, Any]:
        """The finished hand as `app.db.models.HandRecord` column values
        (`app.db.records.save_hand_record` persists the same shape)."""
        if not self.done or self.state is None:
            raise RuntimeError("record() needs a finished episode")
        return hand_record_columns(self.state, self.actions, players=players)

    def _obs(self) -> np.ndarray | None:
        if not self.encode:
            return None
        if self.done:
            return np.zeros(OBS_DIM, dtype=np.float32)
        assert self.state is not None
        return encode_obs(self.state, self._seat)

    def _mask_array(self) -> np.ndarray:
        return np.asarray(self._mask, dtype=bool)

    def _apply(self, aid: int) -> None:
        assert self.state is not None
        action = decode_action(aid, self.state, self._seat)
        self.actions.append(action)
        self.state, _ = reduce(self.state, action)

    def _advance(self) -> None:
        """Run forward to the next decision with more than one legal action, or hand end."""
        assert self.state is not None
        while True:
            if len(self.actions) > _STEP_CAP:
                raise RuntimeError(f"seed={self.seed}: exceeded {_STEP_CAP} actions in one hand")
            state = self.state
            if state.phase in _ENDED:
                self.done = True
                self._seat = -1
                return
            if state.phase in (Phase.AWAIT_CLAIMS, Phase.AWAIT_KONG_ROB):
                assert state.claim_window is not None
                pending = [
                    o.seat
                    for o in state.claim_window.offers
                    if o.seat not in state.claim_window.responses
                ]
                seat = self._rng.choice(pending)
            else:
                seat = state.turn
            mask = legal_mask(state, seat)
            self._seat = seat
            self._mask = mask
            if sum(mask) == 1:
                self._apply(mask.index(True))
                continue
            return


def replay_hand(record: Mapping[str, Any]) -> GameState:
    """Rebuild the final state of a `HandEnv.record()` (or a `HandRecord` row's columns) through
    `new_hand` + `reduce`."""
    if record["engine_version"] != ENGINE_VERSION:
        raise ValueError(
            f"record engine_version {record['engine_version']!r} != {ENGINE_VERSION!r}"
        )
    state = new_hand(
        RuleSet.from_dict(record["ruleset"]),
        record["seed"],
        dealer=record["dealer"],
        prevailing=Wind(record["prevailing"]),
    )
    for data in record["action_log"]:
        state, _ = reduce(state, action_from_dict(data))
    return state
