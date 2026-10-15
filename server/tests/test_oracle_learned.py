"""`bots/oracle_learned.py`: the `ORACLE` tier, the `T4` policy plus exact-information vetoes
(docs/bots.md §9). The policy is stubbed with fixed logits so each veto is tested on its own."""

from __future__ import annotations

import asyncio
import dataclasses
import time
from pathlib import Path

import numpy as np
import pytest

from app.views import SeatView, _omniscient_seat_view, seat_view
from bots.arena import BOT_REGISTRY, OMNISCIENT_BOTS
from bots.base import NO_DEADLINE
from bots.learned import LearnedBot
from bots.oracle_learned import OracleLearnedBot
from bots.safety import tile_risk
from bots.worker import compute_action
from mahjong_core.config import HandSet, RuleSet
from mahjong_core.state import Phase, Wind
from mahjong_core.tiles import TileId, TileType, tile_ids_for_type
from ml.env import HandEnv
from tests.latency import check_latency


def _pool(*types: TileType) -> tuple[TileId, ...]:
    used: dict[TileType, int] = {}
    ids = []
    for t in types:
        n = used.get(t, 0)
        ids.append(tile_ids_for_type(t)[n])
        used[t] = n + 1
    return tuple(ids)


# seat 0: 123m 456m 789m 12p + 東 南 (14 tiles, 1-shanten after an honor discard)
_OWN = [
    TileType.MAN_1,
    TileType.MAN_2,
    TileType.MAN_3,
    TileType.MAN_4,
    TileType.MAN_5,
    TileType.MAN_6,
    TileType.MAN_7,
    TileType.MAN_8,
    TileType.MAN_9,
    TileType.PIN_1,
    TileType.PIN_2,
    TileType.SOU_5,
    TileType.WIND_EAST,
    TileType.WIND_NORTH,
]

# seat 1: seven pairs one 北 short
_SEVEN_PAIRS_ON_NORTH = _pool(
    TileType.SOU_1,
    TileType.SOU_1,
    TileType.SOU_3,
    TileType.SOU_3,
    TileType.PIN_5,
    TileType.PIN_5,
    TileType.PIN_6,
    TileType.PIN_6,
    TileType.SOU_6,
    TileType.SOU_6,
    TileType.PIN_7,
    TileType.PIN_7,
    TileType.WIND_NORTH,
)


def _view(hands: tuple[tuple[TileId, ...], ...] | None) -> SeatView:
    own = _pool(*_OWN)
    return SeatView(
        seat=0,
        hand_no=1,
        prevailing=Wind.EAST,
        dealer=0,
        turn=10,
        phase=Phase.AWAIT_ACTION,
        own_hand=own,
        concealed_counts=(len(own), 13, 13, 13),
        melds=((), (), (), ()),
        discard_pools=((), (), (), ()),
        flowers=((), (), (), ()),
        wall_remaining=50,
        seat_status=("connected", "connected", "connected", "connected"),
        names=(None, None, None, None),
        scores=(0, 0, 0, 0),
        legal_actions=(),
        claim_options=(),
        deadline_ts=None,
        host_seat=None,
        ruleset=RuleSet(hand_sets=frozenset(HandSet)),
        hands=hands,
    )


_HANDS = ((), _SEVEN_PAIRS_ON_NORTH, (), ())


def _mask(*aids: int) -> list[bool]:
    mask = [False] * 109
    for a in aids:
        mask[a] = True
    return mask


def _discards() -> list[int]:
    return sorted({int(t) for t in _OWN})


def _bot(prefs: dict[int, float]) -> tuple[OracleLearnedBot, list]:
    """A bot whose policy returns `prefs` (others -10) and records every view it was shown."""
    bot = OracleLearnedBot()
    seen: list[SeatView] = []

    def logits(view: SeatView) -> np.ndarray:
        seen.append(view)
        out = np.full(109, -10.0)
        for a, v in prefs.items():
            out[a] = v
        return out

    bot.policy.logits = logits  # type: ignore[method-assign]
    return bot, seen


async def test_refuses_a_public_view() -> None:
    bot, _ = _bot({})
    with pytest.raises(ValueError):
        await bot.act(_view(None), _mask(*_discards()), NO_DEADLINE)


