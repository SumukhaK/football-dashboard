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
    if query.before is not None and at_or_newer_than_cursor(
        event, query.before, query.before_id
    ):
        return False
    if query.events and event.event not in query.events:
        return False
    if query.request_id is not None and event.request_id != query.request_id:
        return False
    if query.request_ids and event.request_id not in query.request_ids:
        return False
    if query.route is not None and event.attributes.get("route") != query.route:
        return False
    if query.min_status is None and query.max_status is None:
        return True
    found = event.attributes.get("status")
    if not isinstance(found, int):
        return False
    if query.min_status is not None and found < query.min_status:
        return False
    return query.max_status is None or found < query.max_status


def at_or_newer_than_cursor(
    event: TelemetryEvent, before: datetime, before_id: str | None
) -> bool:
    """Whether an event is not older than the pagination cursor.

    The cursor is ``(before, before_id)``: rows are ordered by timestamp and
    then request id, newest first, so this is the exact complement of "comes
    after the cursor in that order". Without a ``before_id`` the rule reduces to
    "the timestamp is not strictly older", which is the plain ``before`` filter.
    """
    return (event.timestamp, event.request_id or "") >= (before, before_id or "")


def select_events(
    events: Iterable[TelemetryEvent], query: EventQuery
) -> list[TelemetryEvent]:
    """Return matching events, newest first, cut to the query's limit."""
    found = [event for event in events if matches(event, query)]
    found.sort(key=newest_first, reverse=True)
    return found[: query.limit]


def newest_first(event: TelemetryEvent) -> tuple[datetime, str]:
    """The order rows are paged in: timestamp, then request id, newest first."""
    return (event.timestamp, event.request_id or "")


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
