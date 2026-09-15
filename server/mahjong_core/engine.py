"""`reduce(state, action) -> (state, events)` -- the turn/claim/hand/game state machine
(docs/01-rules-spec.md §4; docs/00-architecture.md §3) wiring `config`, `tiles`, `wall`,
`melds`, `state`, `actions`, `claims` together (docs/05-roadmap.md §1).

Pure: no asyncio, no I/O, no clock, no unseeded randomness (server/AGENTS.md). Every action
is validated against `actions.legal_actions` before it's applied -- an action the server
didn't already offer that seat is a hard error, never silently ignored.

**Two entry points, not one.** `reduce()` applies exactly one `Action` and everything that
automatically cascades from it with no further seat decision required (flower chains, a
claim window with no legal claims, a kong's replacement draw, a resolved claim). It stops the
moment either a real decision is needed from some seat (`AWAIT_ACTION`, or `AWAIT_CLAIMS`/
`AWAIT_KONG_ROB` with live offers) or the hand ends (`Phase.HAND_OVER`, `hand_result` set).
Advancing from `HAND_OVER` to the next hand (or to `GAME_OVER`) is `start_next_hand()`, a
second pure function mirroring `state.new_game()` -- there is no `Action` for "deal the next
hand" because it isn't a seat's decision (`actions.py`'s docstring: "server-computed
transitions, no seat decision"), so it can't go through `reduce()`'s `(state, action)` shape.
A caller (the M3 Room actor, or this module's own self-play test) checks
`state.phase == Phase.HAND_OVER` and calls `start_next_hand()` before offering anyone
anything else.

**Hang-safety.** The only place this module loops at all is the flower-replacement cascade,
and it's bounded by the fixed 8-physical-flower count (`_MAX_FLOWERS`) with an assertion, not
a "should terminate eventually" comment. Hand-to-hand and game-to-game bookkeeping
(`start_next_hand`) is straight-line arithmetic -- `hand_no` strictly increments every call,
dealer/prevailing-wind rotation is O(1) -- so it cannot loop at all, let alone hang.

**SCORING is a real box in the docs/01-rules-spec.md §4 diagram that never appears in
`GameState.phase`.** M1 has no faan math (`scoring/` doesn't exist yet -- docs/05-roadmap.md
§2 is M2), so there is nothing to compute there beyond hand *shape*, which is already known
the moment a win is declared/claimed. `_end_hand` folds that zero-duration stub step directly
into the `HAND_OVER` transition rather than returning a state a caller would need to bounce
straight back out of with no action available -- consistent with `legal_actions` already
returning `()` for `SCORING` for the same "no seat decision" reason.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, cast

from mahjong_core.actions import (
    Action,
    ActionKind,
    ClaimChow,
    ClaimKong,
    ClaimPung,
    ClaimWin,
    DeclareAddedKong,
    DeclareConcealedKong,
    DeclareWin,
    Discard,
    Pass,
    hand_is_winning_shape,
    legal_actions,
)
from mahjong_core.claims import ClaimResponse, can_close_early, resolve_claims
from mahjong_core.config import GameLength
from mahjong_core.melds import Meld, MeldKind, legal_claims
from mahjong_core.state import (
    ClaimKind,
    ClaimOffer,
    ClaimWindow,
    GameOutcome,
    GameState,
    HandOutcome,
    HandResult,
    Phase,
    Seats,
    SeatState,
    Wind,
    WinType,
    derive_hand_seed,
    new_game,
)
from mahjong_core.tiles import Flower, TileId
from mahjong_core.wall import WallTile, deal_hands, draw_back, draw_front, new_wall, replace_flowers

__all__ = [
    "ENGINE_VERSION",
    "Action",
    "ClaimResolved",
    "Discarded",
    "Drawn",
    "Event",
    "EventKind",
    "FlowerReplaced",
    "GameEnded",
    "HandEnded",
    "IllegalActionError",
    "KongReplacementDrawn",
    "MeldFormed",
    "game_outcome",
    "new_game",
    "reduce",
    "start_next_hand",
]

ENGINE_VERSION = "1.0.0"
# bump on any change to the reducer, wall order, or flower-replacement ordering
# (docs/06-ml.md §2). Every persisted GameRecord stamps this value; a mismatch against the
# running engine's ENGINE_VERSION means the record is not replayable, full stop -- there is
# no migration path (see app/db/records.is_replayable).


class IllegalActionError(ValueError):
    """Raised when `reduce()`/`start_next_hand()` is asked to apply something
    `actions.legal_actions` didn't actually offer. The server must never construct an action
    outside that set (server/AGENTS.md: "never trust a client-supplied [legal-action set]");
    a client-supplied action reaching here unvalidated is an app/ bug, not a game state to
    tolerate."""


class EventKind(StrEnum):
    """Discriminator tag, one per `Event` variant -- mirrors `actions.ActionKind`."""

    DRAWN = "drawn"
    FLOWER_REPLACED = "flower_replaced"
    DISCARDED = "discarded"
    MELD_FORMED = "meld_formed"
    CLAIM_RESOLVED = "claim_resolved"
    KONG_REPLACEMENT_DRAWN = "kong_replacement_drawn"
    HAND_ENDED = "hand_ended"
    GAME_ENDED = "game_ended"


@dataclass(frozen=True)
class Drawn:
    """A normal front-of-wall draw landed in `seat`'s hand (01-rules-spec.md §4
    `AWAIT_DRAW`)."""

    seat: int
    tile_id: TileId
    kind: Literal[EventKind.DRAWN] = EventKind.DRAWN


@dataclass(frozen=True)
class FlowerReplaced:
    """`seat` revealed `flower` and drew a replacement (§3 step 4, §11.1). One event per
    flower shed -- a chained replacement that's itself a flower produces another of these,
    followed eventually by exactly one `Drawn`/`KongReplacementDrawn` for the tile that
    finally lands."""

    seat: int
    flower: Flower
    kind: Literal[EventKind.FLOWER_REPLACED] = EventKind.FLOWER_REPLACED


@dataclass(frozen=True)
class Discarded:
    seat: int
    tile_id: TileId
    kind: Literal[EventKind.DISCARDED] = EventKind.DISCARDED


@dataclass(frozen=True)
class MeldFormed:
    """`seat` formed `meld` -- by claiming a discard, or declaring a concealed/added kong on
    their own turn. `meld.from_seat` (melds.py) already distinguishes claimed from
    self-declared; no separate event needed for that."""

    seat: int
    meld: Meld
    kind: Literal[EventKind.MELD_FORMED] = EventKind.MELD_FORMED


@dataclass(frozen=True)
class ClaimResolved:
    """A claim window (`AWAIT_CLAIMS`/`AWAIT_KONG_ROB`) closed. `winning_seat`/`action_kind`
    are both `None` when nobody's claim beat a Pass (00-architecture.md §4)."""

    window_id: int
    claim_kind: ClaimKind
    winning_seat: int | None
    action_kind: ActionKind | None
    kind: Literal[EventKind.CLAIM_RESOLVED] = EventKind.CLAIM_RESOLVED


