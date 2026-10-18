"""Tests for the errors routes."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Config
from app.dependencies import get_errors
from app.domain.errors import SourceUnavailableError
from app.domain.models import (
    ALL_CAPABILITIES,
    ErrorGroup,
    EventQuery,
    PlatformEvent,
    SourceCapabilities,
    TelemetryEvent,
    TimeWindow,
    Trace,
)
from app.main import create_app
from app.services.errors import ErrorsService
from app.services.source_status import LOCAL_CRASH_NOTE, LOCAL_ONLY_NOTE

from .pages_helpers import fixture_line, make_local_client, make_local_log

CLOCK_TIME = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)

GROUP_TYPES = (
    "backend.app.exceptions.AssistantNotAvailableError",
    "builtins.KeyError",
    "builtins.ValueError",
    "builtins.ZeroDivisionError",
)


def _client() -> TestClient:
    """A test client over the fixture source with a fixed clock."""
    return TestClient(create_app(Config(), clock=lambda: CLOCK_TIME))


def test_errors_page_lists_the_groups_and_the_platform_event() -> None:
    """GET /errors names the fixture crash groups and the out-of-memory."""
    response = _client().get("/errors")
    assert response.status_code == 200
    body = response.text
    for exception_type in GROUP_TYPES:
        assert exception_type in body
    assert "out_of_memory" in body
    assert "Memory limit of 2 GiB exceeded" in body


def test_errors_page_offers_the_window_picker() -> None:
    """The picker swaps the errors body and pushes a shareable URL."""
    body = _client().get("/errors").text
    assert 'aria-label="Time window"' in body
    assert 'hx-target="#errors-body"' in body
    assert 'hx-push-url="/errors?hours=' in body


def test_partial_returns_body_only() -> None:
    """The HTMX partial renders the errors body, not a whole document."""
    response = _client().get("/partials/errors?hours=24")
    assert response.status_code == 200
    assert "<!DOCTYPE html>" not in response.text
    assert 'id="errors-body"' in response.text
    assert "Handled errors" in response.text


def test_unsupported_hours_returns_structured_422() -> None:
    """A window the picker does not offer is a 422 with error and detail."""
    response = _client().get("/partials/errors?hours=5")
    assert response.status_code == 422
    assert "error" in response.json()


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

    def capabilities(self) -> SourceCapabilities:
        """Reads fail, but the source still says what it can answer."""
        return ALL_CAPABILITIES


def test_source_error_renders_a_banner_with_status_200() -> None:
    """A failing source shows a banner and 200, never a 500."""
    app = create_app(Config(), clock=lambda: CLOCK_TIME)
    broken = ErrorsService(BrokenSource(), lambda: CLOCK_TIME, Config())
    app.dependency_overrides[get_errors] = lambda: broken

    response = TestClient(app).get("/errors")
    assert response.status_code == 200
    assert "google is down" in response.text


def test_a_local_log_file_shows_the_groups_it_grouped_itself(tmp_path: Path) -> None:
    """The crash groups come from the file's app.crash lines, and it says so."""
    path, _ = make_local_log(tmp_path)
    body = make_local_client(path).get("/errors").text
    exception_type = fixture_line("app.crash")["attributes"]["exception_type"]
    assert exception_type in body
    assert LOCAL_CRASH_NOTE in body


def test_a_local_log_file_marks_the_platform_events_not_available(
    tmp_path: Path,
) -> None:
    """A local file holds no Cloud Run platform log, so the section says so."""
    path, _ = make_local_log(tmp_path)
    body = make_local_client(path).get("/errors").text
    assert "Platform events" in body
    assert body.count(LOCAL_ONLY_NOTE) == 1
    assert "No platform events in this window" not in body
