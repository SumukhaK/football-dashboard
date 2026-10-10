"""Builders shared by the source tests."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from app.domain.models import TelemetryEvent

BASE = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def make_event(
    minute: int,
    event: str = "http.request",
    request_id: str | None = "req-00000001",
    attributes: Mapping[str, object] | None = None,
) -> TelemetryEvent:
    """Build a TelemetryEvent at BASE plus the given minute."""
    return TelemetryEvent(
        timestamp=BASE.replace(minute=minute),
        severity="INFO",
        event=event,
        message="sample",
        request_id=request_id,
        trace_id=None,
        span_id=None,
        revision=None,
        attributes=attributes or {"route": "/v2/fixtures", "status": 200},
    )


EventFactory = Callable[..., TelemetryEvent]
