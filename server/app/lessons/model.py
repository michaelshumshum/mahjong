"""Lesson vocabulary and position specs. Tiles are written in `parse_tiles` compact notation
(`"123m456p789s1122z"`); `position.build_position` turns a spec into a `GameState`."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from mahjong_core.actions import Action
from mahjong_core.melds import MeldKind
from mahjong_core.presets import RULESET_PRESETS
from mahjong_core.state import Wind

# pinned (adr 0025): must not follow DEFAULT_PRESET_ID
LESSON_RULESET = RULESET_PRESETS["hk_classic"]


class PuzzleKind(StrEnum):
    WINNING_TILES = "winning_tiles"
    BEST_DISCARD = "best_discard"
    COUNT_FAAN = "count_faan"
    SAFE_DISCARD = "safe_discard"


class SafeReason(StrEnum):
    """Why a `safe_discard` answer is safe, judged on what seat 0 can see. A stated fact, not a
    proof: the answer key also checks every accepted tile against the real hands."""

    # in every opponent's own pool. weak in hk: no furiten
    GENBUTSU = "genbutsu"
    # every copy visible: nobody holds one, so no pair or pung wait on it
    ALL_COPIES_VISIBLE = "all_copies_visible"
    # suited, and every run through it has another member with every copy visible: no run wait
    NO_CHANCE = "no_chance"


class LessonKind(StrEnum):
    PUZZLE = "puzzle"
    TUTORIAL = "tutorial"


class Band(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class Track(StrEnum):
    """`/learn`'s sections, in display order: hand-written basics, then one per puzzle kind."""

    BASICS = "basics"
    WAITS = "waits"
    EFFICIENCY = "efficiency"
    DEFENCE = "defence"
    FAAN = "faan"


@dataclass(frozen=True)
class MeldSetup:
    kind: MeldKind
    tiles: str
    from_seat: int | None = None


@dataclass(frozen=True)
class SeatSetup:
    """`discards` are the tiles still in this seat's pool; a claimed discard sits only in the
    claimer's meld."""

    hand: str = ""
    melds: tuple[MeldSetup, ...] = ()
    discards: str = ""
    flowers: str = ""


@dataclass(frozen=True)
class Position:
    """`turn` has just drawn and is to act (`AWAIT_ACTION`); claim positions are reached by
    reducing a `Discard` from the state before, never built here. `wall_front` is the next
    front draws in order; the rest of the wall is shuffled from `seed`."""

    seats: tuple[SeatSetup, SeatSetup, SeatSetup, SeatSetup]
    turn: int = 0
    dealer: int = 0
    prevailing: Wind = Wind.EAST
    wall_front: str = ""
    seed: int = 0


@dataclass(frozen=True)
class FromSeed:
    """A position reached by play: `new_game(LESSON_RULESET, seed)` then `actions`. Breaks on
    any change to dealing, so prefer `Position`."""

    seed: int
    actions: tuple[Action, ...] = ()


@dataclass(frozen=True)
class Puzzle:
    """A catalog entry, posed to seat 0. `answer` is the author's, checked against the engine's
    key: tile codes for the tile kinds (`safe_discard`: the accepted tiles, `reason` saying why),
    the total faan for `count_faan`. `discard` (`count_faan` only): the tile the seat to act
    discards into seat 0's win; `None` is a self-draw. `text` is the message stem, read as
    `lesson_<text>_title|prompt|explain`."""

    id: str
    kind: PuzzleKind
    track: Track
    band: Band
    position: Position | FromSeed
    answer: tuple[str, ...] | int
    text: str
    reason: SafeReason | None = None
    discard: str | None = None
