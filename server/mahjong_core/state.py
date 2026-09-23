"""GameState, SeatState, Phase: the frozen state shape the turn machine operates on
(docs/01-rules-spec.md §4; docs/00-architecture.md §3, §5; docs/05-roadmap.md §1).

Everything here is frozen. No transitions live in this module — `reduce(state, action) ->
(state, events)` is engine.py's job (a later sub-task); this module only builds the very
first `GameState` (`new_game`) so the shape has been exercised end to end against `wall.py`
and `melds.py` before `actions.py`/`claims.py`/`engine.py` build on it.
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
    # deferred: claims.py imports ClaimOffer/ClaimWindow from this module, so this import
    # only runs for type-checking (PEP 563 string annotations below), never at runtime.
    from mahjong_core.claims import ClaimResponse


class Phase(StrEnum):
    """Every distinct state the turn machine can be in (01-rules-spec.md §4, which names
    exactly these seven). `EXHAUSTIVE_DRAW` (流局) isn't its own phase: the spec's
    named-phases list omits it, so it's modeled as a `HAND_OVER` outcome instead of an
    eighth phase — see the (future) hand-result field engine.py adds alongside `HAND_OVER`.
    """

    AWAIT_DRAW = "AWAIT_DRAW"
    AWAIT_ACTION = "AWAIT_ACTION"
    AWAIT_CLAIMS = "AWAIT_CLAIMS"
    AWAIT_KONG_ROB = "AWAIT_KONG_ROB"  # 搶槓 window on an added-kong declaration, not a discard
    SCORING = "SCORING"
    HAND_OVER = "HAND_OVER"
    GAME_OVER = "GAME_OVER"


class Wind(IntEnum):
    """Prevailing (圈風) or seat (門風) wind, sharing the seat-frame numbering
    (01-rules-spec.md §2): East=0 .. North=3, the same axis `(seat + 1) % 4` "next seat"
    arithmetic already used in melds.py."""

    EAST = 0
    SOUTH = 1
    WEST = 2
    NORTH = 3


class ClaimKind(StrEnum):
    """What opened the live claim window (00-architecture.md §4): a discard, or an
    added-kong declaration opening a robbing-the-kong window (搶槓, 01-rules-spec.md §5,
    §11.3) — "same machinery, different trigger"."""

    DISCARD = "discard"
    KONG_ROB = "kong_rob"


@dataclass(frozen=True)
class ClaimOffer:
    """One eligible seat's live options on the current claim window. Only seats that
    actually have a claim get an offer (00-architecture.md §4: "only offer claims to
    players who actually have one" — broadcasting "someone may claim" leaks information).
    `melds` never includes a win option — winning isn't a meld (melds.py) — so `can_win` is
    a separate flag.
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
    """Live `AWAIT_CLAIMS`/`AWAIT_KONG_ROB` state (00-architecture.md §4): what's being
    offered to whom, so claims.py/engine.py (later sub-tasks) can resolve it. `deadline_ts`
    is carried as an opaque value only — the pure engine never reads a clock or compares it
    against one; arming and enforcing the actual timer is app/table.py's job
    (server/AGENTS.md: "a clock, socket or random value... belongs in app/").
    """

    window_id: int
    kind: ClaimKind
    source_seat: int  # discarder (DISCARD) or kong-declarer (KONG_ROB)
    tile: TileId
    offers: tuple[ClaimOffer, ...]
    responses: Mapping[int, ClaimResponse] = field(default_factory=dict)
    # accumulated across separate reduce() calls -- one per seat's Pass/Claim* action --
    # since a claim window genuinely waits on multiple independent actors (00-architecture.md
    # §4). Keyed by seat. engine.py is the only writer; a seat missing here is an implicit
    # Pass, same convention claims.py's resolve_claims/can_close_early already use.
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
    """How a hand ended (01-rules-spec.md §4, §9) -- the hand-result field this module's
    class docstring above flagged as engine.py's addition."""

    WIN = "win"
    EXHAUSTIVE_DRAW = "exhaustive_draw"  # 流局, §9


class WinType(StrEnum):
    """How the winning tile was obtained -- affects New-6 faan patterns (01-rules-spec.md
    §7: 自摸/海底撈月/搶槓). `FLOWERS` is the instant-win variant (§7 "Flower faan",
    `seven_flowers_instant_win`/`eight_flowers_instant_win`): it ends the hand on flower
    count alone, with no winning tile and no meld decomposition, so it's its own value
    rather than forced into `SELF_DRAW` -- engine.py's scoring skips `scoring.faan` entirely
    for it (patterns.py's "What doesn't fit here" note) but still pays out like a self-draw
    (no seat fed the win)."""

    SELF_DRAW = "self_draw"
    DISCARD = "discard"
    KONG_ROB = "kong_rob"
    FLOWERS = "flowers"


@dataclass(frozen=True)
class HandResult:
    """The outcome of the hand that just ended, carried on `GameState.hand_result` only
    while `phase == Phase.HAND_OVER` -- cleared once the next hand deals or the game ends.

    `faan`/`faan_breakdown`/`points`/`payments` are only populated for `HandOutcome.WIN`
    (engine.py's `_finish_win`) -- an `EXHAUSTIVE_DRAW` carries none of them (no
    `tenpai_payments` support yet, see config.py). `payments` is the per-seat point delta,
    keyed by seat, summing to zero -- `scoring.payout.payout`'s own contract.
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
    """Final result of a completed game (`Phase.GAME_OVER`) -- one component of the
    `GameRecord` `docs/06-ml.md §2` defines for persistence. Mirrors `engine.GameEnded`'s
    payload, the only other place this data already exists, pulled out as its own type so
    `app/db` doesn't need to depend on an `Event` just to read a finished game's result.
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
    """One seat's persistent table state. `docs/00-architecture.md §5`'s `SeatView` is
    derived from this (plus redaction) — every field a seat-visible view needs lives here.

    No `seat_status` field: connected/disconnected/autoplay/bot (00-architecture.md §5's
    `SeatView.seat_status`) is session state owned by `app/table.py`'s `SeatBinding`
    (00-architecture.md §3), not the pure engine. `reduce()` never needs to know whether a
    seat is a human, a disconnected human, or a bot to compute the next `GameState` — only
    `app/table.py` (which owns sockets, timers and bot dispatch) cares, and layering it in at
    `seat_view()` time keeps `mahjong_core` free of exactly the "clock, socket, or random
    value" server/AGENTS.md reserves for `app/`.
    """

    concealed: tuple[TileId, ...]
    melds: tuple[Meld, ...] = ()
    discards: tuple[TileId, ...] = ()
    flowers: tuple[Flower, ...] = ()
    score: int = 0


Seats = tuple[SeatState, SeatState, SeatState, SeatState]


@dataclass(frozen=True)
class GameState:
    """The whole authoritative table (00-architecture.md §3). Never mutated in place:
    `reduce(state, action) -> (state, events)` (engine.py, a later sub-task) always produces
    a new instance. `SeatView` (app/views.py, later) is derived from this by redaction;
    nothing here is ever serialized to a client directly.
    """

    ruleset: RuleSet
    game_seed: int
    # game_seed never leaves this process, not even redacted, not ever during play
    # (00-architecture.md §3, D2). Kept on GameState (not just passed to `new_game` and
    # dropped) because engine.py derives every later hand's `hand_seed` from it, and
    # Table.__init__ (00-architecture.md §3) keeps no separate copy of its own — GameState is
    # the only place it lives, which is why it's a stdlib int and never touches app/protocol.
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
    # count of discards so far this hand -- engine.py's win-timing context (天糊/地糊,
    # 01-rules-spec.md §7): 0 means nobody has discarded yet (only the dealer can win with
    # this true), 1 on the dealer's own first discard, checked at claim-resolution time.
    wall_exhausted_at_last_draw: bool = False
    # whether the most recent draw (front or back, any seat) brought the wall to
    # `ruleset.wall_reserve` or below -- 海底撈月/河底撈魚's "last tile" flag. Monotonic
    # within a hand: once true it stays true (no further draw can un-exhaust the wall), reset
    # to False only by the next hand's deal.
    last_draw_was_kong_replacement: bool = False
    # whether the most recent draw was a kong replacement (back-of-wall) rather than a normal
    # front draw -- 槓上開花's flag, read only together with a self-draw win on that same turn.
    self_draw_win_allowed: bool = True
    # whether the current AWAIT_ACTION turn may end by self-draw win. True at the start of a
    # hand (heavenly hand) and after any draw; False after a chow/pung claim, since the claimer
    # did not draw the tile and already passed on claiming it as a win.

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
    """`hand_seed = SHA256(game_seed || hand_no)` (00-architecture.md §3). Only `hand_seed`
    is ever revealed, and only at that hand's end — `game_seed` never goes with it. Matches
    the `f"{game_seed}:{hand_no}"` encoding tests/test_wall.py's own seed helper already
    uses, so hand_seeds derived here and in those tests agree for the same inputs.
    """
    return hashlib.sha256(f"{game_seed}:{hand_no}".encode()).digest()


def _as_tile_ids(tiles: Sequence[WallTile]) -> tuple[TileId, ...]:
    """Narrow a post-flower-replacement hand from `WallTile` to `TileId`. `replace_flowers`
    guarantees no `Flower` remains; this only makes that guarantee visible to mypy."""
    assert not any(isinstance(t, Flower) for t in tiles), "flower tile survived replace_flowers"
    return tuple(cast(TileId, t) for t in tiles)


def new_game(ruleset: RuleSet, game_seed: int) -> GameState:
    """Deal and resolve hand 1 (01-rules-spec.md §3): shuffle, deal 13/14, replace flowers,
    and land in `AWAIT_ACTION` with the dealer to discard. The dealer's post-deal 14th tile
    stands in for the "draw" the turn diagram (01-rules-spec.md §4) would otherwise show as
    a separate `AWAIT_DRAW` step, so hand 1 starts one step further along than every later
    hand will after a normal draw.

    Hand-to-hand transitions — dealer rotation, prevailing-wind advance, scoring, dealing
    hand 2 onward — are engine.py's job (a later sub-task), not this function's
    (05-roadmap.md §1).
    """
    dealer = 0  # East seats first for hand 1 (01-rules-spec.md §2); rotation is engine.py's job
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
