"""`RuleSet.provable_fairness` commit/reveal through a real `Table` (docs/protocol.md §3
"Fairness"): `hand_start`/`state_sync` carry `seed_commit`, `hand_end`/`hand_history` carry the
`{hand_seed, nonce}` that opens it, and the revealed seed redeals the hand's wall."""

from __future__ import annotations

import dataclasses
import hashlib
import random

from app.fairness import GAME_SEED_BITS, new_game_seed
from app.table import Table
from mahjong_core.config import GameLength, RuleSet
from mahjong_core.state import Phase, derive_hand_seed
from mahjong_core.wall import deal_hands, new_wall, replace_flowers
from tests.test_table import _STEP_CAP, _drive_one_step
from tools.verify_fairness import main as verify_main

_RULES = RuleSet(
    dealer_repeat_on_win=False,
    dealer_repeat_on_draw=False,
    game_length=GameLength.EAST_ONLY,
    hand_end_seconds=0,
    provable_fairness=True,
)


def _frames(table: Table, seat: int, kind: str) -> list[dict[str, object]]:
    return [e.event for e in table.ring[seat] if e.event["t"] == kind]


async def _play_game(table: Table, seed: int) -> None:
    rng = random.Random(seed)
    for _ in range(_STEP_CAP):
        if table.state.phase == Phase.GAME_OVER:
            return
        await _drive_one_step(table, rng)
    raise RuntimeError("game did not finish")


async def test_every_hand_end_opens_the_commit_its_hand_start_published() -> None:
    table = Table("fair-1", _RULES, game_seed=7)
    received: list[dict[str, object]] = []
    table.register_spectator("spec", lambda seq, wire: received.append(wire))
    table._publish_hand_start_and_deal()  # a bare Table never starts hand 1 by itself
    await _play_game(table, 7)

    starts = {f["hand_no"]: f["seed_commit"] for f in received if f["t"] == "hand_start"}
    ends = {f["hand_no"]: f["fairness"] for f in received if f["t"] == "hand_end"}
    assert sorted(starts) == sorted(ends) == [1, 2, 3, 4]
    for hand_no, reveal in ends.items():
        assert isinstance(reveal, dict)
        hand_seed = bytes.fromhex(reveal["hand_seed"])
        opened = hashlib.sha256(hand_seed + bytes.fromhex(reveal["nonce"])).hexdigest()
        assert opened == starts[hand_no]
        assert hand_seed == derive_hand_seed(7, hand_no)
    # every seat's own stream carries the same commit as the spectator's
    last_start = _frames(table, 0, "hand_start")[-1]
    assert last_start["seed_commit"] == starts[last_start["hand_no"]]


async def test_revealed_seed_redeals_hand_one_exactly() -> None:
    table = Table("fair-2", _RULES, game_seed=11)
    opening = table.state
    await _play_game(table, 11)

    reveal = table.state_sync_wire(0)["hand_history"][0]["fairness"]
    _, wall = new_wall(bytes.fromhex(reveal["hand_seed"]), _RULES)
    hands, wall = deal_hands(wall, dealer_seat=0)
    hands, wall, flowers = replace_flowers(hands, wall, dealer_seat=0)
    assert [tuple(h) for h in hands] == [s.concealed for s in opening.seats]
    assert list(flowers) == [s.flowers for s in opening.seats]
    assert wall.tiles == opening.wall.tiles


async def test_state_sync_carries_the_current_commit_and_history_reveals() -> None:
    table = Table("fair-3", _RULES, game_seed=13)
    table._publish_hand_start_and_deal()
    commit = _frames(table, 0, "hand_start")[0]["seed_commit"]
    assert table.state_sync_wire(0)["seed_commit"] == commit
    assert table.state_sync_wire(None)["seed_commit"] == commit

    await _play_game(table, 13)
    history = table.state_sync_wire(None)["hand_history"]
    assert all("fairness" in h for h in history)


async def test_fields_are_omitted_without_provable_fairness() -> None:
    table = Table("fair-off", dataclasses.replace(_RULES, provable_fairness=False), game_seed=5)
    table._publish_hand_start_and_deal()
    await _play_game(table, 5)

    assert "seed_commit" not in _frames(table, 0, "hand_start")[0]
    assert all("fairness" not in f for f in _frames(table, 0, "hand_end"))
    sync = table.state_sync_wire(0)
    assert "seed_commit" not in sync
    assert all("fairness" not in h for h in sync["hand_history"])


def test_new_game_seed_is_random_and_fits_a_signed_bigint() -> None:
    seeds = {new_game_seed() for _ in range(64)}
    assert len(seeds) == 64
    assert all(0 <= s < 2**GAME_SEED_BITS for s in seeds)


def test_verify_tool_accepts_a_true_reveal_and_rejects_a_forged_one(capsys) -> None:  # type: ignore[no-untyped-def]
    hand_seed, nonce = derive_hand_seed(3, 1), bytes(16)
    commit = hashlib.sha256(hand_seed + nonce).hexdigest()
    args = ["--commit", commit, "--hand-seed", hand_seed.hex(), "--nonce", nonce.hex()]
    assert verify_main(args) == 0
    assert "commit verified" in capsys.readouterr().out
    forged = [
        "--commit",
        commit,
        "--hand-seed",
        derive_hand_seed(3, 2).hex(),
        "--nonce",
        nonce.hex(),
    ]
    assert verify_main(forged) == 1
