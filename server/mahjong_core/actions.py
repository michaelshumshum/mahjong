"""Action union and `legal_actions(state, seat)` (docs/05-roadmap.md §1).

Scope (docs/01-rules-spec.md §4, §6; docs/00-architecture.md §4): every action a seat may
take from `GameState`, and the pure function enumerating which of them are legal for a given
seat right now. `reduce(state, action) -> (state, events)` (engine.py, a later sub-task)
applies one of these; claim *priority* between simultaneously-legal claims from different
seats (claims.py) is a separate later sub-task too — this module only answers "what can this
one seat do", the same scope `melds.py`'s `legal_claims`/`legal_self_melds` already have for
melds specifically.

**`AWAIT_DRAW` offers no actions.** `docs/02-protocol.md §2` has no client intent for
"draw" — a seat never *chooses* to draw, the engine advances it automatically (including any
flower-replacement chain, 01-rules-spec.md §3 step 4) on the way to `AWAIT_ACTION`. So
`AWAIT_DRAW` is never a phase where a seat is expected to decide anything, and
`legal_actions` returning `()` for every seat in it does not violate the "`legal_actions`
never empty in an active phase" invariant (05-roadmap.md §3) — that invariant is about seats
*expected to act*, and nobody is, here. Same reasoning covers `SCORING`/`HAND_OVER`/
`GAME_OVER`: server-computed transitions, no seat decision.

**Win legality is structural shape plus `min_faan`.** `01-rules-spec.md §11.8` requires a
mechanically-complete hand below `min_faan` to be unable to win, server-side. M1 offered
`DeclareWin`/`ClaimWin` on shape alone (standard melds+pair via `melds.decompose`, Seven
Pairs, Thirteen Orphans) because `scoring/` didn't exist yet to check faan for real; that gap
closed in M2 sub-task 8 (`05-roadmap.md §2`) -- `can_declare_win` below runs the same
`scoring.faan.score_winning_hand` the actual win will be scored with, and only offers
`DeclareWin` when `clears_min_faan` is true. `engine.py`'s claim-offer construction
(`_discard_claim_offers`/`_kong_rob_offers`) does the equivalent for `ClaimWin`, via
`build_scoring_context` below -- offers live there, not here, since they're built while
processing a *different* seat's discard/kong, not this seat's own turn. `hand_sets` gating
of which shapes count is still not a factor here: `score_winning_hand` already applies
`ruleset.hand_sets`/`faan_overrides` internally (faan.py), so a shape worth zero faan under
the table's config (an unregistered hand_set, or every override zeroed) is naturally caught
by the same `clears_min_faan` check, with no separate shape-gating needed here.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from mahjong_core.melds import Meld, MeldKind, decompose, legal_self_melds
from mahjong_core.scoring.faan import score_winning_hand
from mahjong_core.scoring.patterns import ScoringContext, seat_wind_for
from mahjong_core.state import ClaimWindow, GameState, Phase, SeatState
from mahjong_core.tiles import TileId, TileType, tile_id_type


class ActionKind(StrEnum):
    """Discriminator tag, one per `Action` variant below — mirrors `melds.py`'s `MeldKind`
    pattern, applied to a union of distinctly-shaped dataclasses instead of one shared shape,
    since a `Discard` and a `ClaimChow` have nothing but the tag in common."""

    DISCARD = "discard"
    CLAIM_CHOW = "claim_chow"
    CLAIM_PUNG = "claim_pung"
    CLAIM_KONG = "claim_kong"
    CLAIM_WIN = "claim_win"
    PASS = "pass"
    DECLARE_CONCEALED_KONG = "declare_concealed_kong"
    DECLARE_ADDED_KONG = "declare_added_kong"
    DECLARE_WIN = "declare_win"


def _validate_seat(seat: int) -> None:
    if not 0 <= seat < 4:
        raise ValueError(f"seat must be 0..3, got {seat}")


@dataclass(frozen=True)
class Discard:
    """Discard a concealed tile on your own turn (`AWAIT_ACTION`).
    `docs/02-protocol.md` §2 `discard{tile_id}`."""

    tile_id: TileId
    kind: Literal[ActionKind.DISCARD] = ActionKind.DISCARD


@dataclass(frozen=True)
class ClaimChow:
    """Claim a discard to form a chow (`docs/02-protocol.md` §2 `claim{choice:"chow"}`).
    `meld` already carries the exact concealed tiles plus the claimed discard — the same
    `Meld` `melds.legal_claims` produces — so there's no separate `tiles` disambiguator the
    way the wire `claim` message needs one; the meld itself is unambiguous."""

    window_id: int
    seat: int
    meld: Meld
    kind: Literal[ActionKind.CLAIM_CHOW] = ActionKind.CLAIM_CHOW

    def __post_init__(self) -> None:
        _validate_seat(self.seat)
        if self.meld.kind != MeldKind.CHOW:
            raise ValueError(f"ClaimChow needs a chow meld, got {self.meld.kind}")


@dataclass(frozen=True)
class ClaimPung:
    """Claim a discard to form a pung (`claim{choice:"pung"}`)."""

    window_id: int
    seat: int
    meld: Meld
    kind: Literal[ActionKind.CLAIM_PUNG] = ActionKind.CLAIM_PUNG

    def __post_init__(self) -> None:
        _validate_seat(self.seat)
        if self.meld.kind != MeldKind.PUNG:
            raise ValueError(f"ClaimPung needs a pung meld, got {self.meld.kind}")


@dataclass(frozen=True)
class ClaimKong:
    """Claim a discard to complete an exposed kong — the 4th copy of a concealed triple
    (`claim{choice:"kong"}`). 01-rules-spec.md §5's kong-vs-pung note means a holder of 3
    concealed matches sees both `ClaimPung` and `ClaimKong` offered for the same discard and
    picks; that's one seat's own choice, not the different-seats tiebreak in §6."""

    window_id: int
    seat: int
    meld: Meld
    kind: Literal[ActionKind.CLAIM_KONG] = ActionKind.CLAIM_KONG

    def __post_init__(self) -> None:
        _validate_seat(self.seat)
        if self.meld.kind != MeldKind.EXPOSED_KONG:
            raise ValueError(f"ClaimKong needs an exposed_kong meld, got {self.meld.kind}")


@dataclass(frozen=True)
class ClaimWin:
    """Win off someone else's tile — a discard (食糊) or a kong-robbing window (搶槓,
    01-rules-spec.md §11.3). Structurally identical from the claimant's side; which one it is
    lives on `state.claim_window.kind`, not duplicated onto this action."""

    window_id: int
    seat: int
    kind: Literal[ActionKind.CLAIM_WIN] = ActionKind.CLAIM_WIN

    def __post_init__(self) -> None:
        _validate_seat(self.seat)


@dataclass(frozen=True)
class Pass:
    """Decline every option on a live claim window, including a winning one —
    `docs/02-protocol.md` §2 "Declining a claim on purpose": there's no `auto_win` pre-arm,
    since declining a win is a real strategic choice under `min_faan`."""

    window_id: int
    seat: int
    kind: Literal[ActionKind.PASS] = ActionKind.PASS

    def __post_init__(self) -> None:
        _validate_seat(self.seat)


@dataclass(frozen=True)
class DeclareConcealedKong:
    """暗槓 from your own concealed tiles, own turn only (`declare{kind:"concealed_kong"}`)."""

    meld: Meld
    kind: Literal[ActionKind.DECLARE_CONCEALED_KONG] = ActionKind.DECLARE_CONCEALED_KONG

    def __post_init__(self) -> None:
        if self.meld.kind != MeldKind.CONCEALED_KONG:
            raise ValueError(
                f"DeclareConcealedKong needs a concealed_kong meld, got {self.meld.kind}"
            )


@dataclass(frozen=True)
class DeclareAddedKong:
    """加槓: add a matching concealed tile to your own exposed pung, own turn only
    (`declare{kind:"added_kong"}`). Opens a robbing-the-kong window (§5, §11.3) — resolving
    that is claims.py/engine.py's job, not this module's."""

    meld: Meld
    kind: Literal[ActionKind.DECLARE_ADDED_KONG] = ActionKind.DECLARE_ADDED_KONG

    def __post_init__(self) -> None:
        if self.meld.kind != MeldKind.ADDED_KONG:
            raise ValueError(f"DeclareAddedKong needs an added_kong meld, got {self.meld.kind}")


@dataclass(frozen=True)
class DeclareWin:
    """Self-draw win (自摸), own turn only (`declare{kind:"win"}`). No tile payload: the
    whole hand (concealed + exposed melds) is the win, so there's nothing to disambiguate —
    unlike the wire `declare` message, this doesn't need a `tiles` field."""

    kind: Literal[ActionKind.DECLARE_WIN] = ActionKind.DECLARE_WIN


