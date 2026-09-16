"""`mahjong_core.ml`: the fixed 109-action space, `legal_mask`, and the `action_id`/
`decode_action` round trip (docs/06-ml.md §1, docs/05-roadmap.md §2's M2 done gate).

Decision points are swept from real self-play games (`RandomBot` + `engine.reduce`), the same
machinery `tests/test_selfplay.py` uses, rather than hand-constructed states -- this is what
docs/06-ml.md §1's property test calls for: "across every state the self-play harness reaches."
"""

from __future__ import annotations

import random
from collections.abc import Iterator

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from bots import RandomBot
from mahjong_core import ml
from mahjong_core.actions import (
    Action,
    ClaimWin,
    DeclareWin,
    Discard,
    Pass,
    legal_actions,
)
from mahjong_core.config import RuleSet
from mahjong_core.engine import new_game, reduce, start_next_hand
from mahjong_core.state import GameState, Phase
from mahjong_core.tiles import TileType, tile_id_type

_STEP_CAP = 2000  # generous vs. test_selfplay.py's observed ~450-step max for a 4-hand game
_BOUNDED_RULESET = RuleSet(dealer_repeat_on_win=False, dealer_repeat_on_draw=False)

_EXPECTED_RANGES: list[tuple[str, int, int]] = [
    ("discard", 0, 34),
    ("concealed_kong", 34, 68),
    ("added_kong", 68, 102),
    ("pass", 102, 103),
    ("chow_low", 103, 104),
    ("chow_middle", 104, 105),
    ("chow_high", 105, 106),
    ("pung", 106, 107),
    ("kong", 107, 108),
    ("win", 108, 109),
]


# --- action-space shape (docs/06-ml.md §1's table) --------------------------------------------


def test_action_space_is_109_contiguous_no_gaps_no_duplicates() -> None:
    assert ml.N_ACTIONS == 109
    covered: set[int] = set()
    prev_end = 0
    for _name, start, end in _EXPECTED_RANGES:
        assert start == prev_end, f"gap/overlap before {_name}: expected {prev_end}, got {start}"
        ids = set(range(start, end))
        assert not (ids & covered), f"{_name} overlaps a previously assigned id"
        covered |= ids
        prev_end = end
    assert prev_end == ml.N_ACTIONS
    assert covered == set(range(ml.N_ACTIONS))


def test_discard_ids_span_all_34_tile_types_directly() -> None:
    """Directed sanity check, independent of self-play: `action_id` on a hand-built `Discard`
    lands at exactly `tile_type`'s ordinal, for every type."""
    for tile_type in TileType:
        tile_id = tile_type * 4  # canonical id 0 of that type, tiles.py's numbering
        aid = ml.action_id(Discard(tile_id=tile_id), state=_dummy_state())
        assert aid == int(tile_type)


def _dummy_state() -> GameState:
    """A `GameState` for the directed tests above that don't touch claim/self-kong context --
    `action_id` on a bare `Discard` never reads `state`, so any valid state works."""
    return new_game(_BOUNDED_RULESET, game_seed=0)


def test_pass_and_win_ids_are_fixed_constants() -> None:
    state = _dummy_state()
    assert ml.action_id(Pass(window_id=1, seat=0), state) == 102
    assert ml.action_id(DeclareWin(), state) == 108
    assert ml.action_id(ClaimWin(window_id=1, seat=0), state) == 108


# --- self-play state sweep ---------------------------------------------------------------------


def _decision_points(seed: int, ruleset: RuleSet) -> Iterator[tuple[GameState, int]]:
    """Play one seeded `RandomBot` game to completion, yielding every `(state, seat)` where
    `seat` has a live decision -- the same traversal `test_selfplay.py`'s `_play_one_game` uses,
    minus the tile-conservation assertions (out of scope here)."""
    rng = random.Random(seed)
    bots = [RandomBot(rng=rng) for _ in range(4)]
    state = new_game(ruleset, seed)
    steps = 0
    while state.phase != Phase.GAME_OVER:
        steps += 1
        assert steps <= _STEP_CAP, f"seed={seed}: exceeded {_STEP_CAP} steps"

        if state.phase == Phase.HAND_OVER:
            state, _ = start_next_hand(state)
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

        yield state, seat
        action = bots[seat].act(state, seat)
        state, _ = reduce(state, action)


def _actions_equivalent(a: Action, b: Action) -> bool:
    """Type-level equivalence: a `Discard` matches iff its `tile_type` matches (06-ml.md §1 --
    the action space is type-level only, physical `tile_id` is fungible); every other variant
    reconstructs exactly, since `decode_action` pulls the same meld/window objects
    `legal_actions` itself offered."""
    if isinstance(a, Discard) and isinstance(b, Discard):
        return tile_id_type(a.tile_id) == tile_id_type(b.tile_id)
    return a == b


@pytest.mark.parametrize("seed", range(12))
def test_legal_mask_matches_legal_actions_directly(seed: int) -> None:
    """`legal_mask` bit `i` is set iff some action `actions.legal_actions` actually offers
    encodes to `i` -- checked at every decision point of a played-out game, not hand-picked
    states."""
    for state, seat in _decision_points(seed, _BOUNDED_RULESET):
        legal = legal_actions(state, seat)
        assert legal, f"seed={seed}: legal_actions empty at a yielded decision point"

        expected_ids = {ml.action_id(a, state) for a in legal}
        mask = ml.legal_mask(state, seat)
        assert len(mask) == ml.N_ACTIONS
        assert any(mask), f"seed={seed}: mask all-False in an acting phase"
        actual_ids = {i for i, bit in enumerate(mask) if bit}
        assert actual_ids == expected_ids

        # every set bit decodes to something the engine actually offered this seat
        for aid in actual_ids:
            decoded = ml.decode_action(aid, state, seat)
            assert any(_actions_equivalent(decoded, a) for a in legal), (
                f"seed={seed}: id {aid} decoded to {decoded!r}, not offered by legal_actions"
            )


@settings(
    max_examples=40,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(seed=st.integers(min_value=0, max_value=2**31 - 1))
def test_round_trip_property_across_selfplay(seed: int) -> None:
    """docs/06-ml.md §1's property test: for every type-level legal action at every state a
    self-play game reaches, `action_id` then `decode_action` reproduces an equivalent action --
    checked here as `action_id(decode_action(action_id(a), ...)) == action_id(a)`, since both
    sides operate on `tile_type`, never physical `tile_id` (the doc's own resolution of why the
    naive `tile_id`-level version of this test was false by construction)."""
    for state, seat in _decision_points(seed, _BOUNDED_RULESET):
        legal = legal_actions(state, seat)
        assert legal

        for action in legal:
            aid = ml.action_id(action, state)
            assert 0 <= aid < ml.N_ACTIONS

            decoded = ml.decode_action(aid, state, seat)
            assert ml.action_id(decoded, state) == aid, (
                f"seed={seed}: round trip broke for {action!r} -> {aid} -> {decoded!r}"
            )
            assert any(_actions_equivalent(decoded, a) for a in legal)
