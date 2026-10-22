from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from mahjong_core.presets import RULESET_PRESETS

FLUSH = ["1s", "2s", "3s", "4s", "5s", "6s", "7s", "8s", "9s", "2s", "2s", "2s", "5s", "5s"]


def _post(body: dict[str, Any]) -> Any:
    with TestClient(app) as client:
        return client.post("/score", json=body)


def test_scores_a_hand_under_a_preset() -> None:
    response = _post({"ruleset": "hk_casual", "tiles": FLUSH, "self_drawn": True})
    assert response.status_code == 200
    body = response.json()
    assert body["winning"] is True
    assert "清一色" in body["breakdown"]
    assert body["min_faan"] == 1
    assert body["clears_min_faan"] is True
    assert body["points"] == 2 ** body["total_faan"]  # hk_casual is full spicy


def test_a_custom_ruleset_scores_its_overrides() -> None:
    rules = {**RULESET_PRESETS["hk_classic"].to_dict(), "faan_overrides": {"清一色": 2}}
    body = _post({"ruleset": "custom", "rules": rules, "tiles": FLUSH}).json()
    assert body["breakdown"]["清一色"] == 2


def test_a_non_winning_hand_has_no_score() -> None:
    tiles = [*FLUSH[:-1], "z1"]
    body = _post({"tiles": tiles}).json()
    assert body == {
        "winning": False,
        "total_faan": None,
        "breakdown": {},
        "clears_min_faan": None,
        "points": None,
        "min_faan": 3,
    }


@pytest.mark.parametrize(
    "body",
    [
        {"tiles": [*FLUSH[:-1], "x9"]},
        {"tiles": [*FLUSH[:-1], "f1"]},
        {"tiles": FLUSH, "flowers": ["1m"]},
        {"tiles": FLUSH[:-1]},
        {"tiles": [*FLUSH, "1m"]},
        {"tiles": ["1s"] * 5 + FLUSH[5:]},
        {"tiles": FLUSH, "seat_wind": 4},
    ],
)
def test_rejects_impossible_hands(body: dict[str, Any]) -> None:
    assert _post(body).status_code == 422
