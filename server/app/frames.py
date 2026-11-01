"""Outbound frame payloads, one recipient at a time (docs/architecture.md §5).

Pure: `(state, recipient, event…)` in, a flat wire dict (`t` plus the payload fields, what
`Table.publish_to_seat` takes) out. Built on `seat_view`/`redact_event`, which stay the only
paths to seat-visible state. No clock, socket, seq or timer: whatever only the caller knows
(a deadline it armed, a fairness nonce, seat bindings, hand history) comes in as an argument,
so `Table` and an offline caller (learn-mode tutorials, ADR 0025) build the same bytes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.views import (
    CLAIM_KIND_WIRE,
    HandHistoryRecord,
    hand_history_wire,
    redact_event,
    seat_view,
    seat_view_wire,
)
from mahjong_core.actions import action_to_dict, legal_actions
from mahjong_core.events import Discarded, Event, HandEnded
from mahjong_core.presets import preset_id_for
from mahjong_core.state import ClaimOffer, ClaimWindow, GameState, Phase
from mahjong_core.tiles import TileId, tile_code, tile_id_type

__all__ = [
    "claim_offer_frame",
    "claim_options_wire",
    "deal_frame",
    "event_frame",
    "hand_start_frame",
    "score_frame",
    "state_sync_frame",
    "to_envelope",
    "turn_frame",
]


def turn_frame(
    state: GameState, recipient: int | None, *, deadline_ts: int
) -> dict[str, Any] | None:
    """`None` outside `AWAIT_ACTION`. `legal` only for the acting seat: it names that seat's own
    concealed tile ids, so spectators and every other seat get the public half."""
    if state.phase != Phase.AWAIT_ACTION:
        return None
    seat = state.turn
    wire: dict[str, Any] = {
        "t": "turn",
        "seat": seat,
        "phase": state.phase.value,
        "deadline_ts": deadline_ts,
    }
    if recipient == seat:
        wire["legal"] = [action_to_dict(a) for a in legal_actions(state, seat)]
    return wire


def claim_options_wire(offer: ClaimOffer, claimed: TileId) -> list[dict[str, Any]]:
    """`tiles` names only the claimer's own tiles, excluding the claimed discard -- echoing
    the full meld here made every disambiguated claim fail `_pick_claim_meld` as
    `illegal`."""
    options: list[dict[str, Any]] = []
    if offer.can_win:
        options.append({"kind": "win"})
    for meld in offer.melds:
        own = [t for t in meld.tiles if t != claimed]
        options.append({"kind": CLAIM_KIND_WIRE[meld.kind], "tiles": own})
    options.append({"kind": "pass"})
    return options


def _claim_offer_payload(
    window: ClaimWindow, offers: Sequence[ClaimOffer], seat: int, deadline_ts: int
) -> dict[str, Any] | None:
    """`claim_offer`'s payload, shared with `state_sync.claim_offer`. `None` once `seat` has
    answered: a second answer is dropped, so there is nothing left to offer."""
    offer = next((o for o in offers if o.seat == seat), None)
    if offer is None or seat in window.responses:
        return None
    return {
        "window_id": window.window_id,
        "options": claim_options_wire(offer, window.tile),
        "deadline_ts": deadline_ts,
    }


def claim_offer_frame(state: GameState, seat: int, *, deadline_ts: int) -> dict[str, Any] | None:
    """`None` when `seat` holds no unanswered offer in the live window. Unicast: only an
    offered seat ever gets one."""
    window = state.claim_window
    if window is None:
        return None
    payload = _claim_offer_payload(window, window.offers, seat, deadline_ts)
    return None if payload is None else {"t": "claim_offer", **payload}


def hand_start_frame(
    state: GameState, *, seats: Sequence[str], seed_commit: str | None = None
) -> dict[str, Any]:
    """`seats` is each seat's wire status; `seed_commit` only on `provable_fairness` tables."""
    wire: dict[str, Any] = {
        "t": "hand_start",
        "hand_no": state.hand_no,
        "prevailing": state.prevailing.name,
        "dealer": state.dealer,
        "seats": list(seats),
    }
    if seed_commit is not None:
        wire["seed_commit"] = seed_commit
    return wire


