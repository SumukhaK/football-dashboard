"""Base protocol for telemetry sources.

Read-only access to the backend's telemetry, using the ``EventQuery``
filter dataclass from ``app.domain``.
"""

from __future__ import annotations

from typing import Protocol

from app.domain.errors import SourceUnavailableError
from app.domain.models import EventQuery, TimeWindow
from app.domain.models import TelemetryEvent, ErrorGroup, PlatformEvent


class TelemetrySource(Protocol):
    """Read-only access to the backend's telemetry."""

    def events(self, query: EventQuery) -> list[TelemetryEvent]: ...
    def trace(self, trace_id: str) -> TelemetryEvent | None: ...
    def error_groups(self, window: TimeWindow) -> list[ErrorGroup]: ...
    def platform_events(self, window: TimeWindow) -> list[PlatformEvent]: ...
