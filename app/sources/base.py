"""Base protocol for telemetry sources.

Implemented by D2 fixtures and GCP sources; this file has signatures only.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence
from typing import Protocol

from app.domain.models import ErrorGroup, PlatformEvent, TelemetryEvent, TimeWindow


class TelemetrySource(Protocol):
    """Base protocol for telemetry sources."""

    @abstractmethod
    def query_events(self, window: TimeWindow) -> Sequence[TelemetryEvent]:
        """Return all telemetry events in the given time window."""

    @abstractmethod
    def get_traces(self, trace_id: str) -> dict[str, object]:
        """Return trace data for the given trace id."""

    @abstractmethod
    def get_errors(self, window: TimeWindow) -> Sequence[ErrorGroup]:
        """Return grouped errors in the given time window."""

    @abstractmethod
    def get_platform_events(self, window: TimeWindow) -> Sequence[PlatformEvent]:
        """Return platform lifecycle events in the given time window."""
