"""In-memory filtering shared by the file-based sources."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from app.domain.models import (
    ErrorGroup,
    EventQuery,
    PlatformEvent,
    TelemetryEvent,
    TimeWindow,
)


def in_window(moment: datetime, window: TimeWindow) -> bool:
    """Return whether a moment falls in the window (start included, end not)."""
    return window.start <= moment < window.end


def matches(event: TelemetryEvent, query: EventQuery) -> bool:
    """Return whether one event satisfies every filter in the query."""
    if not in_window(event.timestamp, query.window):
        return False
    if query.events and event.event not in query.events:
        return False
    if query.request_id is not None and event.request_id != query.request_id:
        return False
    if query.route is not None and event.attributes.get("route") != query.route:
        return False
    if query.min_status is not None:
        status = event.attributes.get("status")
        if not isinstance(status, int) or status < query.min_status:
            return False
    return True


def select_events(
    events: Iterable[TelemetryEvent], query: EventQuery
) -> list[TelemetryEvent]:
    """Return matching events, newest first, cut to the query's limit."""
    found = [event for event in events if matches(event, query)]
    found.sort(key=lambda event: event.timestamp, reverse=True)
    return found[: query.limit]


def overlapping_groups(
    groups: Iterable[ErrorGroup], window: TimeWindow
) -> list[ErrorGroup]:
    """Return error groups seen at any point inside the window."""
    found = [
        group
        for group in groups
        if group.last_seen >= window.start and group.first_seen < window.end
    ]
    found.sort(key=lambda group: group.last_seen, reverse=True)
    return found


def platform_in_window(
    events: Iterable[PlatformEvent], window: TimeWindow
) -> list[PlatformEvent]:
    """Return platform events inside the window, newest first."""
    found = [event for event in events if in_window(event.timestamp, window)]
    found.sort(key=lambda event: event.timestamp, reverse=True)
    return found
