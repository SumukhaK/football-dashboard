"""Clients, fakes and builders shared by the requests route tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.config import Config
from app.contract import load_contract
from app.dependencies import get_requests
from app.domain.errors import SourceUnavailableError
from app.domain.models import (
    ALL_CAPABILITIES,
    MAX_QUERY_LIMIT,
    ErrorGroup,
    EventQuery,
    PlatformEvent,
    SourceCapabilities,
    TelemetryEvent,
    TimeWindow,
    Trace,
)
from app.main import create_app
from app.services.requests import RequestsService
from app.services.windows import window_for_hours
from app.sources.filtering import select_events
from app.sources.fixture_source import FixtureSource

CLOCK_TIME = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)
RETRY_TRACE = "923a736994e3bf911a61dbe22e44158b"


def make_client() -> TestClient:
    """A test client over the fixture source with a fixed clock."""
    return TestClient(create_app(Config(), clock=lambda: CLOCK_TIME))


def chat_request_id() -> str:
    """The fixture request whose trace carries the two retries."""
    source = FixtureSource(Config().fixture_dir, load_contract(), now=CLOCK_TIME)
    window = window_for_hours(24, CLOCK_TIME)
    for event in source.events(
        EventQuery(window=window, events=("http.request",), limit=MAX_QUERY_LIMIT)
    ):
        if event.trace_id == RETRY_TRACE and event.request_id:
            return event.request_id
    raise AssertionError("the fixture chat request was not found")


def make_line(
    minutes_ago: int,
    event: str,
    request_id: str | None,
    attributes: dict[str, object],
) -> TelemetryEvent:
    """One catalogued line, minutes_ago before the fixed clock."""
    return TelemetryEvent(
        timestamp=CLOCK_TIME - timedelta(minutes=minutes_ago),
        severity="INFO",
        event=event,
        message=event,
        request_id=request_id,
        trace_id=None,
        span_id=None,
        revision=None,
        attributes=attributes,
    )


class ListSource:
    """An in-memory source over a fixed list of events."""

    def __init__(self, events: list[TelemetryEvent]) -> None:
        self._events = events

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Return the stored events that match the query, newest first."""
        return select_events(self._events, query)

    def trace(self, trace_id: str) -> Trace | None:
        """There are no traces here."""
        return None

    def error_groups(self, window: TimeWindow) -> list[ErrorGroup]:
        """There are no error groups here."""
        return []

    def platform_events(self, window: TimeWindow) -> list[PlatformEvent]:
        """There are no platform events here."""
        return []

    def capabilities(self) -> SourceCapabilities:
        """Say every query can be answered; the fake is not a local log file."""
        return ALL_CAPABILITIES


def make_list_client(events: list[TelemetryEvent]) -> TestClient:
    """A test client whose requests service reads a fixed list of events."""
    app = create_app(Config(), clock=lambda: CLOCK_TIME)
    service = RequestsService(ListSource(events), lambda: CLOCK_TIME, Config())
    app.dependency_overrides[get_requests] = lambda: service
    return TestClient(app)


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


class BrokenTraceSource(FixtureSource):
    """The fixture source with a failing trace read."""

    def trace(self, trace_id: str) -> Trace | None:
        """Always fails."""
        raise SourceUnavailableError("unavailable", "trace is down")
