"""Pure functions for filtering telemetry events.

These have no Google Cloud imports and can be fully unit tested.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.domain.models import EventQuery, TelemetryEvent


def matches(event: TelemetryEvent, query: EventQuery) -> bool:
    """Return True if *event* matches all filters in *query*."""
    if query.events and event.event not in query.events:
        return False

    if query.request_id is not None and event.request_id != query.request_id:
        return False

    attrs = event.attributes
    if query.route is not None and attrs.get("route") != query.route:
        return False

    if query.min_status is not None:
        status = attrs.get("status")
        if status is not None and int(status) < query.min_status:
            return False

    return True