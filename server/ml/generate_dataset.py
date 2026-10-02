"""Self-play dataset generation for the opponent-danger model (docs/06-ml.md §5).

    python -m ml.generate_dataset --out data/danger_model \
        --bots FaanBot,FaanBotAggressive,FaanBotDefensive,FaanBotFlushChasing --parallel 12

Plays real self-play games (same stepping logic as `bots/selfplay.py`'s `play_game`), and at
every genuine turn decision (not a claim-window response -- a different decision type this model
doesn't cover) records the acting seat's public table state as compact 34-tile-type counts, paired
with the other three seats' ground-truth danger labels (`bots/labels.py`, computed from the real
`GameState`, never through `app.views._omniscient_seat_view`). Writes shards of that as parquet,
plus one `manifest.json` per output directory (ruleset + bot roster, written once, not repeated
per row -- it's constant for the whole run).

Row schema stores raw per-tile-type counts (uint8 range, 0-4), not a specific model-input
encoding (e.g. thermometer planes) -- that's a training-time choice for `ml/dataset.py` to make
and revisit later without needing to regenerate data. `context` fields that are constant *by the
row-capture design itself* (every row is the acting seat's own `AWAIT_ACTION` turn, verified
against the previous dataset generation: relative turn-holder position and phase never vary) are
dropped entirely rather than stored redundantly; `prevailing_wind` is kept despite being constant
under the single ruleset this run uses, since that constancy is a property of the ruleset
(`hk_classic` is `EAST_ONLY`), not of the capture design, and doesn't generalize to a future
multi-ruleset run.

**Seat<->personality assignment is randomized per game** (seeded off that game's own seed, via an
independent `random.Random` instance from the one driving in-game claim-arrival order) and
recorded as `seat_personalities` metadata -- never fed to the model. A prior version of this
script fixed one personality per seat for the *entire* run, which let dealer/seat-wind context
leak seat identity (and therefore personality identity) directly to the model -- a real
shortcut-learning risk flagged in review, not a hypothetical one.

`ml`-extra only -- pyarrow isn't a base dependency (`server/AGENTS.md`). Notably does **not**
depend on numpy: `bots/labels.py`, `bots/features.py`, and `mahjong_core` are all pure Python, so
this script only needs pyarrow for the parquet write -- keeping the numpy-heavy thermometer
expansion out of the per-row hot path (both compute and inter-process pickling cost under
`--parallel`) is itself a real speedup, not just a storage optimization.

Runs until `--games` is reached, or forever (default) until interrupted (SIGINT/SIGTERM) -- the
in-progress shard is flushed before exit either way, so a stop never loses more than the games
buffered since the last completed shard.

`--parallel N` runs games across a `ProcessPoolExecutor`, same pattern as `bots/arena.py`'s
`--parallel` -- each worker plays one game start to finish via `_play_and_label_sync` (a
top-level, picklable entry point), so nothing needs pickling beyond `(seed, ruleset, bot_names)`.
Games complete out of seed order under parallelism, so shard filenames use the real min/max seed
*among that shard's accumulated rows*, not an assumed-contiguous range -- the `game_seed` column
is the source of truth regardless.
"""

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import json
import multiprocessing
import random
import signal
import sys
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from app.views import SeatView, seat_view
from bots.arena import BOT_REGISTRY
from bots.base import Bot
from bots.labels import OpponentDangerLabel, danger_labels_for_opponents
from mahjong_core.config import RuleSet
from mahjong_core.engine import new_game, reduce, start_next_hand
from mahjong_core.ml import decode_action, legal_mask
from mahjong_core.presets import DEFAULT_PRESET_ID, RULESET_PRESETS
from mahjong_core.state import Phase
from ml.raw import raw_row, relative_seats

__all__ = ["build_parser", "main"]

_STEP_CAP = 8000
_NO_DEADLINE = float("inf")
_N_TILE_TYPES = 34
SCHEMA_VERSION = 3


