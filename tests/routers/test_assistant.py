"""Tests for the assistant routes."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient

from app.config import Config
from app.dependencies import get_assistant
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
from app.services.assistant import AssistantService
from tests.auth.console import console, console_client
from tests.services.assistant_helpers import (
    ListSource,
    answer_line,
    call_line,
    retry_line,
)

CLOCK_TIME = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)

# The window ends at the clock time and excludes it, so events a minute earlier
# are the newest ones a page load sees.
EVENT_TIME = CLOCK_TIME - timedelta(minutes=1)

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
    """A signed-in test client over the fixture source with a fixed clock."""
    return console_client(clock=lambda: CLOCK_TIME)


def _client_over(events: Sequence[TelemetryEvent]) -> TestClient:
    """A client whose assistant service reads exactly the given events."""
    signed = console(
        Config(inr_per_usd=80, inr_per_usd_as_of=date(2026, 10, 20)),
        clock=lambda: CLOCK_TIME,
    )
    service = AssistantService(ListSource(events), lambda: CLOCK_TIME, signed.settings)
    signed.app.dependency_overrides[get_assistant] = lambda: service
    return signed.client


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


def test_reported_cost_shows_the_total_and_the_per_answer_value() -> None:
    """A provider that reports a cost puts the converted INR total and average up."""
    body = (
        _client_over(
            [
                answer_line(EVENT_TIME, cost_usd=0.1),
                answer_line(EVENT_TIME, cost_usd=0.15),
            ]
        )
        .get("/assistant")
        .text
    )

    assert "Cost (INR, estimate)" in body
    assert '<span class="stat-value">INR 20.00</span>' in body
    assert "INR 10.00 per answer" in body
    assert "Not reported by the current model provider" not in body


def test_a_reported_zero_cost_is_shown_as_a_zero() -> None:
    """A provider that reports a zero is shown as a zero, not as no data."""
    body = _client_over([answer_line(EVENT_TIME, cost_usd=0.0)]).get("/assistant").text

    assert "Cost (INR, estimate)" in body
    assert '<span class="stat-value">INR 0.00</span>' in body
    assert "Not reported by the current model provider" not in body


def test_an_unreported_cost_keeps_the_quiet_note() -> None:
    """A null cost renders the note, and the page never invents a zero."""
    body = _client_over([answer_line(EVENT_TIME, cost_usd=None)]).get("/assistant").text

    assert "Not reported by the current model provider" in body
    assert "Cost (INR, estimate)" not in body
    assert '<span class="stat-value">INR 0.00</span>' not in body


def test_an_empty_window_says_model_calls_were_not_measured() -> None:
    """No dependency calls is missing data, not proof every call answered."""
    body = _client_over([]).get("/assistant").text

    assert "no model calls measured" in body
    assert "every dependency answered" not in body


def test_a_retry_only_window_is_missing_data_too() -> None:
    """Retries with no call lines are no evidence that a dependency answered."""
    body = _client_over([retry_line(EVENT_TIME)]).get("/assistant").text

    assert "no model calls measured" in body
    assert ">No calls measured<" in body
    assert ">No failures<" not in body


def test_a_healthy_window_names_the_dependency_that_answered() -> None:
    """Measured calls with no failures keep the healthy words and the name."""
    body = (
        _client_over(
            [call_line(EVENT_TIME, attempt=1), call_line(EVENT_TIME, attempt=2)]
        )
        .get("/assistant")
        .text
    )

    assert "Ollama chat answered every call" in body
    assert ">No failures<" in body
    assert "no model calls measured" not in body


def test_a_failing_window_shows_the_rate_and_names_the_dependency() -> None:
    """A measured failure shows its rate, names the dependency and is not no data."""
    body = (
        _client_over([call_line(EVENT_TIME, status="timeout")]).get("/assistant").text
    )

    assert "100.0%" in body
    assert "Ollama chat" in body
    assert "no model calls measured" not in body


def test_the_attempts_bar_labels_and_counts_every_status() -> None:
    """Each slice is named and counted, visibly and to a screen reader."""
    body = (
        _client_over(
            [
                call_line(EVENT_TIME, status="ok", attempt=1),
                call_line(EVENT_TIME, status="timeout", attempt=2),
                call_line(EVENT_TIME, status="http_error", attempt=3),
            ]
        )
        .get("/assistant")
        .text
    )

    assert 'role="img"' in body
    assert (
        'aria-label="Attempts by status: Succeeded 1, Timeout 1, HTTP error 1"' in body
    )
    for label in ("Succeeded", "Timeout", "HTTP error"):
        assert f'<span class="call-legend-label">{label}</span>' in body
    assert body.count('<span class="call-legend-count">1</span>') == 3


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

    def capabilities(self) -> SourceCapabilities:
        """Reads fail, but the source still says what it can answer."""
        return ALL_CAPABILITIES


def test_source_error_renders_a_banner_with_status_200() -> None:
    """A failing source shows a banner and 200, never a 500."""
    signed = console(clock=lambda: CLOCK_TIME)
    broken = AssistantService(BrokenSource(), lambda: CLOCK_TIME, Config())
    signed.app.dependency_overrides[get_assistant] = lambda: broken

    response = signed.client.get("/assistant")

    assert response.status_code == 200
    assert "google is down" in response.text
