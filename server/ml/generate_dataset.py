"""Self-play dataset generation for the Phase 1 opponent-danger model (docs/06-ml.md §6.2).

    python -m ml.generate_dataset --out data/danger_model --bots FaanBot,FaanBot,FaanBot,FaanBot

Plays real self-play games (same stepping logic as `bots/selfplay.py`'s `play_game`), and at
every genuine turn decision (not a claim-window response -- a different decision type this model
doesn't cover) encodes the acting seat's real `SeatView` (`ml/encode.py`) and pairs it with the
other three seats' ground-truth danger labels (`bots/labels.py`, computed from the real
`GameState`, never through `app.views._omniscient_seat_view`). Writes shards of that as parquet.

`ml`-extra only -- numpy/pyarrow aren't base dependencies (`server/AGENTS.md`).

Runs until `--games` is reached, or forever (default) until interrupted (SIGINT/SIGTERM) -- the
in-progress shard is flushed before exit either way, so a stop never loses more than the games
buffered since the last completed shard.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import signal
import sys
import time
from collections.abc import Sequence
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from app.views import SeatView, seat_view
from bots.arena import BOT_REGISTRY
from bots.base import Bot
from bots.labels import danger_labels_for_opponents
from mahjong_core.config import RuleSet
from mahjong_core.engine import new_game, reduce, start_next_hand
from mahjong_core.ml import decode_action, legal_mask
from mahjong_core.presets import DEFAULT_PRESET_ID, RULESET_PRESETS
from mahjong_core.state import GameState, Phase
from ml.encode import encode_seat_view

__all__ = ["build_parser", "main"]

_STEP_CAP = 8000
_NO_DEADLINE = float("inf")


def _make_bots(names: Sequence[str], seed: int) -> list[Bot]:
    if len(names) != 4:
        raise ValueError(f"--bots needs exactly 4 comma-separated names, got {len(names)}")
    bots = []
    for i, name in enumerate(names):
        try:
            factory = BOT_REGISTRY[name]
        except KeyError:
            raise ValueError(f"unknown bot {name!r}; choices: {sorted(BOT_REGISTRY)}") from None
        bots.append(factory(seed + i))
    return bots


def _example_row(seed: int, state: GameState, seat: int, view: SeatView) -> dict[str, object]:
    encoded = encode_seat_view(view)
    labels = danger_labels_for_opponents(state, seat)
    order = [(seat + offset) % 4 for offset in (1, 2, 3)]  # matches encode.py's relative order
    return {
        "game_seed": seed,
        "hand_no": state.hand_no,
        "seat": seat,
        "hand": encoded.hand.tolist(),
        "melds": encoded.melds.tolist(),
        "discards": encoded.discards.tolist(),
        "concealed_counts": encoded.concealed_counts.tolist(),
        "context": encoded.context.tolist(),
        "wall_remaining": float(encoded.wall_remaining[0]),
        "ruleset": encoded.ruleset.tolist(),
        "opponent_seats": order,
        "opponent_is_tenpai": [labels[o].is_tenpai for o in order],
        "opponent_winning_tiles": [list(labels[o].winning_tiles) for o in order],
        "opponent_expected_faan": [list(labels[o].expected_faan_by_tile_type) for o in order],
    }


async def play_and_label(
    seed: int, ruleset: RuleSet, bots: Sequence[Bot]
) -> list[dict[str, object]]:
    """Plays one complete game, returning one row per real turn decision (docs/06-ml.md §6.2's
    "Labels: from the real GameState at each recorded decision"). Claim-window responses are a
    different decision type this model doesn't cover, so they advance the game without emitting
    a row -- same as `bots/selfplay.py`'s `play_game`, whose stepping logic this mirrors."""
    rng = random.Random(seed)
    state = new_game(ruleset, seed)
    rows: list[dict[str, object]] = []
    steps = 0

    while state.phase != Phase.GAME_OVER:
        steps += 1
        if steps > _STEP_CAP:
            raise RuntimeError(f"seed={seed}: exceeded {_STEP_CAP} steps -- possible deadlock")

        if state.phase == Phase.HAND_OVER:
            state, _ = start_next_hand(state)
            continue

        is_claim = state.phase in (Phase.AWAIT_CLAIMS, Phase.AWAIT_KONG_ROB)
        if is_claim:
            assert state.claim_window is not None
            pending = [
                o.seat
                for o in state.claim_window.offers
                if o.seat not in state.claim_window.responses
            ]
            seat = rng.choice(pending)
        else:
            seat = state.turn

        view = seat_view(state, seat)
        if not is_claim:
            rows.append(_example_row(seed, state, seat, view))

        mask = legal_mask(state, seat)
        aid = await bots[seat].act(view, mask, _NO_DEADLINE)
        action = decode_action(aid, state, seat)
        state, _ = reduce(state, action)

    return rows


def _write_shard(
    rows: list[dict[str, object]], out_dir: Path, first_seed: int, last_seed: int
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"shard_{first_seed:08d}_{last_seed:08d}.parquet"
    pq.write_table(pa.Table.from_pylist(rows), path)
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ml.generate_dataset",
        description="Self-play dataset generation for the Phase 1 opponent-danger model.",
    )
    parser.add_argument("--games", type=int, default=0, help="0 = run until interrupted (default)")
    parser.add_argument("--seed-start", type=int, default=0)
    parser.add_argument(
        "--bots",
        default="FaanBot,FaanBot,FaanBot,FaanBot",
        help=f"comma-separated, 4 entries, from {sorted(BOT_REGISTRY)}",
    )
    parser.add_argument("--ruleset", default=DEFAULT_PRESET_ID, choices=sorted(RULESET_PRESETS))
    parser.add_argument("--out", default="data/danger_model", type=Path)
    parser.add_argument("--shard-games", type=int, default=20)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    ruleset = RULESET_PRESETS[args.ruleset]
    bot_names = args.bots.split(",")

    stop = False

    def _request_stop(signum: int, _frame: object) -> None:
        nonlocal stop
        print(f"received signal {signum}, finishing the in-flight shard then exiting", flush=True)
        stop = True

    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)

    seed = args.seed_start
    games_done = 0
    shard_rows: list[dict[str, object]] = []
    shard_first_seed = seed
    started = time.monotonic()

    while not stop and (args.games == 0 or games_done < args.games):
        bots = _make_bots(bot_names, seed)
        rows = asyncio.run(play_and_label(seed, ruleset, bots))
        shard_rows.extend(rows)
        games_done += 1
        seed += 1

        if len(shard_rows) and games_done % args.shard_games == 0:
            path = _write_shard(shard_rows, args.out, shard_first_seed, seed - 1)
            elapsed = time.monotonic() - started
            print(
                f"wrote {path} ({len(shard_rows)} examples, {games_done} games, "
                f"{elapsed:.0f}s elapsed)",
                flush=True,
            )
            shard_rows = []
            shard_first_seed = seed

    if shard_rows:
        path = _write_shard(shard_rows, args.out, shard_first_seed, seed - 1)
        print(f"wrote final partial shard {path} ({len(shard_rows)} examples)", flush=True)

    print(f"done: {games_done} games, seeds [{args.seed_start}, {seed - 1}]", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
