"""`GET /me`, `POST /auth/logout`, `ACCOUNTS_ENABLED` and credentialed CORS
(docs/protocol.md §10 "Accounts")."""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app.accounts.config import AccountsConfig, cors_origins
from app.accounts.sessions import COOKIE_NAME
from app.main import app
from tests.accounts import create_user, session_count, sign_in

_WEB = "http://localhost:5173"


@pytest.mark.parametrize("flag", [None, "0", "false"])
@pytest.mark.parametrize(
    ("method", "path"), [("GET", "/me"), ("POST", "/auth/logout")], ids=["me", "logout"]
)
def test_accounts_routes_404_while_the_flag_is_off(
    accounts_db: str, monkeypatch: pytest.MonkeyPatch, flag: str | None, method: str, path: str
) -> None:
    if flag is None:
        monkeypatch.delenv("ACCOUNTS_ENABLED")
    else:
        monkeypatch.setenv("ACCOUNTS_ENABLED", flag)
    token = sign_in(accounts_db, create_user(accounts_db))
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, token)
        assert client.request(method, path).status_code == 404


def test_accounts_routes_404_without_a_database(
    accounts_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DATABASE_URL")
    with TestClient(app) as client:
        assert client.get("/me").status_code == 404


def test_me_without_a_cookie_is_401(accounts_db: str) -> None:
    with TestClient(app) as client:
        assert client.get("/me").status_code == 401


def test_me_with_a_bad_cookie_is_401(accounts_db: str) -> None:
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, "forged")
        assert client.get("/me").status_code == 401


def test_me_returns_the_signed_in_user(accounts_db: str) -> None:
    user_id = create_user(accounts_db, display_name="Ann")
    token = sign_in(accounts_db, user_id)
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, token)
        response = client.get("/me")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(user_id)
    assert body["display_name"] == "Ann"
    assert body["training_consent_at"] is None
    assert body["consent_version"] is None
    assert "created_at" in body


def test_me_rejects_a_disabled_user(accounts_db: str) -> None:
    user_id = create_user(accounts_db, disabled_at=dt.datetime.now(dt.UTC))
    token = sign_in(accounts_db, user_id)
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, token)
        assert client.get("/me").status_code == 401
    assert session_count(accounts_db) == 0


def test_logout_deletes_the_session_and_clears_the_cookie(accounts_db: str) -> None:
    token = sign_in(accounts_db, create_user(accounts_db))
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, token)
        response = client.post("/auth/logout")
        assert response.status_code == 204
        cookie = response.headers["set-cookie"]
        assert cookie.startswith(f"{COOKIE_NAME}=")
        assert "Max-Age=0" in cookie
        client.cookies.set(COOKIE_NAME, token)
        assert client.get("/me").status_code == 401
    assert session_count(accounts_db) == 0


def test_logout_without_a_cookie_is_still_204(accounts_db: str) -> None:
    with TestClient(app) as client:
        assert client.post("/auth/logout").status_code == 204


def test_cors_allows_credentials_for_a_listed_origin(accounts_db: str) -> None:
    token = sign_in(accounts_db, create_user(accounts_db))
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, token)
        response = client.get("/me", headers={"Origin": _WEB})
        preflight = client.options(
            "/auth/logout",
            headers={"Origin": _WEB, "Access-Control-Request-Method": "POST"},
        )
    assert response.headers["access-control-allow-origin"] == _WEB
    assert response.headers["access-control-allow-credentials"] == "true"
    assert preflight.headers["access-control-allow-credentials"] == "true"


def test_config_derives_from_env() -> None:
    config = AccountsConfig.from_env(
        {
            "ACCOUNTS_ENABLED": "1",
            "CORS_ORIGINS": "*, https://web.example ,https://other.example",
            "PUBLIC_API_URL": "https://api.example/",
        }
    )
    assert cors_origins({"CORS_ORIGINS": "*,https://web.example"}) == ["https://web.example"]
    assert config.enabled
    assert config.api_url == "https://api.example"
    assert config.web_url == "https://web.example"
    assert config.cookie_secure
    assert config.session_max_age == dt.timedelta(days=90)
    assert config.session_idle == dt.timedelta(days=30)
    local = AccountsConfig.from_env({"PUBLIC_WEB_URL": "http://localhost:5173"})
    assert not local.enabled
    assert not local.cookie_secure
    assert local.web_url == "http://localhost:5173"


def test_cors_never_echoes_an_unlisted_origin(accounts_db: str) -> None:
    with TestClient(app) as client:
        response = client.get("/me", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers
