"""Answer keys for lesson puzzles (ADR 0025 "Puzzle kinds"): what the engine says is right for
a position, plus the numbers feedback quotes. Pure and cheap per call, since
`GET /lessons/random` (phase 4) grades at request time.

What a player is graded on reads only `seat_view(state, seat)`: public tiles plus the seat's own
hand. Whether a win actually happens reads the real hands, as the engine does."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from app.lessons.model import Puzzle, PuzzleKind, SafeReason
from app.lessons.position import build_position, discard_on
from app.views import SeatView, seat_view
from bots.features import is_closed, seen34
from bots.safety import is_genbutsu, no_chance, walls_every_run
from mahjong_core.actions import (
    Discard,
    build_scoring_context,
    can_declare_win,
    hand_is_winning_shape,
)
from mahjong_core.engine import can_win_on, reduce
from mahjong_core.scoring.faan import FaanResult, score_winning_hand, seven_pairs_enabled
from mahjong_core.scoring.payout import points
from mahjong_core.shanten import shanten, ukeire
from mahjong_core.state import ClaimKind, GameState, Phase, SeatState, WinType
from mahjong_core.tiles import (
    COPIES_PER_TYPE,
    N_TILE_TYPES,
    TileId,
    TileType,
    parse_tile,
    tile_code,
    tile_id_type,
    tile_ids_for_type,
)


@dataclass(frozen=True)
class WaitOption:
    """A tile type that completes the hand's shape. `*_faan` is what the win would score;
    `*_wins` whether it clears `min_faan`. `live` counts copies the seat can't see."""

    tile: str
    discard_faan: int
    discard_wins: bool
    self_draw_faan: int
    self_draw_wins: bool
    live: int


@dataclass(frozen=True)
class WinningTilesKey:
    """`correct`: tiles that win by discard or self-draw and can still arrive. `below_minimum`:
    complete the shape but clear `min_faan` neither way. `dead`: would win, but the seat can see
    every copy."""

    correct: tuple[str, ...]
    below_minimum: tuple[str, ...]
    dead: tuple[str, ...]
    options: tuple[WaitOption, ...]


@dataclass(frozen=True)
class DiscardOption:
    """`kinds`/`tiles`: tile types and live copies that lower `shanten` once discarded."""

    tile: str
    shanten: int
    kinds: int
    tiles: int


@dataclass(frozen=True)
class BestDiscardKey:
    correct: tuple[str, ...]
    options: tuple[DiscardOption, ...]


@dataclass(frozen=True)
class FaanLine:
    pattern: str
    faan: int


@dataclass(frozen=True)
class CountFaanKey:
    """`correct` is the total faan, capped as paid."""

    correct: int
    win_type: WinType
    breakdown: tuple[FaanLine, ...]
    points: int


@dataclass(frozen=True)
class SafeOption:
    """`deals_in_to`: seats whose real hand wins on this discard. `reasons`: the reasons that
    hold for it from the seat's own view."""

    tile: str
    deals_in_to: tuple[int, ...]
    reasons: tuple[SafeReason, ...]


@dataclass(frozen=True)
class SafeDiscardKey:
    """`correct`: the author's accepted tiles, each checked. `safe`: every discard no one can win
    on, deducible or not."""

    correct: tuple[str, ...]
    reason: SafeReason
    safe: tuple[str, ...]
    options: tuple[SafeOption, ...]


def _code(tile_type: int) -> str:
    return tile_code(TileType(tile_type))


def _visible34(view: SeatView) -> list[int]:
    """`seen34` plus each kong's fourth tile, which it drops (shanten counts a kong as three)."""
    counts = seen34(view)
    for melds in view.melds:
        for meld in melds:
            if meld.is_kong:
                counts[int(tile_id_type(meld.tiles[0]))] += 1
    return counts