Action = (
    Discard
    | ClaimChow
    | ClaimPung
    | ClaimKong
    | ClaimWin
    | Pass
    | DeclareConcealedKong
    | DeclareAddedKong
    | DeclareWin
)


_ORPHAN_TYPES = frozenset(
    {
        TileType.MAN_1,
        TileType.MAN_9,
        TileType.PIN_1,
        TileType.PIN_9,
        TileType.SOU_1,
        TileType.SOU_9,
        TileType.WIND_EAST,
        TileType.WIND_SOUTH,
        TileType.WIND_WEST,
        TileType.WIND_NORTH,
        TileType.DRAGON_RED,
        TileType.DRAGON_GREEN,
        TileType.DRAGON_WHITE,
    }
)


def _is_seven_pairs(concealed: Sequence[TileId]) -> bool:
    """Seven pairs (七對子): 14 concealed tiles as 7 *distinct* pairs. A table's
    `hand_sets`/`faan_overrides` decide whether this scores anything — see the module
    docstring's boundary note — this only checks the shape."""
    if len(concealed) != 14:
        return False
    counts = Counter(tile_id_type(t) for t in concealed)
    return len(counts) == 7 and all(c == 2 for c in counts.values())


def _is_thirteen_orphans(concealed: Sequence[TileId]) -> bool:
    """Thirteen orphans (十三么): all 13 terminal/honor types present at least once among 14
    concealed tiles (the 14th is necessarily a duplicate of one of them)."""
    if len(concealed) != 14:
        return False
    return {tile_id_type(t) for t in concealed} == _ORPHAN_TYPES


