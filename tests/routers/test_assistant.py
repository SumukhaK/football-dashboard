"""Tests for the assistant routes."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.config import Config
from app.dependencies import get_assistant
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
from app.services.assistant import AssistantService

CLOCK_TIME = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)

HEADINGS = (
    "How questions were answered",
    "Model calls",
    "Tools",
    "Slowest answers",
    "Fallbacks",
    "Tokens",
)

GAVE_UP = "5051c1ccd17f9acae01f5057ca02135e"


def _client() -> TestClient:
    """A test client over the fixture source with a fixed clock."""
    return TestClient(create_app(Config(), clock=lambda: CLOCK_TIME))


def test_assistant_page_shows_every_section() -> None:
    """GET /assistant renders one heading per section of the page."""
    response = _client().get("/assistant")

    assert response.status_code == 200
    for heading in HEADINGS:
        assert f">{heading}<" in response.text


def test_assistant_page_links_the_gave_up_request() -> None:
    """The fixture's one gave-up request links to its detail page."""
    body = _client().get("/assistant").text

    assert f'href="/requests/{GAVE_UP}"' in body
    assert "Ollama" in body or "ollama_chat" in body


def test_an_empty_window_says_no_data_without_a_stray_percent() -> None:
    """A window with nothing in it reports "no data", never "no data%"."""
    body = _client().get("/assistant?hours=1").text

    assert "0 answers" in body
    assert "no data%" not in body
    assert ">No answers in this window.<" in body
    assert ">No tool calls in this window.<" in body


def test_assistant_page_says_when_cost_is_not_reported() -> None:
    """Ollama reports tokens but no cost, and the page never invents one."""
    body = _client().get("/assistant").text

    assert "10933" in body
    assert "Not reported by the current model provider" in body
    assert "0.0000" not in body


def test_assistant_page_offers_the_window_picker() -> None:
    """The picker swaps the assistant body and pushes a shareable URL."""
    body = _client().get("/assistant").text

    assert 'aria-label="Time window"' in body
    assert 'hx-target="#assistant-body"' in body
    assert 'hx-push-url="/assistant?hours=' in body
    assert 'href="/assistant"' in body


def test_partial_returns_body_only() -> None:
    """The HTMX partial renders the assistant body, not a whole document."""
    response = _client().get("/partials/assistant?hours=1")

    assert response.status_code == 200
    assert "<!DOCTYPE html>" not in response.text
    assert 'id="assistant-body"' in response.text
    assert ">Model calls<" in response.text


def test_unsupported_hours_returns_structured_422() -> None:
    """A window the picker does not offer is a 422 with error and detail."""
    response = _client().get("/partials/assistant?hours=5")

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


def test_source_error_renders_a_banner_with_status_200() -> None:
    """A failing source shows a banner and 200, never a 500."""
    app = create_app(Config(), clock=lambda: CLOCK_TIME)
    broken = AssistantService(BrokenSource(), lambda: CLOCK_TIME, Config())
    app.dependency_overrides[get_assistant] = lambda: broken

    response = TestClient(app).get("/assistant")

    assert response.status_code == 200
    assert "google is down" in response.text
