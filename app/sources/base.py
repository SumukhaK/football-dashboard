"""The read-only interfaces every telemetry and crash source implements."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain.crashes import CrashEvent
from app.domain.models import (
    ErrorGroup,
    EventQuery,
    LocalReadStats,
    PlatformEvent,
    SourceCapabilities,
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

    def capabilities(self) -> SourceCapabilities:
        """Return what this source can answer, so pages can say what is missing."""
        ...


@runtime_checkable
class LocalLogStats(Protocol):
    """A source that can say how it read its own log file.

    Kept apart from TelemetrySource because only a source reading a local file
    has a read to describe; everything else answers None.
    """

    def read_stats(self) -> LocalReadStats | None:
        """Return the counts from the last read, or None when there is none."""
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
