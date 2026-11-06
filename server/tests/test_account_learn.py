"""`GET /me/learn`, `PUT /me/learn/{lesson_id}`, `PUT /me/learn/endless/{kind}` and `PATCH /me`
prefs (docs/protocol.md §10 "Accounts", ADR 0028 "Learn progress: guest vs signed in")."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.learn import MAX_LEARN_COUNT
from app.accounts.sessions import COOKIE_NAME
from app.accounts.users import upsert_identity
from app.db.models import LearnEndlessScore, LearnProgress
from app.lessons.catalog import CATALOG, TUTORIALS
from app.main import app
from tests.accounts import create_user, fetch, run_db, sign_in

_WEB = "http://localhost:5173"
PUZZLE = CATALOG[0].id
TUTORIAL = TUTORIALS[0].id
T0 = dt.datetime(2026, 11, 1, 12, 0, tzinfo=dt.UTC)


def _signed_in(client: TestClient, accounts_db: str) -> uuid.UUID:
    user_id = create_user(accounts_db)
    client.cookies.set(COOKIE_NAME, sign_in(accounts_db, user_id))
    return user_id


def _iso(at: dt.datetime) -> str:
    return at.isoformat()


def _seed_imported(accounts_db: str, user_id: uuid.UUID) -> None:
    async def work(db: AsyncSession) -> None:
        db.add(
            LearnProgress(
                user_id=user_id,
                lesson_id=PUZZLE,
                solved=False,
                attempts=3,
                imported=True,
                updated_at=T0,
            )
        )
        db.add(
            LearnEndlessScore(
                user_id=user_id,
                kind="count_faan",
                streak=0,
                best=5,
                solved=9,
                imported=True,
                updated_at=T0,
            )
        )
        await db.commit()

    run_db(accounts_db, work)


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/me/learn", None),
        ("PUT", f"/me/learn/{PUZZLE}", {"solved": False, "attempts": 1}),
        ("PUT", "/me/learn/endless/winning_tiles", {"streak": 0, "best": 0, "solved": 0}),
    ],
)
def test_learn_routes_need_a_session(
    accounts_db: str, method: str, path: str, body: dict[str, Any] | None
) -> None:
    with TestClient(app) as client:
        assert client.request(method, path, json=body).status_code == 401


def test_learn_routes_404_while_the_flag_is_off(
    accounts_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ACCOUNTS_ENABLED")
    with TestClient(app) as client:
        _signed_in(client, accounts_db)
        assert client.get("/me/learn").status_code == 404
        put = client.put(f"/me/learn/{PUZZLE}", json={"solved": False, "attempts": 1})
        assert put.status_code == 404


def test_a_new_account_has_no_progress(accounts_db: str) -> None:
    with TestClient(app) as client:
        _signed_in(client, accounts_db)
        assert client.get("/me/learn").json() == {"progress": {}, "endless": {}, "prefs": {}}


def test_put_lesson_round_trips(accounts_db: str) -> None:
    with TestClient(app) as client:
        _signed_in(client, accounts_db)
        put = client.put(
            f"/me/learn/{PUZZLE}",
            json={"solved": True, "attempts": 2, "solved_at": _iso(T0)},
        )
        step = client.put(f"/me/learn/{TUTORIAL}", json={"solved": False, "attempts": 0, "step": 4})
        body = client.get("/me/learn").json()
    assert put.status_code == 200 and step.status_code == 200
    progress = body["progress"]
    assert progress[PUZZLE]["solved"] is True
    assert progress[PUZZLE]["attempts"] == 2
    assert dt.datetime.fromisoformat(progress[PUZZLE]["solved_at"]) == T0
    assert progress[PUZZLE]["imported"] is False
    assert progress[TUTORIAL] | {"solved_at": None} == {
        "solved": False,
        "attempts": 0,
        "solved_at": None,
        "step": 4,
        "imported": False,
    }


def test_put_lesson_never_undoes_a_solve(accounts_db: str) -> None:
    with TestClient(app) as client:
        _signed_in(client, accounts_db)
        client.put(
            f"/me/learn/{TUTORIAL}",
            json={"solved": True, "attempts": 3, "step": 2, "solved_at": _iso(T0)},
        )
        # a second device's stale copy
        later = T0 + dt.timedelta(days=1)
        stale = client.put(
            f"/me/learn/{TUTORIAL}",
            json={"solved": True, "attempts": 1, "solved_at": _iso(later), "step": None},
        )
        regress = client.put(f"/me/learn/{TUTORIAL}", json={"solved": False, "attempts": 0})
    row = regress.json()
    assert stale.status_code == 200
    assert row["solved"] is True
    assert row["attempts"] == 3
    assert dt.datetime.fromisoformat(row["solved_at"]) == T0
    # the resume point is the latest one, cleared included
    assert row["step"] is None


@pytest.mark.parametrize(
    ("lesson_id", "body"),
    [
        ("no-such-lesson", {"solved": False, "attempts": 1}),
        (PUZZLE, {"solved": False, "attempts": 1, "step": 2}),
        (PUZZLE, {"solved": True, "attempts": 0}),
        (PUZZLE, {"solved": False, "attempts": 1, "solved_at": "2026-11-01T12:00:00Z"}),
        (PUZZLE, {"solved": False, "attempts": MAX_LEARN_COUNT + 1}),
        (PUZZLE, {"solved": False, "attempts": -1}),
        (PUZZLE, {"solved": True, "attempts": 1, "solved_at": "2026-11-01T12:00:00"}),
        (PUZZLE, {"solved": False, "attempts": 1, "extra": 1}),
        (TUTORIAL, {"solved": False, "attempts": 0, "step": MAX_LEARN_COUNT + 1}),
    ],
)
def test_put_lesson_rejects_a_bad_entry(
    accounts_db: str, lesson_id: str, body: dict[str, Any]
) -> None:
    with TestClient(app) as client:
        _signed_in(client, accounts_db)
        assert client.put(f"/me/learn/{lesson_id}", json=body).status_code == 422
        assert client.get("/me/learn").json()["progress"] == {}


def test_put_lesson_clamps_solved_at_to_now(accounts_db: str) -> None:
    now = dt.datetime.now(dt.UTC)
    with TestClient(app) as client:
        _signed_in(client, accounts_db)
        ahead = client.put(
            f"/me/learn/{PUZZLE}",
            json={"solved": True, "attempts": 1, "solved_at": _iso(now + dt.timedelta(minutes=1))},
        )
        future = client.put(
            f"/me/learn/{TUTORIAL}",
            json={"solved": True, "attempts": 1, "solved_at": _iso(now + dt.timedelta(days=1))},
        )
    assert dt.datetime.fromisoformat(ahead.json()["solved_at"]) <= dt.datetime.now(dt.UTC)
    assert future.status_code == 422


def test_a_server_recorded_solve_clears_imported(accounts_db: str) -> None:
    with TestClient(app) as client:
        user_id = _signed_in(client, accounts_db)
        _seed_imported(accounts_db, user_id)
        attempt = client.put(f"/me/learn/{PUZZLE}", json={"solved": False, "attempts": 4})
        solve = client.put(
            f"/me/learn/{PUZZLE}",
            json={"solved": True, "attempts": 5, "solved_at": _iso(T0)},
        )
    assert attempt.json()["imported"] is True
    assert solve.json()["imported"] is False


def test_put_endless_round_trips(accounts_db: str) -> None:
    with TestClient(app) as client:
        _signed_in(client, accounts_db)
        put = client.put("/me/learn/endless/count_faan", json={"streak": 2, "best": 4, "solved": 7})
        body = client.get("/me/learn").json()
    assert put.status_code == 200
    assert body["endless"] == {
        "count_faan": {"streak": 2, "best": 4, "solved": 7, "imported": False}
    }


def test_put_endless_keeps_best_and_solved_and_takes_the_streak(accounts_db: str) -> None:
    with TestClient(app) as client:
        _signed_in(client, accounts_db)
        client.put("/me/learn/endless/best_discard", json={"streak": 4, "best": 6, "solved": 9})
        stale = client.put(
            "/me/learn/endless/best_discard", json={"streak": 0, "best": 2, "solved": 3}
        )
    assert stale.json() == {"streak": 0, "best": 6, "solved": 9, "imported": False}


@pytest.mark.parametrize(
    ("kind", "body"),
    [
        ("no_such_kind", {"streak": 0, "best": 0, "solved": 0}),
        ("safe_discard", {"streak": 3, "best": 2, "solved": 5}),
        ("safe_discard", {"streak": 1, "best": 5, "solved": 4}),
        ("safe_discard", {"streak": 0, "best": 0, "solved": MAX_LEARN_COUNT + 1}),
        ("safe_discard", {"streak": 0, "best": 0}),
    ],
)
def test_put_endless_rejects_a_bad_score(accounts_db: str, kind: str, body: dict[str, Any]) -> None:
    with TestClient(app) as client:
        _signed_in(client, accounts_db)
        assert client.put(f"/me/learn/endless/{kind}", json=body).status_code == 422


def test_a_better_best_clears_imported(accounts_db: str) -> None:
    with TestClient(app) as client:
        user_id = _signed_in(client, accounts_db)

        async def seed(db: AsyncSession) -> None:
            db.add(
                LearnEndlessScore(
                    user_id=user_id,
                    kind="winning_tiles",
                    streak=0,
                    best=5,
                    solved=9,
                    imported=True,
                    updated_at=T0,
                )
            )
            await db.commit()

        run_db(accounts_db, seed)
        same = client.put(
            "/me/learn/endless/winning_tiles", json={"streak": 5, "best": 5, "solved": 10}
        )
        better = client.put(
            "/me/learn/endless/winning_tiles", json={"streak": 6, "best": 6, "solved": 11}
        )
    assert same.json()["imported"] is True
    assert better.json() == {"streak": 6, "best": 6, "solved": 11, "imported": False}


def test_patch_prefs_merges_known_keys(accounts_db: str) -> None:
    with TestClient(app) as client:
        _signed_in(client, accounts_db)
        first = client.patch("/me", json={"prefs": {"learn_band": "advanced"}})
        client.patch("/me", json={"prefs": {"coach_marks_done": True}})
        both = client.get("/me/learn").json()["prefs"]
        client.patch("/me", json={"prefs": {"learn_band": None}})
        cleared = client.get("/me/learn").json()["prefs"]
    assert first.status_code == 200
    assert "prefs" not in first.json()
    assert both == {"learn_band": "advanced", "coach_marks_done": True}
    assert cleared == {"coach_marks_done": True}


@pytest.mark.parametrize(
    "prefs",
    [{"theme": "dark"}, {"learn_band": "expert"}, {"coach_marks_done": "yes"}, ["learn_band"]],
)
def test_patch_rejects_unknown_or_bad_prefs(accounts_db: str, prefs: Any) -> None:
    with TestClient(app) as client:
        _signed_in(client, accounts_db)
        assert client.patch("/me", json={"prefs": prefs}).status_code == 422
        assert client.get("/me/learn").json()["prefs"] == {}


def test_export_holds_learn_progress(accounts_db: str) -> None:
    with TestClient(app) as client:
        _signed_in(client, accounts_db)
        client.put(f"/me/learn/{PUZZLE}", json={"solved": False, "attempts": 2})
        client.put("/me/learn/endless/winning_tiles", json={"streak": 1, "best": 1, "solved": 1})
        client.patch("/me", json={"prefs": {"learn_band": "intermediate"}})
        learn = client.get("/me/learn").json()
        body = client.get("/me/export").json()
    assert body["learn"] == learn
    assert set(learn["progress"]) == {PUZZLE}
    assert learn["prefs"] == {"learn_band": "intermediate"}


def test_deleting_the_account_deletes_its_progress(accounts_db: str) -> None:
    with TestClient(app) as client:
        user_id = _signed_in(client, accounts_db)
        _seed_imported(accounts_db, user_id)
        assert client.delete("/me").status_code == 204
    assert fetch(accounts_db, LearnProgress, user_id, PUZZLE) is None
    assert fetch(accounts_db, LearnEndlessScore, user_id, "count_faan") is None


def test_cors_preflight_allows_put(accounts_db: str) -> None:
    with TestClient(app) as client:
        response = client.options(
            f"/me/learn/{PUZZLE}",
            headers={
                "Origin": _WEB,
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Headers": "content-type",
            },
        )
    assert response.status_code == 200
    assert "PUT" in response.headers["access-control-allow-methods"]


def test_sign_in_and_me_work_before_the_learn_migration(accounts_db: str) -> None:
    """Code deployed ahead of `make prod-migrate` (ADR 0028 "Pull requests")."""

    async def unmigrate(db: AsyncSession) -> None:
        await db.execute(text("DROP TABLE learn_progress"))
        await db.execute(text("DROP TABLE learn_endless_scores"))
        await db.execute(text("ALTER TABLE users DROP COLUMN prefs"))
        await db.execute(text("ALTER TABLE users DROP COLUMN learn_imported_at"))
        await db.commit()

    run_db(accounts_db, unmigrate)

    async def first_sign_in(db: AsyncSession) -> uuid.UUID:
        user, created = await upsert_identity(db, provider="google", subject="s-1", email=None)
        assert created
        return user.id

    user_id = run_db(accounts_db, first_sign_in)
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, sign_in(accounts_db, user_id))
        me = client.get("/me")
        renamed = client.patch("/me", json={"display_name": "Ann"})
    assert me.status_code == 200
    assert renamed.json()["display_name"] == "Ann"
