"""T2 `FaanBot` (docs/04-bots.md §2/§4/§5): T1's shanten/ukeire machinery plus value-planning
and a defence model -- the bot M4's done-gate actually needs, per docs/04-bots.md §4: "A
T1-only bot loses by construction in HK... T1 alone cannot satisfy M4's done-gate."

**Scoring formula (docs/04-bots.md §4, verbatim structure):**

```
score(discard) = w_speed  * ukeire_after
               + w_value  * E[faan | best reachable pattern]
               + w_safety * (-deal_in_risk)
               + w_flex   * pattern_optionality
```

`ukeire_after` and `E[faan]` don't share a scale by default (tiles_accepted can run past 40,
faan tops out around 13), so `_speed_term` folds `result_shanten` in at a fixed exchange rate
(`_SHANTEN_UNIT`) rather than scoring shanten and ukeire as separate lexicographic keys the way
T1 does -- see `_speed_term`'s docstring for exactly what that buys: it's what lets `w_value`
outweigh a one-shanten speed cost mid-hand (committing to a flush) while still leaving shanten
dominant early, matching docs/04-bots.md §4's "speed early -> value mid -> safety late" weight
schedule without a separate code path per phase.

**Assumed `min_faan = 3`, not read from a live ruleset.** `Bot.act` only ever receives a
`SeatView` (`bots/base.py`) -- deliberately, so a bot never touches `GameState` -- and
`SeatView` carries no ruleset field (00-architecture.md §5's canonical shape; adding one is a
cross-cutting change to a frozen, depended-on wire type, out of this sub-task's scope). §4's own
scoring section is written entirely in terms of `min_faan = 3` (the ruleset default,
`mahjong_core.config.DEFAULT_RULESET.min_faan`), so `_ASSUMED_MIN_FAAN` below hardcodes that
value for the claim-safety guard (`_should_claim`) rather than leaving it unset. A future sub-
task that runs `FaanBot` under a non-default `min_faan` ruleset would need to either widen
`SeatView` or accept this bot tuned for the documented default -- flagged here, not silently
assumed to generalize.
"""

from __future__ import annotations

from app.views import SeatView
from bots.features import is_closed, is_terminal_or_honor, own_hand34, seen34
from bots.safety import opponent_threat_level, tile_risk
from bots.valuation import estimate_best_faan, pattern_optionality
from mahjong_core.shanten import shanten, ukeire
from mahjong_core.state import Phase
from mahjong_core.tiles import tile_id_type

__all__ = ["FaanBot"]

_DISCARD_BASE = 0
_CONCEALED_KONG_BASE = 34
_ADDED_KONG_BASE = 68
_PASS = 102
_CHOW_LOW = 103
_CHOW_MIDDLE = 104
_CHOW_HIGH = 105
_CHOW_AIDS = (_CHOW_LOW, _CHOW_MIDDLE, _CHOW_HIGH)
_PUNG = 106
_KONG = 107
_WIN = 108

_ASSUMED_MIN_FAAN = 3
"""See module docstring's "Assumed min_faan" note."""

_SHANTEN_UNIT = 5.0
"""Cost, in composite-score units, of one extra shanten -- sized so a genuinely large value gain
(a 6+ faan Full Flush, or the closed bonus stacked on top of a 3-faan route) can outweigh a
single shanten step once `w_value` ramps up mid-hand, while a routine 1-2 faan difference (most
candidate discards, most of the time) cannot, which is what keeps early-game play close to pure
efficiency even with `w_value > 0`. Tuned by hand (see `bots/safety.py`'s module docstring on
the project-wide hand-tuned-vs-trained tradeoff) and checked by `tests/test_faanbot.py`'s
scripted "commit to the flush" case, not derived from any formula."""
_UKEIRE_SCALE = 8.0
"""`tiles_accepted / _UKEIRE_SCALE` puts the speed term's ukeire component on the same
handful-of-points scale as `_SHANTEN_UNIT` and `w_value * E[faan]`. **Measured, not guessed**:
`tests/test_faanbot.py`'s scripted "commit to the flush" hand (9 man tiles + a dragon/wind pair,
one off-suit floater, two isolated honor floaters -- a real ≥7-tiles-in-suit-plus-honors Half
Flush candidate per docs/04-bots.md §4) showed a divisor of 4 leaves ukeire's raw tile-count
scale (discarding a flexible numbered floater keeps ~3x the ukeire of discarding an honor
floater, since honor floaters can only ever pair, never form a ryanmen/kanchan) large enough to
outweigh the whole route-commit signal even at `w_value=1.5`; 8 was the smallest divisor at
which that scripted hand's mid-game discard actually became the flush-preserving one, verified
by hand-computing both candidates' composite scores before pinning the test."""

