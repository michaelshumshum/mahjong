import dataclasses
import json

import pytest

from mahjong_core.config import (
    CLIENT_RULE_BOUNDS,
    DEFAULT_RULESET,
    DiscardPayment,
    GameLength,
    HandSet,
    RuleSet,
    ScoreTable,
)
from mahjong_core.presets import RULESET_PRESETS


def test_default_min_faan() -> None:
    assert DEFAULT_RULESET.min_faan == 3


def test_default_faan_cap() -> None:
    assert DEFAULT_RULESET.faan_cap == 10


def test_default_score_table() -> None:
    assert DEFAULT_RULESET.score_table == ScoreTable.HALF_SPICY


def test_default_hand_sets() -> None:
    assert DEFAULT_RULESET.hand_sets == frozenset({HandSet.CLASSIC, HandSet.NEW_6})


def test_default_faan_overrides() -> None:
    assert DEFAULT_RULESET.faan_overrides == {}


def test_default_discard_payment() -> None:
    assert DEFAULT_RULESET.discard_payment == DiscardPayment.ALL


def test_default_self_draw_multiplier() -> None:
    assert DEFAULT_RULESET.self_draw_multiplier == 1.5


def test_default_game_length() -> None:
    assert DEFAULT_RULESET.game_length == GameLength.EAST_ONLY


def test_default_dealer_repeat_on_win() -> None:
    assert DEFAULT_RULESET.dealer_repeat_on_win is True


def test_default_dealer_repeat_on_draw() -> None:
    assert DEFAULT_RULESET.dealer_repeat_on_draw is True


def test_default_wall_reserve() -> None:
    assert DEFAULT_RULESET.wall_reserve == 0


def test_default_four_kong_abort() -> None:
    assert DEFAULT_RULESET.four_kong_abort is False


def test_default_nine_terminals_abort() -> None:
    assert DEFAULT_RULESET.nine_terminals_abort is False


def test_default_tenpai_payments() -> None:
    assert DEFAULT_RULESET.tenpai_payments is False


def test_default_flowers_enabled() -> None:
    assert DEFAULT_RULESET.flowers_enabled is True


def test_default_flowers_score() -> None:
    assert DEFAULT_RULESET.flowers_score is True


def test_default_seven_flowers_instant_win() -> None:
    assert DEFAULT_RULESET.seven_flowers_instant_win is False


def test_default_eight_flowers_instant_win() -> None:
    assert DEFAULT_RULESET.eight_flowers_instant_win is False


def test_default_thirteen_orphans_wait_bonus() -> None:
    assert DEFAULT_RULESET.thirteen_orphans_wait_bonus is False


def test_default_multi_win() -> None:
    assert DEFAULT_RULESET.multi_win is False


def test_default_kong_rob_enabled() -> None:
    assert DEFAULT_RULESET.kong_rob_enabled is True


def test_default_concealed_kong_robbable() -> None:
    assert DEFAULT_RULESET.concealed_kong_robbable is False


def test_default_pao_rules() -> None:
    assert DEFAULT_RULESET.pao_rules is False


def test_default_provable_fairness() -> None:
    assert DEFAULT_RULESET.provable_fairness is False


def test_default_turn_seconds() -> None:
    assert DEFAULT_RULESET.turn_seconds == 15


def test_default_claim_seconds() -> None:
    assert DEFAULT_RULESET.claim_seconds == 5


def test_default_turn_timeout_strikes() -> None:
    assert DEFAULT_RULESET.turn_timeout_strikes == 3


def test_frozen_raises_on_mutation() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        DEFAULT_RULESET.min_faan = 1  # type: ignore[misc]


def test_invalid_min_faan_rejected() -> None:
    with pytest.raises(ValueError, match="min_faan"):
        RuleSet(min_faan=2)


def test_invalid_faan_cap_rejected() -> None:
    with pytest.raises(ValueError, match="faan_cap"):
        RuleSet(faan_cap=9)


def test_negative_wall_reserve_rejected() -> None:
    with pytest.raises(ValueError, match="wall_reserve"):
        RuleSet(wall_reserve=-1)


