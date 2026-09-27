"""`seat_view()` + `redact_event()` -- the redaction layer (docs/00-architecture.md §5).

Lives in `app/`, not `mahjong_core/`: this module answers "what may seat X see right now",
which is about a specific wire recipient, not a game rule. `mahjong_core` never redacts -- see
melds.py's `Meld.tiles` docstring.

Two entry points:
    seat_view(state, seat) -> SeatView       full per-recipient snapshot
    redact_event(state, seat, event) -> dict  per-event wire redaction

Both are built the same way: an explicitly `Entitlement`-annotated dataclass is constructed
first (never a bare dict), then converted to a wire dict -- `tests/test_redaction.py`'s schema
walker inspects that annotated instance directly, not a re-derivation of the redaction logic.

`legal_actions`/`claim_options` reuse `mahjong_core.actions.Action`/`mahjong_core.state.
ClaimOffer` directly rather than inventing separate wire types -- both already carry only this
seat's own tiles or already-public tiles, so a parallel type would add translation with no
redaction benefit. `seat_status`/`names`/`deadline_ts`/`host_seat` are all override points a
caller with a real `Table` behind it supplies (see `seat_view()`); a caller with none (bots/
arena.py, bots/selfplay.py, direct tests) gets inert defaults instead.

**One deliberate, contained exception to "a real seat never sees another seat's tiles":**
`_omniscient_seat_view()` builds a `SeatView` for a real acting seat with `.hands` (every seat's
concealed tiles) populated -- exactly what `seat_view()`'s `_check_reveal` guard exists to forbid
for a real `seat`. It backs the `"ORACLE"` bot tier (docs/04-bots.md §10), an explicitly opt-in,
non-ladder tier a live table may be configured to run -- driven by a plain `FaanBot()`
(`bots/worker.py`), whose `bots/safety.py`-derived discard scoring becomes exact rather than
probabilistic once it sees `.hands` populated. This is safe to hand across
the `ProcessPoolExecutor` boundary (`app/table.py`'s `_submit_bot_job`, the only caller) because
`SeatView` never carries `game_seed`/`hand_seed` -- see its field list below, there is no seed
field -- so `docs/00-architecture.md §3`'s "`game_seed` never leaves this process" invariant is
untouched; that invariant is about the seed specifically, not about tile visibility. It is never
reachable from any wire-facing/protocol-facing path (`seat_view_wire`, `state_sync_wire`, or
anything a real WS client's own traffic goes through) -- those all go through `seat_view()`'s
public, unmodified contract. Do not call `_omniscient_seat_view` from anywhere but
`app/table.py`'s oracle-tier branch, and do not weaken `_check_reveal` to make it "unnecessary" --
that guard is the real security boundary for every real client and stays exactly as strict as it
is today.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields, replace
from enum import Enum
from typing import Any, Literal, cast

from mahjong_core.actions import Action, action_to_dict
from mahjong_core.actions import legal_actions as compute_legal_actions
from mahjong_core.config import RuleSet
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
    "HandHistoryRecord",
    "KongReplaceWire",
    "MeldWire",
    "SeatView",
    "hand_history_wire",
    "redact_event",
    "seat_view",
    "seat_view_wire",
]


class Entitlement(Enum):
    """Per-field annotation the schema walker checks structurally, not a docstring promise --
    `tests/test_redaction.py` reads this metadata off the actual produced instance, so it can't
    be satisfied by a field that merely happens to contain a plausible-looking integer."""

    PUBLIC = "public"
    OWN_SEAT = "own_seat"
    COUNT_ONLY = "count_only"
    HAND_END = "hand_end"
    OPEN_HANDS = "open_hands"  # only an open-hands spectator (`reveal_hands`)


def _entitled(entitlement: Entitlement) -> dict[str, Any]:
    return {"entitlement": entitlement}


_SeatStatus = tuple[str, str, str, str]
_DEFAULT_SEAT_STATUS: _SeatStatus = ("connected", "connected", "connected", "connected")

_SeatNames = tuple[str | None, str | None, str | None, str | None]
_DEFAULT_NAMES: _SeatNames = (None, None, None, None)


@dataclass(frozen=True)
class SeatView:
    """Full redacted snapshot for one recipient; `seat=None` is the spectator view. Canonical
    shape depended on by bots and ML encoders -- don't change unilaterally.
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
    # public: a name is never a secret. None when there's no Table behind the caller (bots/arena).
    names: _SeatNames = field(metadata=_entitled(Entitlement.PUBLIC))
    scores: tuple[int, int, int, int] = field(metadata=_entitled(Entitlement.PUBLIC))
    legal_actions: tuple[Action, ...] = field(metadata=_entitled(Entitlement.OWN_SEAT))
    claim_options: tuple[ClaimOffer, ...] = field(metadata=_entitled(Entitlement.OWN_SEAT))
    deadline_ts: int | None = field(metadata=_entitled(Entitlement.OWN_SEAT))
    # public: which seat is host isn't a secret. None for a caller with no Table behind it.
    host_seat: int | None = field(metadata=_entitled(Entitlement.PUBLIC))
    # public: a table's ruleset isn't secret -- every seat and spectator already sees it.
    ruleset: RuleSet = field(metadata=_entitled(Entitlement.PUBLIC))
    # every seat's concealed tiles, open-hands spectator only (`reveal_hands`); `None` otherwise
    hands: tuple[tuple[TileId, ...], ...] | None = field(
        default=None, metadata=_entitled(Entitlement.OPEN_HANDS)
    )