def hand_is_winning_shape(seat: SeatState) -> bool:
    """Whether `seat`'s current hand is a structurally complete winning hand right now —
    standard melds+pair, Seven Pairs, or Thirteen Orphans. See the module docstring: this is
    shape only, no `min_faan` check (deferred to M2). Seven Pairs and Thirteen Orphans both
    require a fully concealed hand by definition — any exposed meld rules both out."""
    if not seat.melds and (_is_seven_pairs(seat.concealed) or _is_thirteen_orphans(seat.concealed)):
        return True
    return decompose(seat.concealed) != ()


def build_scoring_context(
    state: GameState,
    seat: int,
    *,
    self_drawn: bool,
    is_robbing_kong: bool = False,
    discarder: int | None = None,
) -> ScoringContext:
    """The `ScoringContext` for `seat` winning *right now*, real timing flags included --
    shared by this module's own `can_declare_win` (self-declared, always `self_drawn=True`,
    `discarder=None`) and `engine.py`'s claim-offer construction and actual win scoring
    (`_discard_claim_offers`/`_kong_rob_offers`/`_end_win`), so there is exactly one place
    that knows how a `GameState` maps to a `ScoringContext` -- see `GameState.total_discards`/
    `wall_exhausted_at_last_draw`/`last_draw_was_kong_replacement`'s docstrings for what each
    flag below reads.
    """
    seat_state = state.seats[seat]
    return ScoringContext(
        seat_wind=seat_wind_for(seat, state.dealer),
        prevailing_wind=state.prevailing,
        self_drawn=self_drawn,
        flowers=seat_state.flowers,
        won_before_any_discard=(self_drawn and seat == state.dealer and state.total_discards == 0),
        won_on_dealer_first_discard=(
            not self_drawn
            and not is_robbing_kong
            and discarder == state.dealer
            and state.total_discards == 1
        ),
        is_last_tile=state.wall_exhausted_at_last_draw,
        is_kong_replacement=state.last_draw_was_kong_replacement,
        is_robbing_kong=is_robbing_kong,
        flowers_score=state.ruleset.flowers_score,
    )


def can_declare_win(state: GameState, seat: int) -> bool:
    """Whether `seat` may `DeclareWin` right now: structurally complete (`hand_is_winning_shape`)
    *and* clears `state.ruleset.min_faan` under real scoring -- the M1/M2 boundary this
    module's docstring describes. A self-declared win is always self-drawn, off no discarder,
    and is only allowed on a turn that reached AWAIT_ACTION via a draw (or the initial deal).
    """
    if not state.self_draw_win_allowed:
        return False
    seat_state = state.seats[seat]
    if not hand_is_winning_shape(seat_state):
        return False
    ctx = build_scoring_context(state, seat, self_drawn=True)
    result = score_winning_hand(seat_state.concealed, seat_state.melds, ctx, state.ruleset)
    return result.clears_min_faan


def legal_actions(state: GameState, seat: int) -> tuple[Action, ...]:
    """Every action `seat` may legally take right now, given `state.phase`/`state.turn`/
    `state.claim_window`. Pure: no mutation, no I/O. Returns `()` for a seat that isn't
    currently expected to decide anything — see the module docstring for why that's correct
    for `AWAIT_DRAW`, `SCORING`, `HAND_OVER`, `GAME_OVER`, and any seat other than the one
    with a live decision in `AWAIT_ACTION`/`AWAIT_CLAIMS`/`AWAIT_KONG_ROB`.
    """
    _validate_seat(seat)

    if state.phase in (Phase.AWAIT_CLAIMS, Phase.AWAIT_KONG_ROB):
        return _claim_actions(state.claim_window, seat)

    if state.phase != Phase.AWAIT_ACTION or state.turn != seat:
        return ()

    return _turn_actions(state, seat)


