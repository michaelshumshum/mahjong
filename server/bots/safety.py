"""Defence/safety model for T2 `FaanBot` (docs/bots.md §5) -- read that section before
touching this module.

Hand-tuned, not trained. Weights are checked per-signal for *direction* (`tests/test_safety.py`),
not calibrated accuracy: offline, `deal_in_probability` ranks legal waits at AUC ~0.50 across
opponents (docs/ml.md §5). Kept as-is; the learned bot is a separate RL policy.

No `is_safe(tile) -> bool`: every signal is a multiplier into `deal_in_probability`, a float in
`[0, 1]` -- `_provably_safe` (no-chance plus every run and Thirteen Orphans wait blocked) is the
only hard zero. Genbutsu/suji only ever scale the estimate down,
never to exactly zero (HK has no furiten).

**`tile_risk` is hands-aware.** When `view.hands` is populated (the `"ORACLE"` tier's omniscient
view, `app.views._omniscient_seat_view`, docs/bots.md §9) every opponent's real hand is
known, so "does this exact tile complete seat X's exact hand right now" is a direct, cheap, exact
check -- no rollout, no sampling, and no need for the statistical signals above at all for that
tier. `_exact_deal_in_faan` replicates `mahjong_core.engine.can_win_on`'s candidate-hand
pattern outside a live `GameState`/claim window. This is a strict superset: `view.hands is None`
(every other tier) is untouched, byte-for-byte (`tests/test_safety.py::
test_tile_risk_hands_none_matches_the_original_probabilistic_behavior` pins it).
"""

from __future__ import annotations

from collections.abc import Sequence
from statistics import fmean

from app.views import SeatView
from bots.features import is_terminal_or_honor, seen34
from mahjong_core.actions import _is_thirteen_orphans, hand_is_winning_shape
from mahjong_core.scoring.faan import score_winning_hand
from mahjong_core.scoring.patterns import ScoringContext, seat_wind_for
from mahjong_core.shanten import shanten
from mahjong_core.state import SeatState
from mahjong_core.tiles import (
    COPIES_PER_TYPE,
    DRAGON_TYPES,
    N_SUITED_TYPES,
    ORPHAN_INDICES,
    RANKS_PER_SUIT,
    TileId,
    new_count_array,
    tile_id_type,
)

__all__ = [
    "deal_in_probability",
    "expected_cost",
    "is_genbutsu",
    "kong_rob_risk",
    "no_chance",
    "opponent_threat_level",
    "ron_credit",
    "synthetic_tile_id",
    "tile_risk",
    "walls_every_run",
]


_BASE_RATE = 0.06
"""Flat prior P(deal-in) before any signal adjusts it -- not calibrated to a real rate (no
corpus yet); sized so multipliers stay in a believable 0-0.3 range without saturating."""

_ONE_CHANCE_FACTOR = 0.4
"""Soft half of one-chance/no-chance: exactly one copy left. Not a hard constraint, just a real
reduction since only one hidden copy can support the wait."""

_NO_CHANCE_FACTOR = 0.2
"""Every copy accounted for but a run (or Thirteen Orphans) wait through the tile still open:
pair/pung/tanki waits are gone, so below one-chance, which still allows them. Hand-set, like the
other factors."""

_RUN_LENGTH = 3

_GENBUTSU_FACTOR = 0.35
"""Weakest-guarantee, highest-volume signal -- largest reduction here short of `no_chance`,
never 0 (HK has no furiten)."""

_SUJI_FACTOR = 0.75
"""Smaller reduction than genbutsu -- suji's force in riichi comes entirely from furiten, which
HK doesn't have."""

_MELD_SUIT_DANGER = 1.4
"""2+ melds in one suit plausibly means Half/Full Flush -- same-suit tiles get a danger bump."""

_DRAGON_PUNG_DANGER = 1.5
"""A dragon pung on the table makes the next dragon expensive."""

_TEMPO_THREAT_FACTOR = 1.3
"""A middle-tile discard right after a terminal/honor string often marks a hand that just
reached tenpai."""

