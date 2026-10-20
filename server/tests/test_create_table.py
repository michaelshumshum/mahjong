"""`POST /tables` (`app/main.py`'s `create_table`) -- the one-request table-creation path that
resolves a ruleset and mints a table id together, replacing client-side id generation
(`web/src/lib/table/table-code.ts`). `?ruleset=`/`?rules=` on `/ws` (`server/tests/
test_ruleset_selection.py`) is the lower-level fallback this endpoint's ruleset resolution
(`mahjong_core.presets.resolve_ruleset`) is shared with."""

import re
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import _TABLE_CODE_ALPHABET, _TABLE_CODE_LENGTH, _generate_table_id, app
from app.ws import get_table
from mahjong_core.config import DEFAULT_RULESET, RuleSet

_TABLE_ID_RE = re.compile(f"^[{_TABLE_CODE_ALPHABET}]{{{_TABLE_CODE_LENGTH}}}$")


def test_default_body_creates_hk_classic_table() -> None:
    with TestClient(app) as client:
        response = client.post("/tables", json={})
    assert response.status_code == 200
    body = response.json()
    assert _TABLE_ID_RE.match(body["table_id"])
    assert body["ruleset_preset"] == "hk_classic"
    assert body["ruleset"] == DEFAULT_RULESET.to_dict()


def test_named_preset_resolves() -> None:
    with TestClient(app) as client:
        response = client.post("/tables", json={"ruleset": "hk_casual"})
    body = response.json()
    assert body["ruleset_preset"] == "hk_casual"
    assert body["ruleset"]["min_faan"] == 1
    assert body["ruleset"]["faan_cap"] == 13


def test_unknown_preset_falls_back_to_default() -> None:
    with TestClient(app) as client:
        response = client.post("/tables", json={"ruleset": "not_a_real_preset"})
    assert response.json()["ruleset_preset"] == "hk_classic"


def test_custom_rules_round_trip_and_apply_to_the_real_table() -> None:
    custom = RuleSet(min_faan=0, faan_cap=13, turn_seconds=30, wall_reserve=16)
    with TestClient(app) as client:
        response = client.post("/tables", json={"ruleset": "custom", "rules": custom.to_dict()})
        body = response.json()
        assert body["ruleset_preset"] is None
        assert body["ruleset"] == custom.to_dict()

        table = get_table(body["table_id"])
        assert table is not None
        assert table.state.ruleset == custom


def test_invalid_custom_rules_fall_back_to_default() -> None:
    # min_faan=2 fails RuleSet.__post_init__'s own validation (not one of 0|1|3|5)
    bad = {**DEFAULT_RULESET.to_dict(), "min_faan": 2}
    with TestClient(app) as client:
        response = client.post("/tables", json={"ruleset": "custom", "rules": bad})
    assert response.json()["ruleset_preset"] == "hk_classic"


def test_practice_binds_bots_to_seats_one_through_three() -> None:
    with TestClient(app) as client:
        response = client.post("/tables", json={"practice": True})
        table = get_table(response.json()["table_id"])
    assert table is not None
    assert [b.status if b is not None else None for b in table.seat_bindings][1:] == [
        "bot",
        "bot",
        "bot",
    ]


def test_practice_bot_tiers_picks_a_difficulty_per_seat() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/tables",
            json={"practice": True, "bot_tiers": {"1": "T1", "2": "T2", "3": "ORACLE"}},
        )
        table = get_table(response.json()["table_id"])
    assert table is not None
    assert table._effective_bot_tier(1) == "T1"
    assert table._effective_bot_tier(2) == "T2"
    assert table._effective_bot_tier(3) == "ORACLE"


def test_practice_bot_tiers_accepts_expert() -> None:
    with TestClient(app) as client:
        response = client.post("/tables", json={"practice": True, "bot_tiers": {"2": "T4"}})
        table = get_table(response.json()["table_id"])
    assert table is not None
    assert table._effective_bot_tier(2) == "T4"
    assert table._effective_bot_tier(1) == "T2"


def test_practice_bot_tiers_ignores_an_unrecognized_tier_and_an_out_of_range_seat() -> None:
    """Same lenient-fallback posture as `ruleset`/`rules` -- a malformed entry is dropped, not a
    400, and that seat just falls back to `DEFAULT_BOT_TIER` ("T2")."""
    with TestClient(app) as client:
        response = client.post(
            "/tables",
            json={"practice": True, "bot_tiers": {"1": "not_a_real_tier", "4": "T1"}},
        )
        table = get_table(response.json()["table_id"])
    assert table is not None
    assert table._effective_bot_tier(1) == "T2"


def test_bot_tiers_without_practice_is_a_no_op() -> None:
    """`bot_tiers` has no bot seats to apply to when `practice` is false -- there is nothing to
    silently ignore vs. reject, since seat 0 is never a bot seat outside practice/all_bots."""
    with TestClient(app) as client:
        response = client.post("/tables", json={"bot_tiers": {"1": "ORACLE"}})
        table = get_table(response.json()["table_id"])
    assert table is not None
    assert [b.status if b is not None else None for b in table.seat_bindings] == [
        None,
        None,
        None,
        None,
    ]


def test_a_later_ws_connect_to_the_created_id_joins_the_same_table() -> None:
    """The id/ruleset are fixed at `POST /tables` time -- a subsequent `/ws` connect to that id
    (with, deliberately, a *different* `?ruleset=` to prove it's ignored) must join the table
    already created, not construct a second one under a different ruleset
    (`TableRegistry.get_or_create`'s "never creates a second Table for an id that already has
    one")."""
    with TestClient(app) as client:
        created = client.post("/tables", json={"ruleset": "hk_casual"}).json()
        table_id = created["table_id"]

        with client.websocket_connect(f"/ws?table={table_id}&ruleset=hk_strict") as ws:
            ws.send_json({"v": 1, "t": "hello", "ts": 0, "d": {"client_version": "test"}})
            ws.send_json(
                {"v": 1, "t": "join", "ts": 0, "id": "j-1", "d": {"seat": 0, "name": "P1"}}
            )
            frame = ws.receive_json()
            while frame["t"] != "state_sync":
                frame = ws.receive_json()
            assert frame["d"]["ruleset_preset"] == "hk_casual"


def test_generated_ids_retry_past_a_collision() -> None:
    with TestClient(app) as client:
        occupied = "AAAAAA"
        with client.websocket_connect(f"/ws?table={occupied}"):
            pass  # the connect alone is enough to auto-create the table under this id
        # first attempt collides with the table just created above, second is free
        with patch("app.main.secrets.choice", side_effect=list(occupied) + list("BBBBBB")):
            assert _generate_table_id() == "BBBBBB"


def test_generated_id_exhausting_attempts_raises() -> None:
    with TestClient(app) as client:
        occupied = "CCCCCC"
        with client.websocket_connect(f"/ws?table={occupied}"):
            pass
        with patch("app.main.secrets.choice", side_effect=list(occupied) * 10):
            try:
                _generate_table_id()
            except RuntimeError:
                pass
            else:
                raise AssertionError("expected RuntimeError once every attempt collides")


def test_private_table_is_left_out_of_listing() -> None:
    with TestClient(app) as client:
        private_id = client.post("/tables", json={"private": True}).json()["table_id"]
        public_id = client.post("/tables", json={}).json()["table_id"]
        for table_id in (private_id, public_id):
            table = get_table(table_id)
            assert table is not None
            table.join(f"s-{table_id}", lambda _seq, _frame: None, seat=0, name="Alice")
        listed = {t["id"] for t in client.get("/tables").json()["tables"]}
    assert public_id in listed
    assert private_id not in listed
