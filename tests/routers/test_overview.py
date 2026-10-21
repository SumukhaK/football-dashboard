"""Tests for the overview routes."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.config import Config
from app.contract import load_contract
from app.dependencies import get_overview
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
from app.services.overview import OverviewService
from app.sources.filtering import select_events
from tests.auth.console import console, console_client

CLOCK_TIME = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)
COMPONENTS = tuple(load_contract().components)


def _client() -> TestClient:
    """A signed-in test client over the fixture source with a fixed clock."""
    return console_client(clock=lambda: CLOCK_TIME)


def test_overview_page_shows_what_needs_attention() -> None:
    """GET / names the components that need attention, with pills and links."""
    body = _client().get("/").text
    assert "Needs attention" in body
    assert "Assistant" in body
    assert "Data freshness" in body
    assert "Degraded" in body
    assert "Failed" in body
    assert "component=assistant" in body
    assert 'href="/data"' in body
    assert "9 healthy" in body


def test_short_window_still_shows_what_needs_attention() -> None:
    """A one-hour window still grades tiles from the lookback, not all grey."""
    body = _client().get("/partials/overview?hours=1").text
    assert "Data freshness" in body
    assert "Failed" in body
    assert "10 healthy" in body


def test_headline_cards_name_the_comparison() -> None:
    """The four large cards name the window they compare against."""
    body = _client().get("/").text
    for label in ("Requests", "Error rate", "p95 latency", "Server crashes"):
        assert label in body
    assert "no earlier data" in body


def test_a_window_with_an_earlier_one_names_the_comparison() -> None:
    """A short window compares against the window of the same length before it."""
    body = _client().get("/partials/overview?hours=1").text
    assert "vs previous 1h" in body


def test_the_three_headline_sparklines_are_rendered() -> None:
    """Requests, error rate and p95 latency each get a sparkline element."""
    body = _client().get("/").text
    for element in ("spark-requests", "spark-error_rate", "spark-p95_latency"):
        assert f'id="{element}"' in body


def test_the_overview_links_its_own_stylesheet() -> None:
    """The overview-specific rules load on the overview page."""
    assert 'href="/static/css/overview.css"' in _client().get("/").text


def test_times_render_as_ist_text_and_numbers_link_out() -> None:
    """Times are human-readable and headline numbers link to the request list."""
    body = _client().get("/").text
    assert "Updated 23:30 IST" in body
    assert "+00:00" not in body
    assert "/requests?" in body
    assert "status=5xx" in body


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

    def capabilities(self) -> SourceCapabilities:
        """Reads fail, but the source still says what it can answer."""
        return ALL_CAPABILITIES


def test_source_error_renders_a_banner_with_status_200() -> None:
    """A failing source shows a banner and 200, never a 500."""
    signed = console(clock=lambda: CLOCK_TIME)
    broken = OverviewService(BrokenSource(), lambda: CLOCK_TIME, Config(), COMPONENTS)
    signed.app.dependency_overrides[get_overview] = lambda: broken

    response = signed.client.get("/")
    assert response.status_code == 200
    assert "google is down" in response.text


class FixedSource:
    """A telemetry source backed by a fixed event list, filtered like the real one."""

    def __init__(self, events: list[TelemetryEvent]) -> None:
        self._events = list(events)

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Return the stored events matching the query, newest first."""
        return select_events(self._events, query)

    def trace(self, trace_id: str) -> Trace | None:
        """There are no traces in the fake."""
        return None

    def error_groups(self, window: TimeWindow) -> list[ErrorGroup]:
        """There are no error groups in the fake."""
        return []

    def platform_events(self, window: TimeWindow) -> list[PlatformEvent]:
        """There are no platform events in the fake."""
        return []

    def capabilities(self) -> SourceCapabilities:
        """Say every query can be answered; the fake is not a local log file."""
        return ALL_CAPABILITIES


def _event(event: str, attributes: dict[str, object]) -> TelemetryEvent:
    """Build a telemetry event of the given type with its attributes."""
    return TelemetryEvent(
        timestamp=CLOCK_TIME - timedelta(minutes=5),
        severity="INFO",
        event=event,
        message=event,
        request_id=None,
        trace_id=None,
        span_id=None,
        revision=None,
        attributes=attributes,
    )


def _request(status: int, duration_ms: float) -> TelemetryEvent:
    """Build an http.request event on the fixture route."""
    return _event(
        "http.request",
        {
            "method": "GET",
            "route": "/v2/predict",
            "status": status,
            "duration_ms": duration_ms,
            "error_code": None,
        },
    )


def _page_with(events: list[TelemetryEvent]) -> str:
    """Render the overview over a fixed source."""
    signed = console(clock=lambda: CLOCK_TIME)
    service = OverviewService(
        FixedSource(events), lambda: CLOCK_TIME, Config(), COMPONENTS
    )
    signed.app.dependency_overrides[get_overview] = lambda: service
    return str(signed.client.get("/").text)


def test_all_healthy_components_say_so_in_one_line() -> None:
    """With nothing wrong, the attention card says every component is healthy."""
    events = [
        _event("component.load", {"component": name, "status": "ok"})
        for name in COMPONENTS
    ]
    events.append(_event("refresh.run", {"status": "ok", "error": None}))
    events.append(
        _event("data.freshness", {"competition": "premier_league", "age_hours": 1.0})
    )

    body = _page_with(events)
    assert "All 11 components healthy" in body


def test_slowest_routes_show_a_duration_and_a_fail_pill() -> None:
    """A 2.5 s route at exactly 1% failures wears the fail pill."""
    events = [_request(500, 2500.0)]
    events += [_request(200, 2500.0) for _ in range(99)]

    body = _page_with(events)
    assert "2.5 s" in body
    assert re.search(r'pill-fail">1\.0%</span>', body) is not None