@dataclass(frozen=True)
class KongReplacementDrawn:
    """A kong (own-turn declare or claimed) drew its replacement from the back of the wall
    (§5). Distinct from `Drawn` so a client/bot can tell 槓上開花 apart from a normal draw."""

    seat: int
    tile_id: TileId
    kind: Literal[EventKind.KONG_REPLACEMENT_DRAWN] = EventKind.KONG_REPLACEMENT_DRAWN


@dataclass(frozen=True)
class HandEnded:
    hand_no: int
    outcome: HandOutcome
    winner: int | None
    win_type: WinType | None
    discarder: int | None
    kind: Literal[EventKind.HAND_ENDED] = EventKind.HAND_ENDED


@dataclass(frozen=True)
class GameEnded:
    hand_no: int  # the last hand actually played
    scores: tuple[int, int, int, int]
    kind: Literal[EventKind.GAME_ENDED] = EventKind.GAME_ENDED


Event = (
    Drawn
    | FlowerReplaced
    | Discarded
    | MeldFormed
    | ClaimResolved
    | KongReplacementDrawn
    | HandEnded
    | GameEnded
)


_MAX_FLOWERS = 8  # tiles.py TOTAL_PHYSICAL_TILES - 136: the whole physical flower/season set
_ALLOWED_ROUNDS: dict[GameLength, int] = {
    GameLength.EAST_ONLY: 1,  # 一圈
    GameLength.EAST_SOUTH: 2,  # 半莊
    GameLength.FULL: 4,  # 四圈
}


