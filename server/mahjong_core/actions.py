"""Action union and `legal_actions(state, seat)`: what one seat may do right now.

`AWAIT_DRAW`/`SCORING`/`HAND_OVER`/`GAME_OVER` offer no actions — the engine drives those
transitions itself, no seat decision involved.

Win legality is structural shape (`hand_is_winning_shape`) plus a real `min_faan` check via
`score_winning_hand` — a mechanically-complete hand below `min_faan` cannot win.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from mahjong_core.melds import Meld, MeldKind, _is_standard_shape, legal_self_melds
from mahjong_core.scoring.faan import score_winning_hand, seven_pairs_enabled
from mahjong_core.scoring.patterns import ScoringContext, seat_wind_for
from mahjong_core.state import ClaimWindow, GameState, Phase, SeatState, validate_seat
from mahjong_core.tiles import N_TILE_TYPES, ORPHAN_INDICES, ORPHAN_TYPES, TileId, tile_id_type


class ActionKind(StrEnum):
    """Discriminator tag for the `Action` union — variants are distinctly-shaped dataclasses
    that share nothing but this tag."""

    DISCARD = "discard"
    CLAIM_CHOW = "claim_chow"
    CLAIM_PUNG = "claim_pung"
    CLAIM_KONG = "claim_kong"
    CLAIM_WIN = "claim_win"
    PASS = "pass"
    DECLARE_CONCEALED_KONG = "declare_concealed_kong"
    DECLARE_ADDED_KONG = "declare_added_kong"
    DECLARE_WIN = "declare_win"


@dataclass(frozen=True)
class Discard:
    """Discard a concealed tile on your own turn (`AWAIT_ACTION`)."""

    tile_id: TileId
    kind: Literal[ActionKind.DISCARD] = ActionKind.DISCARD


@dataclass(frozen=True)
class ClaimChow:
    """`meld` already carries the concealed tiles plus the claimed discard, so no separate
    `tiles` disambiguator is needed."""

    window_id: int
    seat: int
    meld: Meld
    kind: Literal[ActionKind.CLAIM_CHOW] = ActionKind.CLAIM_CHOW

    def __post_init__(self) -> None:
        validate_seat(self.seat)
        if self.meld.kind != MeldKind.CHOW:
            raise ValueError(f"ClaimChow needs a chow meld, got {self.meld.kind}")


@dataclass(frozen=True)
class ClaimPung:
    window_id: int
    seat: int
    meld: Meld
    kind: Literal[ActionKind.CLAIM_PUNG] = ActionKind.CLAIM_PUNG

    def __post_init__(self) -> None:
        validate_seat(self.seat)
        if self.meld.kind != MeldKind.PUNG:
            raise ValueError(f"ClaimPung needs a pung meld, got {self.meld.kind}")


@dataclass(frozen=True)
class ClaimKong:
    """A holder of 3 concealed matches sees both `ClaimPung` and `ClaimKong` offered for the
    same discard and picks — that's this seat's own choice, distinct from the cross-seat
    tiebreak in `claims.resolve_claims`."""

    window_id: int
    seat: int
    meld: Meld
    kind: Literal[ActionKind.CLAIM_KONG] = ActionKind.CLAIM_KONG

    def __post_init__(self) -> None:
        validate_seat(self.seat)
        if self.meld.kind != MeldKind.EXPOSED_KONG:
            raise ValueError(f"ClaimKong needs an exposed_kong meld, got {self.meld.kind}")


@dataclass(frozen=True)
class ClaimWin:
    """Win off another seat's tile — a discard or a kong-rob window. Which one it is lives on
    `state.claim_window.kind`, not duplicated onto this action."""

    window_id: int
    seat: int
    kind: Literal[ActionKind.CLAIM_WIN] = ActionKind.CLAIM_WIN

    def __post_init__(self) -> None:
        validate_seat(self.seat)


@dataclass(frozen=True)
class Pass:
    """Decline every option on a live claim window, including a winning one — there's no
    `auto_win` pre-arm, since declining a win is a real strategic choice under `min_faan`."""

    window_id: int
    seat: int
    kind: Literal[ActionKind.PASS] = ActionKind.PASS

    def __post_init__(self) -> None:
        validate_seat(self.seat)


@dataclass(frozen=True)
class DeclareConcealedKong:
    """暗槓 from your own concealed tiles, own turn only."""

    meld: Meld
    kind: Literal[ActionKind.DECLARE_CONCEALED_KONG] = ActionKind.DECLARE_CONCEALED_KONG

    def __post_init__(self) -> None:
        if self.meld.kind != MeldKind.CONCEALED_KONG:
            raise ValueError(
                f"DeclareConcealedKong needs a concealed_kong meld, got {self.meld.kind}"
            )


@dataclass(frozen=True)
class DeclareAddedKong:
    """加槓: add a matching concealed tile to your own exposed pung, own turn only. Opens a
    robbing-the-kong window — resolving that is claims.py/engine.py's job, not this module's."""

    meld: Meld
    kind: Literal[ActionKind.DECLARE_ADDED_KONG] = ActionKind.DECLARE_ADDED_KONG

    def __post_init__(self) -> None:
        if self.meld.kind != MeldKind.ADDED_KONG:
            raise ValueError(f"DeclareAddedKong needs an added_kong meld, got {self.meld.kind}")


@dataclass(frozen=True)
class DeclareWin:
    """Self-draw win (自摸), own turn only. No tile payload: the whole hand is the win."""

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


def _is_seven_pairs(concealed: Sequence[TileId]) -> bool:
    """Seven pairs (七對子): 14 concealed tiles as 7 *distinct* pairs. Shape only — whether it
    scores depends on the table's `hand_sets`/`faan_overrides`."""
    if len(concealed) != 14:
        return False
    counts = Counter(tile_id_type(t) for t in concealed)
    return len(counts) == 7 and all(c == 2 for c in counts.values())


