"""GameState, SeatState, Phase: the frozen state shape the turn machine operates on.

Everything here is frozen. No transitions live in this module — `reduce(state, action) ->
(state, events)` is engine.py's job; this module only builds the very first `GameState`
(`new_game`).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import TYPE_CHECKING, Any, cast

from mahjong_core.config import RuleSet
from mahjong_core.melds import Meld
from mahjong_core.tiles import Flower, TileId
from mahjong_core.wall import Wall, WallTile, deal_hands, new_wall, replace_flowers

if TYPE_CHECKING:
    # claims.py imports ClaimOffer/ClaimWindow from here, so this stays type-checking-only
    # to avoid a circular import at runtime.
    from mahjong_core.claims import ClaimResponse


class Phase(StrEnum):
    """Every distinct state the turn machine can be in. `EXHAUSTIVE_DRAW` (流局) isn't its
    own phase — it's modeled as a `HAND_OVER` outcome via `HandResult` instead."""

    AWAIT_DRAW = "AWAIT_DRAW"
    AWAIT_ACTION = "AWAIT_ACTION"
    AWAIT_CLAIMS = "AWAIT_CLAIMS"
    AWAIT_KONG_ROB = "AWAIT_KONG_ROB"  # 搶槓 window on an added-kong declaration, not a discard
    SCORING = "SCORING"
    HAND_OVER = "HAND_OVER"
    GAME_OVER = "GAME_OVER"


class Wind(IntEnum):
    """Prevailing (圈風) or seat (門風) wind, sharing the seat-frame numbering: East=0 ..
    North=3, the same axis `(seat + 1) % 4` "next seat" arithmetic uses."""

    EAST = 0
    SOUTH = 1
    WEST = 2
    NORTH = 3


class ClaimKind(StrEnum):
    """What opened the live claim window: a discard, or an added-kong declaration opening a
    robbing-the-kong window (搶槓) — same machinery, different trigger."""

    DISCARD = "discard"
    KONG_ROB = "kong_rob"


@dataclass(frozen=True)
class ClaimOffer:
    """One eligible seat's live options on the current claim window. Only seats that
    actually have a claim get an offer — broadcasting "someone may claim" leaks information.
    `melds` never includes a win option — winning isn't a meld — so `can_win` is separate.
    """

    seat: int
    can_win: bool
    melds: tuple[Meld, ...] = ()

    def __post_init__(self) -> None:
        if not 0 <= self.seat < 4:
            raise ValueError(f"seat must be 0..3, got {self.seat}")
        if not self.can_win and not self.melds:
            raise ValueError("a claim offer must include at least a win or a meld option")


@dataclass(frozen=True)
class ClaimWindow:
    """Live `AWAIT_CLAIMS`/`AWAIT_KONG_ROB` state: what's being offered to whom, so
    claims.py/engine.py can resolve it. `deadline_ts` is carried as an opaque value only — the
    pure engine never reads a clock; arming and enforcing the actual timer is app/table.py's
    job.
    """

    window_id: int
    kind: ClaimKind
    source_seat: int  # discarder (DISCARD) or kong-declarer (KONG_ROB)
    tile: TileId
    offers: tuple[ClaimOffer, ...]
    responses: Mapping[int, ClaimResponse] = field(default_factory=dict)
    # accumulated across separate reduce() calls, one per seat's Pass/Claim* action. keyed by
    # seat; a seat missing here is an implicit Pass, same convention claims.py uses.
    deadline_ts: int | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.source_seat < 4:
            raise ValueError(f"source_seat must be 0..3, got {self.source_seat}")
        if not self.offers:
            raise ValueError("a claim window with no offers should never be constructed")
        seats = [offer.seat for offer in self.offers]
        if len(seats) != len(set(seats)):
            raise ValueError(f"duplicate seat among claim offers: {seats}")
        if self.source_seat in seats:
            raise ValueError("the source seat cannot hold an offer on its own discard/kong")


class HandOutcome(StrEnum):
    """How a hand ended."""

    WIN = "win"
    EXHAUSTIVE_DRAW = "exhaustive_draw"  # 流局


