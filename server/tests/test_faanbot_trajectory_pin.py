"""Whole-bot trajectory pin for `FaanBot` on a plain `seat_view` (`view.hands is None`): the
RL evaluation baseline (docs/ml.md §12) and the probabilistic half of every hands-aware helper
(docs/bots.md §9). Four `FaanBot`s play seeded hands; every chosen action id is hashed. A change
to the hands-aware branches (`OracleFaanBot`, `OracleLearnedBot`'s vetoes) must leave every
digest unchanged.

Regenerate only for an intended `FaanBot` behaviour change:

    uv run python -m tests.test_faanbot_trajectory_pin
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from typing import Any

import pytest

from app.views import seat_view
from bots.faanbot import FaanBot
from mahjong_core.engine import new_hand, prevailing_winds, reduce
from mahjong_core.ml import decode_action, legal_mask
from mahjong_core.presets import RULESET_PRESETS
from mahjong_core.state import Phase

_STEP_CAP = 2000
_SEEDS = range(200, 208)

_BOUNDED = {"dealer_repeat_on_win": False, "dealer_repeat_on_draw": False}


async def _play_hand(preset: str, seed: int, digest: Any) -> None:
    ruleset = replace(RULESET_PRESETS[preset], **_BOUNDED)
    winds = prevailing_winds(ruleset)
    state = new_hand(ruleset, seed, dealer=seed % 4, prevailing=winds[seed % len(winds)])
    bot = FaanBot()
    for _ in range(_STEP_CAP):
        if state.phase == Phase.HAND_OVER:
            return
        if state.phase in (Phase.AWAIT_CLAIMS, Phase.AWAIT_KONG_ROB):
            assert state.claim_window is not None
            window = state.claim_window
            seat = min(o.seat for o in window.offers if o.seat not in window.responses)
        else:
            seat = state.turn
        aid = await bot.act(seat_view(state, seat), legal_mask(state, seat), float("inf"))
        digest.update(f"{seat}:{aid},".encode())
        state, _ = reduce(state, decode_action(aid, state, seat))
    raise AssertionError(f"{preset} seed={seed}: exceeded {_STEP_CAP} steps")


def _case_digest(preset: str) -> str:
    digest = hashlib.sha256()
    for seed in _SEEDS:
        asyncio.run(_play_hand(preset, seed, digest))
        digest.update(b"\n")
    return digest.hexdigest()


_PINNED: dict[str, str] = {
    "hk_casual": "b4e64e1704b7685ebcd0d606e44e6482f45091e96db79ed14dcf9934b7d840f0",
    "hk_classic": "0e85f7b538aa4664efee8f18bef00cf9a7e02faebc44cad02c09efb96759ef8d",
    "hk_strict": "82587bebb1a67cbfdaebe7d5002e4748c3adc68a29b189dae0d7429cf48babcb",
}


@pytest.mark.parametrize("preset", sorted(RULESET_PRESETS))
def test_faanbot_trajectory_digest_is_pinned(preset: str) -> None:
    assert _case_digest(preset) == _PINNED[preset]


if __name__ == "__main__":
    for name in sorted(RULESET_PRESETS):
        print(f'    "{name}": "{_case_digest(name)}",')