def _is_thirteen_orphans(concealed: Sequence[TileId]) -> bool:
    """Thirteen orphans (十三么): all 13 terminal/honor types present at least once among 14
    concealed tiles (the 14th is necessarily a duplicate of one of them)."""
    if len(concealed) != 14:
        return False
    return {tile_id_type(t) for t in concealed} == ORPHAN_TYPES


def hand_is_winning_shape(seat: SeatState, *, seven_pairs: bool = True) -> bool:
    """Structurally complete hand right now — standard melds+pair, Seven Pairs, or Thirteen
    Orphans. Shape only, no `min_faan` check. Seven Pairs/Thirteen Orphans require a fully
    concealed hand; any exposed meld rules both out. `seven_pairs=False` drops Seven Pairs
    (ruleset doesn't score it, `seven_pairs_enabled`)."""
    return _is_winning_shape(seat.concealed, closed=not seat.melds, seven_pairs=seven_pairs)


def _is_winning_shape(
    concealed: Sequence[TileId], *, closed: bool, seven_pairs: bool = True
) -> bool:
    """`hand_is_winning_shape` on one 34-array pass; equivalence-tested against the
    `_is_seven_pairs`/`_is_thirteen_orphans`/`decompose` form in tests/test_winning_shape.py."""
    if len(concealed) % 3 != 2:
        return False
    counts = [0] * N_TILE_TYPES
    for t in concealed:
        counts[tile_id_type(t)] += 1
    if closed and len(concealed) == 14:
        if seven_pairs and all(c == 0 or c == 2 for c in counts):
            return True
        if all(counts[i] for i in ORPHAN_INDICES) and sum(counts[i] for i in ORPHAN_INDICES) == 14:
            return True
    return _is_standard_shape(counts)


def build_scoring_context(
    state: GameState,
    seat: int,
    *,
    self_drawn: bool,
    is_robbing_kong: bool = False,
    discarder: int | None = None,
    winning_tile: TileId | None = None,
) -> ScoringContext:
    """The `ScoringContext` for `seat` winning *right now*. Shared by `can_declare_win` here
    and `engine.py`'s claim-offer construction/win scoring, so there's exactly one place that
    maps a `GameState` to a `ScoringContext`."""
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
        is_chained_kong_replacement=state.kong_replacement_streak >= 2,
        is_robbing_kong=is_robbing_kong,
        flowers_score=state.ruleset.flowers_score,
        winning_tile=winning_tile,
    )


def can_declare_win(state: GameState, seat: int) -> bool:
    """Whether `seat` may `DeclareWin` right now: structurally complete
    (`hand_is_winning_shape`) *and* clears `state.ruleset.min_faan` under real scoring."""
    if not state.self_draw_win_allowed:
        return False
    seat_state = state.seats[seat]
    if not hand_is_winning_shape(seat_state, seven_pairs=seven_pairs_enabled(state.ruleset)):
        return False
    ctx = build_scoring_context(state, seat, self_drawn=True)
    result = score_winning_hand(seat_state.concealed, seat_state.melds, ctx, state.ruleset)
    return result.clears_min_faan


# one-entry memo on state identity: a table tick asks for the same frozen state's turn actions
# ~4 times (mask, authorize, reduce, publish). only state.turn reaches it, so seat isn't keyed.
_last_turn_actions: tuple[GameState, tuple[Action, ...]] | None = None


def legal_actions(state: GameState, seat: int) -> tuple[Action, ...]:
    """Every action `seat` may legally take right now. Returns `()` for a seat not currently
    expected to decide anything (see module docstring)."""
    validate_seat(seat)

    if state.phase in (Phase.AWAIT_CLAIMS, Phase.AWAIT_KONG_ROB):
        return _claim_actions(state.claim_window, seat)

    if state.phase != Phase.AWAIT_ACTION or state.turn != seat:
        return ()

    global _last_turn_actions
    last = _last_turn_actions
    if last is not None and last[0] is state:
        return last[1]
    actions = _turn_actions(state, seat)
    _last_turn_actions = (state, actions)
    return actions


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


def _meld_to_dict(meld: Meld) -> dict[str, Any]:
    return {"kind": meld.kind.value, "tiles": list(meld.tiles), "from_seat": meld.from_seat}


def _meld_from_dict(data: Mapping[str, Any]) -> Meld:
    return Meld(
        kind=MeldKind(data["kind"]),
        tiles=tuple(TileId(t) for t in data["tiles"]),
        from_seat=data["from_seat"],
    )


def action_to_dict(action: Action) -> dict[str, Any]:
    """JSON-safe representation of one `Action`, round-trips via `action_from_dict`. Used for
    the persisted action log — distinct from the compact fixed-id ML action encoding."""
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
