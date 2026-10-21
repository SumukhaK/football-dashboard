"""Tests for the startup check that says what the console reads.

The deployed console must log one line naming its project and Cloud Run service,
and it must not build a Google client (or reach the network) while it starts, so
a cold start stays fast.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import google.auth
import google.cloud.logging as cloud_logging
import pytest

from app.config import Config
from app.factory import create_app

NOW = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)


def _clock() -> datetime:
    """A clock frozen just after the sample fixture's newest event."""
    return NOW


def _refuse(*args: object, **kwargs: object) -> None:
    """Stand in for a Google constructor that must not run at startup."""
    raise AssertionError("a Google client was built while the app started")


def test_create_app_with_gcp_builds_no_google_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A gcp console starts without constructing a client or authenticating."""
    monkeypatch.setattr(cloud_logging, "Client", _refuse)
    monkeypatch.setattr(google.auth, "default", _refuse)

    app = create_app(Config(source="gcp", gcp_project_id="fake-project"), clock=_clock)

    assert app.state.source is not None


def test_the_gcp_startup_line_names_the_project_and_service(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The one line an operator needs to confirm what the console reads."""
    with caplog.at_level(logging.INFO, logger="app"):
        create_app(
            Config(
                source="gcp",
                gcp_project_id="demo-project",
                api_service_name="football-api-staging",
            ),
            clock=_clock,
        )

    assert "demo-project" in caplog.text
    assert "football-api-staging" in caplog.text


def test_the_fixture_startup_line_names_the_sample_files(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A fixture console says which sample files it reads."""
    with caplog.at_level(logging.INFO, logger="app"):
        create_app(Config(), clock=_clock)

    assert "sample files" in caplog.text
