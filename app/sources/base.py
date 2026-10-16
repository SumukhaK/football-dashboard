"""The read-only interfaces every telemetry and crash source implements."""

from __future__ import annotations

from typing import Protocol

from app.domain.crashes import CrashEvent
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


class CrashSource(Protocol):
    """Read-only access to the app's Crashlytics events."""

    def crash_events(self, window: TimeWindow, limit: int) -> list[CrashEvent]:
        """Return up to limit events inside the window, newest first.

        Events may come without stack frames; issue_events carries those.
        """
        ...

    def issue_events(
        self, issue_id: str, window: TimeWindow, limit: int
    ) -> list[CrashEvent]:
        """Return up to limit events of one issue in the window, newest first."""
        ...