def _free_id(tile_type: int, seat_state: SeatState) -> TileId | None:
    held = {*seat_state.concealed, *(t for m in seat_state.melds for t in m.tiles)}
    return next((t for t in tile_ids_for_type(TileType(tile_type)) if t not in held), None)


def _require_to_act(state: GameState, seat: int) -> None:
    if state.phase != Phase.AWAIT_ACTION or state.turn != seat:
        raise ValueError(f"seat {seat} is not the seat to act")


def winning_tiles(state: GameState, seat: int) -> WinningTilesKey:
    """`seat` holds a hand one tile short. Each type is tried as a discard from the seat about
    to act, and as `seat`'s own next draw."""
    seat_state = state.seats[seat]
    if len(seat_state.concealed) % 3 != 1:
        raise ValueError(f"seat {seat} is not one tile short of a hand")
    visible = _visible34(seat_view(state, seat))
    sevens = seven_pairs_enabled(state.ruleset)
    discarder = state.turn if state.turn != seat else (seat - 1) % 4
    ron_state = dataclasses.replace(state, total_discards=state.total_discards + 1)
    # an ordinary wall draw: no last-tile or kong-replacement timing faan
    draw_state = dataclasses.replace(
        state,
        wall_exhausted_at_last_draw=False,
        last_draw_was_kong_replacement=False,
        kong_replacement_streak=0,
    )

    options: list[WaitOption] = []
    for t in range(N_TILE_TYPES):
        tile = _free_id(t, seat_state)
        if tile is None:
            continue
        concealed = (*seat_state.concealed, tile)
        completed = dataclasses.replace(seat_state, concealed=concealed)
        if not hand_is_winning_shape(completed, seven_pairs=sevens):
            continue
        ron_ctx = build_scoring_context(
            ron_state, seat, self_drawn=False, discarder=discarder, winning_tile=tile
        )
        ron = score_winning_hand(concealed, seat_state.melds, ron_ctx, state.ruleset)
        draw_ctx = build_scoring_context(draw_state, seat, self_drawn=True)
        draw = score_winning_hand(concealed, seat_state.melds, draw_ctx, state.ruleset)
        options.append(
            WaitOption(
                tile=_code(t),
                discard_faan=ron.total_faan,
                discard_wins=can_win_on(ron_state, seat, tile, discarder=discarder),
                self_draw_faan=draw.total_faan,
                self_draw_wins=draw.clears_min_faan,
                live=COPIES_PER_TYPE - visible[t],
            )
        )

    wins = [o for o in options if o.discard_wins or o.self_draw_wins]
    return WinningTilesKey(
        correct=tuple(o.tile for o in wins if o.live),
        below_minimum=tuple(o.tile for o in options if o not in wins),
        # a dead wait isn't a tile you can win on, so it isn't graded correct
        dead=tuple(o.tile for o in wins if not o.live),
        options=tuple(options),
    )


def best_discard(state: GameState, seat: int) -> BestDiscardKey:
    """Lowest shanten after the discard, then most live tiles accepted; ties are all correct.
    Live means not visible to `seat`."""
    _require_to_act(state, seat)
    view = seat_view(state, seat)
    hand34 = [0] * N_TILE_TYPES
    for tile in view.own_hand:
        hand34[int(tile_id_type(tile))] += 1
    melds = len(view.melds[seat])
    closed = is_closed(view)
    hand_sets = state.ruleset.hand_sets
    accepts = ukeire(hand34, _visible34(view), closed=closed, hand_sets=hand_sets, melds=melds)

    options: list[DiscardOption] = []
    for t in sorted({int(tile_id_type(tile)) for tile in view.own_hand}):
        hand34[t] -= 1
        after = shanten(hand34, closed=closed, hand_sets=hand_sets, melds=melds)
        hand34[t] += 1
        kinds, tiles = accepts[t]
        options.append(DiscardOption(tile=_code(t), shanten=after, kinds=kinds, tiles=tiles))

    best = min((o.shanten, -o.tiles) for o in options)
    return BestDiscardKey(
        correct=tuple(o.tile for o in options if (o.shanten, -o.tiles) == best),
        options=tuple(options),
    )


