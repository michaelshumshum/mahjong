"""Auxiliary-head dataset for `PolicyNet` (docs/ml.md §8, R1): states from self-play, exact
labels from `GameState`.

    python -m ml.generate_aux --out data/rl_aux --games N --parallel 10
    python -m ml.aux_data --src data/rl_aux --out data/rl_aux_packed

States come from the `FaanBot` weight-profile mix with the roster shuffled per game, as v3 did
(`ml.generate_dataset._shuffled_roster`). Only states are kept: no bot action is ever a target
(§6). One row per decision with more than one legal action (the env's auto-play rule), every
decision type, from the acting seat's point of view:

- encoder v2 policy row and oracle row (`ml.encode_v2`), raw counts only;
- opponents' tenpai, structural waits and legal-win faan per tile (`bots/labels.py`);
- shanten and ukeire after each possible discard, on the seat's own discard turns (`PAD` else);
- the hand's outcome for that seat: won, dealt in, payment.

Writes one `.npz` shard per `--shard-games` games plus `manifest.json`.
"""

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import json
import random
import sys
import time
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from app.views import seat_view
from bots.base import GAME_STEP_CAP, NO_DEADLINE, Bot
from bots.labels import danger_labels_for_opponents, seat_hand34
from mahjong_core.config import RuleSet
from mahjong_core.engine import new_game, reduce, start_next_hand
from mahjong_core.ml import decode_action, legal_mask
from mahjong_core.presets import DEFAULT_PRESET_ID, RULESET_PRESETS
from mahjong_core.shanten import shanten
from mahjong_core.state import GameState, HandOutcome, Phase
from mahjong_core.tiles import N_TILE_TYPES
from ml.encode import PAD
from ml.encode_v2 import ORACLE_FIELDS, POLICY_FIELDS, oracle_raw, policy_raw
from ml.generate_dataset import _make_bots, _shuffled_roster
from ml.mp import mp_context
from ml.stop_signal import StopSignal

__all__ = [
    "LABEL_FIELDS",
    "SCHEMA_VERSION",
    "build_parser",
    "main",
    "record_game",
    "shanten_labels",
]

SCHEMA_VERSION = 1

LABEL_FIELDS: dict[str, tuple[tuple[int, ...], str]] = {
    "opp_tenpai": ((3,), "uint8"),
    "opp_wait": ((3, N_TILE_TYPES), "uint8"),
    "opp_faan": ((3, N_TILE_TYPES), "uint8"),
    "shanten": ((N_TILE_TYPES,), "uint8"),
    "ukeire": ((N_TILE_TYPES,), "uint8"),
    "own_turn": ((), "uint8"),
    "win": ((), "uint8"),
    "deal_in": ((), "uint8"),
    "payment": ((), "int16"),
    "hand_no": ((), "uint8"),
    "seat": ((), "uint8"),
    "game_seed": ((), "int64"),
}


