"""Fakes and builders shared by the data and jobs service tests.

The fixture-scenario tests use :func:`fixture_service` (a fixed clock keeps the
fixture shift deterministic); the arithmetic tests use :class:`ListSource` with
events built here, so the hand-computed numbers stay readable.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from app.config import REPO_ROOT, Config
from app.contract import load_contract
from app.domain.models import (
    ErrorGroup,
    EventQuery,
    PlatformEvent,
    TelemetryEvent,
    TimeWindow,
    Trace,
)
from app.services.data_jobs import DataJobsService
from app.sources.base import TelemetrySource
from app.sources.filtering import select_events
from app.sources.fixture_source import FixtureSource

NOW = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)


class ListSource:
    """An in-test telemetry source backed by a fixed event list."""

    def __init__(self, events: Sequence[TelemetryEvent]) -> None:
        self._events = list(events)

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Return the stored events that match the query, newest first."""
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


class RecordingSource(ListSource):
    """A list source that also keeps the queries it was asked."""

    def __init__(self, events: Sequence[TelemetryEvent]) -> None:
        super().__init__(events)
        self.queries: list[EventQuery] = []

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Record the query, then answer it like the list source."""
        self.queries.append(query)
        return super().events(query)


class FullSource(ListSource):
    """A source that always returns a full page of one refresh event."""

    def __init__(self) -> None:
        super().__init__([refresh_line(NOW)])

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Return exactly the query's limit, so the service flags truncation."""
        return [self._events[0]] * query.limit


def make_service(source: TelemetrySource, now: datetime = NOW) -> DataJobsService:
    """A data and jobs service over the given source with a fixed clock."""
    return DataJobsService(source, lambda: now, Config())


def fixture_service() -> DataJobsService:
    """A data and jobs service over the committed fixtures, fixed clock."""
    source = FixtureSource(REPO_ROOT / "fixtures", load_contract(), now=NOW)
    return make_service(source)


def moment(minutes: int = 0, hours: int = 0) -> datetime:
    """A moment that many minutes (and hours) before the fixed clock."""
    return NOW - timedelta(minutes=minutes, hours=hours)


def line(
    at: datetime,
    event: str,
    severity: str = "INFO",
    revision: str | None = None,
    **attributes: object,
) -> TelemetryEvent:
    """One catalogued event with the given attributes."""
    return TelemetryEvent(
        timestamp=at,
        severity=severity,
        event=event,
        message=event,
        request_id=None,
        trace_id=None,
        span_id=None,
        revision=revision,
        attributes=dict(attributes),
    )


def refresh_line(
    at: datetime,
    status: str = "ok",
    duration_ms: float | None = 3600,
    dataset: str | None = "football_data.csv",
    error: str | None = None,
    revision: str | None = None,
) -> TelemetryEvent:
    """Build a refresh.run event."""
    return line(
        at,
        "refresh.run",
        status=status,
        duration_ms=duration_ms,
        dataset=dataset,
        error=error,
        revision=revision,
    )


def fallback_line(
    at: datetime,
    from_path: str = "fresh_match_data",
    to_path: str = "previous_match_data",
    cause: str = "refresh_failed",
    revision: str | None = None,
) -> TelemetryEvent:
    """Build a fallback event."""
    return line(
        at,
        "fallback",
        from_path=from_path,
        to_path=to_path,
        cause=cause,
        revision=revision,
    )


def fixture_fallback_line(at: datetime, revision: str | None = None) -> TelemetryEvent:
    """Build the fallback that keeps the previous fixtures inside a refresh."""
    return fallback_line(
        at,
        from_path="fresh_fixtures",
        to_path="previous_fixtures",
        cause="fixtures_refresh_failed",
        revision=revision,
    )


def load_line(
    at: datetime,
    component: str = "fixtures",
    status: str = "ok",
    duration_ms: float | None = 10,
    reason: str | None = None,
    revision: str | None = None,
) -> TelemetryEvent:
    """Build a component.load event."""
    return line(
        at,
        "component.load",
        component=component,
        status=status,
        duration_ms=duration_ms,
        reason=reason,
        revision=revision,
    )


def freshness_line(
    at: datetime,
    competition: str = "Premier League",
    matches_through: str | None = "2026-10-05",
    age_hours: float | None = 10.0,
) -> TelemetryEvent:
    """Build a data.freshness event."""
    return line(
        at,
        "data.freshness",
        competition=competition,
        matches_through=matches_through,
        age_hours=age_hours,
    )


def call_line(
    at: datetime,
    dependency: str = "football_data",
    operation: str = "download",
    status: str = "ok",
    http_status: int | None = 200,
    attempt: int = 1,
    duration_ms: float | None = 100,
) -> TelemetryEvent:
    """Build a dependency.call event."""
    return line(
        at,
        "dependency.call",
        dependency=dependency,
        operation=operation,
        status=status,
        http_status=http_status,
        attempt=attempt,
        duration_ms=duration_ms,
    )


def retry_line(
    at: datetime,
    dependency: str = "football_data",
    operation: str = "download",
    attempt: int = 1,
    max_attempts: int = 2,
    wait_ms: int = 5000,
    cause: str = "http_error",
) -> TelemetryEvent:
    """Build a retry event."""
    return line(
        at,
        "retry",
        dependency=dependency,
        operation=operation,
        attempt=attempt,
        max_attempts=max_attempts,
        wait_ms=wait_ms,
        cause=cause,
    )
