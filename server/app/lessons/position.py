"""Hand-written or seeded positions -> a valid `GameState` (ADR 0025)."""

from __future__ import annotations

import random
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from app.lessons.model import LESSON_RULESET, FromSeed, MeldSetup, Position, SeatSetup
from mahjong_core.actions import Action, Discard, hand_is_winning_shape
from mahjong_core.config import RuleSet
from mahjong_core.engine import reduce
from mahjong_core.melds import Meld, MeldKind
from mahjong_core.scoring.faan import seven_pairs_enabled
from mahjong_core.state import GameState, Phase, SeatState, Wind, derive_hand_seed, new_game
from mahjong_core.tiles import (
    Flower,
    TileType,
    all_flowers,
    all_tile_ids,
    assign_tile_ids,
    format_tiles,
    parse_tile,
    parse_tiles,
    tile_id_type,
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


def discard_on(state: GameState, code: str) -> GameState:
    """The seat to act discards a `code` tile, so the engine opens the claim window (ADR 0025
    "Claim positions")."""
    want = parse_tile(code)
    tile = next((t for t in state.seats[state.turn].concealed if tile_id_type(t) == want), None)
    if tile is None:
        raise ValueError(f"seat {state.turn} holds no {code}")
    after, _ = reduce(state, Discard(tile_id=tile))
    return after


def from_seed(ruleset: RuleSet, seed: int, actions: Iterable[Action]) -> GameState:
    state = new_game(ruleset, seed)
    for action in actions:
        state, _ = reduce(state, action)
    return state


def _seat_setup(seat_state: SeatState, rotate: Callable[[int], int]) -> SeatSetup:
    return SeatSetup(
        hand=format_tiles(sorted(tile_id_type(t) for t in seat_state.concealed)),
        melds=tuple(
            MeldSetup(
                kind=m.kind,
                tiles=format_tiles(tile_id_type(t) for t in m.tiles),
                from_seat=None if m.from_seat is None else rotate(m.from_seat),
            )
            for m in seat_state.melds
        ),
        discards=format_tiles(tile_id_type(t) for t in seat_state.discards),
        flowers=format_tiles(seat_state.flowers),
    )


def position_from_state(state: GameState, *, seed: int, seat: int = 0) -> Position:
    """A live `AWAIT_ACTION` state as an explicit spec, rotated so `seat` sits at seat 0: seat
    winds follow the dealer, so the rotation scores and grades the same. `seed` reshuffles only
    the hidden wall. Scores, `hand_no` and wall order are dropped; no answer key reads them.

    Raises `ValueError` on what a `Position` can't carry: another ruleset or phase, a
    kong-replacement or last-tile draw (their timing faan), or a complete hand that may not
    self-draw because it was just claimed into."""
    if state.ruleset != LESSON_RULESET:
        raise ValueError("lesson positions use LESSON_RULESET")
    if state.phase != Phase.AWAIT_ACTION:
        raise ValueError(f"a position is an AWAIT_ACTION state, not {state.phase}")
    if (
        state.wall_exhausted_at_last_draw
        or state.last_draw_was_kong_replacement
        or state.kong_replacement_streak
    ):
        raise ValueError("a last-tile or kong-replacement draw has no Position field")
    to_act = state.seats[state.turn]
    if not state.self_draw_win_allowed and hand_is_winning_shape(
        to_act, seven_pairs=seven_pairs_enabled(state.ruleset)
    ):
        raise ValueError("a complete hand after a claim would rebuild as a self-draw win")

    def rotate(n: int) -> int:
        return (n - seat) % 4

    seats = [_seat_setup(state.seats[(n + seat) % 4], rotate) for n in range(4)]
    return Position(
        seats=(seats[0], seats[1], seats[2], seats[3]),
        turn=rotate(state.turn),
        dealer=rotate(state.dealer),
        prevailing=state.prevailing,
        seed=seed,
    )


def position_to_dict(spec: Position) -> dict[str, Any]:
    """JSON-ready; `position_from_dict` reads it back."""
    return {
        "seats": [
            {
                "hand": s.hand,
                "melds": [
                    {"kind": str(m.kind), "tiles": m.tiles, "from_seat": m.from_seat}
                    for m in s.melds
                ],
                "discards": s.discards,
                "flowers": s.flowers,
            }
            for s in spec.seats
        ],
        "turn": spec.turn,
        "dealer": spec.dealer,
        "prevailing": spec.prevailing.name,
        "wall_front": spec.wall_front,
        "seed": spec.seed,
    }


def position_from_dict(data: Mapping[str, Any]) -> Position:
    s0, s1, s2, s3 = (
        SeatSetup(
            hand=s["hand"],
            melds=tuple(
                MeldSetup(MeldKind(m["kind"]), m["tiles"], m["from_seat"]) for m in s["melds"]
            ),
            discards=s["discards"],
            flowers=s["flowers"],
        )
        for s in data["seats"]
    )
    return Position(
        seats=(s0, s1, s2, s3),
        turn=data["turn"],
        dealer=data["dealer"],
        prevailing=Wind[data["prevailing"]],
        wall_front=data["wall_front"],
        seed=data["seed"],
    )
