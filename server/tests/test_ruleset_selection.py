"""Table-creation ruleset selection (presets + custom) through `POST /tables`.
`mahjong_core.presets` itself (preset content, `preset_id_for` matching) plus the resolver's
never-hard-reject posture and `state_sync`'s `ruleset`/`ruleset_preset` fields."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.ws import get_table
from mahjong_core.config import DEFAULT_RULESET, RuleSet
from mahjong_core.presets import (
    DEFAULT_PRESET_ID,
    RULESET_PRESETS,
    preset_id_for,
    resolve_ruleset,
)
from mahjong_core.scoring.patterns import LIMIT_FAAN


def test_default_preset_id_is_hk_classic() -> None:
    assert DEFAULT_PRESET_ID == "hk_classic"
    assert RULESET_PRESETS[DEFAULT_PRESET_ID] == DEFAULT_RULESET


def test_preset_id_for_matches_known_preset() -> None:
    assert preset_id_for(RULESET_PRESETS["hk_casual"]) == "hk_casual"


def test_preset_id_for_custom_ruleset_is_none() -> None:
    custom = RuleSet(min_faan=0, turn_seconds=30)
    assert preset_id_for(custom) is None


def test_resolve_ruleset_named_preset() -> None:
    assert resolve_ruleset("hk_casual", None) == RULESET_PRESETS["hk_casual"]


def test_resolve_ruleset_unknown_preset_falls_back_to_default() -> None:
    assert resolve_ruleset("does_not_exist", None) == DEFAULT_RULESET


def test_resolve_ruleset_custom_dict() -> None:
    custom = RuleSet(min_faan=1, wall_reserve=8)
    assert resolve_ruleset("custom", custom.to_dict()) == custom


def test_resolve_ruleset_custom_with_no_rules_falls_back_to_default() -> None:
    assert resolve_ruleset("custom", None) == DEFAULT_RULESET


def test_resolve_ruleset_custom_with_invalid_rules_falls_back_to_default() -> None:
    bad = {**DEFAULT_RULESET.to_dict(), "min_faan": 2}
    assert resolve_ruleset("custom", bad) == DEFAULT_RULESET


def test_resolve_ruleset_custom_with_missing_keys_falls_back_to_default() -> None:
    assert resolve_ruleset("custom", {"min_faan": 1}) == DEFAULT_RULESET


@pytest.mark.parametrize(
    "overrides", [{"not_a_pattern": 1}, {"平糊": LIMIT_FAAN + 1}, {"平糊": -1}, {"平糊": True}]
)
def test_resolve_ruleset_custom_with_invalid_faan_overrides_falls_back_to_default(
    overrides: dict[str, object],
) -> None:
    bad = {**DEFAULT_RULESET.to_dict(), "faan_overrides": overrides}
    assert resolve_ruleset("custom", bad) == DEFAULT_RULESET


def test_resolve_ruleset_custom_keeps_valid_faan_overrides() -> None:
    custom = RuleSet(faan_overrides={"雞糊": 0, "七對子": LIMIT_FAAN})
    assert resolve_ruleset("custom", custom.to_dict()) == custom


# H3: zero timers + huge strikes/grace + dealer repeat looped hundreds of hands a second
_RUNAWAY_RULES = {
    **DEFAULT_RULESET.to_dict(),
    "turn_seconds": 0,
    "claim_seconds": 0,
    "hand_end_seconds": 0,
    "turn_timeout_strikes": 10**9,
    "disconnect_grace_seconds": 1e9,
}


def test_resolve_ruleset_custom_with_runaway_timing_falls_back_to_default() -> None:
    assert resolve_ruleset("custom", _RUNAWAY_RULES) == DEFAULT_RULESET


def test_resolve_ruleset_custom_below_client_floor_falls_back_to_default() -> None:
    # valid for a directly-built RuleSet (tests use 0-second timers), not for a client
    zero_timers = RuleSet(turn_seconds=0, claim_seconds=0, hand_end_seconds=0)
    assert resolve_ruleset("custom", zero_timers.to_dict()) == DEFAULT_RULESET


def test_resolve_ruleset_custom_with_non_finite_falls_back_to_default() -> None:
    bad = {**DEFAULT_RULESET.to_dict(), "disconnect_grace_seconds": float("nan")}
    assert resolve_ruleset("custom", bad) == DEFAULT_RULESET


def test_resolve_ruleset_custom_with_bool_as_int_falls_back_to_default() -> None:
    bad = {**DEFAULT_RULESET.to_dict(), "min_faan": True}
    assert resolve_ruleset("custom", bad) == DEFAULT_RULESET


def _create_and_join(client: TestClient, body: dict[str, object]) -> tuple[str, dict]:
    table_id = client.post("/tables", json=body).json()["table_id"]
    with client.websocket_connect(f"/ws?table={table_id}") as ws:
        ws.send_json({"v": 1, "t": "hello", "ts": 1000, "d": {"client_version": "test"}})
        ws.send_json({"v": 1, "t": "join", "ts": 1001, "id": "j-1", "d": {"seat": 0, "name": "P1"}})
        # join's own broadcast (seat_state) lands before the unicast state_sync/ack
        frame = ws.receive_json()
        while frame["t"] != "state_sync":
            frame = ws.receive_json()
        return table_id, frame


def test_empty_body_defaults_to_hk_classic() -> None:
    with TestClient(app) as client:
        _, state_sync = _create_and_join(client, {})
        assert state_sync["d"]["ruleset_preset"] == "hk_classic"
        assert state_sync["d"]["ruleset"] == DEFAULT_RULESET.to_dict()


def test_named_preset_selected() -> None:
    with TestClient(app) as client:
        _, state_sync = _create_and_join(client, {"ruleset": "hk_casual"})
        assert state_sync["d"]["ruleset_preset"] == "hk_casual"
        assert state_sync["d"]["ruleset"]["min_faan"] == 1
        assert state_sync["d"]["ruleset"]["faan_cap"] == 13


def test_unknown_preset_falls_back_to_default() -> None:
    with TestClient(app) as client:
        _, state_sync = _create_and_join(client, {"ruleset": "not_a_real_preset"})
        assert state_sync["d"]["ruleset_preset"] == "hk_classic"


def test_custom_ruleset_round_trips() -> None:
    custom = RuleSet(min_faan=0, faan_cap=13, turn_seconds=30, wall_reserve=16)
    with TestClient(app) as client:
        table_id, state_sync = _create_and_join(
            client, {"ruleset": "custom", "rules": custom.to_dict()}
        )
        assert state_sync["d"]["ruleset_preset"] is None
        assert state_sync["d"]["ruleset"] == custom.to_dict()

        table = get_table(table_id)
        assert table is not None
        assert table.state.ruleset == custom


def test_custom_with_invalid_ruleset_fields_falls_back_to_default() -> None:
    # min_faan=2 fails RuleSet.__post_init__'s own validation (not one of 0|1|3|5)
    bad = {**DEFAULT_RULESET.to_dict(), "min_faan": 2}
    with TestClient(app) as client:
        _, state_sync = _create_and_join(client, {"ruleset": "custom", "rules": bad})
        assert state_sync["d"]["ruleset_preset"] == "hk_classic"


def test_custom_with_runaway_timing_falls_back_to_default() -> None:
    with TestClient(app) as client:
        _, state_sync = _create_and_join(client, {"ruleset": "custom", "rules": _RUNAWAY_RULES})
        assert state_sync["d"]["ruleset_preset"] == "hk_classic"