def _check_reveal(seat: int | None, reveal_hands: bool) -> None:
    if reveal_hands and seat is not None:
        raise ValueError(f"reveal_hands is spectator-only, got seat {seat}")


def _sees_concealed(viewer: int | None, owner: int, reveal_hands: bool) -> bool:
    return viewer == owner or (reveal_hands and viewer is None)


def seat_view(
    state: GameState,
    seat: int | None,
    *,
    seat_status: _SeatStatus | None = None,
    names: _SeatNames | None = None,
    claim_deadline_ts: int | None = None,
    turn_deadline_ts: int | None = None,
    hand_end_deadline_ts: int | None = None,
    host_seat: int | None = None,
    reveal_hands: bool = False,
) -> SeatView:
    """Build `seat`'s full redacted snapshot (`seat=None` -> spectator). The `*_deadline_ts`/
    `seat_status`/`names`/`host_seat` params are override points for `app/table.py`'s live state
    -- the pure engine has no clock or session state of its own (`GameState` never sets
    `ClaimWindow.deadline_ts`), so a caller with no `Table` behind it (bots/arena, bots/selfplay,
    direct tests) omits them and gets the inert defaults. `turn_deadline_ts` only ever surfaces
    when `seat == state.turn` and `state.phase == Phase.AWAIT_ACTION`; `hand_end_deadline_ts`
    applies regardless of `seat` (a whole-table wait, not per-seat). `reveal_hands` fills `hands`
    for a spectator (module docstring); raises if `seat` is not `None`.
    """
    _check_reveal(seat, reveal_hands)
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
    elif state.phase == Phase.HAND_OVER:
        deadline_ts = hand_end_deadline_ts

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
        names=names if names is not None else _DEFAULT_NAMES,
        scores=cast("tuple[int, int, int, int]", tuple(s.score for s in state.seats)),
        legal_actions=legal,
        claim_options=claim_options,
        deadline_ts=deadline_ts,
        host_seat=host_seat,
        ruleset=state.ruleset,
        hands=tuple(s.concealed for s in state.seats) if reveal_hands else None,
    )


def _omniscient_seat_view(state: GameState, seat: int) -> SeatView:
    """DANGEROUS -- do not call this from anywhere except `app/table.py`'s `_submit_bot_job`,
    in its oracle-tier branch. That is the ONLY sanctioned call site in the whole codebase
    (`tests/test_oracle_containment.py` pins this structurally); see the module docstring's
    "deliberate, contained exception" section for the full safety argument.

    Builds `seat`'s ordinary `seat_view(state, seat)` and then replaces `.hands` with every
    seat's concealed tiles -- the one thing `seat_view(..., reveal_hands=True)` refuses to do
    for a real `seat` (`_check_reveal` raises). This function exists specifically to bypass that
    guard for the `"ORACLE"` tier -- a plain `FaanBot()` handed full information a live table may
    opt into (docs/04-bots.md §10); `seat_view()`'s own public contract, and `_check_reveal`, are
    left completely untouched by this function's existence.

    Never call this for a spectator (`seat_view(..., reveal_hands=True)` already covers that
    case) and never call this for a disconnect-handover autoplay seat -- `app/table.py` pins
    disconnect-handover to `T2`/`FaanBot` unconditionally, specifically so a real human's seat
    never lands on this path.
    """
    view = seat_view(state, seat)
    return replace(view, hands=tuple(s.concealed for s in state.seats))


