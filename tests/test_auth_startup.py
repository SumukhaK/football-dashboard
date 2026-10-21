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

from app.config import REPO_ROOT, Config
from app.domain.listen import ListenAddress
from app.main import create_app

NOW = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
LOOPBACK = ListenAddress("127.0.0.1", 8000)


def _loopback_client(app: Any) -> TestClient:
    """A client whose connection facts are what the demo launcher serves."""
    return TestClient(
        app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 51000)
    )


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
    app = create_app(settings, clock=_clock, listen=LOOPBACK)

    with _loopback_client(app) as client:
        assert client.get("/healthz").status_code == 200


def test_building_the_app_never_needs_the_google_settings() -> None:
    """Only serving does, so tests and tooling can build the app offline."""
    assert create_app(Config(), clock=_clock) is not None


def _config_from_example(**overrides: Any) -> Config:
    """Load the committed example the way the README says to load a .env file.

    pydantic-settings accepts ``_env_file`` at runtime, but the Pydantic mypy
    plugin only models field keywords, so the one argument it cannot see is
    ignored rather than every call site being rewritten.
    """
    return Config(_env_file=REPO_ROOT / ".env.example", **overrides)  # type: ignore[call-arg]


def test_the_committed_example_file_runs_the_fixture_demonstration() -> None:
    """Copying the published example and choosing fixture must start.

    The documented workflow is to load .env.example explicitly; every line in
    it is then a provided value, so an empty assignment is not "unset".
    """
    settings = _config_from_example(auth_mode="fixture")

    assert settings.source == "fixture"
    assert settings.invites_enabled is False
    app = create_app(settings, clock=_clock, listen=LOOPBACK)
    with _loopback_client(app) as client:
        assert client.get("/healthz").status_code == 200


def test_the_committed_example_file_is_not_a_working_google_profile() -> None:
    """The example carries no credentials, so the default mode still fails."""
    settings = _config_from_example()

    assert settings.auth_mode == "google"
    with (
        pytest.raises(ValueError, match="GOOGLE_CLIENT_ID"),
        TestClient(create_app(settings, clock=_clock)),
    ):
        pass
