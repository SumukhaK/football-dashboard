"""The signed, one-hour console session cookie.

One signed-in session travels in one signed cookie: the Google subject, the
owner address, the absolute issue and expiry times, and a random identifier
that also serves as the logout CSRF token. Nothing else is serialised: no
provider token, name, picture or whole userinfo.

The payload is signed, not encrypted. Its key and salt are separate from the
five-minute login transaction's, so neither cookie can stand in for the other.
The absolute expiry in the payload is authoritative: reading a session never
extends it, however recently it was used.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from itsdangerous import BadData, URLSafeTimedSerializer

from app.config import Config
from app.domain.auth import (
    OAUTH_COOKIE,
    OAUTH_COOKIE_LOCAL,
    SESSION_COOKIE,
    SESSION_COOKIE_LOCAL,
    ConsoleSession,
)
from app.domain.clock import Clock
from app.services.auth import AuthFailure

SESSION_SALT = "dashboard-console-session"
_FIELDS = ("subject", "email", "issued_at", "expires_at", "session_id")


def local_auth(settings: Config) -> bool:
    """Whether sign-in runs on plain HTTP loopback, the explicit local mode.

    Configuration only allows ``http://`` for ``127.0.0.1``, so this cannot
    silently turn a hosted console into an insecure one.
    """
    return (settings.auth_public_origin or "").startswith("http://")


def session_cookie_name(settings: Config) -> str:
    """The session cookie name for this deployment."""
    return SESSION_COOKIE_LOCAL if local_auth(settings) else SESSION_COOKIE


def oauth_cookie_name(settings: Config) -> str:
    """The pending-transaction cookie name for this deployment."""
    return OAUTH_COOKIE_LOCAL if local_auth(settings) else OAUTH_COOKIE


def cookie_security(settings: Config) -> dict[str, Any]:
    """The flags every auth cookie carries: HttpOnly, Secure unless loopback."""
    return {
        "httponly": True,
        "secure": not local_auth(settings),
        "samesite": "lax",
        "path": "/",
    }


@dataclass(frozen=True, slots=True)
class SessionCookie:
    """Serialises one ``ConsoleSession`` and refuses anything else."""

    signing_key: str
    max_age_seconds: int
    clock: Clock

    @classmethod
    def from_config(cls, settings: Config, clock: Clock) -> SessionCookie:
        """The codec the console runs with, from its validated settings."""
        if settings.session_signing_key is None:
            raise ValueError("session_signing_key is required for console sessions")
        return cls(
            signing_key=settings.session_signing_key.get_secret_value(),
            max_age_seconds=settings.session_max_age_seconds,
            clock=clock,
        )

    @property
    def serializer(self) -> URLSafeTimedSerializer:
        """A serializer bound to this key and this purpose."""
        return URLSafeTimedSerializer(self.signing_key, salt=SESSION_SALT)

    def dumps(self, session: ConsoleSession) -> str:
        """Sign one session into the cookie value."""
        payload = {
            "subject": session.subject,
            "email": session.email,
            "issued_at": session.issued_at.isoformat(),
            "expires_at": session.expires_at.isoformat(),
            "session_id": session.session_id,
        }
        return str(self.serializer.dumps(payload))

    def loads(self, value: str) -> ConsoleSession:
        """Read a session back, or raise ``AuthFailure("session")``.

        The signature is checked first, then the shape, the configured lifetime
        maximum and the absolute window against the injected clock. A payload
        that is signed but wrong is still refused.
        """
        try:
            payload = self.serializer.loads(value)
        except BadData as exc:
            raise AuthFailure("session") from exc
        if not isinstance(payload, dict) or set(payload) != set(_FIELDS):
            raise AuthFailure("session")

        session = self._session(payload)
        lifetime = session.expires_at - session.issued_at
        if lifetime.total_seconds() > self.max_age_seconds:
            raise AuthFailure("session")
        if not session.is_valid_at(self.clock()):
            raise AuthFailure("session")
        return session

    @staticmethod
    def _session(payload: dict[str, object]) -> ConsoleSession:
        """Validate every field's presence, type and order."""
        strings = {name: payload[name] for name in ("subject", "email", "session_id")}
        if not all(isinstance(value, str) and value for value in strings.values()):
            raise AuthFailure("session")

        try:
            issued_at = datetime.fromisoformat(str(payload["issued_at"]))
            expires_at = datetime.fromisoformat(str(payload["expires_at"]))
        except ValueError as exc:
            raise AuthFailure("session") from exc
        if issued_at.tzinfo is None or expires_at.tzinfo is None:
            raise AuthFailure("session")
        if expires_at <= issued_at:
            raise AuthFailure("session")

        return ConsoleSession(
            subject=str(strings["subject"]),
            email=str(strings["email"]),
            issued_at=issued_at,
            expires_at=expires_at,
            session_id=str(strings["session_id"]),
        )
