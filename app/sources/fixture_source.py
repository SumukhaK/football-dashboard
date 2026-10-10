"""Telemetry source backed by the committed sample files."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from app.contract import Contract
from app.domain.models import (
    ErrorGroup,
    EventQuery,
    PlatformEvent,
    Span,
    TelemetryEvent,
    TimeWindow,
    Trace,
)
from app.sources import fixture_files
from app.sources.filtering import (
    overlapping_groups,
    platform_in_window,
    select_events,
)


class FixtureSource:
    """Reads the four fixture files once and answers queries in memory."""

    def __init__(
        self, fixture_dir: Path, contract: Contract, now: datetime | None = None
    ) -> None:
        events = fixture_files.load_events(
            fixture_dir / fixture_files.EVENTS_FILE, contract
        )
        traces = fixture_files.load_traces(fixture_dir / fixture_files.TRACES_FILE)
        groups = fixture_files.load_error_groups(
            fixture_dir / fixture_files.ERROR_GROUPS_FILE
        )
        platform = fixture_files.load_platform_events(
            fixture_dir / fixture_files.PLATFORM_EVENTS_FILE
        )
        shift = _shift_to(now, events)
        self._events = [replace(e, timestamp=e.timestamp + shift) for e in events]
        self._traces = {t.trace_id: _shift_trace(t, shift) for t in traces}
        self._groups = [_shift_group(g, shift) for g in groups]
        self._platform = [replace(p, timestamp=p.timestamp + shift) for p in platform]

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Return events matching the query, newest first."""
        return select_events(self._events, query)

    def trace(self, trace_id: str) -> Trace | None:
        """Return one trace, or None when it does not exist."""
        return self._traces.get(trace_id)

    def error_groups(self, window: TimeWindow) -> list[ErrorGroup]:
        """Return error groups that overlap the window."""
        return overlapping_groups(self._groups, window)

    def platform_events(self, window: TimeWindow) -> list[PlatformEvent]:
        """Return platform events inside the window, newest first."""
        return platform_in_window(self._platform, window)


def _shift_to(now: datetime | None, events: list[TelemetryEvent]) -> timedelta:
    """Offset that moves the newest event to now, so local runs look current."""
    if now is None or not events:
        return timedelta(0)
    return now - max(event.timestamp for event in events)


def _shift_span(span: Span, shift: timedelta) -> Span:
    """Move a span and its span events by the offset."""
    return replace(
        span,
        start=span.start + shift,
        end=span.end + shift,
        events=tuple(
            replace(event, timestamp=event.timestamp + shift) for event in span.events
        ),
    )


def _shift_trace(trace: Trace, shift: timedelta) -> Trace:
    """Move every span in a trace by the offset."""
    return replace(trace, spans=tuple(_shift_span(s, shift) for s in trace.spans))


def _shift_group(group: ErrorGroup, shift: timedelta) -> ErrorGroup:
    """Move an error group's first and last seen times by the offset."""
    return replace(
        group, first_seen=group.first_seen + shift, last_seen=group.last_seen + shift
    )
