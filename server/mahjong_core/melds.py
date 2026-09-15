"""Meld types, claim legality, and concealed-tile decomposition (docs/01-rules-spec.md §5, §6;
docs/00-architecture.md §4).

stdlib-only, see mahjong_core/config.py's note on pyproject.toml.

Scope (docs/05-roadmap.md §1): the meld data model, what claims are legal against a discard
or your own draw, and splitting a concealed hand into melds + a pair. Claim *priority*
between simultaneously-legal claims (claims.py), the turn state machine (engine.py), and
`legal_actions` (actions.py) are later sub-tasks that build on this one.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from mahjong_core.tiles import TileId, TileType, tile_id_type

_SUIT_TYPE_COUNT = 27  # types 0-26 are suited (m/p/s), 27-33 are winds/dragons: no chows


class MeldKind(StrEnum):
    """Every way three or more tiles can form a named group (§5). Kong is split into three
    distinct kinds rather than one kind + a flag: exposed/concealed/added differ in how
    they're formed, how they're claimed (added kong alone opens 搶槓, §11.3), and — the part
    that matters most here — whether their tiles are public (`Meld.concealed`)."""

    CHOW = "chow"
    PUNG = "pung"
    EXPOSED_KONG = "exposed_kong"
    CONCEALED_KONG = "concealed_kong"
    ADDED_KONG = "added_kong"
    PAIR = "pair"


_MELD_SIZES: dict[MeldKind, int] = {
    MeldKind.CHOW: 3,
    MeldKind.PUNG: 3,
    MeldKind.EXPOSED_KONG: 4,
    MeldKind.CONCEALED_KONG: 4,
    MeldKind.ADDED_KONG: 4,
    MeldKind.PAIR: 2,
}

KONG_KINDS = frozenset({MeldKind.EXPOSED_KONG, MeldKind.CONCEALED_KONG, MeldKind.ADDED_KONG})


@dataclass(frozen=True)
class Meld:
    """One meld: a chow, pung, kong (of any of the three kinds), or a pair.

    `tiles` always holds true tile identities — this module is inside `mahjong_core`, which
    never redacts (00-architecture.md §5 redaction is `app/views.py`'s job, at the seat-view
    layer, not the pure engine's). `concealed` is what that later layer reads to decide
    whether it may reveal them: a concealed kong (暗槓) is laid face down and its identity
    stays hidden from every other seat until hand end, unlike every other meld kind, which is
    exposed the instant it's formed.

    `from_seat` records whose discard was claimed (chow/pung/exposed_kong). It's `None` for
    concealed_kong and added_kong, both formed from your own draw rather than a claim, and for
    any meld produced by `decompose()`, which reasons about concealed tiles with no claim
    history attached.
    """

    kind: MeldKind
    tiles: tuple[TileId, ...]
    from_seat: int | None = None

    def __post_init__(self) -> None:
        expected = _MELD_SIZES[self.kind]
        if len(self.tiles) != expected:
            raise ValueError(f"{self.kind} needs {expected} tiles, got {len(self.tiles)}")
        if len(set(self.tiles)) != len(self.tiles):
            raise ValueError(f"{self.kind} tiles must be distinct physical tiles: {self.tiles}")

        types = [tile_id_type(t) for t in self.tiles]
        if self.kind == MeldKind.CHOW:
            a, b, c = sorted(types)
            if not (a < _SUIT_TYPE_COUNT and a % 9 <= 6 and b == a + 1 and c == a + 2):
                raise ValueError(f"not a valid chow: tile types {types}")
        elif len(set(types)) != 1:
            raise ValueError(f"{self.kind} needs identical tile types, got {types}")

        if self.from_seat is not None:
            if not 0 <= self.from_seat < 4:
                raise ValueError(f"from_seat must be 0..3, got {self.from_seat}")
            if self.kind in (MeldKind.CONCEALED_KONG, MeldKind.PAIR):
                raise ValueError(f"{self.kind} cannot have a from_seat (never claimed)")

        object.__setattr__(self, "tiles", tuple(sorted(self.tiles)))

    @property
    def concealed(self) -> bool:
        """Whether this meld's tile identities must stay hidden from other seats (§5)."""
        return self.kind == MeldKind.CONCEALED_KONG

    @property
    def is_kong(self) -> bool:
        return self.kind in KONG_KINDS

    @property
    def tile_type(self) -> TileType:
        """The `TileType` this meld is built from (a chow's lowest-rank tile)."""
        return min(tile_id_type(t) for t in self.tiles)


def legal_claims(
    concealed: Sequence[TileId],
    discarded_tile: TileId,
    discarder_seat: int,
    claimer_seat: int,
) -> tuple[Meld, ...]:
    """Every meld `claimer_seat` could legally form by claiming `discarded_tile` off
    `discarder_seat`'s discard, given only `claimer_seat`'s concealed hand (§5, §6;
    00-architecture.md §4). Win claims aren't melds and aren't covered here. This answers
    "is X a legal option for this one claimer" — it doesn't arbitrate between simultaneously
    legal claims from different seats (claims.py's job, a later sub-task).

    A holder of 3 concealed matching tiles gets *both* a pung and an exposed-kong option:
    the kong-vs-pung tiebreak in 01-rules-spec.md §6 is about two different players each
    claiming the same discard as pung vs. kong, not about restricting one player's own
    choice — a player may still elect the smaller meld. See the note added to
    01-rules-spec.md §5.
    """
    if not 0 <= discarder_seat < 4 or not 0 <= claimer_seat < 4:
        raise ValueError("seats must be 0..3")
    if discarder_seat == claimer_seat:
        raise ValueError("a seat cannot claim its own discard")

    discard_type = tile_id_type(discarded_tile)
    matching = sorted(t for t in concealed if tile_id_type(t) == discard_type)

    claims: list[Meld] = []
    if len(matching) >= 3:
        claims.append(
            Meld(MeldKind.EXPOSED_KONG, (*matching[:3], discarded_tile), from_seat=discarder_seat)
        )
    if len(matching) >= 2:
        claims.append(
            Meld(MeldKind.PUNG, (*matching[:2], discarded_tile), from_seat=discarder_seat)
        )
    if claimer_seat == (discarder_seat + 1) % 4:
        claims.extend(_chow_options(concealed, discarded_tile, discarder_seat))
    return tuple(claims)


def _chow_options(
    concealed: Sequence[TileId], discarded_tile: TileId, discarder_seat: int
) -> tuple[Meld, ...]:
    """Every chow `discarded_tile` could complete, one per position (low/mid/high) it could
    occupy in the run. A middle tile with concealed tiles on both sides yields more than one
    legal option — e.g. holding 3m,4m,6m,7m on a 5m discard offers (3,4,5), (4,5,6), (5,6,7)."""
    discard_type = tile_id_type(discarded_tile)
    if discard_type >= _SUIT_TYPE_COUNT:
        return ()

    suit_base = (discard_type // 9) * 9
    rank = discard_type % 9
    by_type: dict[TileType, list[TileId]] = {}
    for t in concealed:
        by_type.setdefault(tile_id_type(t), []).append(t)
    for ids in by_type.values():
        ids.sort()

    options: list[Meld] = []
    for offset in (-2, -1, 0):
        low = rank + offset
        if low < 0 or low + 2 > 8:
            continue
        run = [TileType(suit_base + low + k) for k in range(3)]
        picks: list[TileId] = []
        for run_type in run:
            if run_type == discard_type:
                continue
            available = by_type.get(run_type)
            if not available:
                break
            picks.append(available[0])
        else:
            options.append(Meld(MeldKind.CHOW, (*picks, discarded_tile), from_seat=discarder_seat))
    return tuple(options)


def legal_self_melds(
    concealed: Sequence[TileId], exposed_melds: Sequence[Meld] = ()
) -> tuple[Meld, ...]:
    """Concealed-kong and added-kong options available on your own turn (§5). `concealed` is
    the seat's full concealed hand including whatever tile was just drawn — legality only
    depends on which tiles are currently held, not on which one arrived last, so there's no
    separate `drawn_tile` parameter the way `legal_claims` has `discarded_tile`."""
    by_type: dict[TileType, list[TileId]] = {}
    for t in concealed:
        by_type.setdefault(tile_id_type(t), []).append(t)

    options: list[Meld] = []
    for ids in by_type.values():
        if len(ids) >= 4:
            options.append(Meld(MeldKind.CONCEALED_KONG, tuple(sorted(ids[:4]))))

    for meld in exposed_melds:
        if meld.kind != MeldKind.PUNG:
            continue
        match = by_type.get(meld.tile_type)
        if match:
            options.append(
                Meld(MeldKind.ADDED_KONG, (*meld.tiles, match[0]), from_seat=meld.from_seat)
            )
    return tuple(options)


def decompose(tiles: Sequence[TileId]) -> tuple[tuple[Meld, ...], ...]:
    """Every way `tiles` can be fully partitioned into complete chow/pung melds plus exactly
    one pair, using each tile exactly once (§5; the shanten/hand-validity building block
    flagged in docs/05-roadmap.md §1). Returns one tuple-of-melds per valid split; empty if
    `tiles` can't be decomposed this way at all — the normal case for a hand mid-shanten,
    which is exactly what shanten.py needs to detect.

    Kongs never appear here: a declared kong already lives in a seat's exposed melds, never
    in its concealed tiles, so this function only ever needs chows, pungs, and the one pair —
    the shape every standard shanten algorithm decomposes into. Seven Pairs and Thirteen
    Orphans are different hand shapes entirely (mahjong_core/shanten.py, a later sub-task),
    not this function's concern.
    """
    if len(tiles) % 3 != 2:
        return ()

    counts = [0] * 34
    queues: list[deque[TileId]] = [deque() for _ in range(34)]
    for t in tiles:
        tt = int(tile_id_type(t))
        counts[tt] += 1
        queues[tt].append(t)
    for q in queues:
        q_sorted = deque(sorted(q))
        q.clear()
        q.extend(q_sorted)

    results: list[tuple[Meld, ...]] = []
    trail: list[tuple[MeldKind, int]] = []

    def backtrack(counts: list[int], pair_used: bool) -> None:
        idx = next((i for i, c in enumerate(counts) if c > 0), None)
        if idx is None:
            if pair_used:
                results.append(_materialize(trail, queues))
            return

        if not pair_used and counts[idx] >= 2:
            counts[idx] -= 2
            trail.append((MeldKind.PAIR, idx))
            backtrack(counts, True)
            trail.pop()
            counts[idx] += 2

        if counts[idx] >= 3:
            counts[idx] -= 3
            trail.append((MeldKind.PUNG, idx))
            backtrack(counts, pair_used)
            trail.pop()
            counts[idx] += 3

        if (
            idx < _SUIT_TYPE_COUNT
            and idx % 9 <= 6
            and counts[idx] >= 1
            and counts[idx + 1] >= 1
            and counts[idx + 2] >= 1
        ):
            counts[idx] -= 1
            counts[idx + 1] -= 1
            counts[idx + 2] -= 1
            trail.append((MeldKind.CHOW, idx))
            backtrack(counts, pair_used)
            trail.pop()
            counts[idx] += 1
            counts[idx + 1] += 1
            counts[idx + 2] += 1

    backtrack(counts, False)
    return tuple(results)


def _materialize(
    trail: Sequence[tuple[MeldKind, int]], queues: Sequence[deque[TileId]]
) -> tuple[Meld, ...]:
    """Assign concrete `TileId`s to a group-shape trail found by `decompose`'s backtracking.
    Physical tiles of the same type are interchangeable for legality, so a fresh, deterministic
    (sorted) per-type queue is popped from in trail order — no further branching needed here."""
    work = [deque(q) for q in queues]
    melds: list[Meld] = []
    for kind, start in trail:
        if kind == MeldKind.CHOW:
            picked = tuple(work[start + k].popleft() for k in range(3))
        else:
            picked = tuple(work[start].popleft() for _ in range(_MELD_SIZES[kind]))
        melds.append(Meld(kind, picked))
    return tuple(melds)
