"""Check one hand's provable-fairness reveal and print the wall it deals (docs/protocol.md §3
"Fairness").

Usage: uv run python tools/verify_fairness.py --commit HEX --hand-seed HEX --nonce HEX
       [--no-flowers]

`--commit` is `hand_start.seed_commit`; `--hand-seed`/`--nonce` are `hand_end.fairness`. Exits 1
when the reveal doesn't match the commit. The wall is printed front-to-back (draw order); compare
it against the tiles actually dealt and drawn that hand.
"""

from __future__ import annotations

import argparse
import hmac
import sys

from app.fairness import seed_commit
from mahjong_core.config import RuleSet
from mahjong_core.tiles import Flower, tile_code, tile_id_type
from mahjong_core.wall import new_wall


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--commit", required=True)
    parser.add_argument("--hand-seed", required=True)
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--no-flowers", action="store_true", help="table had flowers_enabled off")
    args = parser.parse_args(argv)

    hand_seed = bytes.fromhex(args.hand_seed)
    expected = seed_commit(hand_seed, bytes.fromhex(args.nonce))
    if not hmac.compare_digest(expected, args.commit.lower()):
        print(f"MISMATCH: SHA256(hand_seed || nonce) = {expected}, commit = {args.commit}")
        return 1

    dice, wall = new_wall(hand_seed, RuleSet(flowers_enabled=not args.no_flowers))
    codes = [tile_code(t if isinstance(t, Flower) else tile_id_type(t)) for t in wall.tiles]
    print("commit verified")
    print(f"dice: {dice[0]} {dice[1]}")
    print(f"wall ({len(codes)} tiles, front to back): {' '.join(codes)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