def shanten_labels(state: GameState, seat: int, unseen: np.ndarray) -> tuple[list[int], list[int]]:
    """Per tile type held: shanten after discarding it, and ukeire = unseen copies of the tile
    types that would then lower shanten. `PAD`/0 for types not held."""
    seat_state = state.seats[seat]
    hand = seat_hand34(seat_state)
    concealed = [0] * N_TILE_TYPES
    for t in seat_state.concealed:
        concealed[t // 4] += 1
    closed = not seat_state.melds
    sets = state.ruleset.hand_sets
    sh_out, uk_out = [PAD] * N_TILE_TYPES, [0] * N_TILE_TYPES
    for t in range(N_TILE_TYPES):
        if not concealed[t]:
            continue
        hand[t] -= 1
        sh = shanten(hand, closed=closed, hand_sets=sets)
        uk = 0
        for u in range(N_TILE_TYPES):
            if unseen[u] and hand[u] < 4:
                hand[u] += 1
                if shanten(hand, closed=closed, hand_sets=sets) < sh:
                    uk += int(unseen[u])
                hand[u] -= 1
        hand[t] += 1
        sh_out[t], uk_out[t] = sh, uk
    return sh_out, uk_out


def _unseen(row: dict[str, np.ndarray]) -> np.ndarray:
    melds = row["melds"].astype(np.int64)
    seq = row["discard_seq"]
    disc = np.bincount(seq[seq != PAD], minlength=N_TILE_TYPES)
    seen = row["concealed"] + melds.sum(axis=0) + disc
    return np.clip(4 - seen, 0, 4)


def _label_row(state: GameState, seat: int) -> dict[str, object]:
    labels = danger_labels_for_opponents(state, seat)
    opps = [(seat + r) % 4 for r in (1, 2, 3)]
    wait = np.zeros((3, N_TILE_TYPES), dtype=np.uint8)
    for i, o in enumerate(opps):
        wait[i, list(labels[o].winning_tiles)] = 1
    row: dict[str, object] = {
        "opp_tenpai": [labels[o].is_tenpai for o in opps],
        "opp_wait": wait,
        "opp_faan": [
            [min(255, int(f)) for f in labels[o].expected_faan_by_tile_type] for o in opps
        ],
    }
    return row


async def _play(
    seed: int, ruleset: RuleSet, bots: Sequence[Bot], max_hands: int
) -> dict[str, np.ndarray]:
    rng = random.Random(seed)
    state = new_game(ruleset, seed)
    rows: list[dict[str, object]] = []
    hand_rows: list[dict[str, object]] = []
    steps = hands = 0
    while state.phase != Phase.GAME_OVER:
        steps += 1
        if steps > GAME_STEP_CAP:
            raise RuntimeError(f"seed={seed}: exceeded {GAME_STEP_CAP} steps")
        if state.phase == Phase.HAND_OVER:
            _fill_outcome(state, hand_rows)
            rows += hand_rows
            hand_rows = []
            hands += 1
            if hands == max_hands:
                break
            state, _ = start_next_hand(state)
            continue
        if state.phase in (Phase.AWAIT_CLAIMS, Phase.AWAIT_KONG_ROB):
            assert state.claim_window is not None
            window = state.claim_window
            seat = rng.choice([o.seat for o in window.offers if o.seat not in window.responses])
        else:
            seat = state.turn
        mask = legal_mask(state, seat)
        if sum(mask) > 1:
            hand_rows.append(_row(state, seat))
        aid = await bots[seat].act(seat_view(state, seat), mask, NO_DEADLINE)
        state, _ = reduce(state, decode_action(aid, state, seat))
    if state.hand_result is not None and hand_rows:
        _fill_outcome(state, hand_rows)
        rows += hand_rows
    return _stack(rows, seed)


def _row(state: GameState, seat: int) -> dict[str, object]:
    pol = policy_raw(state, seat)
    own_turn = state.phase == Phase.AWAIT_ACTION and state.turn == seat
    if own_turn:
        sh, uk = shanten_labels(state, seat, _unseen(pol))
    else:
        sh, uk = [PAD] * N_TILE_TYPES, [0] * N_TILE_TYPES
    return {
        **pol,
        **oracle_raw(state, seat),
        **_label_row(state, seat),
        "shanten": sh,
        "ukeire": uk,
        "own_turn": own_turn,
        "hand_no": state.hand_no,
        "seat": seat,
    }


def _fill_outcome(state: GameState, rows: list[dict[str, object]]) -> None:
    result = state.hand_result
    assert result is not None
    won = result.outcome != HandOutcome.EXHAUSTIVE_DRAW and result.winner is not None
    for row in rows:
        seat = int(row["seat"])  # type: ignore[call-overload]
        row["win"] = won and result.winner == seat
        row["deal_in"] = won and result.discarder == seat and result.winner != seat
        row["payment"] = int(result.payments.get(seat, 0))


def _stack(rows: list[dict[str, object]], seed: int) -> dict[str, np.ndarray]:
    out: dict[str, np.ndarray] = {}
    for name in (*POLICY_FIELDS, *ORACLE_FIELDS):
        out[name] = np.stack([np.asarray(r[name], dtype=np.uint8) for r in rows])
    for name, (_, dtype) in LABEL_FIELDS.items():
        if name == "game_seed":
            continue
        out[name] = np.asarray([r[name] for r in rows], dtype=dtype)
    out["game_seed"] = np.full(len(rows), seed, dtype=np.int64)
    return out


def record_game(
    seed: int, ruleset: RuleSet, bot_names: Sequence[str], max_hands: int = 0
) -> dict[str, np.ndarray]:
    """One game's rows as stacked arrays, stopping after `max_hands` hands if > 0; picklable
    pool entry point."""
    roster = _shuffled_roster(bot_names, seed)
    return asyncio.run(_play(seed, ruleset, _make_bots(roster, seed), max_hands))


def _concat(parts: list[dict[str, np.ndarray]]) -> dict[str, np.ndarray]:
    return {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m ml.generate_aux", description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--games", type=int, required=True)
    parser.add_argument("--seed-start", type=int, default=0)
    parser.add_argument(
        "--bots", default="FaanBot,FaanBotAggressive,FaanBotDefensive,FaanBotFlushChasing"
    )
    parser.add_argument("--ruleset", default=DEFAULT_PRESET_ID, choices=sorted(RULESET_PRESETS))
    parser.add_argument("--shard-games", type=int, default=50)
    parser.add_argument("--max-hands", type=int, default=0, help="0 = play the whole game")
    parser.add_argument("--parallel", type=int, default=1)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    ruleset = RULESET_PRESETS[args.ruleset]
    bot_names = args.bots.split(",")
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "ruleset_preset": args.ruleset,
        "ruleset": ruleset.to_dict(),
        "bot_roster": bot_names,
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2))

    stop = StopSignal("finishing in-flight games")

    seeds = iter(range(args.seed_start, args.seed_start + args.games))
    pending: list[dict[str, np.ndarray]] = []
    done_seeds: list[int] = []
    started = time.monotonic()

    def flush() -> None:
        if not pending:
            return
        path = args.out / f"shard_{min(done_seeds):08d}_{max(done_seeds):08d}.npz"
        np.savez(path, **_concat(pending))
        rows = sum(len(p["seat"]) for p in pending)
        print(
            f"wrote {path.name} ({rows} rows, {len(done_seeds)} games, "
            f"{time.monotonic() - started:.0f}s)",
            flush=True,
        )
        pending.clear()
        done_seeds.clear()

    with ProcessPoolExecutor(max_workers=args.parallel, mp_context=mp_context()) as pool:
        in_flight: dict[concurrent.futures.Future[dict[str, np.ndarray]], int] = {}

        def top_up() -> None:
            while len(in_flight) < args.parallel and not stop.requested:
                seed = next(seeds, None)
                if seed is None:
                    return
                in_flight[pool.submit(record_game, seed, ruleset, bot_names, args.max_hands)] = seed

        top_up()
        while in_flight:
            finished, _ = concurrent.futures.wait(
                in_flight, return_when=concurrent.futures.FIRST_COMPLETED
            )
            for fut in finished:
                done_seeds.append(in_flight.pop(fut))
                pending.append(fut.result())
            if len(done_seeds) >= args.shard_games:
                flush()
            top_up()
    flush()
    print(f"done in {time.monotonic() - started:.0f}s", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
