import dataclasses

import pytest

from app.lessons.model import LESSON_RULESET, FromSeed, MeldSetup, Position, SeatSetup
from app.lessons.position import build_position, from_seed
from mahjong_core.actions import Action, Discard, Pass, legal_actions
from mahjong_core.engine import reduce
from mahjong_core.melds import MeldKind
from mahjong_core.state import GameState, Phase, Wind, derive_hand_seed, new_game
from mahjong_core.tiles import (
    TOTAL_PHYSICAL_TILES,
    Flower,
    TileId,
    TileType,
    all_flowers,
    all_tile_ids,
    parse_tiles,
    tile_id_type,
)
from tests.game_state import total_tiles

SPEC = Position(
    seats=(
        SeatSetup(hand="123m456p789s11223z", discards="7z", flowers="1f"),
        SeatSetup(hand="2345678m999p", melds=(MeldSetup(MeldKind.PUNG, "555s", from_seat=0),)),
        SeatSetup(hand="13579m13579p135s"),
        SeatSetup(hand="2468m2468p2468s7z", discards="9m", flowers="5f"),
    ),
    turn=0,
    dealer=0,
    prevailing=Wind.SOUTH,
    wall_front="6s2f4z",
    seed=11,
)


def _with_seat(spec: Position, seat: int, **overrides: object) -> Position:
    seats = list(spec.seats)
    seats[seat] = dataclasses.replace(seats[seat], **overrides)  # type: ignore[arg-type]
    return dataclasses.replace(spec, seats=tuple(seats))  # type: ignore[arg-type]


def _types(ids: tuple[TileId, ...]) -> list[TileType]:
    return sorted(tile_id_type(i) for i in ids)


def test_every_tile_is_placed_exactly_once() -> None:
    state = build_position(SPEC)
    assert total_tiles(state) == TOTAL_PHYSICAL_TILES
    ids = [t for t in state.wall.tiles if not isinstance(t, Flower)]
    flowers = [t for t in state.wall.tiles if isinstance(t, Flower)]
    for seat in state.seats:
        ids += [*seat.concealed, *seat.discards, *(t for m in seat.melds for t in m.tiles)]
        flowers += seat.flowers
    assert sorted(ids) == list(all_tile_ids())
    assert sorted(flowers) == list(all_flowers())


def test_seats_match_the_spec() -> None:
    state = build_position(SPEC)
    assert _types(state.seats[0].concealed) == sorted(parse_tiles("123m456p789s11223z"))
    assert _types(state.seats[3].discards) == [TileType.MAN_9]
    assert state.seats[0].flowers == (Flower.FLOWER_1,)
    [pung] = state.seats[1].melds
    assert pung.kind == MeldKind.PUNG and pung.from_seat == 0
    assert _types(pung.tiles) == [TileType.SOU_5] * 3


def test_state_fields() -> None:
    state = build_position(SPEC)
    assert state.ruleset == LESSON_RULESET
    assert state.phase == Phase.AWAIT_ACTION
    assert (state.turn, state.dealer, state.prevailing, state.hand_no) == (0, 0, Wind.SOUTH, 1)
    assert state.hand_seed == derive_hand_seed(11, 1)
    # two pool discards plus the claimed pung's tile
    assert state.total_discards == 3


def test_wall_front_draws_first() -> None:
    front = build_position(SPEC).wall.tiles[:3]
    assert tile_id_type(front[0]) == TileType.SOU_6  # type: ignore[arg-type]
    assert front[1] == Flower.FLOWER_2
    assert tile_id_type(front[2]) == TileType.WIND_NORTH  # type: ignore[arg-type]


def test_engine_plays_on_from_a_built_position() -> None:
    state = build_position(SPEC)
    discard = next(a for a in legal_actions(state, 0) if isinstance(a, Discard))
    after, _ = reduce(state, discard)
    assert total_tiles(after) == TOTAL_PHYSICAL_TILES
    assert after.total_discards == 4


def test_deterministic_per_seed() -> None:
    assert build_position(SPEC) == build_position(SPEC)
    assert build_position(SPEC).wall != build_position(dataclasses.replace(SPEC, seed=12)).wall


@pytest.mark.parametrize(
    "spec",
    [
        pytest.param(dataclasses.replace(SPEC, wall_front="5s"), id="fifth-copy-in-wall"),
        pytest.param(_with_seat(SPEC, 2, hand="13579m13579p155s"), id="fifth-copy-in-hand"),
        pytest.param(_with_seat(SPEC, 3, flowers="1f"), id="duplicate-flower"),
        pytest.param(dataclasses.replace(SPEC, wall_front="5f"), id="flower-in-hand-and-wall"),
        pytest.param(_with_seat(SPEC, 2, hand="13579m13579p13s"), id="short-hand"),
        pytest.param(_with_seat(SPEC, 1, hand="2345678m999p1s"), id="hand-ignores-meld"),
        pytest.param(dataclasses.replace(SPEC, turn=2), id="turn-seat-has-not-drawn"),
        pytest.param(_with_seat(SPEC, 0, flowers="1m"), id="tile-as-flower"),
        pytest.param(_with_seat(SPEC, 2, hand="13579m13579p13s1f"), id="flower-in-hand"),
        pytest.param(
            _with_seat(SPEC, 1, melds=(MeldSetup(MeldKind.PUNG, "555s", from_seat=1),)),
            id="claim-own-discard",
        ),
        pytest.param(
            _with_seat(SPEC, 1, melds=(MeldSetup(MeldKind.CHOW, "135s", from_seat=0),)),
            id="bad-chow",
        ),
        pytest.param(_with_seat(SPEC, 0, hand="123m456p789s11223"), id="ranks-without-suit"),
    ],
)
def test_rejects_unreachable_positions(spec: Position) -> None:
    with pytest.raises(ValueError):
        build_position(spec)


def _script(seed: int, steps: int) -> tuple[Action, ...]:
    """Seeded play that passes every claim and discards the first legal tile."""
    state = new_game(LESSON_RULESET, seed)
    actions: list[Action] = []
    for _ in range(steps):
        for seat in range(4):
            options = legal_actions(state, seat)
            pick = next((a for a in options if isinstance(a, Pass | Discard)), None)
            if pick is not None:
                break
        assert pick is not None
        actions.append(pick)
        state, _ = reduce(state, pick)
    return tuple(actions)


def test_from_seed_matches_new_game_and_reduce() -> None:
    actions = _script(seed=5, steps=12)
    state: GameState = new_game(LESSON_RULESET, 5)
    for action in actions:
        state, _ = reduce(state, action)
    assert from_seed(LESSON_RULESET, 5, actions) == state
    assert build_position(FromSeed(seed=5, actions=actions)) == state
