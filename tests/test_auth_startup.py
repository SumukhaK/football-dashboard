"""Tests for the startup check that refuses an unconfigured owner login.

A console must not serve real telemetry behind no gate. Building the app still
works without credentials (tests and tooling need that); the check runs when
the ASGI server starts, so a hosted revision exits instead of serving.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Config
from app.main import create_app

NOW = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)


def _clock() -> datetime:
    """A clock frozen for the life of one test."""
    return NOW


def google_settings(**overrides: Any) -> Config:
    """A console configured for Google sign-in, with placeholder credentials."""
    fields: dict[str, Any] = {
        "google_client_id": "114958444175-abcdefghijklmnop.apps.googleusercontent.com",
        "google_client_secret": "GOCSPX-not-a-real-secret",
        "auth_public_origin": "https://console.example",
        "auth_callback_url": "https://console.example/auth/callback",
        "session_signing_key": "session-8f14e45fceea167a0b1c2d3e4f5a6b7c8d9e0f1a",
        "oauth_signing_key": "oauth-3f6a1c37b90d2e5847a9c0b1d2e3f4a5b6c7d8e9",
    }
    fields.update(overrides)
    return Config(**fields)


def test_a_console_refuses_to_serve_without_its_owner_login() -> None:
    """The default configuration is Google sign-in, and it is not set up."""
    app = create_app(Config(), clock=_clock)

    with pytest.raises(ValueError, match="GOOGLE_CLIENT_ID"), TestClient(app):
        pass


def test_a_console_refuses_to_serve_with_partial_credentials() -> None:
    """One setting filled in is not configuration; the missing one is named."""
    app = create_app(
        Config(
            auth_mode="google",
            google_client_id="114958444175-abcdef.apps.googleusercontent.com",
        ),
        clock=_clock,
    )

    with pytest.raises(ValueError, match="GOOGLE_CLIENT_SECRET"), TestClient(app):
        pass


def test_a_configured_console_serves() -> None:
    """With every Google setting present, the console starts."""
    with TestClient(create_app(google_settings(), clock=_clock)) as client:
        assert client.get("/healthz").status_code == 200


def test_the_fixture_demonstration_mode_serves_without_google_settings() -> None:
    """The explicit loopback demonstration mode needs no provider."""
    settings = Config(auth_mode="fixture")

    with TestClient(create_app(settings, clock=_clock)) as client:
        assert client.get("/healthz").status_code == 200


def test_building_the_app_never_needs_the_google_settings() -> None:
    """Only serving does, so tests and tooling can build the app offline."""
    assert create_app(Config(), clock=_clock) is not None