_WALL_PRESSURE_TIERS: tuple[tuple[int, float], ...] = ((20, 1.5), (40, 1.2))
"""`(remaining_at_or_below, multiplier)`, checked in order; falls through to 1.0 with plenty of
wall left."""

_ASSUMED_DEALIN_FAAN = 5.0
"""Baseline assumed faan if this discard deals in -- arbitrary but documented (halfway between
min_faan=3 and a half-flush-plus-dragon hand), scaled by `_meld_danger_multiplier`. A relative
cost unit for ranking candidates, never a real point estimate."""

_SHANTEN_THREAT_BASE = 3
"""Real-shanten mapping's zero-crossing for `opponent_threat_level`'s hands-aware branch --
chosen to equal `bots/faanbot.py`'s `_FOLD_SHANTEN` (not imported, to avoid a `safety<->faanbot`
cycle: `faanbot` already imports this module): an opponent within the same shanten distance our
own fold gate treats as "still chasing" is exactly the band this scale should call threatening.
Real shanten 0 (tenpai) -> `3 * _SHANTEN_THREAT_STEP` = 0.9, real shanten 1 -> 0.6, both well past
`_THREAT_THRESHOLD` (0.3, `bots/faanbot.py`) -- decisive, not borderline. Real shanten 3+ -> 0.0,
clamped -- clearly safe. `-1` (opponent already complete) -> 1.2, the scale's max, matching
"worse than any meld-count reading" intent."""
_SHANTEN_THREAT_STEP = 0.3
"""Per-shanten-step weight, deliberately equal to the probabilistic proxy's per-meld weight
(`melds * 0.3` below) -- keeps the two branches on a comparable scale rather than inventing an
unrelated unit: one shanten step closer to tenpai reads as one exposed meld would.

Deliberately shanten-only, not faan-weighted, even though a bigger threatened hand is more
dangerous (the same idea `tile_risk`'s exact-faan already captures for defence). This gate only
decides *whether* `_best_discard` enters pure-defence mode at all; once it does, `tile_risk` --
already hands-aware -- prices each candidate discard's real faan exactly, including returning 0
for a structurally-complete-but-sub-`min_faan` opponent hand. Folding a beat early against a
tenpai opponent who turns out to be sub-minimum costs only tie-break quality among safe discards,
not a real deal-in avoided that shouldn't have been; duplicating `tile_risk`'s value/min_faan
logic here would just re-run that check one level up for no behavioural gain."""


def no_chance(tile_type: int, seen: Sequence[int]) -> bool:
    """Every copy of `tile_type` is accounted for (`seen` counts your own hand too), so no
    opponent holds one concealed: rules out the waits that need a held copy -- pair/pung
    (shanpon), tanki, Seven Pairs. Not run waits *through* `tile_type` (3m+5m waiting 4m holds no
    4m), nor Thirteen Orphans' single wait; `deal_in_probability` checks those separately
    (docs/bots.md §5)."""
    return seen[tile_type] >= COPIES_PER_TYPE


def walls_every_run(tile_type: int, seen: Sequence[int]) -> bool:
    """Every run containing suited `tile_type` has another tile with every copy accounted for,
    so no opponent can hold the two-tile shape that waits on it. `False` for honors (no runs)."""
    if tile_type >= N_SUITED_TYPES:
        return False
    rank = tile_type % RANKS_PER_SUIT
    suit = tile_type - rank
    for start in range(max(0, rank - _RUN_LENGTH + 1), min(rank, RANKS_PER_SUIT - _RUN_LENGTH) + 1):
        others = (suit + start + i for i in range(_RUN_LENGTH) if start + i != rank)
        if not any(no_chance(other, seen) for other in others):
            return False
    return True


def _orphans_wait_open(
    view: SeatView, opponent_seat: int, tile_type: int, seen: Sequence[int]
) -> bool:
    """Whether `opponent_seat` could be waiting on `tile_type` for Thirteen Orphans, which needs
    no copy of the winning tile in hand: closed, and every other orphan type still has a copy
    unaccounted for."""
    if tile_type not in ORPHAN_INDICES or view.melds[opponent_seat]:
        return False
    return not any(no_chance(o, seen) for o in ORPHAN_INDICES if o != tile_type)


