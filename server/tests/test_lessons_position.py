import asyncio
import dataclasses
import json
from collections import Counter
from collections.abc import Callable, Iterator

import pytest

from app.lessons.grade import (
    SafeOption,
    best_discard,
    count_faan,
    safe_options,
    winning_tiles,
)
from app.lessons.model import LESSON_RULESET, FromSeed, MeldSetup, Position, SeatSetup
from app.lessons.position import (
    build_position,
    from_seed,
    position_from_dict,
    position_from_state,
    position_to_dict,
)
from app.views import seat_view
from bots.base import NO_DEADLINE
from bots.faanbot import FaanBot
from mahjong_core.actions import Action, Discard, Pass, can_declare_win, legal_actions
from mahjong_core.engine import reduce, start_next_hand
from mahjong_core.melds import MeldKind
from mahjong_core.ml import decode_action, legal_mask
from mahjong_core.presets import RULESET_PRESETS
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


def test_wall_back_draws_first_from_the_end() -> None:
    state = build_position(dataclasses.replace(SPEC, wall_back="1s3f"))
    assert tile_id_type(state.wall.tiles[-1]) == TileType.SOU_1  # type: ignore[arg-type]
    assert state.wall.tiles[-2] == Flower.FLOWER_3
    assert total_tiles(state) == TOTAL_PHYSICAL_TILES
    with pytest.raises(ValueError):
        build_position(dataclasses.replace(SPEC, wall_back="2f"))  # already in wall_front


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


def _faanbot_turns(seed: int) -> Iterator[tuple[GameState, Action, GameState]]:
    """A seeded 4 x `FaanBot` game: every `AWAIT_ACTION` state, the action taken, and the
    state it led to."""
    bot = FaanBot()
    state = new_game(LESSON_RULESET, seed)
    while state.phase != Phase.GAME_OVER:
        if state.phase == Phase.HAND_OVER:
            state, _ = start_next_hand(state)
            continue
        window = state.claim_window
        if window is not None:
            seat = min(o.seat for o in window.offers if o.seat not in window.responses)
        else:
            seat = state.turn
        aid = asyncio.run(bot.act(seat_view(state, seat), legal_mask(state, seat), NO_DEADLINE))
        action = decode_action(aid, state, seat)
        after, _ = reduce(state, action)
        if window is None:
            yield state, action, after
        state = after


def _safe(state: GameState, seat: int, rotate: Callable[[int], int]) -> list[SafeOption]:
    return [
        dataclasses.replace(o, deals_in_to=tuple(sorted(rotate(s) for s in o.deals_in_to)))
        for o in safe_options(state, seat)
    ]


@pytest.mark.parametrize("seed", [3, 4])
def test_answer_keys_survive_position_from_state(seed: int) -> None:
    """Every kind's key on a live state equals the key on its rebuilt spec, from every seat's
    perspective in turn."""
    kinds: Counter[str] = Counter()
    for n, (state, action, after) in enumerate(_faanbot_turns(seed)):
        perspective = n % 4

        def rotate(s: int, p: int = perspective) -> int:
            return (s - p) % 4

        try:
            spec = position_from_state(state, seed=n, seat=perspective)
        except ValueError:
            kinds["unrepresentable"] += 1
            continue
        rebuilt = build_position(spec)
        turn = state.turn
        assert best_discard(rebuilt, rotate(turn)) == best_discard(state, turn)
        assert _safe(rebuilt, rotate(turn), lambda s: s) == _safe(state, turn, rotate)
        for seat in range(4):
            if seat != turn:
                assert winning_tiles(rebuilt, rotate(seat)) == winning_tiles(state, seat)
                kinds["winning_tiles"] += 1
        if can_declare_win(state, turn):
            assert count_faan(rebuilt, rotate(turn)) == count_faan(state, turn)
            kinds["self_draw"] += 1
        if isinstance(action, Discard) and after.claim_window is not None:
            tile = next(
                t
                for t in rebuilt.seats[rotate(turn)].concealed
                if tile_id_type(t) == tile_id_type(action.tile_id)
            )
            claims, _ = reduce(rebuilt, Discard(tile_id=tile))
            for offer in after.claim_window.offers:
                if offer.can_win:
                    want = count_faan(after, offer.seat)
                    assert count_faan(claims, rotate(offer.seat)) == want
                    kinds["discard_win"] += 1
        kinds["checked"] += 1
    assert kinds["checked"] >= 100
    assert kinds["self_draw"] and kinds["discard_win"]
    assert kinds["unrepresentable"] < kinds["checked"] // 10


def test_position_from_state_rotates_the_perspective_to_seat_0() -> None:
    state = build_position(SPEC)
    spec = position_from_state(state, seed=11, seat=1)
    assert spec.seats[0].hand == "2345678m999p"
    assert spec.seats[0].melds == (MeldSetup(MeldKind.PUNG, "555s", from_seat=3),)
    assert spec.seats[3].hand == "123m456p789s11223z"
    assert spec.seats[3].discards == "7z"
    assert (spec.turn, spec.dealer, spec.prevailing) == (3, 3, Wind.SOUTH)
    assert position_from_state(state, seed=11) == dataclasses.replace(SPEC, wall_front="")


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"last_draw_was_kong_replacement": True}, id="kong-replacement"),
        pytest.param({"wall_exhausted_at_last_draw": True}, id="last-tile"),
        pytest.param({"ruleset": RULESET_PRESETS["hk_casual"]}, id="other-ruleset"),
    ],
)
def test_position_from_state_rejects_what_a_spec_cannot_carry(change: dict[str, object]) -> None:
    state = dataclasses.replace(build_position(SPEC), **change)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        position_from_state(state, seed=0)


def test_position_from_state_rejects_a_claim_window() -> None:
    after = next(a for _, _, a in _faanbot_turns(3) if a.phase == Phase.AWAIT_CLAIMS)
    with pytest.raises(ValueError):
        position_from_state(after, seed=0)


def test_position_dict_round_trip() -> None:
    assert position_from_dict(json.loads(json.dumps(position_to_dict(SPEC)))) == SPEC
    stacked = dataclasses.replace(SPEC, wall_back="1s")
    assert position_from_dict(json.loads(json.dumps(position_to_dict(stacked)))) == stacked
    assert "wall_back" not in position_to_dict(SPEC)


def test_from_seed_matches_new_game_and_reduce() -> None:
    actions = _script(seed=5, steps=12)
    state: GameState = new_game(LESSON_RULESET, 5)
    for action in actions:
        state, _ = reduce(state, action)
    assert from_seed(LESSON_RULESET, 5, actions) == state
    assert build_position(FromSeed(seed=5, actions=actions)) == state
