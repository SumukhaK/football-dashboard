"""Tests for the overview routes."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.config import Config
from app.contract import load_contract
from app.dependencies import get_overview
from app.domain.errors import SourceUnavailableError
from app.domain.models import (
    ErrorGroup,
    EventQuery,
    PlatformEvent,
    TelemetryEvent,
    TimeWindow,
    Trace,
)
from app.main import create_app
from app.services.overview import OverviewService

CLOCK_TIME = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)
COMPONENTS = tuple(load_contract().components)


def _client() -> TestClient:
    """A test client over the fixture source with a fixed clock."""
    return TestClient(create_app(Config(), clock=lambda: CLOCK_TIME))


def test_overview_page_lists_components_and_state_words() -> None:
    """GET / is the home page and names every component and tile state."""
    response = _client().get("/")
    assert response.status_code == 200
    body = response.text
    for name in COMPONENTS:
        assert name in body
    assert "failed" in body
    assert "degraded" in body


def test_partial_returns_body_only() -> None:
    """The HTMX partial renders the body, not a whole document."""
    response = _client().get("/partials/overview?hours=1")
    assert response.status_code == 200
    assert "<!DOCTYPE html>" not in response.text
    assert 'id="overview-body"' in response.text


def test_unsupported_hours_returns_structured_422() -> None:
    """A window the picker does not offer is a 422 with error and detail."""
    response = _client().get("/partials/overview?hours=5")
    assert response.status_code == 422
    data = response.json()
    assert "error" in data
    assert "detail" in data


def test_non_integer_hours_returns_structured_422() -> None:
    """A non-numeric window is a 422 with error and detail."""
    response = _client().get("/partials/overview?hours=abc")
    assert response.status_code == 422
    data = response.json()
    assert "error" in data
    assert "detail" in data


class BrokenSource:
    """A telemetry source whose reads always fail."""

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Always fails."""
        raise SourceUnavailableError("unavailable", "google is down")

    def trace(self, trace_id: str) -> Trace | None:
        """Always fails."""
        raise SourceUnavailableError("unavailable", "google is down")

    def error_groups(self, window: TimeWindow) -> list[ErrorGroup]:
        """Always fails."""
        raise SourceUnavailableError("unavailable", "google is down")

    def platform_events(self, window: TimeWindow) -> list[PlatformEvent]:
        """Always fails."""
        raise SourceUnavailableError("unavailable", "google is down")


def test_source_error_renders_a_banner_with_status_200() -> None:
    """A failing source shows a banner and 200, never a 500."""
    app = create_app(Config(), clock=lambda: CLOCK_TIME)
    broken = OverviewService(BrokenSource(), lambda: CLOCK_TIME, Config(), COMPONENTS)
    app.dependency_overrides[get_overview] = lambda: broken

    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert "google is down" in response.text