def deal_frame(state: GameState, seat: int) -> dict[str, Any]:
    return {
        "t": "deal",
        "your_hand": list(state.seats[seat].concealed),
        "counts": {s: len(state.seats[s].concealed) for s in range(4)},
        "flowers": [[tile_code(f) for f in s.flowers] for s in state.seats],
        "wall_remaining": len(state.wall.tiles),
    }


def event_frame(
    state: GameState,
    recipient: int | None,
    event: Event,
    *,
    reveal_hands: bool = False,
    hand_end_deadline_ts: int | None = None,
    fairness: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """`redact_event` plus what it can't derive in general: `discard.tile`/`pool_index`,
    read off `state` straight after the `reduce()` that discarded (a later claim takes the
    tile out of the pool), and `hand_end`'s deadline and fairness reveal, which the caller
    owns."""
    wire = redact_event(state, recipient, event, reveal_hands=reveal_hands)
    if isinstance(event, Discarded):
        pool = state.seats[event.seat].discards
        wire["tile"] = tile_code(tile_id_type(event.tile_id))
        wire["pool_index"] = len(pool) - 1
    if isinstance(event, HandEnded):
        wire["deadline_ts"] = hand_end_deadline_ts
        if fairness is not None:
            wire["fairness"] = dict(fairness)
    return wire


def score_frame(state: GameState) -> dict[str, Any]:
    """Absolute totals, sent beside every `hand_end`."""
    return {"t": "score", "totals": {s: state.seats[s].score for s in range(4)}}


def state_sync_frame(
    state: GameState,
    seat: int | None,
    *,
    seat_status: tuple[str, str, str, str] | None = None,
    names: tuple[str | None, str | None, str | None, str | None] | None = None,
    claim_deadline_ts: int | None = None,
    turn_deadline_ts: int | None = None,
    hand_end_deadline_ts: int | None = None,
    host_seat: int | None = None,
    reveal_hands: bool = False,
    hand_history: Sequence[HandHistoryRecord] = (),
    bot_levels: Sequence[str | None] | None = None,
    seed_commit: str | None = None,
) -> dict[str, Any]:
    """`seat_view_wire(seat_view(...))` plus the table-level fields and `claim_offer`, built
    from the view's own offer by `claim_offer_frame`'s builder, so a client resumes the
    window from this frame alone. Every keyword is `seat_view`'s or the caller's own state;
    omitted, they read as a table with nobody bound and no clock."""
    view = seat_view(
        state,
        seat,
        seat_status=seat_status,
        names=names,
        claim_deadline_ts=claim_deadline_ts,
        turn_deadline_ts=turn_deadline_ts,
        hand_end_deadline_ts=hand_end_deadline_ts,
        host_seat=host_seat,
        reveal_hands=reveal_hands,
    )
    wire = seat_view_wire(view)
    wire["t"] = "state_sync"
    window = state.claim_window
    wire["claim_offer"] = (
        _claim_offer_payload(
            window,
            view.claim_options,
            seat,
            # no clock: 0, as an offline caller's claim_offer frames carry
            view.deadline_ts if view.deadline_ts is not None else 0,
        )
        if window is not None and seat is not None
        else None
    )
    wire["hand_history"] = hand_history_wire(hand_history)
    wire["ruleset_preset"] = preset_id_for(state.ruleset)
    wire["ruleset"] = state.ruleset.to_dict()
    wire["bot_levels"] = list(bot_levels) if bot_levels is not None else [None] * len(state.seats)
    if seed_commit is not None:
        wire["seed_commit"] = seed_commit
    return wire


def to_envelope(wire: Mapping[str, Any], *, seq: int, ts: int) -> dict[str, Any]:
    """A flat wire dict as the frame a client receives (docs/protocol.md §1)."""
    d = {k: v for k, v in wire.items() if k != "t"}
    return {"v": 1, "t": wire["t"], "seq": seq, "ts": ts, "d": d}