_LATE_TURN = 12
"""docs/04-bots.md §4: "a bot at 3+ shanten on turn 12 against a threatening opponent...".
`turn` here is this seat's own count of discards already made this hand (see `_act_on_turn`),
the closest proxy available from a `SeatView` alone to the doc's turn-number language."""
_FOLD_SHANTEN = 3
_THREAT_THRESHOLD = 0.3
"""Calibrated against `opponent_threat_level`'s own scale (module docstring in
`bots/safety.py`): one exposed meld alone (0.3) is enough to count as "threatening" once
combined with lateness and distance from tenpai -- fold logic is already gated on both of those,
so this threshold doesn't need to be conservative on its own."""


def _weights_for_turn(turn: int) -> tuple[float, float, float, float]:
    """`(w_speed, w_value, w_safety, w_flex)` -- docs/04-bots.md §4: "speed early (turns 1-6) ->
    value mid (6-12) -> safety late (12+)". Values are hand-tuned starting points (same
    disclosure as `bots/safety.py`'s weights), validated end to end by the arena proof run
    (docs/04-bots.md §8's `tenpai_rate_on_sub_minimum_hand` canary and paired-difference CI
    against T1), not derived analytically."""
    if turn <= 6:
        return (1.0, 0.4, 0.3, 0.2)
    if turn <= 12:
        return (0.5, 1.5, 0.6, 0.3)
    return (0.3, 0.6, 1.6, 0.15)


def _opponents(seat: int) -> tuple[int, ...]:
    return tuple(s for s in range(4) if s != seat)


def _best_after_discard(hand34: list[int], *, closed: bool) -> tuple[int, list[int]]:
    """`(best_shanten, resulting_hand34)` reachable from `hand34` by discarding exactly one
    tile -- used to evaluate a claim's resulting hand for *both* shanten and value, so
    `_should_claim`'s value check reads the actual post-discard 13-tile shape rather than the
    pre-discard 14-tile one (adding the claimed tile alone can't change most route signals, but
    checking the real resulting hand is what this needs to actually mean, not what's merely
    convenient to compute). Mirrors `bots/efficiency.py`'s helper of the same name in spirit
    (duplicated rather than imported so T1 and T2 stay independently editable, per
    `bots/base.py`'s "no shared base class" rationale) but returns the hand too, which T1 never
    needed."""
    best_shanten: int | None = None
    best_hand: list[int] | None = None
    for t in range(34):
        if hand34[t] == 0:
            continue
        after = list(hand34)
        after[t] -= 1
        s = shanten(after, closed=closed)
        if best_shanten is None or s < best_shanten:
            best_shanten, best_hand = s, after
    assert best_shanten is not None and best_hand is not None, "hand34 must hold at least one tile"
    return best_shanten, best_hand


def _claimed_type(view: SeatView) -> int | None:
    """See `bots/efficiency.py`'s identical helper for the full derivation -- duplicated for the
    same independence reason as `_best_after_discard`."""
    if view.phase != Phase.AWAIT_CLAIMS:
        return None
    pool = view.discard_pools[view.turn]
    if not pool:
        return None
    return int(tile_id_type(pool[-1]))


def _speed_term(result_shanten: int, tiles_accepted: int) -> float:
    """`-_SHANTEN_UNIT * result_shanten + tiles_accepted / _UKEIRE_SCALE` -- lower shanten is
    always better (subtracted, so `result_shanten=0` beats `result_shanten=1` by a full
    `_SHANTEN_UNIT`), ukeire breaks ties within a shanten level. See module docstring for why
    this is one scalar term instead of T1's lexicographic `(shanten, -tiles, -kinds, ...)` key:
    a single scalar is what lets `w_value` trade off against it in the same weighted sum."""
    return -_SHANTEN_UNIT * result_shanten + tiles_accepted / _UKEIRE_SCALE