def reduce(state: GameState, action: Action) -> tuple[GameState, list[Event]]:
    """Apply one `Action`, already validated against `actions.legal_actions(state, seat)`,
    plus every automatic step it triggers with no further seat decision (see module
    docstring). Raises `IllegalActionError` if `action` isn't currently legal for its seat.
    """
    seat = _acting_seat(state, action)
    if action not in legal_actions(state, seat):
        raise IllegalActionError(f"{action!r} is not legal for seat {seat} in {state.phase}")

    if isinstance(action, Discard):
        return _apply_discard(state, seat, action)
    if isinstance(action, (DeclareConcealedKong, DeclareAddedKong)):
        return _apply_self_kong(state, seat, action.meld)
    if isinstance(action, DeclareWin):
        return _end_hand(
            state, HandOutcome.WIN, winner=seat, win_type=WinType.SELF_DRAW, discarder=None
        )
    return _apply_claim_response(state, seat, action)


def start_next_hand(state: GameState) -> tuple[GameState, list[Event]]:
    """Roll from `Phase.HAND_OVER` into the next hand's deal, or into `Phase.GAME_OVER`.
    Not an `Action` -- see module docstring for why this can't go through `reduce()`.

    Dealer repeats (連莊) on a dealer win, or on any exhaustive draw if configured
    (01-rules-spec.md §2, §9); otherwise the deal passes to `(dealer + 1) % 4`, and once that
    wraps back to seat 0 a full round has completed -- the prevailing wind advances, or the
    game ends if `ruleset.game_length` has no round left (§2's `EAST_ONLY`/`EAST_SOUTH`/
    `FULL` map to 1/2/4 rounds via `_ALLOWED_ROUNDS`). `hand_no` increments unconditionally
    either way, so this can never re-deal the same hand number twice.
    """
    if state.phase != Phase.HAND_OVER:
        raise IllegalActionError(f"start_next_hand requires HAND_OVER, got {state.phase}")
    result = state.hand_result
    assert result is not None  # GameState.__post_init__ guarantees this for HAND_OVER

    ruleset = state.ruleset
    dealer_won = result.outcome == HandOutcome.WIN and result.winner == state.dealer
    repeats = (dealer_won and ruleset.dealer_repeat_on_win) or (
        result.outcome == HandOutcome.EXHAUSTIVE_DRAW and ruleset.dealer_repeat_on_draw
    )

    if repeats:
        next_dealer = state.dealer
        next_prevailing = state.prevailing
        game_over = False
    else:
        next_dealer = (state.dealer + 1) % 4
        next_prevailing = state.prevailing
        game_over = False
        if next_dealer == 0:
            allowed = _ALLOWED_ROUNDS[ruleset.game_length]
            if int(state.prevailing) + 1 >= allowed:
                game_over = True
            else:
                next_prevailing = Wind(int(state.prevailing) + 1)

    if game_over:
        final = dataclasses.replace(
            state, phase=Phase.GAME_OVER, claim_window=None, hand_result=None
        )
        return final, [GameEnded(hand_no=state.hand_no, scores=_scores(state))]

    next_state = _deal_hand(
        state, dealer=next_dealer, prevailing=next_prevailing, hand_no=state.hand_no + 1
    )
    return next_state, []


# --- dispatch helpers ------------------------------------------------------------------------


def _acting_seat(state: GameState, action: Action) -> int:
    if isinstance(action, (ClaimChow, ClaimPung, ClaimKong, ClaimWin, Pass)):
        return action.seat
    return state.turn


def _with_seat(seats: Seats, seat: int, new_state: SeatState) -> Seats:
    updated = list(seats)
    updated[seat] = new_state
    return cast(Seats, tuple(updated))


def _scores(state: GameState) -> tuple[int, int, int, int]:
    return cast(tuple[int, int, int, int], tuple(s.score for s in state.seats))


def game_outcome(state: GameState) -> GameOutcome:
    """Extract `docs/06-ml.md §2`'s `GameOutcome` from a finished game. Same fields as
    `GameEnded`, but callable independently of catching that event -- a persistence path
    saving a `GameRecord` after the fact (app/db/records.py) has the final `GameState` on
    hand, not the event stream that produced it."""
    if state.phase != Phase.GAME_OVER:
        raise IllegalActionError(f"game_outcome requires Phase.GAME_OVER, got {state.phase}")
    return GameOutcome(hand_count=state.hand_no, final_scores=_scores(state))


