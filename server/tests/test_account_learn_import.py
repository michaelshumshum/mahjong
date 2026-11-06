"""`POST /me/learn/import`: a device's one-time upload (docs/protocol.md §10 "Accounts", ADR 0028
"Learn progress: guest vs signed in" and "Trusting the upload")."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.accounts.learn import (
    MAX_LEARN_COUNT,
    EndlessValues,
    LessonValues,
    learn_imported_at,
    merge_endless,
    merge_lesson,
    merge_prefs,
)
from app.accounts.sessions import COOKIE_NAME
from app.body_limit import MAX_REQUEST_BODY_BYTES
from app.lessons.catalog import CATALOG, TUTORIALS
from app.main import app
from tests.accounts import create_user, run_db, sign_in

PUZZLE = CATALOG[0].id
OTHER = CATALOG[1].id
TUTORIAL = TUTORIALS[0].id
T0 = dt.datetime(2026, 11, 1, 12, 0, tzinfo=dt.UTC)
T1 = T0 + dt.timedelta(days=1)


def _signed_in(client: TestClient, accounts_db: str) -> uuid.UUID:
    user_id = create_user(accounts_db)
    client.cookies.set(COOKIE_NAME, sign_in(accounts_db, user_id))
    return user_id


def _lesson(
    solved: bool, attempts: int, solved_at: dt.datetime | None = None, step: int | None = None
) -> LessonValues:
    return LessonValues(solved, attempts, solved_at, step)


@pytest.mark.parametrize(
    ("server", "upload", "merged"),
    [
        (_lesson(False, 2), _lesson(True, 1, T0), _lesson(True, 2, T0)),
        (_lesson(True, 1, T1), _lesson(False, 5), _lesson(True, 5, T1)),
        (_lesson(True, 3, T1), _lesson(True, 1, T0), _lesson(True, 3, T0)),
        (_lesson(True, 3, None), _lesson(True, 1, T1), _lesson(True, 3, T1)),
        (_lesson(False, 0, step=2), _lesson(False, 0, step=5), _lesson(False, 0, step=5)),
        (_lesson(False, 0, step=5), _lesson(False, 0), _lesson(False, 0, step=5)),
        (_lesson(False, 0), _lesson(False, 0, step=3), _lesson(False, 0, step=3)),
        (None, _lesson(True, 4, T0, 1), _lesson(True, 4, T0, 1)),
    ],
)
def test_merge_lesson(
    server: LessonValues | None, upload: LessonValues, merged: LessonValues
) -> None:
    assert merge_lesson(server, upload) == merged


@pytest.mark.parametrize(
    ("server", "upload", "merged"),
    [
        (EndlessValues(1, 3, 4), EndlessValues(5, 6, 9), EndlessValues(1, 6, 9)),
        (EndlessValues(4, 7, 20), EndlessValues(2, 2, 2), EndlessValues(4, 7, 20)),
        (None, EndlessValues(2, 5, 8), EndlessValues(2, 5, 8)),
    ],
)
def test_merge_endless(
    server: EndlessValues | None, upload: EndlessValues, merged: EndlessValues
) -> None:
    assert merge_endless(server, upload) == merged


@pytest.mark.parametrize(
    ("server", "upload", "merged"),
    [
        ({}, {"learn_band": "advanced"}, {"learn_band": "advanced"}),
        ({"learn_band": "beginner"}, {"learn_band": "advanced"}, {"learn_band": "beginner"}),
        ({"coach_marks_done": False}, {"coach_marks_done": True}, {"coach_marks_done": True}),
        ({"coach_marks_done": True}, {"coach_marks_done": False}, {"coach_marks_done": True}),
    ],
)
def test_merge_prefs(
    server: dict[str, Any], upload: dict[str, Any], merged: dict[str, Any]
) -> None:
    assert merge_prefs(server, upload) == merged


def test_import_needs_a_session(accounts_db: str) -> None:
    with TestClient(app) as client:
        assert client.post("/me/learn/import", json={}).status_code == 401


def test_import_404s_while_the_flag_is_off(
    accounts_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ACCOUNTS_ENABLED")
    with TestClient(app) as client:
        _signed_in(client, accounts_db)
        assert client.post("/me/learn/import", json={}).status_code == 404


def test_import_into_a_new_account_tags_every_row(accounts_db: str) -> None:
    upload = {
        "progress": {
            PUZZLE: {"solved": True, "attempts": 2, "solved_at": T0.isoformat()},
            TUTORIAL: {"solved": False, "attempts": 0, "step": 3},
        },
        "endless": {"count_faan": {"streak": 1, "best": 4, "solved": 6}},
        "prefs": {"learn_band": "intermediate", "coach_marks_done": True},
    }
    with TestClient(app) as client:
        user_id = _signed_in(client, accounts_db)
        response = client.post("/me/learn/import", json=upload)
        stored = client.get("/me/learn").json()
    assert response.status_code == 200
    body = response.json()
    assert body["dropped"] == 0
    assert {k: v for k, v in body.items() if k != "dropped"} == stored
    assert stored["progress"][PUZZLE]["imported"] is True
    assert stored["progress"][TUTORIAL] | {"solved_at": None} == {
        "solved": False,
        "attempts": 0,
        "solved_at": None,
        "step": 3,
        "imported": True,
    }
    assert stored["endless"] == {
        "count_faan": {"streak": 1, "best": 4, "solved": 6, "imported": True}
    }
    assert stored["prefs"] == {"learn_band": "intermediate", "coach_marks_done": True}
    assert run_db(accounts_db, lambda db: learn_imported_at(db, user_id)) is not None


def test_import_merges_with_server_rows(accounts_db: str) -> None:
    with TestClient(app) as client:
        _signed_in(client, accounts_db)
        client.put(f"/me/learn/{PUZZLE}", json={"solved": False, "attempts": 4})
        client.put(
            f"/me/learn/{OTHER}",
            json={"solved": True, "attempts": 3, "solved_at": T0.isoformat()},
        )
        client.put("/me/learn/endless/best_discard", json={"streak": 2, "best": 3, "solved": 5})
        client.put("/me/learn/endless/safe_discard", json={"streak": 4, "best": 9, "solved": 30})
        client.patch("/me", json={"prefs": {"learn_band": "beginner"}})
        body = client.post(
            "/me/learn/import",
            json={
                "progress": {
                    PUZZLE: {"solved": True, "attempts": 1, "solved_at": T1.isoformat()},
                    OTHER: {"solved": True, "attempts": 1, "solved_at": T1.isoformat()},
                },
                "endless": {
                    "best_discard": {"streak": 6, "best": 6, "solved": 7},
                    "safe_discard": {"streak": 1, "best": 2, "solved": 3},
                },
                "prefs": {"learn_band": "advanced"},
            },
        ).json()
    progress, endless = body["progress"], body["endless"]
    assert progress[PUZZLE] | {"solved_at": None} == {
        "solved": True,
        "attempts": 4,
        "solved_at": None,
        "step": None,
        "imported": True,
    }
    assert dt.datetime.fromisoformat(progress[PUZZLE]["solved_at"]) == T1
    # nothing taken from the upload: still a server-recorded row
    assert progress[OTHER]["imported"] is False
    assert progress[OTHER]["attempts"] == 3
    assert dt.datetime.fromisoformat(progress[OTHER]["solved_at"]) == T0
    assert endless["best_discard"] == {"streak": 2, "best": 6, "solved": 7, "imported": True}
    assert endless["safe_discard"] == {"streak": 4, "best": 9, "solved": 30, "imported": False}
    assert body["prefs"] == {"learn_band": "beginner"}


def test_replaying_an_upload_changes_nothing(accounts_db: str) -> None:
    upload = {
        "progress": {PUZZLE: {"solved": True, "attempts": 2, "solved_at": T0.isoformat()}},
        "endless": {"winning_tiles": {"streak": 1, "best": 2, "solved": 3}},
        "prefs": {"coach_marks_done": True},
    }
    with TestClient(app) as client:
        _signed_in(client, accounts_db)
        first = client.post("/me/learn/import", json=upload).json()
        client.put("/me/learn/endless/winning_tiles", json={"streak": 0, "best": 2, "solved": 4})
        before = client.get("/me/learn").json()
        replay = client.post("/me/learn/import", json=upload).json()
    assert first["progress"][PUZZLE]["imported"] is True
    assert {k: v for k, v in replay.items() if k != "dropped"} == before
    assert before["endless"]["winning_tiles"]["streak"] == 0


@pytest.mark.parametrize(
    "bad",
    [
        {"progress": {"no-such-lesson": {"solved": False, "attempts": 1}}},
        {"progress": {PUZZLE: {"solved": True, "attempts": 0}}},
        {"progress": {PUZZLE: {"solved": False, "attempts": -1}}},
        {"progress": {PUZZLE: {"solved": False, "attempts": 1.5}}},
        {"progress": {PUZZLE: {"solved": False, "attempts": 1, "step": 2}}},
        {"progress": {PUZZLE: {"solved": False, "attempts": 1, "solved_at": T0.isoformat()}}},
        {
            "progress": {
                PUZZLE: {
                    "solved": True,
                    "attempts": 1,
                    "solved_at": (dt.datetime.now(dt.UTC) + dt.timedelta(days=1)).isoformat(),
                }
            }
        },
        {"progress": {PUZZLE: {"solved": True, "attempts": 1, "solved_at": "2026-11-01T12:00:00"}}},
        {"progress": {PUZZLE: {"solved": True, "attempts": 1, "extra": 1}}},
        {"progress": {PUZZLE: "solved"}},
        {"endless": {"no_such_kind": {"streak": 0, "best": 0, "solved": 0}}},
        {"endless": {"count_faan": {"streak": 3, "best": 2, "solved": 5}}},
        {"endless": {"count_faan": {"streak": 1, "best": 6, "solved": 5}}},
        {"endless": {"count_faan": {"streak": 1, "best": 1}}},
        {"prefs": {"theme": "dark"}},
        {"prefs": {"learn_band": "expert"}},
        {"prefs": {"coach_marks_done": "yes"}},
        {"prefs": {"learn_band": None}},
    ],
)
def test_a_bad_entry_is_dropped_and_the_rest_kept(accounts_db: str, bad: dict[str, Any]) -> None:
    good = {
        "progress": {TUTORIAL: {"solved": False, "attempts": 1}},
        "endless": {"winning_tiles": {"streak": 0, "best": 1, "solved": 1}},
    }
    upload = {
        "progress": good["progress"] | bad.get("progress", {}),
        "endless": good["endless"] | bad.get("endless", {}),
        "prefs": bad.get("prefs", {}),
    }
    with TestClient(app) as client:
        _signed_in(client, accounts_db)
        response = client.post("/me/learn/import", json=upload)
    body = response.json()
    assert response.status_code == 200
    assert body["dropped"] == 1
    assert set(body["progress"]) == {TUTORIAL}
    assert set(body["endless"]) == {"winning_tiles"}
    assert body["prefs"] == {}


def test_counts_past_the_cap_are_clamped(accounts_db: str) -> None:
    huge = MAX_LEARN_COUNT * 10
    with TestClient(app) as client:
        _signed_in(client, accounts_db)
        body = client.post(
            "/me/learn/import",
            json={
                "progress": {PUZZLE: {"solved": False, "attempts": huge}},
                "endless": {"count_faan": {"streak": huge, "best": huge, "solved": huge}},
            },
        ).json()
    assert body["dropped"] == 0
    assert body["progress"][PUZZLE]["attempts"] == MAX_LEARN_COUNT
    assert body["endless"]["count_faan"] | {"imported": None} == {
        "streak": MAX_LEARN_COUNT,
        "best": MAX_LEARN_COUNT,
        "solved": MAX_LEARN_COUNT,
        "imported": None,
    }


def test_a_server_recorded_solve_clears_an_imported_row(accounts_db: str) -> None:
    with TestClient(app) as client:
        _signed_in(client, accounts_db)
        client.post(
            "/me/learn/import",
            json={
                "progress": {PUZZLE: {"solved": False, "attempts": 2}},
                "endless": {"count_faan": {"streak": 0, "best": 3, "solved": 3}},
            },
        )
        solved = client.put(
            f"/me/learn/{PUZZLE}",
            json={"solved": True, "attempts": 3, "solved_at": T0.isoformat()},
        )
        better = client.put(
            "/me/learn/endless/count_faan", json={"streak": 4, "best": 4, "solved": 4}
        )
    assert solved.json()["imported"] is False
    assert better.json()["imported"] is False


def test_import_rejects_unknown_top_level_fields(accounts_db: str) -> None:
    with TestClient(app) as client:
        _signed_in(client, accounts_db)
        assert client.post("/me/learn/import", json={"scores": {}}).status_code == 422


def test_import_body_is_capped(accounts_db: str) -> None:
    padding = {f"x{i}": {"solved": False, "attempts": 1} for i in range(1000)}
    with TestClient(app) as client:
        _signed_in(client, accounts_db)
        response = client.post("/me/learn/import", json={"progress": padding})
    assert len(str(padding)) > MAX_REQUEST_BODY_BYTES
    assert response.status_code == 413


def test_import_is_rate_limited_per_account(
    accounts_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LEARN_IMPORT_RATE_LIMIT", "2")
    with TestClient(app) as client:
        first = sign_in(accounts_db, create_user(accounts_db))
        second = sign_in(accounts_db, create_user(accounts_db))
        client.cookies.set(COOKIE_NAME, first)
        codes = [client.post("/me/learn/import", json={}).status_code for _ in range(3)]
        refused = client.post("/me/learn/import", json={})
        client.cookies.delete(COOKIE_NAME)
        client.cookies.set(COOKIE_NAME, second)
        other = client.post("/me/learn/import", json={}).status_code
    assert codes == [200, 200, 429]
    assert int(refused.headers["retry-after"]) > 0
    assert other == 200