# One dataclass per distinct wire shape -- concealed_kong gets two (owner vs. everyone else)
# rather than one struct with a runtime-conditional entitlement on the same field. `seat`,
# where present, is both "whose event this is" and the `OWN_SEAT` owner for that struct's
# restricted field(s).
#
# Not modeled here (needs Table's own intermediate per-event state, not just (state, event)):
# - discard.pool_index -- if the discard is claimed later in the same reduce() call, the
#   claiming seat's discards entry is already gone from final state by the time this runs.
# - flower_replace fusing in a replacement tile -- FlowerReplaced and the landing Drawn/
#   KongReplacementDrawn/HandEnded are separate Events; this redacts one Event at a time.
# - envelope fields (v/seq/ts) -- Session's job.


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
    """Every meld kind except concealed_kong -- fully public, full tiles to everyone."""

    t: Literal["meld"] = field(metadata=_entitled(Entitlement.PUBLIC))
    seat: int = field(metadata=_entitled(Entitlement.PUBLIC))
    meld_kind: str = field(metadata=_entitled(Entitlement.PUBLIC))
    tiles: tuple[int, ...] = field(metadata=_entitled(Entitlement.PUBLIC))
    from_seat: int | None = field(default=None, metadata=_entitled(Entitlement.PUBLIC))


@dataclass(frozen=True)
class ConcealedKongWire:
    """暗槓's redacted-per-seat wire form: declaring seat sees `tiles`, everyone else sees
    `count`, for the rest of the hand -- a showdown reveal comes only through
    `HandEndWire.winning_hand`."""

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
    """`winning_hand` is `HAND_END`-gated, not owner-gated: every recipient once `revealed`.
    Sourced from `state.seats[winner].concealed`, which already includes the claimed winning
    tile for a DISCARD/KONG_ROB win, not just SELF_DRAW/FLOWERS."""

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


