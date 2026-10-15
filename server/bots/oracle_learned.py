"""`OracleLearnedBot`: the `ORACLE` tier ("Impossible"; docs/bots.md §9) -- the `T4` policy's logits
on the public part of an omniscient view, with exact-information vetoes on top.

The policy never sees `.hands`: `act` strips it before `LearnedBot.logits`, so the network input is
bit-equal to a plain `seat_view`'s. `.hands` is read only by `bots.safety`'s exact helpers.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np

from app.views import SeatView
from bots.learned import DEFAULT_WEIGHTS, LearnedBot
from bots.safety import kong_rob_risk, tile_risk
from mahjong_core.ml import ADDED_KONG_BASE, CONCEALED_KONG_BASE, PASS_ID, WIN_ID

__all__ = ["OracleLearnedBot"]


class OracleLearnedBot:
    def __init__(self, weights: Path = DEFAULT_WEIGHTS) -> None:
        self.policy = LearnedBot(weights)

    async def act(self, view: SeatView, mask: list[bool], deadline: float) -> int:
        del deadline
        if view.hands is None:
            raise ValueError("OracleLearnedBot needs an omniscient view")
        if mask[WIN_ID]:
            return WIN_ID
        return self.choose(view, mask, self.policy.logits(replace(view, hands=None)))

    def choose(self, view: SeatView, mask: list[bool], logits: np.ndarray) -> int:
        """The vetoes over any policy's logits; `view` must be omniscient."""
        assert view.hands is not None
        if mask[WIN_ID]:
            return WIN_ID
        legal = np.asarray(mask, dtype=bool)
        order = [int(a) for a in np.argsort(-np.where(legal, logits, -np.inf)) if legal[a]]

        discards = [a for a in order if a < CONCEALED_KONG_BASE]
        risk = {a: tile_risk(view, a) for a in discards}
        safe = [a for a in discards if risk[a] == 0.0]

        for aid in order:
            if aid < CONCEALED_KONG_BASE:
                if not safe:
                    return min(discards, key=lambda a: (risk[a], discards.index(a)))
                if risk[aid] > 0.0:
                    continue
                return aid
            if aid < ADDED_KONG_BASE:
                if kong_rob_risk(view, aid - CONCEALED_KONG_BASE, concealed=True) > 0.0:
                    continue
                return aid
            if aid < PASS_ID:
                if kong_rob_risk(view, aid - ADDED_KONG_BASE, concealed=False) > 0.0:
                    continue
                return aid
            return aid
        return order[0]
