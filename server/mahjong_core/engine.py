"""`reduce(state, action) -> (state, events)` -- the turn/claim/hand/game state machine wiring
`config`, `tiles`, `wall`, `melds`, `state`, `actions`, `claims` together.

Pure: no asyncio, no I/O, no clock, no unseeded randomness. Every action is validated against
`actions.legal_actions` before it's applied -- an action the server didn't already offer that
seat is a hard error, never silently ignored.

Two entry points: `reduce()` applies one `Action` and everything that automatically cascades
from it with no further seat decision (flower chains, an empty claim window, a kong
replacement draw, a resolved claim), stopping the moment a real decision is needed or the hand
ends (`Phase.HAND_OVER`). Advancing from `HAND_OVER` to the next hand (or `GAME_OVER`) is
`start_next_hand()` -- there's no `Action` for "deal the next hand" since it isn't a seat's
decision, so it can't go through `reduce()`'s `(state, action)` shape.

Hang-safety: the only loop in this module is the flower-replacement cascade, bounded by the
fixed 8-physical-flower count (`_MAX_FLOWERS`) with an assertion. Hand-to-hand bookkeeping
(`start_next_hand`) is straight-line arithmetic and cannot loop.

`Phase.SCORING` never actually appears in `GameState.phase`: `_finish_win` folds that
zero-duration step directly into the `HAND_OVER` transition rather than returning a state a
caller would need to immediately advance out of again with no action available.

Flower instant-win (`seven_flowers_instant_win`/`eight_flowers_instant_win`) cuts the
flower-replacement cascade short: the moment a seat's flower count first reaches the
configured threshold, the hand ends there as `WinType.FLOWERS` with no meld decomposition,
but still goes through `_finish_win` for payout, scored as a self-draw (no seat fed it).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
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
    _is_thirteen_orphans,
    build_scoring_context,
    hand_is_winning_shape,
    legal_actions,
)
from mahjong_core.claims import ClaimResponse, can_close_early, resolve_claims
from mahjong_core.config import GameLength, RuleSet
from mahjong_core.melds import Meld, MeldKind, legal_claims
from mahjong_core.scoring import payout as payout_mod
from mahjong_core.scoring.faan import score_winning_hand
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
# bump on any change to the reducer, wall order, or flower-replacement ordering. every
# persisted GameRecord stamps this value; a mismatch means the record is not replayable, full
# stop -- there is no migration path.


class IllegalActionError(ValueError):
    """Raised when `reduce()`/`start_next_hand()` is asked to apply something
    `actions.legal_actions` didn't actually offer. A client-supplied action reaching here
    unvalidated is an app/ bug, not a game state to tolerate."""


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
    """A normal front-of-wall draw landed in `seat`'s hand."""

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
    are both `None` when nobody's claim beat a Pass."""

    window_id: int
    claim_kind: ClaimKind
    winning_seat: int | None
    action_kind: ActionKind | None
    kind: Literal[EventKind.CLAIM_RESOLVED] = EventKind.CLAIM_RESOLVED


@dataclass(frozen=True)
class KongReplacementDrawn:
    """A kong (own-turn declare or claimed) drew its replacement from the back of the wall.
    Distinct from `Drawn` so a client/bot can tell 槓上開花 apart from a normal draw."""

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
        seat_state = state.seats[seat]
        return _end_win(
            state,
            winner=seat,
            win_type=WinType.SELF_DRAW,
            discarder=None,
            concealed_tiles=seat_state.concealed,
            melds=seat_state.melds,
        )
    return _apply_claim_response(state, seat, action)


