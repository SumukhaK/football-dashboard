"""Fixed-clock sources and events for errors service tests."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from app.config import Config
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
from app.services.errors import (
    ErrorsService,
)
from app.services.windows import window_for_hours
from app.sources.base import TelemetrySource
from app.sources.filtering import (
    overlapping_groups,
    platform_in_window,
    select_events,
)

NOW = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)
WINDOW = window_for_hours(24, NOW)


def _error(
    minutes_ago: int,
    code: str,
    route: str,
    status_code: int,
    exception_type: str = "builtins.ValueError",
) -> TelemetryEvent:
    """One app.error line."""
    return TelemetryEvent(
        timestamp=NOW - timedelta(minutes=minutes_ago),
        severity="ERROR",
        event="app.error",
        message="handled",
        request_id="req-00000001",
        trace_id=None,
        span_id=None,
        revision=None,
        attributes={
            "route": route,
            "status": status_code,
            "error_code": code,
            "exception_type": exception_type,
        },
    )


def _crash(when: datetime, exception_type: str, route: str) -> TelemetryEvent:
    """One uncaught app.crash line at an exact moment."""
    return TelemetryEvent(
        timestamp=when,
        severity="ERROR",
        event="app.crash",
        message=f"{exception_type.rsplit('.', 1)[-1]}: boom",
        request_id="req-00000002",
        trace_id=None,
        span_id=None,
        revision=None,
        attributes={"route": route, "exception_type": exception_type},
    )


def _degraded(minutes_ago: int, component: str, route: str) -> TelemetryEvent:
    """One component.degraded line."""
    return TelemetryEvent(
        timestamp=NOW - timedelta(minutes=minutes_ago),
        severity="WARNING",
        event="component.degraded",
        message="not loaded",
        request_id="req-00000001",
        trace_id=None,
        span_id=None,
        revision=None,
        attributes={"component": component, "route": route},
    )


def _group(
    group_id: str,
    exception_type: str,
    message: str,
    count: int,
    first_minutes_ago: int,
    last_minutes_ago: int,
) -> ErrorGroup:
    """One error group from Error Reporting."""
    return ErrorGroup(
        group_id=group_id,
        exception_type=exception_type,
        message=message,
        count=count,
        first_seen=NOW - timedelta(minutes=first_minutes_ago),
        last_seen=NOW - timedelta(minutes=last_minutes_ago),
        affected_routes=("/v2/predict",),
    )


def _platform(minutes_ago: int, kind: str) -> PlatformEvent:
    """One Cloud Run platform event."""
    return PlatformEvent(
        timestamp=NOW - timedelta(minutes=minutes_ago),
        kind=kind,
        revision="football-api-00042-wum",
        message=f"{kind} happened",
    )


class FakeSource:
    """An in-test source over fixed events, groups and platform events."""

    def __init__(
        self,
        events: Sequence[TelemetryEvent] = (),
        groups: Sequence[ErrorGroup] = (),
        platform: Sequence[PlatformEvent] = (),
    ) -> None:
        self._events = list(events)
        self._groups = list(groups)
        self._platform = list(platform)

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Return the stored events that match the query, newest first."""
        return select_events(self._events, query)

    def trace(self, trace_id: str) -> Trace | None:
        """There are no traces in the fake."""
        return None

    def error_groups(self, window: TimeWindow) -> list[ErrorGroup]:
        """Return the stored groups that overlap the window."""
        return overlapping_groups(self._groups, window)

    def platform_events(self, window: TimeWindow) -> list[PlatformEvent]:
        """Return the stored platform events inside the window."""
        return platform_in_window(self._platform, window)

    def capabilities(self) -> SourceCapabilities:
        """Say every query can be answered; the fake is not a local log file."""
        return ALL_CAPABILITIES


def _service(source: TelemetrySource) -> ErrorsService:
    """An errors service over the given source with a fixed clock."""
    return ErrorsService(source, lambda: NOW, Config())