def _provably_safe(view: SeatView, opponent_seat: int, tile_type: int, seen: Sequence[int]) -> bool:
    """No wait shape can take `tile_type`: no held copy (pair/pung/tanki), every run through it
    walled, and no Thirteen Orphans wait. The only hard zero in the probabilistic model."""
    if not no_chance(tile_type, seen):
        return False
    if tile_type < N_SUITED_TYPES and not walls_every_run(tile_type, seen):
        return False
    return not _orphans_wait_open(view, opponent_seat, tile_type, seen)


def is_genbutsu(view: SeatView, opponent_seat: int, tile_type: int) -> bool:
    """Whether `tile_type` sits in `opponent_seat`'s own discard pool -- weak evidence in HK,
    never a guarantee."""
    return any(int(tile_id_type(t)) == tile_type for t in view.discard_pools[opponent_seat])


def _is_suji(view: SeatView, opponent_seat: int, tile_type: int) -> bool:
    """`tile_type` is a suji of a tile `opponent_seat` already discarded (same suit, 3 ranks
    apart); honors are never suji."""
    if tile_type >= N_SUITED_TYPES:
        return False
    suit, rank = divmod(tile_type, RANKS_PER_SUIT)
    for offset in (-3, 3):
        other_rank = rank + offset
        if 0 <= other_rank < RANKS_PER_SUIT:
            other_type = suit * RANKS_PER_SUIT + other_rank
            if is_genbutsu(view, opponent_seat, other_type):
                return True
    return False


