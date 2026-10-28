"""Hand-written or seeded positions -> a valid `GameState` (ADR 0025)."""

from __future__ import annotations

import random
from collections.abc import Iterable

from app.lessons.model import LESSON_RULESET, FromSeed, Position, SeatSetup
from mahjong_core.actions import Action
from mahjong_core.config import RuleSet
from mahjong_core.engine import reduce
from mahjong_core.melds import Meld
from mahjong_core.state import GameState, Phase, SeatState, derive_hand_seed, new_game
from mahjong_core.tiles import (
    Flower,
    TileType,
    all_flowers,
    all_tile_ids,
    assign_tile_ids,
    parse_tiles,
)
from mahjong_core.wall import DEALT_HAND_SIZE, Wall, WallTile

# a kong still fills one set's three hand slots
_SET_SLOTS = 3


def _types(spec: str, what: str) -> list[TileType]:
    tiles = parse_tiles(spec)
    flowers = [t for t in tiles if isinstance(t, Flower)]
    if flowers:
        raise ValueError(f"{what} cannot hold a flower: {spec!r}")
    return [t for t in tiles if isinstance(t, TileType)]


def _flowers(spec: str, what: str) -> list[Flower]:
    tiles = parse_tiles(spec)
    if any(not isinstance(t, Flower) for t in tiles):
        raise ValueError(f"{what} holds only flowers: {spec!r}")
    return [t for t in tiles if isinstance(t, Flower)]


def _seat_groups(seat: SeatSetup, n: int) -> list[list[TileType]]:
    """Hand, then each meld, then discards: the order `_build_seat` reads ids back in."""
    return [
        _types(seat.hand, f"seat {n} hand"),
        *(_types(m.tiles, f"seat {n} meld") for m in seat.melds),
        _types(seat.discards, f"seat {n} discards"),
    ]


def _check_hand_size(seat: SeatSetup, n: int, hand_len: int, to_act: bool) -> None:
    want = DEALT_HAND_SIZE - _SET_SLOTS * len(seat.melds) + (1 if to_act else 0)
    if hand_len != want:
        raise ValueError(
            f"seat {n} holds {hand_len} tiles with {len(seat.melds)} melds, want {want}"
        )


def build_position(spec: Position | FromSeed) -> GameState:
    """Raises `ValueError` on a position no real deal could reach: a fifth copy, a repeated
    flower, a hand size that doesn't match the melds, or a malformed meld."""
    if isinstance(spec, FromSeed):
        return from_seed(LESSON_RULESET, spec.seed, spec.actions)
    ruleset = LESSON_RULESET

    seat_groups = [_seat_groups(seat, n) for n, seat in enumerate(spec.seats)]
    wall_front_tiles = parse_tiles(spec.wall_front)
    wall_front_types = [t for t in wall_front_tiles if isinstance(t, TileType)]
    ids = assign_tile_ids([*(g for groups in seat_groups for g in groups), wall_front_types])
    wall_front_ids = ids.pop()

    seat_flowers = [
        _flowers(seat.flowers, f"seat {n} flowers") for n, seat in enumerate(spec.seats)
    ]
    flowers_used = [f for fl in seat_flowers for f in fl]
    flowers_used += [t for t in wall_front_tiles if isinstance(t, Flower)]
    if len(set(flowers_used)) != len(flowers_used):
        raise ValueError("each flower is a single tile")
    if flowers_used and not ruleset.flowers_enabled:
        raise ValueError("flowers are off in this ruleset")

    seats: list[SeatState] = []
    total_discards = 0
    cursor = 0
    for n, seat in enumerate(spec.seats):
        hand, *meld_ids, discards = ids[cursor : cursor + len(seat_groups[n])]
        cursor += len(seat_groups[n])
        _check_hand_size(seat, n, len(hand), to_act=n == spec.turn)
        melds = tuple(
            Meld(kind=m.kind, tiles=tuple(t), from_seat=m.from_seat)
            for m, t in zip(seat.melds, meld_ids, strict=True)
        )
        if any(m.from_seat == n for m in melds):
            raise ValueError(f"seat {n} cannot claim its own discard")
        total_discards += len(discards) + sum(1 for m in melds if m.from_seat is not None)
        seats.append(
            SeatState(
                concealed=tuple(hand),
                melds=melds,
                discards=tuple(discards),
                flowers=tuple(seat_flowers[n]),
            )
        )

    front: list[WallTile] = []
    front_ids = iter(wall_front_ids)
    for t in wall_front_tiles:
        front.append(t if isinstance(t, Flower) else next(front_ids))

    placed = {i for group in ids for i in group} | set(wall_front_ids)
    rest: list[WallTile] = [i for i in all_tile_ids() if i not in placed]
    if ruleset.flowers_enabled:
        rest += [f for f in all_flowers() if f not in flowers_used]
    random.Random(spec.seed).shuffle(rest)

    return GameState(
        ruleset=ruleset,
        game_seed=spec.seed,
        hand_seed=derive_hand_seed(spec.seed, 1),
        wall=Wall((*front, *rest)),
        seats=(seats[0], seats[1], seats[2], seats[3]),
        phase=Phase.AWAIT_ACTION,
        turn=spec.turn,
        dealer=spec.dealer,
        prevailing=spec.prevailing,
        hand_no=1,
        total_discards=total_discards,
    )


def from_seed(ruleset: RuleSet, seed: int, actions: Iterable[Action]) -> GameState:
    state = new_game(ruleset, seed)
    for action in actions:
        state, _ = reduce(state, action)
    return state