def count_faan(state: GameState, seat: int) -> CountFaanKey:
    """A won position: `seat` to act holding a winning hand (self-draw), or `seat` offered a win
    in a discard claim window (reduce the feeding `Discard`, ADR 0025 "Claim positions").
    Raises `ValueError` if `seat` can't legally win there."""
    seat_state = state.seats[seat]
    window = state.claim_window
    result: FaanResult
    if state.phase == Phase.AWAIT_ACTION and state.turn == seat:
        if not can_declare_win(state, seat):
            raise ValueError(f"seat {seat} cannot declare a win")
        ctx = build_scoring_context(state, seat, self_drawn=True)
        result = score_winning_hand(seat_state.concealed, seat_state.melds, ctx, state.ruleset)
        win_type = WinType.SELF_DRAW
    elif (
        state.phase == Phase.AWAIT_CLAIMS
        and window is not None
        and window.kind == ClaimKind.DISCARD
        and any(o.seat == seat and o.can_win for o in window.offers)
    ):
        ctx = build_scoring_context(
            state, seat, self_drawn=False, discarder=window.source_seat, winning_tile=window.tile
        )
        concealed = (*seat_state.concealed, window.tile)
        result = score_winning_hand(concealed, seat_state.melds, ctx, state.ruleset)
        win_type = WinType.DISCARD
    else:
        raise ValueError(f"seat {seat} has no win to count")
    return CountFaanKey(
        correct=result.total_faan,
        win_type=win_type,
        breakdown=tuple(FaanLine(name, faan) for name, faan in result.breakdown.items()),
        points=points(result.total_faan, state.ruleset),
    )


def _reasons(
    view: SeatView, visible: list[int], seat: int, tile_type: int
) -> tuple[SafeReason, ...]:
    holds = {
        SafeReason.GENBUTSU: all(
            is_genbutsu(view, opp, tile_type)
            for opp in range(len(view.discard_pools))
            if opp != seat
        ),
        # bots.safety.no_chance is the plain every-copy-visible count
        SafeReason.ALL_COPIES_VISIBLE: no_chance(tile_type, visible),
        SafeReason.NO_CHANCE: walls_every_run(tile_type, visible),
    }
    return tuple(r for r in SafeReason if holds[r])


def safe_options(state: GameState, seat: int) -> tuple[SafeOption, ...]:
    """Each discard is reduced through the engine, so its claim window's `can_win` offers
    (`can_win_on` per opponent) decide exactly who deals in, against the real hands. Never
    `tile_risk`: that is a heuristic."""
    _require_to_act(state, seat)
    view = seat_view(state, seat)
    visible = _visible34(view)
    held: dict[int, TileId] = {}
    for tile in view.own_hand:
        held.setdefault(int(tile_id_type(tile)), tile)

    options: list[SafeOption] = []
    for t in sorted(held):
        after, _ = reduce(state, Discard(tile_id=held[t]))
        window = after.claim_window if after.phase == Phase.AWAIT_CLAIMS else None
        deals_in = tuple(o.seat for o in window.offers if o.can_win) if window else ()
        options.append(SafeOption(_code(t), deals_in, _reasons(view, visible, seat, t)))
    return tuple(options)