def test_multi_win_true_rejected() -> None:
    with pytest.raises(ValueError, match="multi_win"):
        RuleSet(multi_win=True)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("turn_seconds", -1),
        ("claim_seconds", -5),
        ("hand_end_seconds", -1),
        ("turn_timeout_strikes", 0),
        ("disconnect_grace_seconds", -0.5),
        ("turn_seconds", 10**9),
        ("turn_timeout_strikes", 10**9),
        ("disconnect_grace_seconds", 1e9),
        ("wall_reserve", 10**9),
        ("self_draw_multiplier", 0.0),
    ],
)
def test_out_of_range_numeric_field_rejected(field: str, value: float) -> None:
    with pytest.raises(ValueError, match=field):
        RuleSet(**{field: value})


@pytest.mark.parametrize(
    "field",
    [
        "min_faan",
        "faan_cap",
        "wall_reserve",
        "turn_seconds",
        "claim_seconds",
        "hand_end_seconds",
        "turn_timeout_strikes",
    ],
)
@pytest.mark.parametrize("value", [True, 3.0, "3", None])
def test_integer_field_rejects_non_int(field: str, value: object) -> None:
    with pytest.raises(TypeError, match=field):
        RuleSet(**{field: value})


@pytest.mark.parametrize("field", ["disconnect_grace_seconds", "self_draw_multiplier"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_real_field_rejects_non_finite(field: str, value: float) -> None:
    with pytest.raises(ValueError, match=field):
        RuleSet(**{field: value})


@pytest.mark.parametrize("field", ["disconnect_grace_seconds", "self_draw_multiplier"])
@pytest.mark.parametrize("value", [True, "1.5", None])
def test_real_field_rejects_non_number(field: str, value: object) -> None:
    with pytest.raises(TypeError, match=field):
        RuleSet(**{field: value})


def test_real_field_accepts_int() -> None:
    assert RuleSet(disconnect_grace_seconds=20).disconnect_grace_seconds == 20


def test_negative_faan_override_rejected() -> None:
    with pytest.raises(ValueError, match="faan_overrides"):
        RuleSet(faan_overrides={"雞糊": -1})


@pytest.mark.parametrize("overrides", [{"雞糊": True}, {"雞糊": 1.5}, {1: 0}, [("雞糊", 0)]])
def test_non_int_faan_override_rejected(overrides: object) -> None:
    with pytest.raises(TypeError, match="faan_overrides"):
        RuleSet(faan_overrides=overrides)  # type: ignore[arg-type]


def test_zero_second_timers_allowed_on_a_directly_built_ruleset() -> None:
    # the tests' time-control knob; only the client-facing path floors timers
    rules = RuleSet(turn_seconds=0, claim_seconds=0, hand_end_seconds=0, disconnect_grace_seconds=0)
    assert rules.turn_seconds == 0


def test_shipped_presets_pass_client_bounds() -> None:
    for preset in RULESET_PRESETS.values():
        preset.check_client_bounds()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("turn_seconds", 0),
        ("turn_seconds", 4),
        ("turn_seconds", 61),
        ("claim_seconds", 1),
        ("claim_seconds", 31),
        ("hand_end_seconds", 0),
        ("hand_end_seconds", 61),
        ("turn_timeout_strikes", 11),
        ("disconnect_grace_seconds", 0),
        ("disconnect_grace_seconds", 4.9),
        ("disconnect_grace_seconds", 61),
        ("wall_reserve", 31),
        ("self_draw_multiplier", 3.0),
    ],
)
def test_client_bounds_reject_out_of_range(field: str, value: float) -> None:
    with pytest.raises(ValueError, match=field):
        RuleSet(**{field: value}).check_client_bounds()


@pytest.mark.parametrize(("field", "bounds"), sorted(CLIENT_RULE_BOUNDS.items()))
def test_client_bounds_accept_their_endpoints(field: str, bounds: tuple[float, float]) -> None:
    for value in bounds:
        RuleSet(**{field: value}).check_client_bounds()


def test_round_trip_default() -> None:
    raw = json.dumps(DEFAULT_RULESET.to_dict())
    restored = RuleSet.from_dict(json.loads(raw))
    assert restored == DEFAULT_RULESET


def test_round_trip_non_default() -> None:
    custom = RuleSet(
        min_faan=1,
        faan_cap=13,
        score_table=ScoreTable.FULL_SPICY,
        hand_sets=frozenset({HandSet.CLASSIC}),
        faan_overrides={"雞糊": 0, "清一色": 7},
        discard_payment=DiscardPayment.HALF,
        game_length=GameLength.FULL,
        wall_reserve=16,
        concealed_kong_robbable=True,
        provable_fairness=True,
    )
    raw = json.dumps(custom.to_dict())
    restored = RuleSet.from_dict(json.loads(raw))
    assert restored == custom
