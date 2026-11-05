"""Google sign-in against a stubbed token endpoint and userinfo (no network): PKCE + state,
user/identity upsert, session rotation, disabled users, redirects, rate limit
(docs/protocol.md §10 "Accounts")."""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts import google
from app.accounts import routes as accounts
from app.accounts.google import GoogleProvider
from app.accounts.sessions import COOKIE_NAME
from app.db.models import Identity, User
from app.main import app
from tests.accounts import fetch, run_db, session_count, sign_in

_WEB = "http://web.test"
_API = "http://localhost:8000"

type Userinfo = dict[str, object]


class FakeGoogle:
    """Google's token and userinfo endpoints. Checks the PKCE verifier against the challenge
    the login redirect sent."""

    def __init__(self) -> None:
        self.userinfo: Userinfo = {"sub": "g-1", "email": "ann@x.test", "name": "Ann Lee"}
        self.challenge: str | None = None
        self.token_status = 200

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        if str(request.url) == google.TOKEN_URL:
            form = parse_qs(request.content.decode())
            assert form["grant_type"] == ["authorization_code"]
            assert form["code"] == ["the-code"]
            assert form["redirect_uri"] == [f"{_API}/auth/google/callback"]
            digest = hashlib.sha256(form["code_verifier"][0].encode()).digest()
            assert base64.urlsafe_b64encode(digest).rstrip(b"=").decode() == self.challenge
            if self.token_status != 200:
                return httpx2.Response(self.token_status, json={"error": "invalid_grant"})
            return httpx2.Response(
                200, json={"access_token": "at", "token_type": "Bearer", "expires_in": 3600}
            )
        if str(request.url) == google.USERINFO_URL:
            assert request.headers["authorization"] == "Bearer at"
            return httpx2.Response(200, json=self.userinfo)
        raise AssertionError(f"unexpected request {request.url}")


@pytest.fixture
def fake_google(accounts_db: str, monkeypatch: pytest.MonkeyPatch) -> FakeGoogle:
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("PUBLIC_WEB_URL", _WEB)
    return FakeGoogle()


@contextmanager
def _client(fake: FakeGoogle) -> Iterator[TestClient]:
    with TestClient(app) as client:
        accounts.set_google(
            GoogleProvider("cid", "secret", transport=httpx2.MockTransport(fake.handler))
        )
        yield client


