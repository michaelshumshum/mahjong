"""Accounts settings, read from env once per lifespan (docs/infra.md §2). No hostname lives in
code: the cookie's `Secure` flag and every URL derive from `PUBLIC_API_URL`/`PUBLIC_WEB_URL`."""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Mapping
from dataclasses import dataclass

_DEFAULT_API_URL = "http://localhost:8000"
_DEFAULT_SESSION_MAX_AGE_DAYS = 90
_DEFAULT_SESSION_IDLE_DAYS = 30


def _flag(raw: str | None) -> bool:
    return (raw or "").strip().lower() in {"1", "true", "yes", "on"}


def cors_origins(env: Mapping[str, str]) -> list[str]:
    """`CORS_ORIGINS`, comma-separated. `*` is dropped: with credentialed CORS it would let any
    site read a signed-in user's `/me`."""
    origins = [o.strip() for o in env.get("CORS_ORIGINS", "").split(",")]
    return [o for o in origins if o and o != "*"]


@dataclass(frozen=True, slots=True)
class AccountsConfig:
    enabled: bool
    api_url: str
    web_url: str
    session_max_age: dt.timedelta
    session_idle: dt.timedelta
    google_client_id: str | None = None
    google_client_secret: str | None = None
    # CORS_ORIGINS, also the origins a /ws upgrade may carry the session cookie from
    origins: tuple[str, ...] = ()

    @property
    def cookie_secure(self) -> bool:
        # off only for plain-http local dev, where a Secure cookie would never be sent back
        return self.api_url.startswith("https://")

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> AccountsConfig:
        origins = cors_origins(env)

        def get(key: str, default: object) -> str:
            # compose passes an unset var through as "" (`${X:-}`), which means the default
            return env.get(key, "").strip() or str(default)

        return cls(
            enabled=_flag(env.get("ACCOUNTS_ENABLED")),
            api_url=get("PUBLIC_API_URL", _DEFAULT_API_URL).rstrip("/"),
            web_url=get("PUBLIC_WEB_URL", origins[0] if origins else "").rstrip("/"),
            session_max_age=dt.timedelta(
                days=float(get("SESSION_MAX_AGE_DAYS", _DEFAULT_SESSION_MAX_AGE_DAYS))
            ),
            session_idle=dt.timedelta(
                days=float(get("SESSION_IDLE_DAYS", _DEFAULT_SESSION_IDLE_DAYS))
            ),
            google_client_id=get("GOOGLE_CLIENT_ID", "") or None,
            google_client_secret=get("GOOGLE_CLIENT_SECRET", "") or None,
            origins=tuple(origins),
        )
