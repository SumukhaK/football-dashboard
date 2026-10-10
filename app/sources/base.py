"""The read-only interface every telemetry source implements."""

from __future__ import annotations

from typing import Protocol

from app.domain.models import (
    ErrorGroup,
    EventQuery,
    PlatformEvent,
    TelemetryEvent,
    TimeWindow,
    Trace,
)


class TelemetrySource(Protocol):
    """Read-only access to the backend's telemetry."""

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Return events matching the query, newest first."""
        ...

    def trace(self, trace_id: str) -> Trace | None:
        """Return one trace, or None when it does not exist."""
        ...

    def error_groups(self, window: TimeWindow) -> list[ErrorGroup]:
        """Return error groups that overlap the window."""
        ...

    def platform_events(self, window: TimeWindow) -> list[PlatformEvent]:
        """Return platform events inside the window, newest first."""
        ...