def start_next_hand(state: GameState) -> tuple[GameState, list[Event]]:
    """Roll from `Phase.HAND_OVER` into the next hand's deal, or into `Phase.GAME_OVER`.
    Not an `Action` -- see module docstring for why this can't go through `reduce()`.

    Dealer repeats (連莊) on a dealer win, or on any exhaustive draw if configured; otherwise
    the deal passes to `(dealer + 1) % 4`, and once that wraps back to seat 0 a full round has
    completed -- the prevailing wind advances, or the game ends if `ruleset.game_length` has
    no round left. `hand_no` increments unconditionally either way, so this can never re-deal
    the same hand number twice.
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
    """Extract `GameOutcome` from a finished game. Same fields as `GameEnded`, but callable
    independently of catching that event -- a persistence path saving a `GameRecord` after
    the fact has the final `GameState` on hand, not the event stream that produced it."""
    if state.phase != Phase.GAME_OVER:
        raise IllegalActionError(f"game_outcome requires Phase.GAME_OVER, got {state.phase}")
    return GameOutcome(hand_count=state.hand_no, final_scores=_scores(state))


def _can_win_with(
    state: GameState,
    seat: int,
    tile: TileId,
    *,
    is_robbing_kong: bool,
    discarder: int,
) -> bool:
    """Whether `seat` could legally claim a win on `tile` right now -- structural shape plus
    `min_faan`, mirroring `actions.can_declare_win` for the claimed-win path. `tile` is not
    yet in `seat`'s concealed tiles (a claim, not a landed draw), so the candidate hand
    appends it before scoring.
    """
    seat_state = state.seats[seat]
    candidate = dataclasses.replace(seat_state, concealed=(*seat_state.concealed, tile))
    if not hand_is_winning_shape(candidate):
        return False
    ctx = build_scoring_context(
        state, seat, self_drawn=False, is_robbing_kong=is_robbing_kong, discarder=discarder
    )
    result = score_winning_hand(candidate.concealed, candidate.melds, ctx, state.ruleset)
    return result.clears_min_faan


def _wall_exhausted(state: GameState) -> bool:
    return len(state.wall.tiles) <= state.ruleset.wall_reserve


def _draw_and_cascade(
    state: GameState, seat: int, *, from_front: bool
) -> tuple[GameState, TileId | None, list[Event]]:
    """Draw one tile for `seat`, replacing any flowers drawn from the back until a playable
    tile lands. Checks wall exhaustion before every draw in the cascade, not just the first --
    a flower reveal can itself run the wall down to `wall_reserve` with no replacement left,
    which is an exhaustive draw, not an error. Returns `tile=None` in that case; flowers
    already revealed this cascade stay revealed even though the hand ends before a real tile
    lands.

    Bounded by `_MAX_FLOWERS`: a flower is a unique physical tile that can never reappear once
    revealed, so the cascade provably cannot exceed the 8 that exist -- the `AssertionError`
    below is a can't-happen guard.
    """
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
        instant = _flower_instant_win(state.ruleset, len(seat_state.flowers))
        if instant is not None:
            faan, breakdown = instant
            end_state, end_events = _finish_win(
                state,
                winner=seat,
                win_type=WinType.FLOWERS,
                discarder=None,
                total_faan=faan,
                breakdown=breakdown,
            )
            return end_state, None, events + end_events
        if _wall_exhausted(state):
            return state, None, events
        tile, wall = draw_back(wall)

    state = dataclasses.replace(state, seats=_with_seat(state.seats, seat, seat_state), wall=wall)
    return state, tile, events


def _draw_for_turn(
    state: GameState, seat: int, *, from_front: bool, kong: bool
) -> tuple[GameState, list[Event]]:
    """Land a drawn tile in `seat`'s hand and open `AWAIT_ACTION` for them -- or, if the wall
    runs out before or during the draw, end the hand as an exhaustive draw instead. If a
    flower instant-win fired mid-cascade, `state` is already `Phase.HAND_OVER` and this just
    passes that through."""
    state, tile, events = _draw_and_cascade(state, seat, from_front=from_front)
    if state.phase == Phase.HAND_OVER:
        return state, events
    if tile is None:
        more_state, more_events = _end_exhaustive_draw(state)
        return more_state, events + more_events

    seat_state = state.seats[seat]
    seat_state = dataclasses.replace(seat_state, concealed=(*seat_state.concealed, tile))
    state = dataclasses.replace(
        state,
        seats=_with_seat(state.seats, seat, seat_state),
        turn=seat,
        phase=Phase.AWAIT_ACTION,
        claim_window=None,
        wall_exhausted_at_last_draw=_wall_exhausted(state),
        last_draw_was_kong_replacement=kong,
        self_draw_win_allowed=True,
    )
    draw_event: Event = (
        KongReplacementDrawn(seat=seat, tile_id=tile) if kong else Drawn(seat=seat, tile_id=tile)
    )
    return state, [*events, draw_event]


def _discard_claim_offers(state: GameState, discarder: int, tile: TileId) -> tuple[ClaimOffer, ...]:
    offers: list[ClaimOffer] = []
    for seat in range(4):
        if seat == discarder:
            continue
        seat_state = state.seats[seat]
        melds = legal_claims(seat_state.concealed, tile, discarder, seat)
        can_win = _can_win_with(state, seat, tile, is_robbing_kong=False, discarder=discarder)
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
    state = dataclasses.replace(
        state,
        seats=_with_seat(state.seats, seat, seat_state),
        total_discards=state.total_discards + 1,
    )
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


def _kong_rob_offers(
    state: GameState, declarer: int, meld: Meld, rob_tile: TileId
) -> tuple[ClaimOffer, ...]:
    """Robbing an added kong (加槓) is open to any qualifying win; robbing a concealed kong is
    further restricted to a seat whose win would specifically complete Thirteen Orphans
    (十三么) -- real HK convention only carves out that one narrow exception, not "any winning
    hand" once `concealed_kong_robbable` is on.
    """
    ruleset = state.ruleset
    if not ruleset.kong_rob_enabled:
        return ()
    if meld.kind == MeldKind.CONCEALED_KONG and not ruleset.concealed_kong_robbable:
        return ()
    offers = []
    for seat in range(4):
        if seat == declarer:
            continue
        if meld.kind == MeldKind.CONCEALED_KONG:
            candidate = (*state.seats[seat].concealed, rob_tile)
            if not _is_thirteen_orphans(candidate):
                continue
        if _can_win_with(state, seat, rob_tile, is_robbing_kong=True, discarder=declarer):
            offers.append(ClaimOffer(seat=seat, can_win=True))
    return tuple(offers)


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
        winner_state = state.seats[winner]
        # fold the claimed tile into the winner's concealed hand before scoring, not just into
        # the tuple passed below -- state.seats[winner].concealed feeds HandEndWire.winning_hand.
        concealed_tiles = (*winner_state.concealed, window.tile)
        winner_state = dataclasses.replace(winner_state, concealed=concealed_tiles)
        seats = _with_seat(state.seats, winner, winner_state)

        # the claimed tile leaves wherever it came from, or it's double-counted. a discard win
        # pops it off the discarder's pool; a kong-rob win takes it back out of the declarer's
        # kong meld -- an added kong (加槓) reverts to the pung it upgraded from, a concealed
        # kong (暗槓) returns its other 3 tiles to the declarer's concealed hand.
        source_state = state.seats[window.source_seat]
        if window.kind == ClaimKind.KONG_ROB:
            kong_meld = next(m for m in source_state.melds if window.tile in m.tiles)
            remaining_tiles = tuple(t for t in kong_meld.tiles if t != window.tile)
            if kong_meld.kind == MeldKind.ADDED_KONG:
                reverted = Meld(MeldKind.PUNG, remaining_tiles, from_seat=kong_meld.from_seat)
                source_melds = tuple(m for m in source_state.melds if m != kong_meld) + (reverted,)
                source_state = dataclasses.replace(source_state, melds=source_melds)
            else:
                assert kong_meld.kind == MeldKind.CONCEALED_KONG
                source_melds = tuple(m for m in source_state.melds if m != kong_meld)
                source_state = dataclasses.replace(
                    source_state,
                    melds=source_melds,
                    concealed=(*source_state.concealed, *remaining_tiles),
                )
        else:
            assert source_state.discards[-1] == window.tile
            source_state = dataclasses.replace(source_state, discards=source_state.discards[:-1])
        seats = _with_seat(seats, window.source_seat, source_state)

        state = dataclasses.replace(state, seats=seats)
        more_state, more_events = _end_win(
            state,
            winner=winner,
            win_type=win_type,
            discarder=window.source_seat,
            concealed_tiles=concealed_tiles,
            melds=winner_state.melds,
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

    state = dataclasses.replace(
        state,
        turn=winner,
        phase=Phase.AWAIT_ACTION,
        claim_window=None,
        self_draw_win_allowed=False,
    )
    return state, events


def _end_exhaustive_draw(state: GameState) -> tuple[GameState, list[Event]]:
    result = HandResult(outcome=HandOutcome.EXHAUSTIVE_DRAW)
    state = dataclasses.replace(state, phase=Phase.HAND_OVER, claim_window=None, hand_result=result)
    event = HandEnded(
        hand_no=state.hand_no,
        outcome=HandOutcome.EXHAUSTIVE_DRAW,
        winner=None,
        win_type=None,
        discarder=None,
    )
    return state, [event]


_SEVEN_FLOWERS_NAME = "七花"
_EIGHT_FLOWERS_NAME = "八花"
_SEVEN_FLOWERS_FAAN = 3  # seven_flowers_instant_win is a flat 3 faan
_SEVEN_FLOWERS_THRESHOLD = 7
_EIGHT_FLOWERS_THRESHOLD = 8


def _flower_instant_win(ruleset: RuleSet, flower_count: int) -> tuple[int, dict[str, int]] | None:
    """`(faan, breakdown)` if `flower_count` just crossed a configured instant-win threshold,
    else `None`. Eight checked before seven so a table with both enabled resolves to the
    higher tier if a single reveal somehow satisfied both."""
    if ruleset.eight_flowers_instant_win and flower_count >= _EIGHT_FLOWERS_THRESHOLD:
        return ruleset.faan_cap, {_EIGHT_FLOWERS_NAME: ruleset.faan_cap}
    if ruleset.seven_flowers_instant_win and flower_count >= _SEVEN_FLOWERS_THRESHOLD:
        return _SEVEN_FLOWERS_FAAN, {_SEVEN_FLOWERS_NAME: _SEVEN_FLOWERS_FAAN}
    return None


def _apply_payments(state: GameState, payments: Mapping[int, int]) -> GameState:
    seats = list(state.seats)
    for seat, delta in payments.items():
        seats[seat] = dataclasses.replace(seats[seat], score=seats[seat].score + delta)
    return dataclasses.replace(state, seats=cast(Seats, tuple(seats)))


def _finish_win(
    state: GameState,
    *,
    winner: int,
    win_type: WinType,
    discarder: int | None,
    total_faan: int,
    breakdown: Mapping[str, int],
) -> tuple[GameState, list[Event]]:
    """Common tail for every win path (normal or flower instant-win): faan -> points ->
    per-seat payments (`scoring.payout`), applied to `state.seats`, then the `HAND_OVER`
    transition. `WinType.FLOWERS` pays like a self-draw -- no seat fed an instant win."""
    pts = payout_mod.points(total_faan, state.ruleset)
    pay_type: payout_mod.WinType
    if win_type in (WinType.SELF_DRAW, WinType.FLOWERS):
        pay_type = payout_mod.SelfDraw()
    else:
        assert discarder is not None
        pay_type = payout_mod.Discard(discarder_seat=discarder)
    payments = payout_mod.payout(winner, pts, pay_type, state.dealer, state.ruleset)

    state = _apply_payments(state, payments)
    result = HandResult(
        outcome=HandOutcome.WIN,
        winner=winner,
        win_type=win_type,
        discarder=discarder,
        faan=total_faan,
        faan_breakdown=dict(breakdown),
        points=pts,
        payments=payments,
    )
    state = dataclasses.replace(state, phase=Phase.HAND_OVER, claim_window=None, hand_result=result)
    event = HandEnded(
        hand_no=state.hand_no,
        outcome=HandOutcome.WIN,
        winner=winner,
        win_type=win_type,
        discarder=discarder,
    )
    return state, [event]


def _end_win(
    state: GameState,
    *,
    winner: int,
    win_type: WinType,
    discarder: int | None,
    concealed_tiles: tuple[TileId, ...],
    melds: tuple[Meld, ...],
) -> tuple[GameState, list[Event]]:
    """Score a normal (non-instant-win) win -- `concealed_tiles`/`melds` are the winner's hand
    at the moment of the win, including the winning tile. Passed explicitly rather than read
    back off `state` because the self-draw call site never mutates `state` at all."""
    ctx = build_scoring_context(
        state,
        winner,
        self_drawn=win_type == WinType.SELF_DRAW,
        is_robbing_kong=win_type == WinType.KONG_ROB,
        discarder=discarder,
    )
    result = score_winning_hand(concealed_tiles, melds, ctx, state.ruleset)
    return _finish_win(
        state,
        winner=winner,
        win_type=win_type,
        discarder=discarder,
        total_faan=result.total_faan,
        breakdown=result.breakdown,
    )


def _hand_to_concealed(hand: tuple[WallTile, ...]) -> tuple[TileId, ...]:
    """Mirrors `state.py`'s private `_as_tile_ids`: narrow a post-flower-replacement hand
    from `WallTile` to `TileId` (`replace_flowers` guarantees no `Flower` survives)."""
    assert not any(isinstance(t, Flower) for t in hand), "flower tile survived replace_flowers"
    return tuple(cast(TileId, t) for t in hand)


def _deal_hand(state: GameState, *, dealer: int, prevailing: Wind, hand_no: int) -> GameState:
    """Deal hand `hand_no`, mirroring `state.new_game` but for hand 2+: scores and
    `next_window_id` carry over, everything else about a seat starts fresh. `next_window_id`
    must survive the hand boundary since `window_id` is a whole-game identifier, not per-hand
    -- resetting it to 0 caused hand 2's first claim window to collide with hand 1's and
    silently starve it of a claim offer."""
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
        next_window_id=state.next_window_id,
    )