class FaanBot:
    """T2: see module docstring. Never returns an id `mask` doesn't mark legal."""

    async def act(self, view: SeatView, mask: list[bool], deadline: float) -> int:
        del deadline  # heuristic, O(1)-ish per candidate -- no search budget to spend
        if mask[_WIN]:
            return _WIN
        if view.phase in (Phase.AWAIT_CLAIMS, Phase.AWAIT_KONG_ROB):
            return self._act_on_claim(view, mask)
        return self._act_on_turn(view, mask)

    # --- claim window: value-aware version of T1's "only if it strictly helps" rule ---------

    def _act_on_claim(self, view: SeatView, mask: list[bool]) -> int:
        hand = own_hand34(view)
        closed = is_closed(view)
        before_shanten = shanten(hand, closed=closed)
        before_value, _ = estimate_best_faan(hand, closed=closed)

        best_aid = _PASS
        best_shanten = before_shanten

        claimed_type = _claimed_type(view)
        if claimed_type is not None:
            if mask[_PUNG]:
                candidate = list(hand)
                candidate[claimed_type] += 1
                s, resulting_hand = _best_after_discard(candidate, closed=False)
                if s < best_shanten and self._should_claim(before_value, resulting_hand):
                    best_shanten, best_aid = s, _PUNG

            chow_aid = next((aid for aid in _CHOW_AIDS if mask[aid]), None)
            if chow_aid is not None:
                candidate = list(hand)
                candidate[claimed_type] += 1
                s, resulting_hand = _best_after_discard(candidate, closed=False)
                if s < best_shanten and self._should_claim(before_value, resulting_hand):
                    best_shanten, best_aid = s, chow_aid

        # mask[_KONG] (claiming an exposed kong): never beneficial for shanten by construction,
        # same structural reason as bots/efficiency.py's identical omission -- see that
        # module's docstring.
        return best_aid

    def _should_claim(self, before_value: int, resulting_hand: list[int]) -> bool:
        """The value-aware half of T2's claim rule beyond "strictly reduces shanten" (already
        checked by the caller): don't open a hand that was on track to clear `min_faan` into a
        shape that no longer is. Deliberately has **no** "unless it reaches tenpai" exception --
        docs/04-bots.md §4's whole point is that reaching tenpai on a sub-minimum hand is the
        failure mode T2 exists to avoid, so speed alone (not even reaching tenpai) never
        overrides this guard; a hand that was already sub-minimum before the claim has nothing
        to lose and is always allowed through (the condition below is `False` whenever
        `before_value` doesn't already clear `_ASSUMED_MIN_FAAN`)."""
        after_value, _ = estimate_best_faan(resulting_hand, closed=False)
        return not (before_value >= _ASSUMED_MIN_FAAN > after_value)

    # --- own turn: self-declared kongs, then the value+safety-aware discard rule -----------

    def _act_on_turn(self, view: SeatView, mask: list[bool]) -> int:
        hand = own_hand34(view)
        closed = is_closed(view)
        base = shanten(hand, closed=closed)

        best_kong_aid: int | None = None
        best_kong_shanten = base
        for kong_base in (_CONCEALED_KONG_BASE, _ADDED_KONG_BASE):
            for t in range(34):
                aid = kong_base + t
                if not mask[aid]:
                    continue
                candidate = list(hand)
                candidate[t] -= 1
                s = shanten(candidate, closed=False)
                if s < best_kong_shanten:
                    best_kong_shanten, best_kong_aid = s, aid
        if best_kong_aid is not None:
            return best_kong_aid

        assert view.seat is not None
        turn = len(view.discard_pools[view.seat])
        return self._best_discard(view, hand, seen34(view), mask, closed=closed, turn=turn)

    def _best_discard(
        self,
        view: SeatView,
        hand: list[int],
        seen: list[int],
        mask: list[bool],
        *,
        closed: bool,
        turn: int,
    ) -> int:
        assert view.seat is not None
        base_shanten = shanten(hand, closed=closed)
        threatening = any(
            opponent_threat_level(view, opp) >= _THREAT_THRESHOLD for opp in _opponents(view.seat)
        )
        fold_mode = turn >= _LATE_TURN and base_shanten >= _FOLD_SHANTEN and threatening

        w_speed, w_value, w_safety, w_flex = _weights_for_turn(turn)
        accepts = ukeire(hand, seen, closed=closed)

        best_key: tuple[float, int, int] | None = None
        best_aid = -1
        for d in range(34):
            aid = _DISCARD_BASE + d
            if not mask[aid]:
                continue
            after = list(hand)
            after[d] -= 1
            result_shanten = shanten(after, closed=closed)
            kinds, tiles = accepts[d]
            risk = tile_risk(view, d)
            terminal_rank = 0 if is_terminal_or_honor(d) else 1

            if fold_mode:
                # Pure defence: minimise deal-in risk, break ties the same way T1 would.
                key = (risk, -tiles, terminal_rank)
            else:
                value_est, _route = estimate_best_faan(after, closed=closed)
                optionality = pattern_optionality(after, closed=closed)
                score = (
                    w_speed * _speed_term(result_shanten, tiles)
                    + w_value * value_est
                    - w_safety * risk
                    + w_flex * optionality
                )
                # Sort ascending like every other key here, so more negative == better: negate
                # the composite score (higher is better) to match.
                key = (-score, -kinds, terminal_rank)
            if best_key is None or key < best_key:
                best_key, best_aid = key, aid
        assert best_aid >= 0, "act() must not be called with an all-false discard mask"
        return best_aid
