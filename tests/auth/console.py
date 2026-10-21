"""A signed-in console for the route tests.

The real guard is installed. These tests exercise owner pages with a real
signed session cookie, on a fully configured app and a frozen clock, rather
than switching authorization off.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.auth.sessions import SessionCookie, session_cookie_name
from app.config import Config
from app.domain.auth import ConsoleSession, VerifiedIdentity
from app.factory import create_app
from app.services.auth import AuthPolicy
from tests.auth.support import (
    AUTH_OAUTH_KEY,
    AUTH_SESSION_KEY,
    CALLBACK,
    CLIENT_ID,
    NOW,
)

Clock = Callable[[], datetime]
SESSION_ID = "test-console-session"

_AUTH_FIELDS = {
    "google_client_id": CLIENT_ID,
    "google_client_secret": SecretStr("GOCSPX-not-a-real-secret"),
    "auth_public_origin": "https://console.example",
    "auth_callback_url": CALLBACK,
    "session_signing_key": SecretStr(AUTH_SESSION_KEY),
    "oauth_signing_key": SecretStr(AUTH_OAUTH_KEY),
}


@dataclass(frozen=True)
class Console:
    """An app whose client carries a valid owner session."""

    app: FastAPI
    client: TestClient
    settings: Config
    session: ConsoleSession


def auth_settings(settings: Config | None = None) -> Config:
    """The caller's settings with a complete, non-secret test sign-in config."""
    base = settings or Config()
    return base.model_copy(update=_AUTH_FIELDS)


def session_for(
    settings: Config,
    clock: Clock,
    *,
    email: str | None = None,
    subject: str = "google-owner-subject",
    session_id: str = SESSION_ID,
) -> ConsoleSession:
    """A session the policy would issue, or a deliberately foreign one."""
    now = clock()
    policy = AuthPolicy.from_config(settings)
    if email is None:
        return policy.new_session(
            VerifiedIdentity(
                subject=subject,
                email=settings.owner_email,
                email_verified=True,
            ),
            session_id,
            clock,
        )
    return ConsoleSession(
        subject=subject,
        email=email,
        issued_at=now,
        expires_at=now + timedelta(seconds=settings.session_max_age_seconds),
        session_id=session_id,
    )


def console(
    settings: Config | None = None,
    *,
    clock: Clock = lambda: NOW,
    session: ConsoleSession | None = None,
) -> Console:
    """Build a configured app and a client carrying a signed owner session."""
    resolved = auth_settings(settings)
    app = create_app(resolved, clock=clock)
    client = TestClient(app, base_url="https://testserver")
    issued = session or session_for(resolved, clock)
    value = SessionCookie.from_config(resolved, clock).dumps(issued)
    client.cookies.set(session_cookie_name(resolved), value)
    return Console(app=app, client=client, settings=resolved, session=issued)


def console_client(
    settings: Config | None = None, *, clock: Clock = lambda: NOW
) -> TestClient:
    """The signed-in client alone, for tests that need no app handle."""
    return console(settings, clock=clock).client