async def test_policy_never_sees_hands() -> None:
    bot, seen = _bot({int(TileType.WIND_EAST): 5.0})
    await bot.act(_view(_HANDS), _mask(*_discards()), NO_DEADLINE)
    assert seen and all(v.hands is None for v in seen)
    assert dataclasses.replace(seen[0], hands=_HANDS) == _view(_HANDS)


async def test_keeps_the_policy_choice_when_it_is_safe() -> None:
    east = int(TileType.WIND_EAST)
    bot, _ = _bot({east: 5.0, int(TileType.WIND_NORTH): 4.0})
    assert await bot.act(_view(_HANDS), _mask(*_discards()), NO_DEADLINE) == east


async def test_vetoes_a_certain_deal_in_for_the_next_safe_discard() -> None:
    north, east = int(TileType.WIND_NORTH), int(TileType.WIND_EAST)
    view = _view(_HANDS)
    assert tile_risk(view, north) > 0.0
    assert tile_risk(view, east) == 0.0
    bot, _ = _bot({north: 5.0, east: 4.0})
    assert await bot.act(view, _mask(*_discards()), NO_DEADLINE) == east


async def test_every_discard_deals_in_takes_the_cheapest() -> None:
    north = int(TileType.WIND_NORTH)
    bot, _ = _bot({north: 5.0})
    assert await bot.act(_view(_HANDS), _mask(north), NO_DEADLINE) == north


async def test_takes_a_legal_win() -> None:
    bot, _ = _bot({0: 5.0, 108: -5.0})
    assert await bot.act(_view(_HANDS), _mask(0, 108), NO_DEADLINE) == 108


def test_registered_as_omniscient() -> None:
    assert "OracleLearned" in BOT_REGISTRY
    assert "OracleLearned" in OMNISCIENT_BOTS
    assert "OracleLearnedPush" not in BOT_REGISTRY
    assert "ORACLE" in OMNISCIENT_BOTS
    assert type(BOT_REGISTRY["ORACLE"](0)) is OracleLearnedBot


def test_missing_weights_raise_instead_of_falling_back(tmp_path: Path) -> None:
    """same as `T4`: no silent downgrade to another bot when `learned.npz` can't load."""
    with pytest.raises(FileNotFoundError):
        OracleLearnedBot(tmp_path / "missing.npz")
    bad = tmp_path / "bad.npz"
    bad.write_bytes(b"not an npz")
    with pytest.raises(ValueError):
        OracleLearnedBot(bad)


def _omniscient_decisions(n_hands: int, seed0: int) -> list[tuple[SeatView, list[bool]]]:
    """`(omniscient view, mask)` at every decision of `n_hands` hands played by `LearnedBot`."""
    bot = LearnedBot()
    out = []
    for seed in range(seed0, seed0 + n_hands):
        env = HandEnv(encode=False)
        seat, _, mask = env.reset(seed)
        while not env.done:
            assert env.state is not None
            m = mask.tolist()
            out.append((_omniscient_seat_view(env.state, seat), m))
            seat, _, mask, _, _ = env.step(asyncio.run(bot.act(seat_view(env.state, seat), m, 0.0)))
    return out


@pytest.mark.slow
@pytest.mark.latency
def test_served_tier_decision_latency() -> None:
    """The vetoes cost little on top of `T4`: p99 within 2x `LearnedBot`'s on the same decisions
    through `compute_action` (view building excluded). The absolute 5 ms is `make bench-latency`."""
    views = _omniscient_decisions(5, seed0=100)[:400]
    for view, m in views[:20]:
        compute_action(view, m, 0, "ORACLE", 0.0)
        compute_action(dataclasses.replace(view, hands=None), m, 0, "T4", 0.0)
    oracle, t4 = [], []
    for view, m in views:
        start = time.perf_counter()
        compute_action(view, m, 0, "ORACLE", 0.0)
        mid = time.perf_counter()
        compute_action(dataclasses.replace(view, hands=None), m, 0, "T4", 0.0)
        oracle.append(mid - start)
        t4.append(time.perf_counter() - mid)
    check_latency("ORACLE decision", oracle, "T4", t4, max_ratio=2.0)