def safe_discard(
    state: GameState, seat: int, accepted: Iterable[str], reason: SafeReason
) -> SafeDiscardKey:
    """`safe_options`, graded against the author's `accepted` tiles. Raises `ValueError` unless
    every `accepted` tile is in hand, deals in to nobody, and `reason` holds for it."""
    options = safe_options(state, seat)
    by_tile = {o.tile: o for o in options}
    wanted = {tile_code(parse_tile(code)) for code in accepted}
    if not wanted:
        raise ValueError("a safe discard puzzle accepts at least one tile")
    for code in sorted(wanted):
        option = by_tile.get(code)
        if option is None:
            raise ValueError(f"{code} is not in seat {seat}'s hand")
        if option.deals_in_to:
            raise ValueError(f"{code} deals in to seats {option.deals_in_to}")
        if reason not in option.reasons:
            raise ValueError(f"{reason} does not hold for {code}")
    return SafeDiscardKey(
        correct=tuple(o.tile for o in options if o.tile in wanted),
        reason=reason,
        safe=tuple(o.tile for o in options if not o.deals_in_to),
        options=tuple(options),
    )


type AnswerKey = WinningTilesKey | BestDiscardKey | CountFaanKey | SafeDiscardKey


def puzzle_state(puzzle: Puzzle) -> GameState:
    """The state `puzzle` is posed on: its position, plus the feeding discard of a discard win."""
    state = build_position(puzzle.position)
    return state if puzzle.discard is None else discard_on(state, puzzle.discard)


def answer_key(puzzle: Puzzle, state: GameState | None = None) -> AnswerKey:
    """The engine's key for seat 0 on `puzzle_state(puzzle)` (pass `state` if already built).
    `safe_discard` grades the puzzle's own `answer` and `reason`."""
    if state is None:
        state = puzzle_state(puzzle)
    if puzzle.discard is not None and puzzle.kind != PuzzleKind.COUNT_FAAN:
        raise ValueError(f"{puzzle.id}: only count_faan poses a discard win")
    match puzzle.kind:
        case PuzzleKind.WINNING_TILES:
            return winning_tiles(state, 0)
        case PuzzleKind.BEST_DISCARD:
            return best_discard(state, 0)
        case PuzzleKind.COUNT_FAAN:
            return count_faan(state, 0)
        case PuzzleKind.SAFE_DISCARD:
            if puzzle.reason is None or isinstance(puzzle.answer, int):
                raise ValueError(f"{puzzle.id}: safe_discard states accepted tiles and a reason")
            return safe_discard(state, 0, puzzle.answer, puzzle.reason)


def key_from_dict(kind: PuzzleKind, data: Mapping[str, Any]) -> AnswerKey:
    """The inverse of `dataclasses.asdict` on `kind`'s key, as the shortlist stores it."""
    match kind:
        case PuzzleKind.WINNING_TILES:
            return WinningTilesKey(
                correct=tuple(data["correct"]),
                below_minimum=tuple(data["below_minimum"]),
                dead=tuple(data["dead"]),
                options=tuple(WaitOption(**o) for o in data["options"]),
            )
        case PuzzleKind.BEST_DISCARD:
            return BestDiscardKey(
                correct=tuple(data["correct"]),
                options=tuple(DiscardOption(**o) for o in data["options"]),
            )
        case PuzzleKind.COUNT_FAAN:
            return CountFaanKey(
                correct=data["correct"],
                win_type=WinType(data["win_type"]),
                breakdown=tuple(FaanLine(**line) for line in data["breakdown"]),
                points=data["points"],
            )
        case PuzzleKind.SAFE_DISCARD:
            return SafeDiscardKey(
                correct=tuple(data["correct"]),
                reason=SafeReason(data["reason"]),
                safe=tuple(data["safe"]),
                options=tuple(
                    SafeOption(
                        tile=o["tile"],
                        deals_in_to=tuple(o["deals_in_to"]),
                        reasons=tuple(SafeReason(r) for r in o["reasons"]),
                    )
                    for o in data["options"]
                ),
            )


def stated_answer_holds(puzzle: Puzzle, key: AnswerKey) -> bool:
    """The author's `answer` is exactly the key's `correct`, tile order aside."""
    if isinstance(key, CountFaanKey):
        return puzzle.answer == key.correct
    if isinstance(puzzle.answer, int):
        return False
    return sorted(tile_code(parse_tile(c)) for c in puzzle.answer) == sorted(key.correct)
