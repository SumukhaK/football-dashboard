"""Small, pure accessors for telemetry events.

Every page reads the same handful of attributes (event name, status, duration),
so that reading lives here instead of being repeated in each service.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.domain.models import TelemetryEvent


def status(event: TelemetryEvent) -> int | None:
    """The HTTP status recorded on an event, or None when there is none."""
    value = event.attributes.get("status")
    return value if isinstance(value, int) else None


def duration_ms(event: TelemetryEvent) -> float | None:
    """The duration recorded on an event, or None when there is none."""
    value = event.attributes.get("duration_ms")
    if isinstance(value, (int, float)):
        return float(value)
    return None


def durations(events: Iterable[TelemetryEvent]) -> list[float]:
    """The durations of the events that have one."""
    return [value for event in events if (value := duration_ms(event)) is not None]


def by_event(events: Iterable[TelemetryEvent], name: str) -> list[TelemetryEvent]:
    """The events of one catalogue name."""
    return [event for event in events if event.event == name]


def in_status_class(event: TelemetryEvent, low: int, high: int) -> bool:
    """Whether an event's status falls in ``[low, high)``."""
    found = status(event)
    return found is not None and low <= found < high
