"""Builders and fakes shared by the requests service tests."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from app.config import Config
from app.contract import load_contract
from app.domain.models import (
    ErrorGroup,
    EventQuery,
    PlatformEvent,
    TelemetryEvent,
    TimeWindow,
    Trace,
)
from app.domain.requests import RequestFilters
from app.services.requests import RequestsService
from app.services.windows import window_for_hours
from app.sources.base import TelemetrySource
from app.sources.filtering import select_events
from app.sources.fixture_source import FixtureSource

NOW = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)
WINDOW = window_for_hours(24, NOW)
RETRY_TRACE = "923a736994e3bf911a61dbe22e44158b"


def request_line(
    minutes_ago: int,
    status_code: int = 200,
    route: str = "/v2/predict",
    request_id: str | None = "req-00000001",
    trace_id: str | None = None,
) -> TelemetryEvent:
    """An http.request line, minutes_ago before NOW."""
    return TelemetryEvent(
        timestamp=NOW - timedelta(minutes=minutes_ago),
        severity="INFO",
        event="http.request",
        message="request finished",
        request_id=request_id,
        trace_id=trace_id,
        span_id=None,
        revision="rev-0001",
        attributes={
            "method": "GET",
            "route": route,
            "status": status_code,
            "duration_ms": 12,
            "error_code": None,
        },
    )


def event_line(
    minutes_ago: int,
    name: str,
    request_id: str | None,
    attributes: dict[str, Any] | None = None,
) -> TelemetryEvent:
    """Another catalogued line of a request."""
    return TelemetryEvent(
        timestamp=NOW - timedelta(minutes=minutes_ago),
        severity="WARNING",
        event=name,
        message=name,
        request_id=request_id,
        trace_id=None,
        span_id=None,
        revision=None,
        attributes=attributes or {},
    )


class FakeSource:
    """An in-test source over a fixed event and trace list."""

    def __init__(
        self,
        events: Sequence[TelemetryEvent],
        traces: Sequence[Trace] = (),
    ) -> None:
        self._events = list(events)
        self._traces = {trace.trace_id: trace for trace in traces}

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Return the stored events that match the query, newest first."""
        return select_events(self._events, query)

    def trace(self, trace_id: str) -> Trace | None:
        """Return one of the stored traces, or None."""
        return self._traces.get(trace_id)

    def error_groups(self, window: TimeWindow) -> list[ErrorGroup]:
        """There are no error groups in the fake."""
        return []

    def platform_events(self, window: TimeWindow) -> list[PlatformEvent]:
        """There are no platform events in the fake."""
        return []


class FloodSource:
    """A source that always returns a full page, to exercise the query cap."""

    def __init__(self, event: TelemetryEvent) -> None:
        self._event = event

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Return exactly the query's limit."""
        return [self._event] * query.limit

    def trace(self, trace_id: str) -> Trace | None:
        """There are no traces in the fake."""
        return None

    def error_groups(self, window: TimeWindow) -> list[ErrorGroup]:
        """There are no error groups in the fake."""
        return []

    def platform_events(self, window: TimeWindow) -> list[PlatformEvent]:
        """There are no platform events in the fake."""
        return []


class SpySource(FakeSource):
    """A fake source that remembers every query it is asked."""

    def __init__(self, events: Sequence[TelemetryEvent] = ()) -> None:
        super().__init__(events)
        self.queries: list[EventQuery] = []

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Record the query, then answer it like the fake does."""
        self.queries.append(query)
        return super().events(query)


def make_service(
    source: TelemetrySource, settings: Config | None = None
) -> RequestsService:
    """A requests service over the given source with a fixed clock."""
    return RequestsService(source, lambda: NOW, settings or Config())


def make_filters(**overrides: Any) -> RequestFilters:
    """The default filters, with any field overridden."""
    return RequestFilters(window=WINDOW, hours=24, **overrides)


def fixture_service() -> tuple[RequestsService, FixtureSource]:
    """A requests service over the committed fixtures with a fixed clock."""
    source = FixtureSource(Config().fixture_dir, load_contract(), now=NOW)
    return make_service(source), source