def _claim_actions(window: ClaimWindow | None, seat: int) -> tuple[Action, ...]:
    if window is None:
        return ()
    offer = next((o for o in window.offers if o.seat == seat), None)
    if offer is None:
        return ()

    actions: list[Action] = [Pass(window_id=window.window_id, seat=seat)]
    if offer.can_win:
        actions.append(ClaimWin(window_id=window.window_id, seat=seat))
    for meld in offer.melds:
        if meld.kind == MeldKind.CHOW:
            actions.append(ClaimChow(window_id=window.window_id, seat=seat, meld=meld))
        elif meld.kind == MeldKind.PUNG:
            actions.append(ClaimPung(window_id=window.window_id, seat=seat, meld=meld))
        elif meld.kind == MeldKind.EXPOSED_KONG:
            actions.append(ClaimKong(window_id=window.window_id, seat=seat, meld=meld))
        else:
            raise AssertionError(f"unexpected claim-offer meld kind: {meld.kind}")
    return tuple(actions)


def _turn_actions(state: GameState, seat: int) -> tuple[Action, ...]:
    seat_state = state.seats[seat]
    actions: list[Action] = [Discard(tile_id=t) for t in seat_state.concealed]

    for meld in legal_self_melds(seat_state.concealed, seat_state.melds):
        if meld.kind == MeldKind.CONCEALED_KONG:
            actions.append(DeclareConcealedKong(meld=meld))
        else:
            actions.append(DeclareAddedKong(meld=meld))

    if can_declare_win(state, seat):
        actions.append(DeclareWin())

    return tuple(actions)


# --- JSON-safe serialization, for the persisted action log (docs/06-ml.md §2) ----------------


def _meld_to_dict(meld: Meld) -> dict[str, Any]:
    return {"kind": meld.kind.value, "tiles": list(meld.tiles), "from_seat": meld.from_seat}


def _meld_from_dict(data: Mapping[str, Any]) -> Meld:
    return Meld(
        kind=MeldKind(data["kind"]),
        tiles=tuple(TileId(t) for t in data["tiles"]),
        from_seat=data["from_seat"],
    )


def action_to_dict(action: Action) -> dict[str, Any]:
    """JSON-safe representation of one `Action`. Round-trips via `action_from_dict`. Used to
    build the `action_log` a `GameRecord` persists (docs/06-ml.md §2) -- not the fixed
    109-id action *encoding* (06-ml.md §1, M2), which is a distinct, more compact scheme for
    ML consumption, not storage."""
    if isinstance(action, Discard):
        return {"kind": action.kind.value, "tile_id": action.tile_id}
    if isinstance(action, (ClaimChow, ClaimPung, ClaimKong)):
        return {
            "kind": action.kind.value,
            "window_id": action.window_id,
            "seat": action.seat,
            "meld": _meld_to_dict(action.meld),
        }
    if isinstance(action, ClaimWin):
        return {"kind": action.kind.value, "window_id": action.window_id, "seat": action.seat}
    if isinstance(action, Pass):
        return {"kind": action.kind.value, "window_id": action.window_id, "seat": action.seat}
    if isinstance(action, (DeclareConcealedKong, DeclareAddedKong)):
        return {"kind": action.kind.value, "meld": _meld_to_dict(action.meld)}
    if isinstance(action, DeclareWin):
        return {"kind": action.kind.value}
    raise AssertionError(f"unhandled action type: {action!r}")


def action_from_dict(data: Mapping[str, Any]) -> Action:
    kind = ActionKind(data["kind"])
    if kind == ActionKind.DISCARD:
        return Discard(tile_id=TileId(data["tile_id"]))
    if kind == ActionKind.CLAIM_CHOW:
        return ClaimChow(
            window_id=data["window_id"], seat=data["seat"], meld=_meld_from_dict(data["meld"])
        )
    if kind == ActionKind.CLAIM_PUNG:
        return ClaimPung(
            window_id=data["window_id"], seat=data["seat"], meld=_meld_from_dict(data["meld"])
        )
    if kind == ActionKind.CLAIM_KONG:
        return ClaimKong(
            window_id=data["window_id"], seat=data["seat"], meld=_meld_from_dict(data["meld"])
        )
    if kind == ActionKind.CLAIM_WIN:
        return ClaimWin(window_id=data["window_id"], seat=data["seat"])
    if kind == ActionKind.PASS:
        return Pass(window_id=data["window_id"], seat=data["seat"])
    if kind == ActionKind.DECLARE_CONCEALED_KONG:
        return DeclareConcealedKong(meld=_meld_from_dict(data["meld"]))
    if kind == ActionKind.DECLARE_ADDED_KONG:
        return DeclareAddedKong(meld=_meld_from_dict(data["meld"]))
    if kind == ActionKind.DECLARE_WIN:
        return DeclareWin()
    raise AssertionError(f"unhandled action kind: {kind}")
