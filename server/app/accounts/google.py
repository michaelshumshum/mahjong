"""Google sign-in: OAuth 2.0 authorization code with PKCE (S256) and `state`, through Authlib.
The profile comes from Google's userinfo endpoint with the fresh access token, so no ID-token
signature check (and no JWKS fetch) is needed."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

import httpx2
from authlib.integrations.httpx_client import AsyncOAuth2Client

PROVIDER: Final = "google"
# no `profile`: an account starts with a placeholder name, never the user's google name
SCOPES: Final = "openid email"
AUTHORIZE_URL: Final = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL: Final = "https://oauth2.googleapis.com/token"
USERINFO_URL: Final = "https://openidconnect.googleapis.com/v1/userinfo"
_TIMEOUT_SECONDS: Final = 10.0


@dataclass(frozen=True, slots=True)
class Profile:
    subject: str
    email: str | None


class GoogleProvider:
    """`transport` lets tests stub Google's endpoints with `httpx2.MockTransport`."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._transport = transport

    def _client(self, redirect_uri: str) -> AsyncOAuth2Client:
        extra: dict[str, Any] = {"transport": self._transport} if self._transport else {}
        return AsyncOAuth2Client(
            client_id=self._client_id,
            client_secret=self._client_secret,
            scope=SCOPES,
            redirect_uri=redirect_uri,
            code_challenge_method="S256",
            timeout=_TIMEOUT_SECONDS,
            **extra,
        )

    def authorize_url(self, *, redirect_uri: str, state: str, code_verifier: str) -> str:
        url, _ = self._client(redirect_uri).create_authorization_url(
            AUTHORIZE_URL, state=state, code_verifier=code_verifier
        )
        return str(url)

    async def fetch_profile(self, *, redirect_uri: str, code: str, code_verifier: str) -> Profile:
        """Exchange `code` and read the user's profile. Raises on any provider error."""
        async with self._client(redirect_uri) as client:
            await client.fetch_token(TOKEN_URL, code=code, code_verifier=code_verifier)
            response = await client.get(USERINFO_URL)
            response.raise_for_status()
            info = response.json()
        subject = info.get("sub")
        if not isinstance(subject, str) or not subject:
            raise ValueError("userinfo has no subject")
        email = info.get("email")
        return Profile(subject=subject, email=email if isinstance(email, str) else None)