def _login(client: TestClient, fake: FakeGoogle, next_: str | None = None) -> dict[str, str]:
    params = {"next": next_} if next_ is not None else {}
    response = client.get("/auth/google/login", params=params, follow_redirects=False)
    assert response.status_code == 302
    location = urlsplit(response.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == google.AUTHORIZE_URL
    query = {k: v[0] for k, v in parse_qs(location.query).items()}
    fake.challenge = query["code_challenge"]
    return query


def _callback(client: TestClient, state: str, **params: str) -> httpx2.Response:
    return client.get(
        "/auth/google/callback",
        params={"code": "the-code", "state": state} | params,
        follow_redirects=False,
    )


def _sign_in(client: TestClient, fake: FakeGoogle, next_: str | None = None) -> httpx2.Response:
    return _callback(client, _login(client, fake, next_)["state"])


def test_login_redirects_to_google_with_pkce_and_state(fake_google: FakeGoogle) -> None:
    with _client(fake_google) as client:
        query = _login(client, fake_google)
    assert query["client_id"] == "cid"
    assert query["response_type"] == "code"
    assert query["scope"] == "openid email profile"
    assert query["redirect_uri"] == f"{_API}/auth/google/callback"
    assert query["code_challenge_method"] == "S256"
    assert len(query["state"]) >= 43


def test_first_sign_in_creates_the_user_and_asks_for_sign_up(
    fake_google: FakeGoogle, accounts_db: str
) -> None:
    with _client(fake_google) as client:
        response = _sign_in(client, fake_google, "/learn")
        assert response.status_code == 303
        assert response.headers["location"] == f"{_WEB}/learn?signup=1"
        cookies = response.headers.get_list("set-cookie")
        session_cookie = next(c for c in cookies if c.startswith(f"{COOKIE_NAME}="))
        assert "HttpOnly" in session_cookie
        assert "samesite=lax" in session_cookie.lower()
        assert "Domain" not in session_cookie
        me = client.get("/me").json()
    assert me["display_name"] == "Ann Lee"
    identity = fetch(accounts_db, Identity, "google", "g-1")
    assert identity is not None
    assert str(identity.user_id) == me["id"]
    assert identity.email == "ann@x.test"


def test_returning_sign_in_rotates_the_session_and_refreshes_email(
    fake_google: FakeGoogle, accounts_db: str
) -> None:
    with _client(fake_google) as client:
        _sign_in(client, fake_google)
        first = client.cookies[COOKIE_NAME]
        fake_google.userinfo = {"sub": "g-1", "email": "new@x.test", "name": "Someone Else"}
        response = _sign_in(client, fake_google)
        assert response.headers["location"] == f"{_WEB}/"
        second = client.cookies[COOKIE_NAME]
        assert second != first
        me = client.get("/me").json()
        client.cookies.delete(COOKIE_NAME)  # httpx2's set() adds beside the jar's cookie
        client.cookies.set(COOKIE_NAME, first)
        assert client.get("/me").status_code == 401
    assert me["display_name"] == "Ann Lee"  # a returning user's name is theirs, not google's
    assert session_count(accounts_db) == 1
    identity = fetch(accounts_db, Identity, "google", "g-1")
    assert identity is not None and identity.email == "new@x.test"

    async def count_users(db: AsyncSession) -> int:
        return len((await db.scalars(select(User))).all())

    assert run_db(accounts_db, count_users) == 1


def test_a_nameless_profile_gets_a_default_name(fake_google: FakeGoogle) -> None:
    fake_google.userinfo = {"sub": "g-2", "name": "   "}
    with _client(fake_google) as client:
        _sign_in(client, fake_google)
        assert client.get("/me").json()["display_name"] == "Player"


def test_a_disabled_user_is_refused(fake_google: FakeGoogle, accounts_db: str) -> None:
    with _client(fake_google) as client:
        _sign_in(client, fake_google)
        user_id = fetch(accounts_db, Identity, "google", "g-1").user_id  # type: ignore[union-attr]
    sign_in(accounts_db, user_id)

    async def disable(db: AsyncSession) -> None:
        user = await db.get(User, user_id)
        assert user is not None
        user.disabled_at = dt.datetime.now(dt.UTC)
        await db.commit()

    run_db(accounts_db, disable)
    with _client(fake_google) as client:
        response = _sign_in(client, fake_google)
        assert response.status_code == 303
        assert response.headers["location"] == f"{_WEB}/?signin=disabled"
        assert COOKIE_NAME not in client.cookies
    assert session_count(accounts_db) == 0


@pytest.mark.parametrize(
    ("next_", "expected"),
    [
        ("/table/ABC123?x=1", "/table/ABC123?x=1&signup=1"),
        ("//evil.example/", "/?signup=1"),
        ("https://evil.example/", "/?signup=1"),
        ("/\\evil.example", "/?signup=1"),
    ],
)
def test_next_must_be_a_local_path(fake_google: FakeGoogle, next_: str, expected: str) -> None:
    with _client(fake_google) as client:
        response = _sign_in(client, fake_google, next_)
    assert response.headers["location"] == f"{_WEB}{expected}"


def test_a_state_mismatch_is_400(fake_google: FakeGoogle, accounts_db: str) -> None:
    with _client(fake_google) as client:
        _login(client, fake_google)
        assert _callback(client, "forged").status_code == 400
    assert session_count(accounts_db) == 0


def test_a_callback_without_the_login_cookie_is_400(fake_google: FakeGoogle) -> None:
    with _client(fake_google) as client:
        assert _callback(client, "anything").status_code == 400


def test_a_refused_consent_redirects_back(fake_google: FakeGoogle) -> None:
    with _client(fake_google) as client:
        state = _login(client, fake_google)["state"]
        response = client.get(
            "/auth/google/callback",
            params={"error": "access_denied", "state": state},
            follow_redirects=False,
        )
    assert response.status_code == 303
    assert response.headers["location"] == f"{_WEB}/?signin=failed"


def test_a_failed_token_exchange_is_502(fake_google: FakeGoogle, accounts_db: str) -> None:
    fake_google.token_status = 400
    with _client(fake_google) as client:
        assert _sign_in(client, fake_google).status_code == 502
    assert session_count(accounts_db) == 0


@pytest.mark.parametrize("missing", ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"])
def test_google_routes_404_without_credentials(
    fake_google: FakeGoogle, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    monkeypatch.delenv(missing)
    with TestClient(app) as client:
        assert client.get("/auth/google/login", follow_redirects=False).status_code == 404


def test_google_routes_404_while_the_flag_is_off(
    fake_google: FakeGoogle, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ACCOUNTS_ENABLED")
    with TestClient(app) as client:
        assert client.get("/auth/google/login", follow_redirects=False).status_code == 404
        assert client.get("/auth/google/callback").status_code == 404


def test_auth_routes_are_rate_limited_per_ip(
    fake_google: FakeGoogle, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTH_RATE_LIMIT", "2")
    with _client(fake_google) as client:
        hits: list[Callable[[], httpx2.Response]] = [
            lambda: client.get("/auth/google/login", follow_redirects=False),
            lambda: client.post("/auth/logout"),
            lambda: client.get("/auth/google/login", follow_redirects=False),
        ]
        statuses = [hit().status_code for hit in hits]
        refused = client.post("/auth/logout")
        me = client.get("/me")
    assert statuses == [302, 204, 429]
    assert refused.status_code == 429
    assert int(refused.headers["retry-after"]) >= 1
    assert me.status_code == 401  # /me isn't under /auth


def test_odd_userinfo_fields_are_dropped(fake_google: FakeGoogle, accounts_db: str) -> None:
    fake_google.userinfo = {"sub": "g-3", "email": 5, "name": ["x"]}
    with _client(fake_google) as client:
        _sign_in(client, fake_google)
        assert client.get("/me").json()["display_name"] == "Player"
    identity = fetch(accounts_db, Identity, "google", "g-3")
    assert identity is not None and identity.email is None


def test_userinfo_without_a_subject_is_502(fake_google: FakeGoogle) -> None:
    fake_google.userinfo = {"email": "a@x.test"}
    with _client(fake_google) as client:
        assert _sign_in(client, fake_google).status_code == 502