def _can_win_with(seat_state: SeatState, tile: TileId) -> bool:
    candidate = dataclasses.replace(seat_state, concealed=(*seat_state.concealed, tile))
    return hand_is_winning_shape(candidate)


# --- draw, incl. flower cascade ------------------------------------------------------------


def _wall_exhausted(state: GameState) -> bool:
    return len(state.wall.tiles) <= state.ruleset.wall_reserve


def _draw_and_cascade(
    state: GameState, seat: int, *, from_front: bool
) -> tuple[GameState, TileId | None, list[Event]]:
    """Draw one tile for `seat`, replacing any flowers drawn from the back (§3 step 4,
    §11.1) until a playable tile lands. Checks wall exhaustion before *every* draw in the
    cascade, not just the first -- a flower reveal can itself run the wall down to
    `wall_reserve` with no replacement left to draw, which is an exhaustive draw (§9), not an
    error. Returns `tile=None` in that case; any flowers already revealed this cascade stay
    revealed (`state` reflects them) even though the hand ends before a real tile lands.

    Bounded by `_MAX_FLOWERS`: a flower is a unique physical tile that can never reappear
    once revealed, so the cascade provably cannot exceed the 8 that exist -- the
    `AssertionError` below is a can't-happen guard, not a real code path."""
    events: list[Event] = []
    seat_state = state.seats[seat]

    if _wall_exhausted(state):
        return state, None, events

    draw_fn = draw_front if from_front else draw_back
    tile, wall = draw_fn(state.wall)

    steps = 0
    while isinstance(tile, Flower):
        steps += 1
        if steps > _MAX_FLOWERS:
            raise AssertionError("flower cascade exceeded the physical flower count")
        seat_state = dataclasses.replace(seat_state, flowers=(*seat_state.flowers, tile))
        events.append(FlowerReplaced(seat=seat, flower=tile))
        state = dataclasses.replace(
            state, seats=_with_seat(state.seats, seat, seat_state), wall=wall
        )
        if _wall_exhausted(state):
            return state, None, events
        tile, wall = draw_back(wall)

    state = dataclasses.replace(state, seats=_with_seat(state.seats, seat, seat_state), wall=wall)
    return state, tile, events


def _draw_for_turn(
    state: GameState, seat: int, *, from_front: bool, kong: bool
) -> tuple[GameState, list[Event]]:
    """Land a drawn tile in `seat`'s hand and open `AWAIT_ACTION` for them -- or, if the wall
    runs out before or during the draw, end the hand as an exhaustive draw instead."""
    state, tile, events = _draw_and_cascade(state, seat, from_front=from_front)
    if tile is None:
        more_state, more_events = _end_hand(
            state, HandOutcome.EXHAUSTIVE_DRAW, winner=None, win_type=None, discarder=None
        )
        return more_state, events + more_events

    seat_state = state.seats[seat]
    seat_state = dataclasses.replace(seat_state, concealed=(*seat_state.concealed, tile))
    state = dataclasses.replace(
        state,
        seats=_with_seat(state.seats, seat, seat_state),
        turn=seat,
        phase=Phase.AWAIT_ACTION,
        claim_window=None,
    )
    draw_event: Event = (
        KongReplacementDrawn(seat=seat, tile_id=tile) if kong else Drawn(seat=seat, tile_id=tile)
    )
    return state, [*events, draw_event]


# --- discard + claim window --------------------------------------------------------------


def _discard_claim_offers(state: GameState, discarder: int, tile: TileId) -> tuple[ClaimOffer, ...]:
    offers: list[ClaimOffer] = []
    for seat in range(4):
        if seat == discarder:
            continue
        seat_state = state.seats[seat]
        melds = legal_claims(seat_state.concealed, tile, discarder, seat)
        can_win = _can_win_with(seat_state, tile)
        if can_win or melds:
            offers.append(ClaimOffer(seat=seat, can_win=can_win, melds=melds))
    return tuple(offers)


