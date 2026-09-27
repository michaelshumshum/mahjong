"""M1's completion gate (docs/05-roadmap.md §2): `pytest -k selfplay` runs N complete games
with four `RandomBot`s -- no illegal states, no deadlocks, every game terminates -- plus a
`hypothesis` property version of the same invariants (docs/05-roadmap.md §3's testing-strategy
table: tile conservation, hand sizes in `{1,4,7,10,13}` mod melds, `legal_actions` never empty
in an active phase, every game terminates).

**Ruleset choice: dealer repeats disabled.** `RandomBot` almost never completes a winning
*hand* -- most hands end in an exhaustive draw -- so under `DEFAULT_RULESET`
(`dealer_repeat_on_draw=True`), a round can take on the order of 150+ hands before a non-dealer
finally wins and rotates the deal (measured empirically while sizing this test, see
docs/05-roadmap.md §3). That's real engine behaviour, not a bug -- `dealer_repeat_on_win`/
`dealer_repeat_on_draw` are exercised directly by test_engine.py's dedicated unit tests -- but
it makes wall-clock time at 10,000 games unpredictable and turns a legitimate slow-converging
config into self-play flakiness. Both self-play runs below disable both repeat flags, matching
test_engine.py's own `test_game_over_reached_in_bounded_hands_with_no_repeats` precedent: with
repeats off, dealer rotation is unconditional every hand, so a game is bounded at exactly
4/8/16 hands for EAST_ONLY/EAST_SOUTH/FULL regardless of bot skill.
"""

from __future__ import annotations

import random

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from bots.random import random_action
from mahjong_core.actions import legal_actions
from mahjong_core.config import GameLength, RuleSet
from mahjong_core.engine import new_game, reduce, start_next_hand
from mahjong_core.state import GameState, Phase
from mahjong_core.tiles import TOTAL_PHYSICAL_TILES

_STEP_CAP = 8000  # generous vs. the observed max of ~450 steps for a 4-hand EAST_ONLY game
# (see module docstring); a trip is a hard failure, never a silent early exit.

_BOUNDED_RULESET = RuleSet(dealer_repeat_on_win=False, dealer_repeat_on_draw=False)


def _total_tiles(state: GameState) -> int:
    """All physical tiles accounted for: concealed + melds + discards per seat, plus flowers,
    plus what's left in the wall (docs/05-roadmap.md §3's tile-conservation invariant)."""
    seat_tiles = sum(
        len(seat.concealed) + sum(len(m.tiles) for m in seat.melds) + len(seat.discards)
        for seat in state.seats
    )
    seat_flowers = sum(len(seat.flowers) for seat in state.seats)
    return seat_tiles + len(state.wall.tiles) + seat_flowers


def _assert_hand_sizes(state: GameState) -> None:
    """Every seat's concealed count is `13 - 3*len(melds)` -- one of `{1,4,7,10,13}` -- except
    the seat currently holding an undiscarded draw in `AWAIT_ACTION`, which holds one more
    (docs/05-roadmap.md §3: "hand sizes always in `{1,4,7,10,13}` mod melds"). Only checked in
    the three active phases -- `HAND_OVER`/`GAME_OVER` legitimately leave a winner's completing
    tile un-discarded, which is a hand-result snapshot, not a live turn state."""
    if state.phase not in (Phase.AWAIT_ACTION, Phase.AWAIT_CLAIMS, Phase.AWAIT_KONG_ROB):
        return
    for seat_no, seat in enumerate(state.seats):
        budget = 13 - 3 * len(seat.melds)
        assert budget in (1, 4, 7, 10, 13), (
            f"seat {seat_no}: {len(seat.melds)} melds gives an impossible budget {budget}"
        )
        holding_draw = state.phase == Phase.AWAIT_ACTION and state.turn == seat_no
        expected = budget + 1 if holding_draw else budget
        assert len(seat.concealed) == expected, (
            f"seat {seat_no}: concealed={len(seat.concealed)} melds={len(seat.melds)} "
            f"expected {expected} (phase={state.phase}, turn={state.turn})"
        )


def _play_one_game(seed: int, ruleset: RuleSet, *, step_cap: int = _STEP_CAP) -> int:
    """Play one complete game with four `RandomBot`s sharing a single seeded `Random` stream --
    (ruleset, seed) alone reproduces it, per `server/AGENTS.md`'s determinism rule. Asserts
    every invariant after every `reduce()`/`start_next_hand()` call; returns the step count.
    """
    rng = random.Random(seed)
    state = new_game(ruleset, seed)
    total = TOTAL_PHYSICAL_TILES if ruleset.flowers_enabled else 136
    assert _total_tiles(state) == total
    _assert_hand_sizes(state)

    steps = 0
    while state.phase != Phase.GAME_OVER:
        steps += 1
        assert steps <= step_cap, (
            f"seed={seed}: exceeded {step_cap} steps -- possible infinite loop/deadlock"
        )

        if state.phase == Phase.HAND_OVER:
            state, _ = start_next_hand(state)
            assert _total_tiles(state) == total
            _assert_hand_sizes(state)
            continue

        if state.phase in (Phase.AWAIT_CLAIMS, Phase.AWAIT_KONG_ROB):
            assert state.claim_window is not None
            pending = [
                o.seat
                for o in state.claim_window.offers
                if o.seat not in state.claim_window.responses
            ]
            seat = rng.choice(pending)
        else:
            seat = state.turn

        actions = legal_actions(state, seat)
        assert actions, f"seed={seed}: legal_actions empty for seat {seat} in {state.phase}"
        action = random_action(state, seat, rng)
        assert action in actions

        state, _ = reduce(state, action)
        assert _total_tiles(state) == total
        _assert_hand_sizes(state)

    assert state.phase == Phase.GAME_OVER
    return steps


@pytest.mark.slow
def test_selfplay_games_terminate_and_conserve_tiles(games: int) -> None:
    """`--games` (default 10000, Makefile `selfplay` target). Every game must reach
    `Phase.GAME_OVER`; a step-cap trip on any seed is a hard failure, not a skip."""
    for seed in range(games):
        _play_one_game(seed, _BOUNDED_RULESET)


# --- hypothesis: same invariants, seeds and rule variations chosen by hypothesis -------------

_RULESET_VARIATIONS = st.builds(
    RuleSet,
    min_faan=st.sampled_from([0, 1, 3, 5]),
    faan_cap=st.sampled_from([10, 13]),
    game_length=st.sampled_from(list(GameLength)),
    kong_rob_enabled=st.booleans(),
    concealed_kong_robbable=st.booleans(),
    flowers_enabled=st.booleans(),
    # dealer_repeat_* deliberately not varied -- repeats off bounds the game at 4/8/16 hands
    # regardless of what hypothesis picks; repeat paths are covered by test_engine.py's unit tests.
    dealer_repeat_on_win=st.just(False),
    dealer_repeat_on_draw=st.just(False),
)


@pytest.mark.slow
@settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(seed=st.integers(min_value=0, max_value=2**31 - 1), ruleset=_RULESET_VARIATIONS)
def test_selfplay_hypothesis_properties(seed: int, ruleset: RuleSet) -> None:
    """Same invariants as the fixed-count run, but with hypothesis choosing the seed and a
    ruleset within its valid space (docs/05-roadmap.md §2: "Run under hypothesis too")."""
    _play_one_game(seed, ruleset)
