"""Engine output events: one frozen dataclass per variant, tagged by `EventKind`. Produced only
by `engine.reduce`/`engine.start_next_hand`; redacted per recipient by `app/views.py`."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from mahjong_core.actions import ActionKind
from mahjong_core.melds import Meld
from mahjong_core.state import ClaimKind, HandOutcome, WinType
from mahjong_core.tiles import Flower, TileId

__all__ = [
    "ClaimResolved",
    "Discarded",
    "Drawn",
    "Event",
    "EventKind",
    "FlowerReplaced",
    "GameEnded",
    "HandEnded",
    "KongReplacementDrawn",
    "MeldFormed",
]


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
