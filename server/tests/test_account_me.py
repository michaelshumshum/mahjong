"""`PATCH /me`, `DELETE /me`, `GET /me/export` (docs/protocol.md §10 "Accounts")."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.routes import TRAINING_CONSENT_VERSION
from app.accounts.sessions import COOKIE_NAME
from app.db.models import AuthSession, GameRecord, GameSeat, Identity, User
from app.main import app
from app.names import MAX_NAME_LENGTH
from tests.accounts import create_user, fetch, run_db, session_count, sign_in

_WEB = "http://localhost:5173"


def _signed_in(client: TestClient, accounts_db: str, **columns: object) -> uuid.UUID:
    user_id = create_user(accounts_db, **columns)
    client.cookies.set(COOKIE_NAME, sign_in(accounts_db, user_id))
    return user_id


def _seed_game(accounts_db: str, user_id: uuid.UUID, seat: int = 1) -> int:
    async def work(db: AsyncSession) -> int:
        game = GameRecord(
            engine_version="test",
            ruleset={},
            seed=7,
            action_log=[],
            players=["Bob", "Ann", "阿發", "Cy"],
            result={"hand_count": 5, "final_scores": [10, 40, -20, -30]},
            mode="multiplayer",
        )
        db.add(game)
        await db.flush()
        kinds = {0: "guest", 1: "guest", 2: "bot", 3: "guest"} | {seat: "user"}
        db.add_all(
            GameSeat(
                game_id=game.id,
                seat=s,
                kind=kinds[s],
                user_id=user_id if s == seat else None,
                bot_tier="T2" if kinds[s] == "bot" else None,
                final_score=[10, 40, -20, -30][s],
                placement=[2, 1, 3, 4][s],
            )
            for s in range(4)
        )
        await db.commit()
        return game.id

    return run_db(accounts_db, work)


@pytest.mark.parametrize(
    ("method", "path"),
    [("PATCH", "/me"), ("DELETE", "/me"), ("GET", "/me/export")],
)
def test_me_routes_need_a_session(accounts_db: str, method: str, path: str) -> None:
    with TestClient(app) as client:
        assert client.request(method, path, json={}).status_code == 401


@pytest.mark.parametrize(
    ("method", "path"),
    [("PATCH", "/me"), ("DELETE", "/me"), ("GET", "/me/export")],
)
def test_me_routes_404_while_the_flag_is_off(
    accounts_db: str, monkeypatch: pytest.MonkeyPatch, method: str, path: str
) -> None:
    monkeypatch.delenv("ACCOUNTS_ENABLED")
    with TestClient(app) as client:
        _signed_in(client, accounts_db)
        assert client.request(method, path, json={}).status_code == 404


def test_patch_renames_through_the_seat_name_normalizer(accounts_db: str) -> None:
    with TestClient(app) as client:
        _signed_in(client, accounts_db)
        long_name = "  " + "x" * (MAX_NAME_LENGTH + 5) + " "
        response = client.patch("/me", json={"display_name": long_name})
    assert response.status_code == 200
    assert response.json()["display_name"] == "x" * MAX_NAME_LENGTH


@pytest.mark.parametrize("name", ["", "   "])
def test_patch_rejects_an_empty_name(accounts_db: str, name: str) -> None:
    with TestClient(app) as client:
        _signed_in(client, accounts_db, display_name="Ann")
        assert client.patch("/me", json={"display_name": name}).status_code == 422
        assert client.get("/me").json()["display_name"] == "Ann"


def test_patch_gives_and_withdraws_training_consent(accounts_db: str) -> None:
    with TestClient(app) as client:
        user_id = _signed_in(client, accounts_db)
        given = client.patch("/me", json={"training_consent": True}).json()
        again = client.patch("/me", json={"training_consent": True}).json()
        renamed = client.patch("/me", json={"display_name": "Bo"}).json()
        withdrawn = client.patch("/me", json={"training_consent": False}).json()
    assert given["training_consent_at"] is not None
    assert given["consent_version"] == TRAINING_CONSENT_VERSION
    assert again["training_consent_at"] == given["training_consent_at"]
    assert renamed["training_consent_at"] == given["training_consent_at"]
    assert withdrawn["training_consent_at"] is None
    assert withdrawn["consent_version"] is None
    user = fetch(accounts_db, User, user_id)
    assert user is not None and user.training_consent_at is None


def test_patch_rejects_unknown_fields(accounts_db: str) -> None:
    with TestClient(app) as client:
        _signed_in(client, accounts_db)
        assert client.patch("/me", json={"disabled_at": None}).status_code == 422


def test_delete_removes_the_account_and_keeps_its_seats(accounts_db: str) -> None:
    with TestClient(app) as client:
        user_id = _signed_in(client, accounts_db)
        sign_in(accounts_db, user_id)  # a second device

        async def add_identity(db: AsyncSession) -> None:
            db.add(Identity(provider="google", subject="g-1", user_id=user_id, email="a@x.test"))
            await db.commit()

        run_db(accounts_db, add_identity)
        game_id = _seed_game(accounts_db, user_id)

        response = client.delete("/me")
        assert response.status_code == 204
        assert "Max-Age=0" in response.headers["set-cookie"]
        assert client.get("/me").status_code == 401

    assert fetch(accounts_db, User, user_id) is None
    assert fetch(accounts_db, Identity, "google", "g-1") is None
    assert session_count(accounts_db) == 0
    seat = fetch(accounts_db, GameSeat, game_id, 1)
    assert seat is not None and (seat.kind, seat.user_id) == ("user", None)
    game = fetch(accounts_db, GameRecord, game_id)
    assert game is not None and game.players[1] == "Ann"


def test_delete_leaves_other_accounts_alone(accounts_db: str) -> None:
    other = create_user(accounts_db, display_name="Bob")
    sign_in(accounts_db, other)
    with TestClient(app) as client:
        _signed_in(client, accounts_db)
        client.delete("/me")

    async def remaining(db: AsyncSession) -> list[uuid.UUID]:
        return list((await db.scalars(select(AuthSession.user_id))).all())

    assert fetch(accounts_db, User, other) is not None
    assert run_db(accounts_db, remaining) == [other]


def test_export_holds_the_user_identities_and_games(accounts_db: str) -> None:
    with TestClient(app) as client:
        user_id = _signed_in(client, accounts_db, display_name="Ann")

        async def add_identity(db: AsyncSession) -> None:
            db.add(Identity(provider="google", subject="g-1", user_id=user_id, email="a@x.test"))
            await db.commit()

        run_db(accounts_db, add_identity)
        older = _seed_game(accounts_db, user_id, seat=1)
        newer = _seed_game(accounts_db, user_id, seat=3)
        _seed_game(accounts_db, create_user(accounts_db, display_name="Bob"), seat=0)
        response = client.get("/me/export")

    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    body = response.json()
    assert body["user"]["id"] == str(user_id)
    assert body["user"]["display_name"] == "Ann"
    assert body["user"]["disabled_at"] is None
    assert [(i["provider"], i["subject"], i["email"]) for i in body["identities"]] == [
        ("google", "g-1", "a@x.test")
    ]
    games = body["games"]
    assert [g["game_id"] for g in games] == [newer, older]
    assert games[1] | {"created_at": None} == {
        "game_id": older,
        "created_at": None,
        "mode": "multiplayer",
        "seat": 1,
        "hand_count": 5,
        "final_score": 40,
        "placement": 1,
        "players": ["Bob", "Ann", "阿發", "Cy"],
    }
    assert "learn_progress" not in body


def test_cors_preflight_allows_patch_and_delete(accounts_db: str) -> None:
    with TestClient(app) as client:
        for method in ("PATCH", "DELETE"):
            response = client.options(
                "/me",
                headers={
                    "Origin": _WEB,
                    "Access-Control-Request-Method": method,
                    "Access-Control-Request-Headers": "content-type",
                },
            )
            assert response.status_code == 200
            assert method in response.headers["access-control-allow-methods"]
            assert response.headers["access-control-allow-credentials"] == "true"