class WinType(StrEnum):
    """How the winning tile was obtained -- affects New-6 faan patterns (自摸/海底撈月/搶槓).
    `FLOWERS` is the instant-win variant (`seven_flowers_instant_win`/
    `eight_flowers_instant_win`): ends the hand on flower count alone, no winning tile or
    meld decomposition, so it's its own value rather than forced into `SELF_DRAW` -- still
    pays out like a self-draw since no seat fed the win."""

    SELF_DRAW = "self_draw"
    DISCARD = "discard"
    KONG_ROB = "kong_rob"
    FLOWERS = "flowers"


@dataclass(frozen=True)
class HandResult:
    """The outcome of the hand that just ended, carried on `GameState.hand_result` only
    while `phase == Phase.HAND_OVER`.

    `faan`/`faan_breakdown`/`points`/`payments` are only populated for `HandOutcome.WIN` --
    an `EXHAUSTIVE_DRAW` carries none of them. `payments` is the per-seat point delta, keyed
    by seat, summing to zero.
    """

    outcome: HandOutcome
    winner: int | None = None
    win_type: WinType | None = None
    discarder: int | None = None  # who fed the win (discard/kong_rob); None otherwise
    faan: int = 0
    faan_breakdown: Mapping[str, int] = field(default_factory=dict)
    points: int = 0
    payments: Mapping[int, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.outcome == HandOutcome.WIN and self.winner is None:
            raise ValueError("a WIN result requires a winner")
        if self.outcome == HandOutcome.EXHAUSTIVE_DRAW and self.winner is not None:
            raise ValueError("an EXHAUSTIVE_DRAW result cannot have a winner")
        if self.outcome == HandOutcome.EXHAUSTIVE_DRAW and (
            self.faan or self.faan_breakdown or self.points or self.payments
        ):
            raise ValueError("an EXHAUSTIVE_DRAW result cannot carry faan/points/payments")
        if self.payments and sum(self.payments.values()) != 0:
            raise ValueError("payments must sum to zero")


@dataclass(frozen=True)
class GameOutcome:
    """Final result of a completed game (`Phase.GAME_OVER`). Mirrors `engine.GameEnded`'s
    payload, pulled out as its own type so `app/db` doesn't need to depend on an `Event` just
    to read a finished game's result.
    """

    hand_count: int  # last hand actually played (engine.GameEnded.hand_no)
    final_scores: tuple[int, int, int, int]

    def to_dict(self) -> dict[str, Any]:
        return {"hand_count": self.hand_count, "final_scores": list(self.final_scores)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> GameOutcome:
        scores = data["final_scores"]
        return cls(
            hand_count=data["hand_count"], final_scores=(scores[0], scores[1], scores[2], scores[3])
        )


@dataclass(frozen=True)
class SeatState:
    """One seat's persistent table state. `SeatView` is derived from this plus redaction —
    every field a seat-visible view needs lives here.

    No `seat_status` field: connected/disconnected/autoplay/bot is session state owned by
    `app/table.py`'s `SeatBinding`, not the pure engine — `reduce()` never needs to know
    whether a seat is human, disconnected, or a bot to compute the next `GameState`.
    """

    concealed: tuple[TileId, ...]
    melds: tuple[Meld, ...] = ()
    discards: tuple[TileId, ...] = ()
    flowers: tuple[Flower, ...] = ()
    score: int = 0


Seats = tuple[SeatState, SeatState, SeatState, SeatState]


@dataclass(frozen=True)
class GameState:
    """The whole authoritative table. Never mutated in place: `reduce(state, action) ->
    (state, events)` always produces a new instance. `SeatView` is derived from this by
    redaction; nothing here is ever serialized to a client directly.
    """

    ruleset: RuleSet
    game_seed: int
    # never leaves this process, not even redacted, not ever during play (00-architecture.md §3);
    # kept here, not just passed to new_game, because engine.py derives every hand_seed from it.
    hand_seed: bytes
    wall: Wall
    seats: Seats
    phase: Phase
    turn: int
    dealer: int
    prevailing: Wind
    hand_no: int
    claim_window: ClaimWindow | None = None
    next_window_id: int = 0
    hand_result: HandResult | None = None
    total_discards: int = 0
    # discards so far this hand -- 天糊/地糊 win-timing context. 0 = nobody's discarded yet
    # (only the dealer can win with this true), 1 on the dealer's own first discard.
    wall_exhausted_at_last_draw: bool = False
    # whether the most recent draw brought the wall to wall_reserve or below -- 海底撈月/
    # 河底撈魚's "last tile" flag. monotonic within a hand, reset only by the next deal.
    last_draw_was_kong_replacement: bool = False
    # whether the most recent draw was a kong replacement (back-of-wall) -- 槓上開花's flag.
    self_draw_win_allowed: bool = True
    # whether the current AWAIT_ACTION turn may still end by self-draw win: true at hand start
    # and after any draw; false after a chow/pung claim (claimer didn't draw).

    def __post_init__(self) -> None:
        if len(self.seats) != 4:
            raise ValueError(f"seats must have exactly 4 entries, got {len(self.seats)}")
        if not 0 <= self.turn < 4:
            raise ValueError(f"turn must be 0..3, got {self.turn}")
        if not 0 <= self.dealer < 4:
            raise ValueError(f"dealer must be 0..3, got {self.dealer}")
        if self.hand_no < 1:
            raise ValueError(f"hand_no must be >= 1, got {self.hand_no}")
        expects_window = self.phase in (Phase.AWAIT_CLAIMS, Phase.AWAIT_KONG_ROB)
        if expects_window and self.claim_window is None:
            raise ValueError(f"{self.phase} requires a claim_window")
        if not expects_window and self.claim_window is not None:
            raise ValueError(f"{self.phase} must not carry a claim_window")
        if self.claim_window is not None:
            want_kind = (
                ClaimKind.KONG_ROB if self.phase == Phase.AWAIT_KONG_ROB else ClaimKind.DISCARD
            )
            if self.claim_window.kind != want_kind:
                raise ValueError(f"{self.phase} requires a {want_kind} claim_window")
        if self.phase == Phase.HAND_OVER and self.hand_result is None:
            raise ValueError("HAND_OVER requires a hand_result")
        if self.phase != Phase.HAND_OVER and self.hand_result is not None:
            raise ValueError(f"{self.phase} must not carry a hand_result")


def derive_hand_seed(game_seed: int, hand_no: int) -> bytes:
    """`hand_seed = SHA256(game_seed || hand_no)`. Only `hand_seed` is ever revealed, and only
    at that hand's end -- `game_seed` never goes with it.
    """
    return hashlib.sha256(f"{game_seed}:{hand_no}".encode()).digest()


def _as_tile_ids(tiles: Sequence[WallTile]) -> tuple[TileId, ...]:
    """Narrow a post-flower-replacement hand from `WallTile` to `TileId`. `replace_flowers`
    guarantees no `Flower` remains; this only makes that guarantee visible to mypy."""
    assert not any(isinstance(t, Flower) for t in tiles), "flower tile survived replace_flowers"
    return tuple(cast(TileId, t) for t in tiles)


def new_game(ruleset: RuleSet, game_seed: int) -> GameState:
    """Deal and resolve hand 1: shuffle, deal 13/14, replace flowers, land in `AWAIT_ACTION`
    with the dealer to discard. The dealer's post-deal 14th tile stands in for the "draw" step
    a normal turn would otherwise show as a separate `AWAIT_DRAW`.

    Hand-to-hand transitions -- dealer rotation, prevailing-wind advance, scoring, dealing
    hand 2 onward -- are engine.py's job, not this function's.
    """
    dealer = 0  # East seat first for hand 1; rotation is engine.py's job
    hand_no = 1
    hand_seed = derive_hand_seed(game_seed, hand_no)

    _, wall = new_wall(hand_seed, ruleset)
    hands, wall = deal_hands(wall, dealer_seat=dealer)
    hands, wall, flowers = replace_flowers(hands, wall, dealer_seat=dealer)

    seats: Seats = (
        SeatState(concealed=_as_tile_ids(hands[0]), flowers=flowers[0]),
        SeatState(concealed=_as_tile_ids(hands[1]), flowers=flowers[1]),
        SeatState(concealed=_as_tile_ids(hands[2]), flowers=flowers[2]),
        SeatState(concealed=_as_tile_ids(hands[3]), flowers=flowers[3]),
    )

    return GameState(
        ruleset=ruleset,
        game_seed=game_seed,
        hand_seed=hand_seed,
        wall=wall,
        seats=seats,
        phase=Phase.AWAIT_ACTION,
        turn=dealer,
        dealer=dealer,
        prevailing=Wind.EAST,
        hand_no=hand_no,
    )