def _mp_context() -> multiprocessing.context.BaseContext:
    """`fork` over the platform default (`forkserver` on this interpreter, confirmed via
    `multiprocessing.get_start_method()`): measured directly on this workload (120 games, 12
    workers, `hk_classic`, identical bot roster, both legs run back-to-back in one process) --
    `forkserver` managed 0.860 games/sec, `fork` managed 1.518 games/sec, a ~1.8x difference at
    the same worker count.

    Only safe when the current process is single-threaded at pool-creation time -- a thread other
    than main could hold a lock (import lock, malloc, logging) that the forked child inherits
    already-acquired and can never release, deadlocking the child the first time it needs that
    lock. That's not hypothetical here: running this under pytest triggers Python's own
    `DeprecationWarning` for exactly this condition, because pytest's own process is
    multi-threaded. Checking `threading.active_count()` at call time (not import time, since
    thread state can change) picks the fast path only when it's actually safe."""
    if threading.active_count() > 1:
        return multiprocessing.get_context()
    return multiprocessing.get_context("fork")


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


def _shuffled_roster(bot_names: Sequence[str], seed: int) -> list[str]:
    """This game's seat->personality assignment -- a fresh `random.Random(seed)` instance,
    independent of `play_and_label`'s own `random.Random(seed)` (used for claim-arrival order),
    so the two don't share state despite the same seed value. Deterministic and reproducible:
    same seed -> same assignment, every time."""
    return random.Random(seed).sample(list(bot_names), len(bot_names))


def _winning_tiles_multihot(winning_tiles: tuple[int, ...]) -> list[int]:
    row = [0] * _N_TILE_TYPES
    for t in winning_tiles:
        row[t] = 1
    return row


def _example_row(
    seed: int,
    view: SeatView,
    seat_personalities: list[str],
    labels: dict[int, OpponentDangerLabel],
) -> dict[str, object]:
    assert view.seat is not None
    seat = view.seat
    opponent_order = relative_seats(seat)[1:]  # next, across, previous -- relative slots 1, 2, 3

    return {
        "game_seed": seed,
        "hand_no": view.hand_no,
        "seat": seat,
        "seat_personalities": list(seat_personalities),
        **raw_row(view),
        "opponent_seats": list(opponent_order),
        "opponent_is_tenpai": [labels[o].is_tenpai for o in opponent_order],
        "opponent_winning_tiles_multihot": [
            _winning_tiles_multihot(labels[o].winning_tiles) for o in opponent_order
        ],
        "opponent_expected_faan": [
            list(labels[o].expected_faan_by_tile_type) for o in opponent_order
        ],
    }


async def play_and_label(
    seed: int,
    ruleset: RuleSet,
    bots: Sequence[Bot],
    seat_personalities: list[str],
) -> list[dict[str, object]]:
    """Plays one complete game, returning one row per real turn decision, labelled from the real
    `GameState` at that decision (docs/06-ml.md §5). Claim-window responses are a different
    decision type this model doesn't cover, so they advance the game without emitting a row --
    same as `bots/selfplay.py`'s `play_game`, whose stepping logic this mirrors."""
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
            labels = danger_labels_for_opponents(state, seat)
            rows.append(_example_row(seed, view, seat_personalities, labels))

        mask = legal_mask(state, seat)
        aid = await bots[seat].act(view, mask, _NO_DEADLINE)
        action = decode_action(aid, state, seat)
        state, _ = reduce(state, action)

    return rows


def _play_and_label_sync(
    seed: int, ruleset: RuleSet, bot_names: list[str]
) -> list[dict[str, object]]:
    """Top-level, picklable `ProcessPoolExecutor` entry point -- see module docstring. Shuffles
    this game's seat->personality assignment and builds fresh bots inside the worker, so
    reproducibility is unaffected by which process a seed happens to run in."""
    roster = _shuffled_roster(bot_names, seed)
    bots = _make_bots(roster, seed)
    return asyncio.run(play_and_label(seed, ruleset, bots, roster))


