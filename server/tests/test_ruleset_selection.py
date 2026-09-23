"""`?ruleset=`/`?rules=` on `/ws` -- table-creation ruleset selection (presets + custom).
`mahjong_core.presets` itself (preset content, `preset_id_for` matching) plus the `app/ws.py`
resolver's never-hard-reject posture and `state_sync`'s `ruleset`/`ruleset_preset` fields."""

import json
import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.ws import get_table
from mahjong_core.config import DEFAULT_RULESET, RuleSet
from mahjong_core.presets import DEFAULT_PRESET_ID, RULESET_PRESETS, preset_id_for


def test_default_preset_id_is_hk_classic() -> None:
    assert DEFAULT_PRESET_ID == "hk_classic"
    assert RULESET_PRESETS[DEFAULT_PRESET_ID] == DEFAULT_RULESET


def test_preset_id_for_matches_known_preset() -> None:
    assert preset_id_for(RULESET_PRESETS["hk_casual"]) == "hk_casual"


def test_preset_id_for_custom_ruleset_is_none() -> None:
    custom = RuleSet(min_faan=0, turn_seconds=30)
    assert preset_id_for(custom) is None


def _connect_and_join(client: TestClient, table_id: str, query: str) -> dict:
    with client.websocket_connect(f"/ws?table={table_id}{query}") as ws:
        ws.send_json({"v": 1, "t": "hello", "ts": 1000, "d": {"client_version": "test"}})
        ws.send_json({"v": 1, "t": "join", "ts": 1001, "id": "j-1", "d": {"seat": 0, "name": "P1"}})
        # join's own broadcast (seat_state) lands before the unicast state_sync/ack
        frame = ws.receive_json()
        while frame["t"] != "state_sync":
            frame = ws.receive_json()
        return frame


def test_no_query_params_defaults_to_hk_classic() -> None:
    table_id = f"ruleset-default-{uuid.uuid4()}"
    with TestClient(app) as client:
        state_sync = _connect_and_join(client, table_id, "")
        assert state_sync["d"]["ruleset_preset"] == "hk_classic"
        assert state_sync["d"]["ruleset"] == DEFAULT_RULESET.to_dict()


def test_named_preset_selected() -> None:
    table_id = f"ruleset-casual-{uuid.uuid4()}"
    with TestClient(app) as client:
        state_sync = _connect_and_join(client, table_id, "&ruleset=hk_casual")
        assert state_sync["d"]["ruleset_preset"] == "hk_casual"
        assert state_sync["d"]["ruleset"]["min_faan"] == 1
        assert state_sync["d"]["ruleset"]["faan_cap"] == 13


def test_unknown_preset_falls_back_to_default() -> None:
    table_id = f"ruleset-unknown-{uuid.uuid4()}"
    with TestClient(app) as client:
        state_sync = _connect_and_join(client, table_id, "&ruleset=not_a_real_preset")
        assert state_sync["d"]["ruleset_preset"] == "hk_classic"


def test_custom_ruleset_round_trips() -> None:
    table_id = f"ruleset-custom-{uuid.uuid4()}"
    custom = RuleSet(min_faan=0, faan_cap=13, turn_seconds=30, wall_reserve=16)
    rules = json.dumps(custom.to_dict())
    with TestClient(app) as client:
        state_sync = _connect_and_join(client, table_id, f"&ruleset=custom&rules={rules}")
        assert state_sync["d"]["ruleset_preset"] is None
        assert state_sync["d"]["ruleset"] == custom.to_dict()

        table = get_table(table_id)
        assert table is not None
        assert table.state.ruleset == custom


def test_custom_with_malformed_rules_falls_back_to_default() -> None:
    table_id = f"ruleset-malformed-{uuid.uuid4()}"
    with TestClient(app) as client:
        state_sync = _connect_and_join(client, table_id, "&ruleset=custom&rules=not-json")
        assert state_sync["d"]["ruleset_preset"] == "hk_classic"


def test_custom_with_invalid_ruleset_fields_falls_back_to_default() -> None:
    table_id = f"ruleset-invalid-{uuid.uuid4()}"
    # min_faan=2 fails RuleSet.__post_init__'s own validation (not one of 0|1|3|5)
    bad = {**DEFAULT_RULESET.to_dict(), "min_faan": 2}
    rules = json.dumps(bad)
    with TestClient(app) as client:
        state_sync = _connect_and_join(client, table_id, f"&ruleset=custom&rules={rules}")
        assert state_sync["d"]["ruleset_preset"] == "hk_classic"


def test_ruleset_only_meaningful_on_first_connect() -> None:
    """Same "first connect wins" rule `?practice=` already has (`TableRegistry.get_or_create`) --
    a table's ruleset is fixed at construction and a later connect can't change it."""
    table_id = f"ruleset-fixed-{uuid.uuid4()}"
    with TestClient(app) as client:
        first = _connect_and_join(client, table_id, "&ruleset=hk_casual")
        assert first["d"]["ruleset_preset"] == "hk_casual"

        table_id_2 = table_id  # same id, second connection, different seat
        with client.websocket_connect(f"/ws?table={table_id_2}&ruleset=hk_strict") as ws:
            ws.send_json({"v": 1, "t": "hello", "ts": 1000, "d": {"client_version": "test"}})
            ws.send_json(
                {"v": 1, "t": "join", "ts": 1001, "id": "j-2", "d": {"seat": 1, "name": "P2"}}
            )
            frame = ws.receive_json()
            while frame["t"] != "state_sync":
                frame = ws.receive_json()
            assert frame["d"]["ruleset_preset"] == "hk_casual"