def _opponent_suit_meld_counts(view: SeatView, opponent_seat: int) -> dict[int, int]:
    counts: dict[int, int] = {}
    for meld in view.melds[opponent_seat]:
        v = int(meld.tile_type)
        if v < N_SUITED_TYPES:
            counts[v // RANKS_PER_SUIT] = counts.get(v // RANKS_PER_SUIT, 0) + 1
    return counts


def _opponent_dragon_pung_count(view: SeatView, opponent_seat: int) -> int:
    return sum(1 for m in view.melds[opponent_seat] if int(m.tile_type) in DRAGON_TYPES)


def _meld_danger_multiplier(view: SeatView, opponent_seat: int, tile_type: int) -> float:
    """Visible melds narrowing likely hand shape, applied as a multiplier on tiles that shape
    would want -- never standalone."""
    multiplier = 1.0
    if tile_type < N_SUITED_TYPES:
        suit = tile_type // RANKS_PER_SUIT
        suit_melds = _opponent_suit_meld_counts(view, opponent_seat)
        if suit_melds.get(suit, 0) >= 2:
            multiplier *= _MELD_SUIT_DANGER
    if tile_type in DRAGON_TYPES and _opponent_dragon_pung_count(view, opponent_seat) >= 1:
        multiplier *= _DRAGON_PUNG_DANGER
    return multiplier


def _tempo_multiplier(pool: Sequence[TileId]) -> float:
    """Sudden middle-tile discard after a terminal/honor string. Needs >= 3 prior discards to
    call a tempo change at all."""
    if len(pool) < 4:
        return 1.0
    *earlier, most_recent = pool
    earlier_terminal_ratio = fmean(is_terminal_or_honor(int(tile_id_type(t))) for t in earlier)
    recent_is_middle = not is_terminal_or_honor(int(tile_id_type(most_recent)))
    if recent_is_middle and earlier_terminal_ratio >= 0.7:
        return _TEMPO_THREAT_FACTOR
    return 1.0


def wall_pressure_multiplier(wall_remaining: int) -> float:
    for threshold, multiplier in _WALL_PRESSURE_TIERS:
        if wall_remaining <= threshold:
            return multiplier
    return 1.0


def deal_in_probability(view: SeatView, opponent_seat: int, tile_type: int) -> float:
    """`P(deal_in | tile)` against one opponent, all signals folded into one `[0, 1]` estimate
    (`_provably_safe` the only hard override). Genbutsu/suji are mutually exclusive -- suji only
    checked when genbutsu doesn't already apply, since genbutsu is the stronger read."""
    seen = seen34(view)
    if _provably_safe(view, opponent_seat, tile_type, seen):
        return 0.0

    p = _BASE_RATE
    live = COPIES_PER_TYPE - seen[tile_type]
    if live <= 0:
        p *= _NO_CHANCE_FACTOR
    elif live == 1:
        p *= _ONE_CHANCE_FACTOR

    if is_genbutsu(view, opponent_seat, tile_type):
        p *= _GENBUTSU_FACTOR
    elif _is_suji(view, opponent_seat, tile_type):
        p *= _SUJI_FACTOR

    p *= _meld_danger_multiplier(view, opponent_seat, tile_type)
    p *= _tempo_multiplier(view.discard_pools[opponent_seat])
    return min(p, 1.0)


def expected_cost(view: SeatView, opponent_seat: int, tile_type: int) -> float:
    """Assumed faan lost if this deals in -- a relative cost unit, scaled by meld reads and wall
    pressure (raises stakes, not probability)."""
    cost = _ASSUMED_DEALIN_FAAN
    cost *= _meld_danger_multiplier(view, opponent_seat, tile_type)
    cost *= wall_pressure_multiplier(view.wall_remaining)
    return cost


def synthetic_tile_id(tile_type: int, hand: Sequence[TileId]) -> TileId | None:
    """A placeholder physical id for a hypothetical tile of `tile_type`, distinct from every id
    already in `hand`. Every function this feeds (`hand_is_winning_shape`, `decompose`,
    `score_winning_hand`) only ever reads a tile's *type* back out via `tile_id_type` -- never
    raw id equality -- so any *unused* id in that type's 4-id block is interchangeable. Distinct
    still matters, though: `decompose` materializes real `Meld` objects from the candidate
    concealed tiles, and `Meld.__post_init__` (`mahjong_core/melds.py`) rejects a meld built from
    two equal physical ids -- reusing an id already in `hand` (e.g. always `tile_type * 4`) can
    collide with a real tile already there and raise, not just misclassify.

    Returns `None` if all 4 physical copies of `tile_type` are already in `hand` -- a 5th
    physical tile of that type cannot exist, so this discard provably can't deal in via it (the
    same fact `bots/safety.py`'s probabilistic `no_chance` checks, exactly)."""
    used = {int(t) for t in hand if int(tile_id_type(TileId(t))) == tile_type}
    for offset in range(4):
        candidate = tile_type * 4 + offset
        if candidate not in used:
            return TileId(candidate)
    return None


def _exact_deal_in_faan(view: SeatView, opponent_seat: int, tile_type: int) -> float:
    """Exact per-opponent contribution to `tile_risk` under an omniscient view (`view.hands` is
    populated): the real faan `opponent_seat` would score by winning on `tile_type` right now,
    or `0.0` if their real hand provably can't -- either not a complete shape, or a complete
    shape that doesn't clear `view.ruleset.min_faan` (a sub-minimum structural win is not a
    deal-in, docs/bots.md §4). Mirrors `mahjong_core.engine.can_win_on`'s candidate-hand
    pattern (append the tile, check shape, score, check `clears_min_faan`) but built directly
    from `view` rather than a live `GameState`/claim window, since this is a hypothetical
    "what if this seat discards this tile" check, not resolving a real claim."""
    assert view.hands is not None
    assert view.seat is not None
    hand = view.hands[opponent_seat]
    melds = view.melds[opponent_seat]
    synthetic = synthetic_tile_id(tile_type, hand)
    if synthetic is None:
        return 0.0
    candidate = (*hand, synthetic)
    if not hand_is_winning_shape(SeatState(concealed=candidate, melds=melds)):
        return 0.0

    discards_before_this_one = sum(len(pool) for pool in view.discard_pools)
    ctx = ScoringContext(
        seat_wind=seat_wind_for(opponent_seat, view.dealer),
        prevailing_wind=view.prevailing,
        self_drawn=False,
        flowers=view.flowers[opponent_seat],
        won_on_dealer_first_discard=(view.seat == view.dealer and discards_before_this_one == 0),
        is_last_tile=view.wall_remaining == 0,
        flowers_score=view.ruleset.flowers_score,
        winning_tile=candidate[-1],
    )
    result = score_winning_hand(candidate, melds, ctx, view.ruleset)
    return float(result.total_faan) if result.clears_min_faan else 0.0


def tile_risk(view: SeatView, tile_type: int) -> float:
    """`P(deal_in) * expected_cost`, summed across opponents -- summing instead of the stricter
    `1 - prod(1-p_i)` is deliberate: at `_BASE_RATE`'s small magnitude they're nearly identical,
    and summing keeps each opponent's contribution separately testable.

    When `view.hands` is populated (the `"ORACLE"` tier's omniscient view, docs/bots.md §9)
    this is a strict override, not an addition: every opponent's real hand is known, so
    `P(deal_in | tile)` collapses from an estimate to an exact 0-or-1 -- the candidate tile
    either completes that opponent's real hand right now (clearing `min_faan`) or it provably
    doesn't -- and the cost is the real faan that hand would score, not `_ASSUMED_DEALIN_FAAN`'s
    proxy. `view.hands is None` (every other tier) reproduces the original probabilistic
    estimate byte-for-byte -- this function's original behavior is an unconditional fallback,
    not something that gets reached only sometimes."""
    if view.seat is None:
        raise ValueError("tile_risk needs a seated view, not a spectator's")
    if view.hands is not None:
        return sum(
            _exact_deal_in_faan(view, opponent, tile_type)
            for opponent in range(4)
            if opponent != view.seat
        )
    total = 0.0
    for opponent in range(4):
        if opponent == view.seat:
            continue
        total += deal_in_probability(view, opponent, tile_type) * expected_cost(
            view, opponent, tile_type
        )
    return total


def kong_rob_risk(view: SeatView, tile_type: int, *, concealed: bool) -> float:
    """Exact 搶槓 (robbing the kong) risk of declaring a kong that exposes `tile_type` right now
    -- `\"ORACLE\"`-only (`view.hands` populated). Callers must not invoke this at all when
    `view.hands is None`: no other tier has any way to know this, and this function asserts on
    it rather than degrading to an estimate.

    Mirrors `mahjong_core.engine._kong_rob_offers`'s own gating exactly, so this never flags a
    kong the engine itself would never open a robbing window for: `ruleset.kong_rob_enabled`
    gates both kinds; an *added* kong (加槓) exposes the tile completing the existing pung to any
    opponent's win, while a *concealed* kong (暗槓) only matters at all when
    `ruleset.concealed_kong_robbable` is on, and even then only for an opponent whose candidate
    hand specifically completes Thirteen Orphans (十三么) -- real HK convention, not "any winning
    hand" (see `_kong_rob_offers`'s own docstring). `concealed` distinguishes the two kong kinds
    for this gating -- both expose `tile_type` itself as the tile at risk (`mahjong_core.ml.
    action_id`/`_apply_self_kong` both key a kong's action id and its exposed tile off the same
    `meld.tile_type`).

    Reuses `_exact_deal_in_faan`'s exact win check per opponent -- the same exact-faan-or-zero
    shape `tile_risk` already prices for an ordinary discard of the same tile type, since a
    kong-rob deal-in is structurally identical: the declaring seat pays the whole payout alone
    (docs/bots.md §9). Does not add 搶槓's own +1 bonus faan (`_exact_deal_in_faan` hardcodes
    `is_robbing_kong=False`), so a hand exactly one faan under `min_faan` that would only clear it
    with that bonus reads as safe here -- a narrow, accepted gap: reusing `_exact_deal_in_faan`
    unmodified (out of scope for this change) is preferred over reimplementing the scoring path
    for one rare edge case."""
    assert view.hands is not None
    assert view.seat is not None
    if not view.ruleset.kong_rob_enabled:
        return 0.0
    if concealed and not view.ruleset.concealed_kong_robbable:
        return 0.0
    best = 0.0
    for opponent in range(4):
        if opponent == view.seat:
            continue
        if concealed:
            synthetic = synthetic_tile_id(tile_type, view.hands[opponent])
            if synthetic is None or not _is_thirteen_orphans((*view.hands[opponent], synthetic)):
                continue
        best = max(best, _exact_deal_in_faan(view, opponent, tile_type))
    return best


def _opponent_concealed34(view: SeatView, opponent_seat: int) -> list[int]:
    """`opponent_seat`'s real concealed tiles as a 34-array, parsed beside their melds held fixed
    (`shanten`'s `melds=`, docs/bots.md §3) -- only valid when `view.hands` is populated."""
    assert view.hands is not None
    counts = new_count_array()
    for t in view.hands[opponent_seat]:
        counts[int(tile_id_type(t))] += 1
    return counts


def _opponent_real_shanten(view: SeatView, opponent_seat: int) -> int:
    """`opponent_seat`'s exact shanten (`mahjong_core.shanten.shanten`, `-1` = already won, `0` =
    tenpai) computed from their real hand -- only valid when `view.hands` is populated."""
    melds = view.melds[opponent_seat]
    return shanten(
        _opponent_concealed34(view, opponent_seat),
        closed=not melds,
        hand_sets=view.ruleset.hand_sets,
        melds=len(melds),
    )


_RON_CREDIT_SURPLUS = 0.5
"""Acceptance credited per wait copy an opponent holds but doesn't need. Measured discard rates
against `FaanBot` opponents: 26% surplus, 7.6% needed (ADR 0019 §3)."""
_RON_CREDIT_NEEDED = 0.0


def ron_credit(view: SeatView, waits: Sequence[int]) -> dict[int, float]:
    """`ORACLE`-only (`view.hands` populated): expected ron copies per wait type held in
    opponents' real hands. A copy counts `_RON_CREDIT_SURPLUS` if removing it doesn't raise its
    holder's shanten, else `_RON_CREDIT_NEEDED`."""
    assert view.hands is not None
    assert view.seat is not None
    credit = dict.fromkeys(waits, 0.0)
    hand_sets = view.ruleset.hand_sets
    for opponent in range(4):
        if opponent == view.seat:
            continue
        held = _opponent_concealed34(view, opponent)
        if not any(held[w] for w in waits):
            continue
        closed = not view.melds[opponent]
        melds = len(view.melds[opponent])
        base = shanten(held, closed=closed, hand_sets=hand_sets, melds=melds)
        for w in waits:
            if not held[w]:
                continue
            held[w] -= 1
            surplus = shanten(held, closed=closed, hand_sets=hand_sets, melds=melds) <= base
            held[w] += 1
            credit[w] += held[w] * (_RON_CREDIT_SURPLUS if surplus else _RON_CREDIT_NEEDED)
    return credit


def opponent_threat_level(view: SeatView, opponent_seat: int) -> float:
    """Coarse "how worried should T2 be" score for `bots/faanbot.py`'s fold logic -- combines
    meld count and the tempo signal into a threshold-compared scalar, not a probability.

    Hands-aware when `view.hands` is populated (the `"ORACLE"` tier's omniscient view,
    docs/bots.md §9): `opponent_seat`'s real shanten replaces the meld/tempo proxy entirely,
    via `_opponent_real_shanten`/`_SHANTEN_THREAT_STEP` below. `view.hands is None` (every other
    tier) is untouched, byte-for-byte."""
    if view.hands is not None:
        real_shanten = _opponent_real_shanten(view, opponent_seat)
        return max(0.0, (_SHANTEN_THREAT_BASE - real_shanten) * _SHANTEN_THREAT_STEP)
    melds = len(view.melds[opponent_seat])
    tempo_bump = _tempo_multiplier(view.discard_pools[opponent_seat]) - 1.0
    return melds * 0.3 + tempo_bump
