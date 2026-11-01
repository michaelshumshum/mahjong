"""Lesson vocabulary and position specs. Tiles are written in `parse_tiles` compact notation
(`"123m456p789s1122z"`); `position.build_position` turns a spec into a `GameState`."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from mahjong_core.actions import Action, ActionKind
from mahjong_core.melds import MeldKind
from mahjong_core.presets import RULESET_PRESETS
from mahjong_core.state import Phase, Wind

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


class PuzzleTheme(StrEnum):
    """What a mined puzzle teaches, its title on `/learn`. `themes.puzzle_theme` reads it off
    the answer key and seat 0's hand; `THEMES_BY_KIND` lists each kind's themes in the order
    the classifier tries them."""

    # winning_tiles
    TOO_CHEAP = "too_cheap"
    DEAD_WAIT = "dead_wait"
    MANY_SIDED = "many_sided"
    TWO_SIDED = "two_sided"
    PAIR_WAIT = "pair_wait"
    SINGLE_WAIT = "single_wait"
    EDGE_CLOSED = "edge_closed"
    MIXED_WAIT = "mixed_wait"
    # best_discard
    WIDER_WAIT = "wider_wait"
    REACH_READY = "reach_ready"
    TRIM_RUN = "trim_run"
    CUT_TERMINAL = "cut_terminal"
    KEEP_TWO_SIDED = "keep_two_sided"
    CUT_FLOATER = "cut_floater"
    BREAK_PAIR = "break_pair"
    MOST_TILES = "most_tiles"
    # safe_discard
    GENBUTSU = "genbutsu"
    WALLED_RUNS = "walled_runs"
    DEAD_HONOUR = "dead_honour"
    ALL_VISIBLE = "all_visible"
    # count_faan
    LIMIT_HAND = "limit_hand"
    FULL_FLUSH = "full_flush"
    HALF_FLUSH_PUNGS = "half_flush_pungs"
    HALF_FLUSH_HONOURS = "half_flush_honours"
    HALF_FLUSH = "half_flush"
    ALL_PUNGS = "all_pungs"
    ALL_CHOWS = "all_chows"
    FLOWERS = "flowers"
    SMALL_FAAN = "small_faan"


THEMES_BY_KIND: Mapping[PuzzleKind, tuple[PuzzleTheme, ...]] = {
    PuzzleKind.WINNING_TILES: (
        PuzzleTheme.TOO_CHEAP,
        PuzzleTheme.DEAD_WAIT,
        PuzzleTheme.MANY_SIDED,
        PuzzleTheme.TWO_SIDED,
        PuzzleTheme.PAIR_WAIT,
        PuzzleTheme.SINGLE_WAIT,
        PuzzleTheme.EDGE_CLOSED,
        PuzzleTheme.MIXED_WAIT,
    ),
    PuzzleKind.BEST_DISCARD: (
        PuzzleTheme.WIDER_WAIT,
        PuzzleTheme.REACH_READY,
        PuzzleTheme.TRIM_RUN,
        PuzzleTheme.CUT_TERMINAL,
        PuzzleTheme.KEEP_TWO_SIDED,
        PuzzleTheme.CUT_FLOATER,
        PuzzleTheme.BREAK_PAIR,
        PuzzleTheme.MOST_TILES,
    ),
    PuzzleKind.SAFE_DISCARD: (
        PuzzleTheme.GENBUTSU,
        PuzzleTheme.WALLED_RUNS,
        PuzzleTheme.DEAD_HONOUR,
        PuzzleTheme.ALL_VISIBLE,
    ),
    PuzzleKind.COUNT_FAAN: (
        PuzzleTheme.LIMIT_HAND,
        PuzzleTheme.FULL_FLUSH,
        PuzzleTheme.HALF_FLUSH_PUNGS,
        PuzzleTheme.HALF_FLUSH_HONOURS,
        PuzzleTheme.HALF_FLUSH,
        PuzzleTheme.ALL_PUNGS,
        PuzzleTheme.ALL_CHOWS,
        PuzzleTheme.FLOWERS,
        PuzzleTheme.SMALL_FAAN,
    ),
}


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
    front draws in order, `wall_back` the next back (kong and flower replacement) draws; the
    rest of the wall is shuffled from `seed`."""

    seats: tuple[SeatSetup, SeatSetup, SeatSetup, SeatSetup]
    turn: int = 0
    dealer: int = 0
    prevailing: Wind = Wind.EAST
    wall_front: str = ""
    seed: int = 0
    wall_back: str = ""


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
    `lesson_<text>_prompt|explain`, plus `_title` unless `theme` titles it. `theme` (mined
    puzzles) is checked against `themes.puzzle_theme` like `answer`."""

    id: str
    kind: PuzzleKind
    track: Track
    band: Band
    position: Position | FromSeed
    answer: tuple[str, ...] | int
    text: str
    reason: SafeReason | None = None
    discard: str | None = None
    theme: PuzzleTheme | None = None


class StepKind(StrEnum):
    NARRATE = "narrate"
    EXPECT = "expect"
    AUTO = "auto"


class Highlight(StrEnum):
    """What a `narrate` step points at; the web maps each to a table region."""

    HAND = "hand"
    DISCARDS = "discards"
    CLAIM = "claim"
    WALL = "wall"
    MELDS = "melds"
    HUB = "hub"


@dataclass(frozen=True)
class Move:
    """A scripted action by tile codes, matched against `legal_actions` when the script runs.
    `tiles`: the discard; a claim's own tiles (not the claimed one); a declared kong's four.
    Empty for a win or a pass."""

    kind: ActionKind
    tiles: str = ""


@dataclass(frozen=True)
class Narrate:
    text: str
    highlight: Highlight | None = None


@dataclass(frozen=True)
class Expect:
    """Seat 0 must take `move`; `text` is the hint stem."""

    move: Move
    text: str


@dataclass(frozen=True)
class Auto:
    """Another seat's scripted action."""

    seat: int
    move: Move


type TutorialStep = Narrate | Expect | Auto


@dataclass(frozen=True)
class Tutorial:
    """A guided lesson: `position` (its draws stacked in `wall_front`/`wall_back`) played
    through `steps` for all four seats. `text` is the message stem: the title is
    `lesson_<text>_title`, each step's message `lesson_<text>_<step.text>`. The script must
    leave the hand in `end_phase`."""

    id: str
    track: Track
    band: Band
    position: Position
    steps: tuple[TutorialStep, ...]
    text: str
    end_phase: Phase = Phase.HAND_OVER