def _write_shard(
    rows: list[dict[str, object]], out_dir: Path, first_seed: int, last_seed: int
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"shard_{first_seed:08d}_{last_seed:08d}.parquet"
    pq.write_table(pa.Table.from_pylist(rows), path)
    return path


def _write_manifest(
    out_dir: Path, ruleset: RuleSet, ruleset_preset: str, bot_names: list[str]
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "ruleset_preset": ruleset_preset,
        "ruleset": ruleset.to_dict(),
        "bot_roster": bot_names,
        "n_tile_types": _N_TILE_TYPES,
        "note": (
            "seat_personalities in each row records that game's randomized seat->roster-entry "
            "assignment -- metadata only, never a model input. Every row is captured at the "
            "acting seat's own AWAIT_ACTION turn (turn-holder is always relative seat 0, phase "
            "is constant) -- both dropped from the row schema rather than stored redundantly. "
            "v3 adds discard_seq (per-seat discard order), concealed_kongs and flowers, and "
            "hides other seats' concealed-kong tile types in meld_counts."
        ),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ml.generate_dataset",
        description="Self-play dataset generation for the opponent-danger model.",
    )
    parser.add_argument("--games", type=int, default=0, help="0 = run until interrupted (default)")
    parser.add_argument("--seed-start", type=int, default=0)
    parser.add_argument(
        "--bots",
        default="FaanBot,FaanBotAggressive,FaanBotDefensive,FaanBotFlushChasing",
        help=(
            f"comma-separated roster, from {sorted(BOT_REGISTRY)} -- shuffled to a random seat "
            "assignment independently per game, not fixed per seat for the whole run"
        ),
    )
    parser.add_argument("--ruleset", default=DEFAULT_PRESET_ID, choices=sorted(RULESET_PRESETS))
    parser.add_argument("--out", default="data/danger_model", type=Path)
    parser.add_argument("--shard-games", type=int, default=20)
    parser.add_argument("--parallel", type=int, default=1, help="worker processes (1 = no pool)")
    return parser


def _run_sequential(
    args: argparse.Namespace, ruleset: RuleSet, bot_names: list[str], stop: Callable[[], bool]
) -> None:
    seed = args.seed_start
    games_done = 0
    shard_rows: list[dict[str, object]] = []
    shard_first_seed = seed
    started = time.monotonic()

    while not stop() and (args.games == 0 or games_done < args.games):
        rows = _play_and_label_sync(seed, ruleset, bot_names)
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


def _run_parallel(
    args: argparse.Namespace, ruleset: RuleSet, bot_names: list[str], stop: Callable[[], bool]
) -> None:
    games_done = 0
    shard_rows: list[dict[str, object]] = []
    shard_seeds: list[int] = []
    started = time.monotonic()
    last_seed_done = args.seed_start - 1
    next_seed = [args.seed_start]  # single-element cell: mutable from the nested closure below

    with ProcessPoolExecutor(max_workers=args.parallel, mp_context=_mp_context()) as pool:
        in_flight: dict[concurrent.futures.Future[list[dict[str, object]]], int] = {}

        def _top_up() -> None:
            while (
                len(in_flight) < args.parallel
                and not stop()
                and (args.games == 0 or (next_seed[0] - args.seed_start) < args.games)
            ):
                fut = pool.submit(_play_and_label_sync, next_seed[0], ruleset, bot_names)
                in_flight[fut] = next_seed[0]
                next_seed[0] += 1

        _top_up()

        while in_flight:
            done, _pending = concurrent.futures.wait(
                in_flight, return_when=concurrent.futures.FIRST_COMPLETED
            )
            for fut in done:
                completed_seed = in_flight.pop(fut)
                shard_rows.extend(fut.result())
                shard_seeds.append(completed_seed)
                games_done += 1
                last_seed_done = max(last_seed_done, completed_seed)

            if len(shard_rows) and games_done % args.shard_games == 0:
                path = _write_shard(shard_rows, args.out, min(shard_seeds), max(shard_seeds))
                elapsed = time.monotonic() - started
                print(
                    f"wrote {path} ({len(shard_rows)} examples, {games_done} games, "
                    f"{elapsed:.0f}s elapsed, {args.parallel} workers)",
                    flush=True,
                )
                shard_rows = []
                shard_seeds = []

            _top_up()

    if shard_rows:
        path = _write_shard(shard_rows, args.out, min(shard_seeds), max(shard_seeds))
        print(f"wrote final partial shard {path} ({len(shard_rows)} examples)", flush=True)
    print(f"done: {games_done} games, seeds up to {last_seed_done}", flush=True)


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    ruleset = RULESET_PRESETS[args.ruleset]
    bot_names = args.bots.split(",")
    _write_manifest(args.out, ruleset, args.ruleset, bot_names)

    stop_flag = False

    def _request_stop(signum: int, _frame: object) -> None:
        nonlocal stop_flag
        print(f"received signal {signum}, finishing in-flight work then exiting", flush=True)
        stop_flag = True

    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)

    if args.parallel > 1:
        _run_parallel(args, ruleset, bot_names, lambda: stop_flag)
    else:
        _run_sequential(args, ruleset, bot_names, lambda: stop_flag)


if __name__ == "__main__":
    main(sys.argv[1:])
