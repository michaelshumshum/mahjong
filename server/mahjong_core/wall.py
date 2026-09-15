"""Seeded wall shuffle, dice, dealing, and flower replacement (docs/01-rules-spec.md §3, §9).

Everything here is a pure function of an already-derived `hand_seed: bytes` — this module
never touches `game_seed` (docs/00-architecture.md §3: `hand_seed = SHA256(game_seed ||
hand_no)`, only `hand_seed` is ever passed down). `hand_seed` seeds one `random.Random`
instance; the global `random` module is never used. Same `hand_seed` in -> byte-identical
dice roll and wall out, always.

Physical tiles keep the canonical pre-shuffle `TileId` from `tiles.py` (grouped 4-per-type,
independent of any hand's shuffle). Shuffling permutes the *order* of that fixed id list, so
a `TileId` value never encodes wall position — see tiles.py's "TileId is not a wall slot"
note. No extra relabeling step is needed on top of that.

`RuleSet.wall_reserve` is an exhaustion *threshold* ("wall exhausted with `wall_reserve`
tiles left -> exhaustive draw", §9), not a fixed reservation carved out of the wall at
shuffle/deal time — this module doesn't consume it. Whatever drives the turn state machine
compares `len(wall.tiles)` against it.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from mahjong_core.config import RuleSet
from mahjong_core.tiles import Flower, TileId, all_flowers, all_tile_ids

WallTile = TileId | Flower
"""One physical tile as it sits in the wall or a hand: either a playable `TileId` or a
(always-unique-copy) `Flower`."""


@dataclass(frozen=True)
class Wall:
    """Immutable live wall, front-to-back draw order. `tiles[0]` is drawn next from the
    front (normal draw); `tiles[-1]` is drawn next from the back (kong/flower replacement,
    §5, §9 — HK has no separate dead wall, so both ends come off the same sequence)."""

    tiles: tuple[WallTile, ...]


_SeatTiles = tuple[WallTile, ...]
Hands = tuple[_SeatTiles, _SeatTiles, _SeatTiles, _SeatTiles]

_SeatFlowers = tuple[Flower, ...]
SetAsideFlowers = tuple[_SeatFlowers, _SeatFlowers, _SeatFlowers, _SeatFlowers]

_SEATS = 4
_HAND_SIZE = 13


def _physical_tiles(ruleset: RuleSet) -> list[WallTile]:
    tiles: list[WallTile] = list(all_tile_ids())
    if ruleset.flowers_enabled:
        tiles.extend(all_flowers())
    return tiles


def new_wall(hand_seed: bytes, ruleset: RuleSet) -> tuple[tuple[int, int], Wall]:
    """Roll dice and shuffle the wall, both from one `random.Random(hand_seed)` stream (§3
    steps 1-2). The dice roll is cosmetic — it does not affect dealing order, which is
    already a full random permutation — but it's derived from the same seed so the whole
    deal, dice included, is reproducible from `hand_seed` alone.

    144 tiles when `ruleset.flowers_enabled` (the default), 136 (no flowers/seasons)
    otherwise — `01-rules-spec.md §3` only describes the 144-tile case; see the note added
    there for the `flowers_enabled=False` variant.
    """
    rng = random.Random(hand_seed)
    dice = (rng.randint(1, 6), rng.randint(1, 6))
    tiles = _physical_tiles(ruleset)
    rng.shuffle(tiles)
    return dice, Wall(tuple(tiles))


def draw_front(wall: Wall) -> tuple[WallTile, Wall]:
    """Normal draw, from the live end of the wall."""
    if not wall.tiles:
        raise ValueError("wall is empty")
    return wall.tiles[0], Wall(wall.tiles[1:])


def draw_back(wall: Wall) -> tuple[WallTile, Wall]:
    """Kong/flower replacement draw, from the back of the same live wall (§5, §9: HK has no
    separate dead wall)."""
    if not wall.tiles:
        raise ValueError("wall is empty")
    return wall.tiles[-1], Wall(wall.tiles[:-1])


def deal_hands(wall: Wall, dealer_seat: int) -> tuple[Hands, Wall]:
    """13 tiles to each seat, 14 to the dealer (§3 step 3), dealt in seat order starting
    from the dealer, three rounds of four tiles then a round of one, mirroring the physical
    deal; the dealer draws one further tile at the end. All from the front of the wall."""
    if not 0 <= dealer_seat < _SEATS:
        raise ValueError(f"dealer_seat must be 0..{_SEATS - 1}, got {dealer_seat}")
    needed = _HAND_SIZE * _SEATS + 1
    if len(wall.tiles) < needed:
        raise ValueError(f"wall has {len(wall.tiles)} tiles, need at least {needed} to deal")

    order = [(dealer_seat + i) % _SEATS for i in range(_SEATS)]
    hands: list[list[WallTile]] = [[] for _ in range(_SEATS)]
    tiles = list(wall.tiles)
    idx = 0
    for _ in range(3):
        for seat in order:
            hands[seat].extend(tiles[idx : idx + 4])
            idx += 4
    for seat in order:
        hands[seat].append(tiles[idx])
        idx += 1
    hands[dealer_seat].append(tiles[idx])
    idx += 1

    dealt: Hands = (
        tuple(hands[0]),
        tuple(hands[1]),
        tuple(hands[2]),
        tuple(hands[3]),
    )
    return dealt, Wall(tuple(tiles[idx:]))


def replace_flowers(
    hands: Hands, wall: Wall, dealer_seat: int
) -> tuple[Hands, Wall, SetAsideFlowers]:
    """Flower replacement, in seat order starting from the dealer: each seat sets aside
    every flower it holds and draws a replacement from the back of the wall, one at a time,
    repeating until it holds none — a replacement that is itself a flower chains (§3 step 4,
    §11.1). Order matters (it changes who gets which tile), which is why this resolves one
    seat completely before moving to the next, rather than round-robin across seats."""
    if not 0 <= dealer_seat < _SEATS:
        raise ValueError(f"dealer_seat must be 0..{_SEATS - 1}, got {dealer_seat}")

    seat_hands: list[list[WallTile]] = [list(h) for h in hands]
    set_aside: list[list[Flower]] = [[] for _ in range(_SEATS)]
    tiles = list(wall.tiles)
    order = [(dealer_seat + i) % _SEATS for i in range(_SEATS)]

    for seat in order:
        while True:
            flower_idx = next(
                (i for i, t in enumerate(seat_hands[seat]) if isinstance(t, Flower)), None
            )
            if flower_idx is None:
                break
            flower = seat_hands[seat].pop(flower_idx)
            assert isinstance(flower, Flower)
            set_aside[seat].append(flower)
            if not tiles:
                raise ValueError("wall exhausted during flower replacement")
            seat_hands[seat].append(tiles.pop())

    dealt: Hands = (
        tuple(seat_hands[0]),
        tuple(seat_hands[1]),
        tuple(seat_hands[2]),
        tuple(seat_hands[3]),
    )
    aside: SetAsideFlowers = (
        tuple(set_aside[0]),
        tuple(set_aside[1]),
        tuple(set_aside[2]),
        tuple(set_aside[3]),
    )
    return dealt, Wall(tuple(tiles)), aside
