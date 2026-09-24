"""Fixed action-id space, `legal_mask`, and the id<->`Action` codec.

No numpy: `legal_mask` returns a plain `list[bool]`.
"""

from __future__ import annotations

from mahjong_core.actions import (
    Action,
    ClaimChow,
    ClaimKong,
    ClaimPung,
    ClaimWin,
    DeclareAddedKong,
    DeclareConcealedKong,
    DeclareWin,
    Discard,
    Pass,
    legal_actions,
)
from mahjong_core.melds import Meld, MeldKind, legal_self_melds
from mahjong_core.state import ClaimOffer, ClaimWindow, GameState, Phase
from mahjong_core.tiles import TileType, tile_id_type

N_ACTIONS = 109

_DISCARD_BASE = 0
_CONCEALED_KONG_BASE = 34
_ADDED_KONG_BASE = 68
_PASS = 102
_CHOW_LOW = 103
_CHOW_MIDDLE = 104
_CHOW_HIGH = 105
_PUNG = 106
_KONG = 107
_WIN = 108


def action_id(action: Action, state: GameState) -> int:
    """The fixed id for `action`, given the `state` it was legal in. `state` is only read for
    `ClaimChow` -- every other variant is self-describing."""
    if isinstance(action, Discard):
        return _DISCARD_BASE + int(tile_id_type(action.tile_id))
    if isinstance(action, DeclareConcealedKong):
        return _CONCEALED_KONG_BASE + int(action.meld.tile_type)
    if isinstance(action, DeclareAddedKong):
        return _ADDED_KONG_BASE + int(action.meld.tile_type)
    if isinstance(action, Pass):
        return _PASS
    if isinstance(action, ClaimChow):
        return _CHOW_LOW + _chow_offset(action.meld, state)
    if isinstance(action, ClaimPung):
        return _PUNG
    if isinstance(action, ClaimKong):
        return _KONG
    if isinstance(action, (ClaimWin, DeclareWin)):
        return _WIN
    raise AssertionError(f"unhandled action type: {action!r}")


def _chow_offset(meld: Meld, state: GameState) -> int:
    """0/1/2 for low/middle/high -- the claimed discard's rank within the chow's type run,
    relative to `meld.tile_type` (its lowest type, per `Meld.tile_type`'s docstring)."""
    window = state.claim_window
    if window is None:
        raise ValueError("ClaimChow needs a live claim window to determine low/middle/high")
    offset = int(tile_id_type(window.tile)) - int(meld.tile_type)
    if offset not in (0, 1, 2):
        raise ValueError(f"claimed tile isn't part of chow meld {meld!r}: offset {offset}")
    return offset


def decode_action(aid: int, state: GameState, seat: int) -> Action:
    """The inverse of `action_id`: reconstruct a concrete, legal `Action` for `seat` from a
    fixed id, given the current `state`. Raises `ValueError` if `aid` isn't actually legal for
    `seat` right now -- there's no meaningful `Action` to decode it to."""
    if not 0 <= aid < N_ACTIONS:
        raise ValueError(f"action id out of range 0..{N_ACTIONS - 1}: {aid}")

    if _DISCARD_BASE <= aid < _CONCEALED_KONG_BASE:
        return _decode_discard(aid - _DISCARD_BASE, state, seat)
    if _CONCEALED_KONG_BASE <= aid < _ADDED_KONG_BASE:
        meld = _self_kong_meld(aid - _CONCEALED_KONG_BASE, state, seat, MeldKind.CONCEALED_KONG)
        return DeclareConcealedKong(meld=meld)
    if _ADDED_KONG_BASE <= aid < _PASS:
        meld = _self_kong_meld(aid - _ADDED_KONG_BASE, state, seat, MeldKind.ADDED_KONG)
        return DeclareAddedKong(meld=meld)
    if aid == _PASS:
        return Pass(window_id=_require_window(state).window_id, seat=seat)
    if aid in (_CHOW_LOW, _CHOW_MIDDLE, _CHOW_HIGH):
        return _decode_chow(aid - _CHOW_LOW, state, seat)
    if aid == _PUNG:
        return ClaimPung(
            window_id=_require_window(state).window_id,
            seat=seat,
            meld=_offer_meld(state, seat, MeldKind.PUNG),
        )
    if aid == _KONG:
        return ClaimKong(
            window_id=_require_window(state).window_id,
            seat=seat,
            meld=_offer_meld(state, seat, MeldKind.EXPOSED_KONG),
        )
    if aid == _WIN:
        return _decode_win(state, seat)
    raise AssertionError(f"unhandled action id: {aid}")


def _require_window(state: GameState) -> ClaimWindow:
    if state.claim_window is None:
        raise ValueError("no live claim window to decode against")
    return state.claim_window


def _require_offer(state: GameState, seat: int) -> ClaimOffer:
    window = _require_window(state)
    offer = next((o for o in window.offers if o.seat == seat), None)
    if offer is None:
        raise ValueError(f"seat {seat} has no claim offer in the live window")
    return offer


def _offer_meld(state: GameState, seat: int, kind: MeldKind) -> Meld:
    offer = _require_offer(state, seat)
    meld = next((m for m in offer.melds if m.kind == kind), None)
    if meld is None:
        raise ValueError(f"seat {seat}'s claim offer has no {kind} option")
    return meld


def _decode_discard(tile_type_value: int, state: GameState, seat: int) -> Discard:
    tile_type = TileType(tile_type_value)
    concealed = state.seats[seat].concealed
    candidates = sorted(t for t in concealed if tile_id_type(t) == tile_type)
    if not candidates:
        raise ValueError(f"seat {seat} holds no {tile_type.name} to discard")
    return Discard(tile_id=candidates[0])


def _self_kong_meld(tile_type_value: int, state: GameState, seat: int, kind: MeldKind) -> Meld:
    tile_type = TileType(tile_type_value)
    seat_state = state.seats[seat]
    meld = next(
        (
            m
            for m in legal_self_melds(seat_state.concealed, seat_state.melds)
            if m.kind == kind and m.tile_type == tile_type
        ),
        None,
    )
    if meld is None:
        raise ValueError(f"seat {seat} has no {kind} option for {tile_type.name}")
    return meld


def _decode_chow(offset: int, state: GameState, seat: int) -> ClaimChow:
    window = _require_window(state)
    offer = _require_offer(state, seat)
    claimed_type = tile_id_type(window.tile)
    meld = next(
        (
            m
            for m in offer.melds
            if m.kind == MeldKind.CHOW and int(claimed_type) - int(m.tile_type) == offset
        ),
        None,
    )
    if meld is None:
        raise ValueError(f"seat {seat} has no chow option at offset {offset}")
    return ClaimChow(window_id=window.window_id, seat=seat, meld=meld)


def _decode_win(state: GameState, seat: int) -> Action:
    if state.phase == Phase.AWAIT_ACTION and state.turn == seat:
        return DeclareWin()
    if state.phase in (Phase.AWAIT_CLAIMS, Phase.AWAIT_KONG_ROB):
        return ClaimWin(window_id=_require_window(state).window_id, seat=seat)
    raise ValueError(f"no win decodable for seat {seat} in phase {state.phase}")


def legal_mask(state: GameState, seat: int) -> list[bool]:
    """Length-`N_ACTIONS` mask: `True` at every id some currently-legal action for `seat`
    encodes to. Built straight from `actions.legal_actions` -- never invents legality the
    engine wouldn't offer."""
    mask = [False] * N_ACTIONS
    for action in legal_actions(state, seat):
        mask[action_id(action, state)] = True
    return mask