def _build_event_wire(
    state: GameState, seat: int | None, event: Event, *, reveal_hands: bool = False
) -> WireEvent:
    """The actual per-event redaction decision, as a typed `Entitlement`-annotated instance --
    `redact_event` just serializes this. `tests/test_redaction.py` imports it directly so the
    schema walker checks the same object that ships.
    """
    _check_reveal(seat, reveal_hands)
    if isinstance(event, Drawn):
        sees = _sees_concealed(seat, event.seat, reveal_hands)
        return DrawWire(t="draw", seat=event.seat, tile_id=event.tile_id if sees else None)

    if isinstance(event, FlowerReplaced):
        return FlowerReplaceWire(
            t="flower_replace", seat=event.seat, flower=tile_code(event.flower)
        )

    if isinstance(event, Discarded):
        return DiscardWire(t="discard", seat=event.seat, tile_id=event.tile_id)

    if isinstance(event, MeldFormed):
        meld = event.meld
        if meld.kind == MeldKind.CONCEALED_KONG:
            owns = _sees_concealed(seat, event.seat, reveal_hands)
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
        sees = _sees_concealed(seat, event.seat, reveal_hands)
        return KongReplaceWire(
            t="kong_replace", seat=event.seat, tile_id=event.tile_id if sees else None
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


def _meld_wire(
    meld: Meld, *, owner: int, viewer: int | None, reveal_hands: bool = False
) -> dict[str, Any]:
    """Same redaction as `ConcealedKongWire`: tiles only to the declaring seat, count to
    everyone else -- needed because `SeatView.melds`'s `PUBLIC` annotation is right in aggregate
    but wrong for concealed-kong tile identity specifically."""
    if meld.kind == MeldKind.CONCEALED_KONG:
        owns = _sees_concealed(viewer, owner, reveal_hands)
        return {
            "kind": meld.kind.value,
            "tiles": list(meld.tiles) if owns else None,
            "count": None if owns else len(meld.tiles),
            "from_seat": meld.from_seat,
        }
    return {"kind": meld.kind.value, "tiles": list(meld.tiles), "from_seat": meld.from_seat}


def _claim_offer_wire(offer: ClaimOffer, viewer: int | None) -> dict[str, Any]:
    """`offer.melds` can never actually hold a concealed kong -- claim offers only ever carry
    chow/pung/exposed-kong, and concealed kong is self-declared only. Still routes through
    `_meld_wire` defensively, in case that ever changes."""
    return {
        "seat": offer.seat,
        "can_win": offer.can_win,
        "melds": [_meld_wire(m, owner=offer.seat, viewer=viewer) for m in offer.melds],
    }


def seat_view_wire(view: SeatView) -> dict[str, Any]:
    """JSON-safe wire dict for a `SeatView` -- `state_sync`'s payload. `legal_actions`/
    `claim_options` hold real `Action`/`ClaimOffer` instances rather than a `WireEvent`
    dataclass, so they get their own serializers here instead of `_wire_value`'s generic unwrap.
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
            [
                _meld_wire(
                    m, owner=owner_seat, viewer=view.seat, reveal_hands=view.hands is not None
                )
                for m in seat_melds
            ]
            for owner_seat, seat_melds in enumerate(view.melds)
        ],
        "discard_pools": [list(pool) for pool in view.discard_pools],
        "flowers": [[tile_code(f) for f in fl] for fl in view.flowers],
        "wall_remaining": view.wall_remaining,
        "seat_status": list(view.seat_status),
        "names": list(view.names),
        "scores": list(view.scores),
        "legal_actions": [action_to_dict(a) for a in view.legal_actions],
        "claim_options": [_claim_offer_wire(o, view.seat) for o in view.claim_options],
        "deadline_ts": view.deadline_ts,
        "host_seat": view.host_seat,
        "hands": [list(h) for h in view.hands] if view.hands is not None else None,
    }


@dataclass(frozen=True)
class HandHistoryRecord:
    """One completed hand, captured once `HandEnded` fires (`_record_hand_history`) -- backs
    `state_sync.hand_history`. Every field but `winner_melds` is already public; `winner_melds`
    stays raw `Meld`s, redacted per viewer at `state_sync` time (`hand_history_wire`) so a
    non-owner still never learns a past hand's concealed-kong tiles."""

    hand_no: int
    outcome: str
    winner: int | None
    win_type: str | None
    discarder: int | None
    faan: int | None
    faan_breakdown: Mapping[str, int] | None
    points: int | None
    payments: Mapping[int, int] | None
    revealed: bool
    winning_hand: Sequence[int] | None
    dealer: int
    prevailing: str
    winner_melds: tuple[Meld, ...] | None


def hand_history_wire(
    records: Sequence[HandHistoryRecord], *, viewer: int | None, reveal_hands: bool = False
) -> list[dict[str, Any]]:
    """`state_sync.hand_history` -- one dict per completed hand, oldest first. `winner_melds`
    gets the same per-viewer concealed-kong redaction a live `meld` event would."""
    return [
        {
            "hand_no": r.hand_no,
            "outcome": r.outcome,
            "winner": r.winner,
            "win_type": r.win_type,
            "discarder": r.discarder,
            "faan": r.faan,
            "faan_breakdown": dict(r.faan_breakdown) if r.faan_breakdown is not None else None,
            "points": r.points,
            "payments": dict(r.payments) if r.payments is not None else None,
            "revealed": r.revealed,
            "winning_hand": list(r.winning_hand) if r.winning_hand is not None else None,
            "dealer": r.dealer,
            "prevailing": r.prevailing,
            "winner_melds": (
                [
                    _meld_wire(m, owner=r.winner, viewer=viewer, reveal_hands=reveal_hands)
                    for m in r.winner_melds
                ]
                if r.winner_melds is not None and r.winner is not None
                else None
            ),
        }
        for r in records
    ]


def redact_event(
    state: GameState, seat: int | None, event: Event, *, reveal_hands: bool = False
) -> dict[str, Any]:
    """Per-event wire redaction for one recipient (`seat=None` -> spectator). Absent-value
    fields (e.g. `winning_hand` before hand end) are still present as `null`, not omitted --
    envelope assembly is the Session layer's job.
    """
    wire = _build_event_wire(state, seat, event, reveal_hands=reveal_hands)
    return {f.name: _wire_value(getattr(wire, f.name)) for f in fields(wire)}