def _apply_discard(state: GameState, seat: int, action: Discard) -> tuple[GameState, list[Event]]:
    tile = action.tile_id
    seat_state = state.seats[seat]
    new_concealed = tuple(t for t in seat_state.concealed if t != tile)
    seat_state = dataclasses.replace(
        seat_state, concealed=new_concealed, discards=(*seat_state.discards, tile)
    )
    state = dataclasses.replace(state, seats=_with_seat(state.seats, seat, seat_state))
    events: list[Event] = [Discarded(seat=seat, tile_id=tile)]

    offers = _discard_claim_offers(state, seat, tile)
    if not offers:
        more_state, more_events = _draw_for_turn(state, (seat + 1) % 4, from_front=True, kong=False)
        return more_state, events + more_events

    window = ClaimWindow(
        window_id=state.next_window_id,
        kind=ClaimKind.DISCARD,
        source_seat=seat,
        tile=tile,
        offers=offers,
    )
    state = dataclasses.replace(
        state,
        phase=Phase.AWAIT_CLAIMS,
        claim_window=window,
        next_window_id=state.next_window_id + 1,
    )
    return state, events


# --- own-turn kongs, incl. robbing-the-kong window ----------------------------------------


def _kong_rob_offers(
    state: GameState, declarer: int, meld: Meld, rob_tile: TileId
) -> tuple[ClaimOffer, ...]:
    ruleset = state.ruleset
    if not ruleset.kong_rob_enabled:
        return ()
    if meld.kind == MeldKind.CONCEALED_KONG and not ruleset.concealed_kong_robbable:
        return ()
    return tuple(
        ClaimOffer(seat=seat, can_win=True)
        for seat in range(4)
        if seat != declarer and _can_win_with(state.seats[seat], rob_tile)
    )


def _apply_self_kong(state: GameState, seat: int, meld: Meld) -> tuple[GameState, list[Event]]:
    seat_state = state.seats[seat]
    if meld.kind == MeldKind.ADDED_KONG:
        old_pung = next(
            m for m in seat_state.melds if m.kind == MeldKind.PUNG and m.tile_type == meld.tile_type
        )
        new_tile = next(t for t in meld.tiles if t not in old_pung.tiles)
        new_concealed = tuple(t for t in seat_state.concealed if t != new_tile)
        new_melds = tuple(m for m in seat_state.melds if m != old_pung) + (meld,)
    else:
        new_tile = meld.tiles[-1]  # any of the 4 -- all equally "the completing tile"
        remaining = list(seat_state.concealed)
        for t in meld.tiles:
            remaining.remove(t)
        new_concealed = tuple(remaining)
        new_melds = (*seat_state.melds, meld)

    seat_state = dataclasses.replace(seat_state, concealed=new_concealed, melds=new_melds)
    state = dataclasses.replace(state, seats=_with_seat(state.seats, seat, seat_state))
    events: list[Event] = [MeldFormed(seat=seat, meld=meld)]

    offers = _kong_rob_offers(state, seat, meld, new_tile)
    if offers:
        window = ClaimWindow(
            window_id=state.next_window_id,
            kind=ClaimKind.KONG_ROB,
            source_seat=seat,
            tile=new_tile,
            offers=offers,
        )
        state = dataclasses.replace(
            state,
            phase=Phase.AWAIT_KONG_ROB,
            claim_window=window,
            next_window_id=state.next_window_id + 1,
        )
        return state, events

    more_state, more_events = _draw_for_turn(state, seat, from_front=False, kong=True)
    return more_state, events + more_events


# --- claim / kong-rob response accumulation and resolution --------------------------------


