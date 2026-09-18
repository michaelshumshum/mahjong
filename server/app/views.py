"""`seat_view()` + `redact_event()` -- the redaction layer (docs/00-architecture.md §5,
docs/02-protocol.md §3, docs/05-roadmap.md §1).

Lives in `app/`, not `mahjong_core/`: this module answers "what may seat X see right now",
which is about a specific wire recipient, not a game rule (server/AGENTS.md: `mahjong_core`
stays pure; a clock, socket, or *redaction* concern belongs in `app/`). `mahjong_core` never
redacts -- see melds.py's `Meld.tiles` docstring.

Two entry points (00-architecture.md §5, D5):
    seat_view(state, seat) -> SeatView       full per-recipient snapshot
    redact_event(state, seat, event) -> dict  per-event wire redaction

Both are built the same way: a small, explicitly `Entitlement`-annotated dataclass is
constructed first (never a bare dict), then converted to a wire dict. The annotated instance
is also what `tests/test_redaction.py`'s schema walker inspects directly (`_build_event_wire`,
`seat_view` itself) -- so the walker checks the exact structure that ships, not a
reimplementation of the same redaction logic that could drift from it or share its bugs.

**Reconciled against current `mahjong_core` shape** (00-architecture.md §5's own field list
predates several fields added since M1/M2):

- `legal_actions`/`claim_options` reuse `mahjong_core.actions.Action` / `mahjong_core.state.
  ClaimOffer` directly rather than inventing separate `LegalAction`/`ClaimOption` wire types --
  neither module defines those names anywhere, and both real types already carry only this
  seat's own tiles or already-public tiles (verified field by field below), so a parallel type
  would add a translation step with no redaction benefit.
- `legal_actions` is populated whenever `actions.legal_actions(state, seat)` is non-empty --
  covers both "seat's own `AWAIT_ACTION` turn" *and* "seat has a live claim/kong-rob offer",
  not just the `seat == turn` case the architecture doc's prose literally says. The doc undersold
  the claim-window case; the field itself was always meant to cover it (`04-bots.md`'s bot
  `act()` needs actions during a claim window too).
- `seat_status`'s wire vocabulary is connected/disconnected/autoplay/bot/empty.
  `mahjong_core/state.py` deliberately excludes all of it from `SeatState` (see that module's own
  docstring): `app/room.py`'s `SeatBinding`/`Room._seat_status_tuple()` own it instead, without a
  pure-engine round-trip. `seat_view()` itself just takes an optional `seat_status` override and
  defaults to `("connected",) * 4` when the caller has nothing real to pass -- correct for a
  caller with no `Room` behind it at all (bots/arena.py, bots/selfplay.py, tests calling
  `seat_view()` directly), where every seat is a live simulated player, never a lobby seat that
  may genuinely be unjoined. Only `Room._seat_status_tuple()` ever produces `empty`, for a seat
  nobody has joined yet; `bot` remains unused (`SeatBinding.status`'s docstring).
- `deadline_ts` sources from whichever of `app/room.py`'s `TimerHeap`-armed deadlines applies to
  this seat right now (`00-architecture.md §3` D17, `§8` "Turn timeout"): a live claim/kong-rob
  offer (`claim_deadline_ts`), or this seat's own armed `AWAIT_ACTION` turn deadline
  (`turn_deadline_ts`, the turn-timeout sub-task). `GameState` itself never carries either --
  `ClaimWindow.deadline_ts` is just an opaque pass-through (`state.py`'s own docstring: "the pure
  engine never reads a clock") -- so both are override points a caller with a real `Room` behind
  it supplies; a bare `seat_view()` call with neither gets `None` for a seat with no live claim
  offer, matching every pre-Room-integration caller.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from enum import Enum
from typing import Any, Literal, cast

from mahjong_core.actions import Action, action_to_dict
from mahjong_core.actions import legal_actions as compute_legal_actions
from mahjong_core.engine import (
    ClaimResolved,
    Discarded,
    Drawn,
    Event,
    FlowerReplaced,
    GameEnded,
    HandEnded,
    KongReplacementDrawn,
    MeldFormed,
)
from mahjong_core.melds import Meld, MeldKind
from mahjong_core.state import ClaimOffer, GameState, HandOutcome, Phase, Wind
from mahjong_core.tiles import Flower, TileId, tile_code

__all__ = [
    "ClaimResolvedWire",
    "ConcealedKongWire",
    "DiscardWire",
    "DrawWire",
    "Entitlement",
    "FlowerReplaceWire",
    "GameEndWire",
    "HandEndWire",
    "KongReplaceWire",
    "MeldWire",
    "SeatView",
    "redact_event",
    "seat_view",
    "seat_view_wire",
]


class Entitlement(Enum):
    """Per-field annotation the schema walker checks structurally (00-architecture.md §5).
    Not a docstring promise: every restricted field below carries one of these in its
    `dataclasses.field(metadata=...)`, and `tests/test_redaction.py` reads that metadata off
    the actual produced instance -- it cannot be satisfied by a field that merely happens to
    contain a plausible-looking integer (00-architecture.md §5's `"tile_id": 5` vs
    `"pool_index": 5` note)."""

    PUBLIC = "public"
    OWN_SEAT = "own_seat"
    COUNT_ONLY = "count_only"
    HAND_END = "hand_end"


def _entitled(entitlement: Entitlement) -> dict[str, Any]:
    return {"entitlement": entitlement}


# --- SeatView ----------------------------------------------------------------------------


_SeatStatus = tuple[str, str, str, str]
_DEFAULT_SEAT_STATUS: _SeatStatus = ("connected", "connected", "connected", "connected")


@dataclass(frozen=True)
class SeatView:
    """Full redacted snapshot for one recipient (00-architecture.md §5, canonical --
    depended on by 04-bots.md/06-ml.md, neither may change this shape unilaterally).
    `seat=None` is the spectator view.

    Entitlement owner for every `OWN_SEAT` field here is this instance's own `seat` --
    `seat_view(state, X)` only ever builds "X's view", so that's trivially satisfied by
    construction; what the schema walker actually exercises is whether the *content* of
    `legal_actions`/`claim_options` ever names a tile id outside {X's own concealed tiles,
    already-public tiles} -- see `tests/test_redaction.py`.
    """

    seat: int | None = field(metadata=_entitled(Entitlement.PUBLIC))
    hand_no: int = field(metadata=_entitled(Entitlement.PUBLIC))
    prevailing: Wind = field(metadata=_entitled(Entitlement.PUBLIC))
    dealer: int = field(metadata=_entitled(Entitlement.PUBLIC))
    turn: int = field(metadata=_entitled(Entitlement.PUBLIC))
    phase: Phase = field(metadata=_entitled(Entitlement.PUBLIC))
    own_hand: tuple[TileId, ...] = field(metadata=_entitled(Entitlement.OWN_SEAT))
    concealed_counts: tuple[int, int, int, int] = field(metadata=_entitled(Entitlement.COUNT_ONLY))
    melds: tuple[tuple[Meld, ...], ...] = field(metadata=_entitled(Entitlement.PUBLIC))
    discard_pools: tuple[tuple[TileId, ...], ...] = field(metadata=_entitled(Entitlement.PUBLIC))
    flowers: tuple[tuple[Flower, ...], ...] = field(metadata=_entitled(Entitlement.PUBLIC))
    wall_remaining: int = field(metadata=_entitled(Entitlement.COUNT_ONLY))
    seat_status: _SeatStatus = field(metadata=_entitled(Entitlement.PUBLIC))
    scores: tuple[int, int, int, int] = field(metadata=_entitled(Entitlement.PUBLIC))
    legal_actions: tuple[Action, ...] = field(metadata=_entitled(Entitlement.OWN_SEAT))
    claim_options: tuple[ClaimOffer, ...] = field(metadata=_entitled(Entitlement.OWN_SEAT))
    deadline_ts: int | None = field(metadata=_entitled(Entitlement.OWN_SEAT))


def seat_view(
    state: GameState,
    seat: int | None,
    *,
    seat_status: _SeatStatus | None = None,
    claim_deadline_ts: int | None = None,
    turn_deadline_ts: int | None = None,
) -> SeatView:
    """Build `seat`'s full redacted snapshot (`seat=None` -> spectator). `seat_status` is an
    override point for the future `app/room.py` `SeatBinding` (see module docstring); omit it
    and every seat reads as `"connected"`. `claim_deadline_ts` is the same kind of override for
    `deadline_ts` while this seat holds a live claim/kong-rob offer: `ClaimWindow.deadline_ts`
    is never set by the pure engine (state.py's own docstring -- "arming and enforcing the
    actual timer is app/room.py's job"), so `app/room.py` passes its own `TimerHeap`-derived,
    epoch-converted deadline here once a window is armed; omit it (as every caller before the
    Room/Session integration sub-task did) and this falls back to the always-`None`
    `window.deadline_ts`. `turn_deadline_ts` is the analogous override for this seat's own
    `AWAIT_ACTION` decision (00-architecture.md §8 "Turn timeout") -- surfaced only when
    `seat == state.turn` and `state.phase == Phase.AWAIT_ACTION`, mutually exclusive with the
    claim-window branch below (`GameState.__post_init__`: `claim_window` is never set in
    `AWAIT_ACTION`), so there's never ambiguity about which deadline `SeatView.deadline_ts`
    means for a given seat/phase.
    """
    own_hand = state.seats[seat].concealed if seat is not None else ()
    legal = compute_legal_actions(state, seat) if seat is not None else ()

    claim_options: tuple[ClaimOffer, ...] = ()
    deadline_ts: int | None = None
    window = state.claim_window
    if seat is not None and window is not None:
        offer = next((o for o in window.offers if o.seat == seat), None)
        if offer is not None:
            claim_options = (offer,)
            deadline_ts = claim_deadline_ts if claim_deadline_ts is not None else window.deadline_ts
    elif seat is not None and state.phase == Phase.AWAIT_ACTION and state.turn == seat:
        deadline_ts = turn_deadline_ts

    return SeatView(
        seat=seat,
        hand_no=state.hand_no,
        prevailing=state.prevailing,
        dealer=state.dealer,
        turn=state.turn,
        phase=state.phase,
        own_hand=own_hand,
        concealed_counts=cast(
            "tuple[int, int, int, int]", tuple(len(s.concealed) for s in state.seats)
        ),
        melds=tuple(s.melds for s in state.seats),
        discard_pools=tuple(s.discards for s in state.seats),
        flowers=tuple(s.flowers for s in state.seats),
        wall_remaining=len(state.wall.tiles),
        seat_status=seat_status if seat_status is not None else _DEFAULT_SEAT_STATUS,
        scores=cast("tuple[int, int, int, int]", tuple(s.score for s in state.seats)),
        legal_actions=legal,
        claim_options=claim_options,
        deadline_ts=deadline_ts,
    )


# --- per-event wire forms ------------------------------------------------------------------
#
# One frozen dataclass per distinct wire *shape* -- concealed_kong gets two (owner vs. everyone
# else), matching 02-protocol.md §3's "meld has two per-seat wire forms" rather than one struct
# trying to serve both with a runtime-conditional entitlement on the same field.
#
# `seat` on each of these (where present) is both "whose event this is" and the `OWN_SEAT`
# owner for that struct's restricted field(s) -- one convention, no separate owner callable
# needed (see Entitlement's docstring).
#
# Deliberately NOT modeled here (left to the future Session/WS-integration sub-task, which
# controls exactly when `redact_event` runs relative to each event):
#   - discard.pool_index -- 02-protocol.md §3 sketches it, but it isn't derivable from `state`
#     in general: if the discard is claimed later in the *same* `reduce()` call, the claiming
#     seat's discards tuple has the entry removed again by the time `state` reaches here (see
#     `engine._apply_claim_response`), so recomputing it from final state would be wrong for
#     exactly the discards that most need a correct wire form. The Room actor sees each event
#     against its own intermediate state and can compute it there; `redact_event` cannot.
#   - flower_replace fusing a replacement tile into the same frame (02-protocol.md §3's sketch
#     shows one `{seat, flower, replacement?}` message) -- the engine emits `FlowerReplaced`
#     and the landing `Drawn`/`KongReplacementDrawn`/`HandEnded` as separate `Event`s, and this
#     module redacts one `Event` at a time, 1:1, per its own contract.
#   - envelope fields (`v`, `seq`, `ts`) -- Session's job, not the payload's.


@dataclass(frozen=True)
class DrawWire:
    t: Literal["draw"] = field(metadata=_entitled(Entitlement.PUBLIC))
    seat: int = field(metadata=_entitled(Entitlement.PUBLIC))
    tile_id: int | None = field(metadata=_entitled(Entitlement.OWN_SEAT))


@dataclass(frozen=True)
class FlowerReplaceWire:
    t: Literal["flower_replace"] = field(metadata=_entitled(Entitlement.PUBLIC))
    seat: int = field(metadata=_entitled(Entitlement.PUBLIC))
    flower: str = field(metadata=_entitled(Entitlement.PUBLIC))


@dataclass(frozen=True)
class DiscardWire:
    t: Literal["discard"] = field(metadata=_entitled(Entitlement.PUBLIC))
    seat: int = field(metadata=_entitled(Entitlement.PUBLIC))
    tile_id: int = field(metadata=_entitled(Entitlement.PUBLIC))


@dataclass(frozen=True)
class MeldWire:
    """Every meld kind except concealed_kong -- fully public, full tiles to everyone
    (02-protocol.md §3)."""

    t: Literal["meld"] = field(metadata=_entitled(Entitlement.PUBLIC))
    seat: int = field(metadata=_entitled(Entitlement.PUBLIC))
    meld_kind: str = field(metadata=_entitled(Entitlement.PUBLIC))
    tiles: tuple[int, ...] = field(metadata=_entitled(Entitlement.PUBLIC))
    from_seat: int | None = field(default=None, metadata=_entitled(Entitlement.PUBLIC))


@dataclass(frozen=True)
class ConcealedKongWire:
    """暗槓's redacted-per-seat wire form (02-protocol.md §3): the declaring seat sees `tiles`,
    everyone else sees `count` only, for the rest of the hand -- there is no later widening of
    *this* event; a showdown reveal comes only through `HandEndWire.winning_hand`."""

    t: Literal["meld"] = field(metadata=_entitled(Entitlement.PUBLIC))
    seat: int = field(metadata=_entitled(Entitlement.PUBLIC))
    meld_kind: Literal["concealed_kong"] = field(metadata=_entitled(Entitlement.PUBLIC))
    tiles: tuple[int, ...] | None = field(metadata=_entitled(Entitlement.OWN_SEAT))
    count: int | None = field(metadata=_entitled(Entitlement.PUBLIC))


@dataclass(frozen=True)
class ClaimResolvedWire:
    t: Literal["claim_resolved"] = field(metadata=_entitled(Entitlement.PUBLIC))
    window_id: int = field(metadata=_entitled(Entitlement.PUBLIC))
    claim_kind: str = field(metadata=_entitled(Entitlement.PUBLIC))
    seat: int | None = field(metadata=_entitled(Entitlement.PUBLIC))
    action_kind: str | None = field(metadata=_entitled(Entitlement.PUBLIC))


@dataclass(frozen=True)
class KongReplaceWire:
    t: Literal["kong_replace"] = field(metadata=_entitled(Entitlement.PUBLIC))
    seat: int = field(metadata=_entitled(Entitlement.PUBLIC))
    tile_id: int | None = field(metadata=_entitled(Entitlement.OWN_SEAT))


@dataclass(frozen=True)
class HandEndWire:
    """`winning_hand` is `HAND_END`-gated, not owner-gated -- entitled to *every* recipient
    once `revealed` is true, per 00-architecture.md §5's "tile identity allowed only once that
    hand has reached HAND_END". Sourced from `state.seats[winner].concealed` at the moment the
    hand ended.

    **Known gap, not fixed here:** for a win claimed off another seat's discard/kong (as
    opposed to a self-draw), `engine._apply_claim_response` scores the win with the claimed
    tile folded in locally but never merges it back into `state.seats[winner].concealed` --
    only the scoring context sees it. So `winning_hand` is complete for `SELF_DRAW`/`FLOWERS`
    wins and short exactly the winning tile for `DISCARD`/`KONG_ROB` wins. Fixing it means
    touching `engine.py`'s win path (mahjong_core, M1/M2-owned), out of this sub-task's scope;
    tracked in docs/02-protocol.md §3 instead of silently shipped wrong.
    """

    t: Literal["hand_end"] = field(metadata=_entitled(Entitlement.PUBLIC))
    hand_no: int = field(metadata=_entitled(Entitlement.PUBLIC))
    outcome: str = field(metadata=_entitled(Entitlement.PUBLIC))
    winner: int | None = field(metadata=_entitled(Entitlement.PUBLIC))
    win_type: str | None = field(metadata=_entitled(Entitlement.PUBLIC))
    discarder: int | None = field(metadata=_entitled(Entitlement.PUBLIC))
    faan: int | None = field(metadata=_entitled(Entitlement.PUBLIC))
    faan_breakdown: Mapping[str, int] | None = field(metadata=_entitled(Entitlement.PUBLIC))
    points: int | None = field(metadata=_entitled(Entitlement.PUBLIC))
    payments: Mapping[int, int] | None = field(metadata=_entitled(Entitlement.PUBLIC))
    revealed: bool = field(metadata=_entitled(Entitlement.PUBLIC))
    winning_hand: tuple[int, ...] | None = field(metadata=_entitled(Entitlement.HAND_END))


@dataclass(frozen=True)
class GameEndWire:
    t: Literal["game_end"] = field(metadata=_entitled(Entitlement.PUBLIC))
    hand_no: int = field(metadata=_entitled(Entitlement.PUBLIC))
    scores: tuple[int, int, int, int] = field(metadata=_entitled(Entitlement.PUBLIC))


WireEvent = (
    DrawWire
    | FlowerReplaceWire
    | DiscardWire
    | MeldWire
    | ConcealedKongWire
    | ClaimResolvedWire
    | KongReplaceWire
    | HandEndWire
    | GameEndWire
)


def _build_event_wire(state: GameState, seat: int | None, event: Event) -> WireEvent:
    """The actual per-event redaction decision, as a typed, `Entitlement`-annotated instance.
    `redact_event` just serializes this; `tests/test_redaction.py` imports this function
    directly so the schema walker checks the same object that ships, not a re-derivation of it.
    """
    if isinstance(event, Drawn):
        return DrawWire(
            t="draw", seat=event.seat, tile_id=event.tile_id if seat == event.seat else None
        )

    if isinstance(event, FlowerReplaced):
        return FlowerReplaceWire(
            t="flower_replace", seat=event.seat, flower=tile_code(event.flower)
        )

    if isinstance(event, Discarded):
        return DiscardWire(t="discard", seat=event.seat, tile_id=event.tile_id)

    if isinstance(event, MeldFormed):
        meld = event.meld
        if meld.kind == MeldKind.CONCEALED_KONG:
            owns = seat == event.seat
            return ConcealedKongWire(
                t="meld",
                seat=event.seat,
                meld_kind="concealed_kong",
                tiles=tuple(meld.tiles) if owns else None,
                count=None if owns else len(meld.tiles),
            )
        return MeldWire(
            t="meld",
            seat=event.seat,
            meld_kind=meld.kind.value,
            tiles=tuple(meld.tiles),
            from_seat=meld.from_seat,
        )

    if isinstance(event, ClaimResolved):
        return ClaimResolvedWire(
            t="claim_resolved",
            window_id=event.window_id,
            claim_kind=event.claim_kind.value,
            seat=event.winning_seat,
            action_kind=event.action_kind.value if event.action_kind is not None else None,
        )

    if isinstance(event, KongReplacementDrawn):
        return KongReplaceWire(
            t="kong_replace", seat=event.seat, tile_id=event.tile_id if seat == event.seat else None
        )

    if isinstance(event, HandEnded):
        revealed = event.outcome == HandOutcome.WIN
        result = state.hand_result
        winning_hand: tuple[int, ...] | None = None
        faan = faan_breakdown = points = payments = None
        if revealed and event.winner is not None:
            winning_hand = tuple(state.seats[event.winner].concealed)
            if result is not None:
                faan = result.faan
                faan_breakdown = dict(result.faan_breakdown)
                points = result.points
                payments = dict(result.payments)
        return HandEndWire(
            t="hand_end",
            hand_no=event.hand_no,
            outcome=event.outcome.value,
            winner=event.winner,
            win_type=event.win_type.value if event.win_type is not None else None,
            discarder=event.discarder,
            faan=faan,
            faan_breakdown=faan_breakdown,
            points=points,
            payments=payments,
            revealed=revealed,
            winning_hand=winning_hand,
        )

    if isinstance(event, GameEnded):
        return GameEndWire(t="game_end", hand_no=event.hand_no, scores=event.scores)

    raise AssertionError(f"unhandled event type: {event!r}")  # new Event variant, fix this table


def _wire_value(value: Any) -> Any:
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, Mapping):
        return dict(value)
    return value


def _meld_wire(meld: Meld, *, owner: int, viewer: int | None) -> dict[str, Any]:
    """Redact exactly like `_build_event_wire`'s `ConcealedKongWire` branch: a concealed kong's
    tiles go only to the declaring seat (`owner`) for the rest of the hand, `count` to everyone
    else -- `SeatView.melds`' field-level `PUBLIC` annotation is right in aggregate (which seats
    hold which meld kinds is public) but wrong for concealed-kong tile identity specifically,
    which needs this per-viewer check instead."""
    if meld.kind == MeldKind.CONCEALED_KONG:
        owns = viewer == owner
        return {
            "kind": meld.kind.value,
            "tiles": list(meld.tiles) if owns else None,
            "count": None if owns else len(meld.tiles),
            "from_seat": meld.from_seat,
        }
    return {"kind": meld.kind.value, "tiles": list(meld.tiles), "from_seat": meld.from_seat}


def _claim_offer_wire(offer: ClaimOffer, viewer: int | None) -> dict[str, Any]:
    """`offer.melds` can never actually hold a concealed kong: `_discard_claim_offers`
    (mahjong_core/engine.py) builds `melds` from `legal_claims`, which only returns
    chow/pung/exposed-kong -- melds claimable off *another* seat's discard -- and concealed
    kong is exclusively a self-declared action (`DeclareConcealedKong`), never a claim option;
    `_kong_rob_offers` never sets `melds` at all (kong-rob is win-only). Still routing through
    `_meld_wire`'s redaction rather than assuming a bare dict is fine here, in case that ever
    changes."""
    return {
        "seat": offer.seat,
        "can_win": offer.can_win,
        "melds": [_meld_wire(m, owner=offer.seat, viewer=viewer) for m in offer.melds],
    }


def seat_view_wire(view: SeatView) -> dict[str, Any]:
    """JSON-safe wire dict for a `SeatView` -- `state_sync`'s payload (02-protocol.md §3),
    built by app/room.py on `join` and (a later sub-task) reconnect. Mirrors `redact_event`'s
    tail (already-redacted typed data -> wire-safe primitives), but `SeatView.legal_actions`/
    `claim_options` hold real `mahjong_core.actions.Action`/`mahjong_core.state.ClaimOffer`
    instances rather than one `WireEvent` dataclass, so they get their own small serializers
    here instead of `_wire_value`'s generic tuple/mapping unwrap.
    """
    return {
        "seat": view.seat,
        "hand_no": view.hand_no,
        "prevailing": view.prevailing.name,
        "dealer": view.dealer,
        "turn": view.turn,
        "phase": view.phase.value,
        "own_hand": list(view.own_hand),
        "concealed_counts": list(view.concealed_counts),
        "melds": [
            [_meld_wire(m, owner=owner_seat, viewer=view.seat) for m in seat_melds]
            for owner_seat, seat_melds in enumerate(view.melds)
        ],
        "discard_pools": [list(pool) for pool in view.discard_pools],
        "flowers": [[tile_code(f) for f in fl] for fl in view.flowers],
        "wall_remaining": view.wall_remaining,
        "seat_status": list(view.seat_status),
        "scores": list(view.scores),
        "legal_actions": [action_to_dict(a) for a in view.legal_actions],
        "claim_options": [_claim_offer_wire(o, view.seat) for o in view.claim_options],
        "deadline_ts": view.deadline_ts,
    }


def redact_event(state: GameState, seat: int | None, event: Event) -> dict[str, Any]:
    """Per-event wire redaction: the JSON-safe payload for one logical `Event`, to one
    recipient (`seat=None` -> spectator). One dict key per field of the wire form
    `_build_event_wire` chose; this is the logical payload, not a minified wire frame -- keys
    with no value at all (e.g. `winning_hand` before hand end) are still present as `null`
    rather than omitted, leaving the final envelope/omission policy to the Session layer that
    actually assembles `{v,t,seq,id,ts,d}` (02-protocol.md §1).
    """
    wire = _build_event_wire(state, seat, event)
    return {f.name: _wire_value(getattr(wire, f.name)) for f in fields(wire)}
