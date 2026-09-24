"""Claim priority resolution: win > kong/pung > chow, over responses a window has already
collected. Pure — no clock, no inbox, no timer; a seat missing from `responses` is treated as
an implicit `Pass`. `app/table.py` owns arming deadlines and gathering responses off the wire.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import IntEnum

from mahjong_core.actions import ActionKind, ClaimChow, ClaimKong, ClaimPung, ClaimWin, Pass
from mahjong_core.melds import MeldKind
from mahjong_core.state import ClaimOffer, ClaimWindow

ClaimResponse = ClaimChow | ClaimPung | ClaimKong | ClaimWin | Pass


class ClaimPriority(IntEnum):
    """Kong and pung share a tier — kong-over-pung is a same-tier tiebreak (see
    `resolve_claims`), not a separate numeric level."""

    NONE = 0
    CHOW = 1
    PUNG_OR_KONG = 2
    WIN = 3


_PRIORITY: dict[ActionKind, ClaimPriority] = {
    ActionKind.PASS: ClaimPriority.NONE,
    ActionKind.CLAIM_CHOW: ClaimPriority.CHOW,
    ActionKind.CLAIM_PUNG: ClaimPriority.PUNG_OR_KONG,
    ActionKind.CLAIM_KONG: ClaimPriority.PUNG_OR_KONG,
    ActionKind.CLAIM_WIN: ClaimPriority.WIN,
}


def _priority(action: ClaimResponse) -> ClaimPriority:
    return _PRIORITY[action.kind]


def _offer_best_priority(offer: ClaimOffer) -> ClaimPriority:
    """The best tier `offer`'s seat could claim at — the ceiling, not what it will choose.
    `ClaimOffer.__post_init__` guarantees at least a win or a meld, so this never falls through
    to `NONE`."""
    if offer.can_win:
        return ClaimPriority.WIN
    if any(m.kind in (MeldKind.PUNG, MeldKind.EXPOSED_KONG) for m in offer.melds):
        return ClaimPriority.PUNG_OR_KONG
    if any(m.kind == MeldKind.CHOW for m in offer.melds):
        return ClaimPriority.CHOW
    raise AssertionError(f"claim offer for seat {offer.seat} resolves to no priority")


def _validate_response(claim_window: ClaimWindow, seat: int, action: ClaimResponse) -> None:
    eligible_seats = {offer.seat for offer in claim_window.offers}
    if seat not in eligible_seats:
        raise ValueError(f"seat {seat} has no offer on claim window {claim_window.window_id}")
    if action.seat != seat:
        raise ValueError(f"response keyed under seat {seat} but action.seat={action.seat}")
    if action.window_id != claim_window.window_id:
        raise ValueError(
            f"response window_id={action.window_id} doesn't match "
            f"claim_window.window_id={claim_window.window_id}"
        )


@dataclass(frozen=True)
class ClaimResolution:
    """`winning_seat`/`action` are both `None` when nobody's claim wins — everyone passed, or
    nobody responded yet."""

    winning_seat: int | None
    action: ClaimResponse | None

    def __post_init__(self) -> None:
        if (self.winning_seat is None) != (self.action is None):
            raise ValueError("winning_seat and action must both be set or both be None")
        if self.action is not None and self.action.kind == ActionKind.PASS:
            raise ValueError("a Pass cannot be a claim resolution's winning action")


_NO_CLAIM = ClaimResolution(winning_seat=None, action=None)


def resolve_claims(
    claim_window: ClaimWindow, responses: Mapping[int, ClaimResponse]
) -> ClaimResolution:
    """Resolve the winning claim, if any, from the responses collected so far. A seat absent
    from `responses` is treated as Pass."""
    for seat, action in responses.items():
        _validate_response(claim_window, seat, action)

    live = [(seat, action) for seat, action in responses.items() if action.kind != ActionKind.PASS]
    if not live:
        return _NO_CLAIM

    best = max(_priority(action) for _, action in live)
    contenders = [(seat, action) for seat, action in live if _priority(action) == best]

    if best == ClaimPriority.WIN:
        # win-vs-win ties resolve by seat order from the discarder.
        winner = min(contenders, key=lambda sc: (sc[0] - claim_window.source_seat) % 4)
        return ClaimResolution(winning_seat=winner[0], action=winner[1])

    if best == ClaimPriority.PUNG_OR_KONG:
        # kong beats pung. with 4 copies per tile type a kong claim already uses up the
        # other 3, so a second seat's pung can't coexist in practice — handled explicitly
        # anyway since this function arbitrates whatever responses it's handed.
        kongs = [sc for sc in contenders if sc[1].kind == ActionKind.CLAIM_KONG]
        pool = kongs if kongs else contenders
        if len(pool) > 1:
            raise AssertionError(f"multiple undecidable pung/kong claims: {pool}")
        winner = pool[0]
        return ClaimResolution(winning_seat=winner[0], action=winner[1])

    # chow: only claimer_seat == (source_seat + 1) % 4 is ever eligible, so at most one seat
    # can submit a chow claim on one discard.
    if len(contenders) > 1:
        raise AssertionError(f"multiple chow claims on one discard: {contenders}")
    winner = contenders[0]
    return ClaimResolution(winning_seat=winner[0], action=winner[1])


def can_close_early(claim_window: ClaimWindow, responses: Mapping[int, ClaimResponse]) -> bool:
    """True once no seat still pending could out-rank the best claim received so far. Reasons
    from each pending seat's *offer* — the ceiling of what it could claim — never a guess at
    what it will actually choose."""
    for seat, action in responses.items():
        _validate_response(claim_window, seat, action)

    eligible_seats = {offer.seat for offer in claim_window.offers}
    pending_seats = eligible_seats - responses.keys()
    if not pending_seats:
        return True

    live = [(seat, action) for seat, action in responses.items() if action.kind != ActionKind.PASS]
    best = max((_priority(action) for _, action in live), default=ClaimPriority.NONE)
    best_win_distance = (
        min(
            (seat - claim_window.source_seat) % 4
            for seat, action in live
            if action.kind == ActionKind.CLAIM_WIN
        )
        if best == ClaimPriority.WIN
        else None
    )
    best_has_kong = any(action.kind == ActionKind.CLAIM_KONG for _, action in live)

    offers_by_seat = {offer.seat: offer for offer in claim_window.offers}
    for seat in pending_seats:
        tier = _offer_best_priority(offers_by_seat[seat])
        if tier > best:
            return False
        if tier < best:
            continue
        # tier == best: only a same-tier tiebreak can still flip the winner.
        if tier == ClaimPriority.WIN:
            assert best_win_distance is not None
            distance = (seat - claim_window.source_seat) % 4
            if distance < best_win_distance:
                return False
        elif tier == ClaimPriority.PUNG_OR_KONG and not best_has_kong:
            pending_offer = offers_by_seat[seat]
            if any(m.kind == MeldKind.EXPOSED_KONG for m in pending_offer.melds):
                return False
        # chow-tier ties never arise: at most one seat is ever chow-eligible.

    return True