def _apply_claim_response(
    state: GameState, seat: int, action: ClaimResponse
) -> tuple[GameState, list[Event]]:
    window = state.claim_window
    assert window is not None  # legal_actions() already guarantees this

    responses = {**window.responses, seat: action}
    ready = len(responses) == len(window.offers) or can_close_early(window, responses)
    if not ready:
        new_window = dataclasses.replace(window, responses=responses)
        return dataclasses.replace(state, claim_window=new_window), []

    resolution = resolve_claims(window, responses)
    events: list[Event] = [
        ClaimResolved(
            window_id=window.window_id,
            claim_kind=window.kind,
            winning_seat=resolution.winning_seat,
            action_kind=resolution.action.kind if resolution.action else None,
        )
    ]

    if resolution.winning_seat is None:
        if window.kind == ClaimKind.KONG_ROB:
            more_state, more_events = _draw_for_turn(
                state, window.source_seat, from_front=False, kong=True
            )
        else:
            more_state, more_events = _draw_for_turn(
                state, (window.source_seat + 1) % 4, from_front=True, kong=False
            )
        return more_state, events + more_events

    winner = resolution.winning_seat
    won_action = resolution.action
    assert won_action is not None

    if isinstance(won_action, ClaimWin):
        win_type = WinType.KONG_ROB if window.kind == ClaimKind.KONG_ROB else WinType.DISCARD
        more_state, more_events = _end_hand(
            state, HandOutcome.WIN, winner=winner, win_type=win_type, discarder=window.source_seat
        )
        return more_state, events + more_events

    assert isinstance(won_action, (ClaimChow, ClaimPung, ClaimKong))
    meld = won_action.meld
    winner_state = state.seats[winner]
    remaining = list(winner_state.concealed)
    for t in meld.tiles:
        if t != window.tile:
            remaining.remove(t)
    winner_state = dataclasses.replace(
        winner_state, concealed=tuple(remaining), melds=(*winner_state.melds, meld)
    )

    discarder_state = state.seats[window.source_seat]
    assert discarder_state.discards[-1] == window.tile
    discarder_state = dataclasses.replace(discarder_state, discards=discarder_state.discards[:-1])

    seats = _with_seat(state.seats, winner, winner_state)
    seats = _with_seat(seats, window.source_seat, discarder_state)
    state = dataclasses.replace(state, seats=seats)
    events.append(MeldFormed(seat=winner, meld=meld))

    if isinstance(won_action, ClaimKong):
        more_state, more_events = _draw_for_turn(state, winner, from_front=False, kong=True)
        return more_state, events + more_events

    state = dataclasses.replace(state, turn=winner, phase=Phase.AWAIT_ACTION, claim_window=None)
    return state, events


# --- hand end / next hand / game end -------------------------------------------------------


def _end_hand(
    state: GameState,
    outcome: HandOutcome,
    *,
    winner: int | None,
    win_type: WinType | None,
    discarder: int | None,
) -> tuple[GameState, list[Event]]:
    result = HandResult(outcome=outcome, winner=winner, win_type=win_type, discarder=discarder)
    state = dataclasses.replace(state, phase=Phase.HAND_OVER, claim_window=None, hand_result=result)
    event = HandEnded(
        hand_no=state.hand_no,
        outcome=outcome,
        winner=winner,
        win_type=win_type,
        discarder=discarder,
    )
    return state, [event]


def _hand_to_concealed(hand: tuple[WallTile, ...]) -> tuple[TileId, ...]:
    """Mirrors `state.py`'s private `_as_tile_ids`: narrow a post-flower-replacement hand
    from `WallTile` to `TileId` (`replace_flowers` guarantees no `Flower` survives)."""
    assert not any(isinstance(t, Flower) for t in hand), "flower tile survived replace_flowers"
    return tuple(cast(TileId, t) for t in hand)


def _deal_hand(state: GameState, *, dealer: int, prevailing: Wind, hand_no: int) -> GameState:
    """Deal hand `hand_no` (01-rules-spec.md §3), mirroring `state.new_game` but for hand 2+:
    scores carry over, everything else about a seat (concealed, melds, discards, flowers)
    starts fresh."""
    hand_seed = derive_hand_seed(state.game_seed, hand_no)
    _, wall = new_wall(hand_seed, state.ruleset)
    hands, wall = deal_hands(wall, dealer_seat=dealer)
    hands, wall, flowers = replace_flowers(hands, wall, dealer_seat=dealer)

    seats: Seats = cast(
        Seats,
        tuple(
            SeatState(
                concealed=_hand_to_concealed(hands[i]),
                flowers=flowers[i],
                score=state.seats[i].score,
            )
            for i in range(4)
        ),
    )

    return GameState(
        ruleset=state.ruleset,
        game_seed=state.game_seed,
        hand_seed=hand_seed,
        wall=wall,
        seats=seats,
        phase=Phase.AWAIT_ACTION,
        turn=dealer,
        dealer=dealer,
        prevailing=prevailing,
        hand_no=hand_no,
    )
