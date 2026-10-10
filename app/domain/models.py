"""Domain models for telemetry events, traces, and errors.

Frozen (immutable) models. Behaviours are limited to small derived properties.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from app.contract import Contract

# Severity levels for log events


class Severity(StrEnum):
    """Severity level constants used by telemetry events."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

    @classmethod
    def values(cls) -> list[str]:
        """Return the list of valid severity values."""
        return [cls.DEBUG, cls.INFO, cls.WARNING, cls.ERROR, cls.CRITICAL]


@dataclass(frozen=True)
class TimeWindow:
    """A time window for querying events.

    start and end are UTC-aware datetimes and start must be strictly before end.
    """

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if not (self.start < self.end):
            raise ValueError("TimeWindow requires start < end")

    @classmethod
    def last_hours(cls, hours: int, now: datetime) -> TimeWindow:
        """Return a window covering the last N hours, ending at now."""
        return cls(start=now - timedelta(hours=hours), end=now)


@dataclass(frozen=True)
class SpanEvent:
    """A single event recorded inside a span (e.g. a retry)."""

    name: str
    timestamp: datetime
    attributes: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Span:
    """A span in an OpenTelemetry-style trace."""

    span_id: str
    parent_id: str | None
    name: str
    start: datetime
    end: datetime
    attributes: Mapping[str, Any] = field(default_factory=dict)
    events: tuple[SpanEvent, ...] = field(default_factory=tuple)

    @property
    def duration_ms(self) -> int:
        """Span duration in whole milliseconds."""
        delta = self.end - self.start
        return int(delta.total_seconds() * 1000)


@dataclass(frozen=True)
class Trace:
    """A trace containing its root span and children."""

    trace_id: str
    spans: tuple[Span, ...]

    @property
    def root(self) -> Span:
        """The trace's root span (no parent). Raises if none exists."""
        for span in self.spans:
            if span.parent_id is None:
                return span
        raise ValueError("Trace has no root span")


@dataclass(frozen=True)
class ErrorGroup:
    """A group of errors that share the same cause."""

    group_id: str
    exception_type: str
    message: str
    count: int
    first_seen: datetime
    last_seen: datetime
    affected_routes: tuple[str, ...]


@dataclass(frozen=True)
class PlatformEvent:
    """Platform-level events such as crashes and instance lifecycles."""

    timestamp: datetime
    kind: str  # out_of_memory | startup_failed | container_exit | instance_started
    revision: str
    message: str


@dataclass(frozen=True)
class TelemetryEvent:
    """A single telemetry event from the backend."""

    timestamp: datetime
    severity: str
    event: str | None
    message: str
    request_id: str | None
    trace_id: str | None
    span_id: str | None
    revision: str | None
    attributes: Mapping[str, object]

    @classmethod
    def from_log_line(cls, line: dict[str, Any]) -> TelemetryEvent:
        """Build a TelemetryEvent from a raw log line dictionary.

        Reads the contract's field names, including logging.googleapis.com/trace
        (takes the part after /traces/).
        """
        trace = line.get("logging.googleapis.com/trace")
        if trace and "/traces/" in trace:
            trace_id = trace.rsplit("/traces/", 1)[-1]
        else:
            trace_id = line.get("trace_id")

        return cls(
            timestamp=datetime.fromisoformat(line["timestamp"]),
            severity=line["severity"],
            event=line.get("event"),
            message=line["message"],
            request_id=line.get("request_id"),
            trace_id=trace_id,
            span_id=line.get("logging.googleapis.com/spanId"),
            revision=line.get("revision"),
            attributes=line.get("attributes", {}),
        )


@dataclass(frozen=True)
class EventQuery:
    """Filters for reading telemetry events.

    Window rule everywhere: ``start <= timestamp < end``.
    Results are always newest first.
    """

    window: TimeWindow
    events: tuple[str, ...] = ()  # empty means every event
    request_id: str | None = None
    route: str | None = None  # matches attributes["route"] exactly
    min_status: int | None = None  # matches attributes["status"] >= n
    limit: int = 1000  # 1 to 5000, else ValueError in __post_init__

    def __post_init__(self) -> None:
        if not (1 <= self.limit <= 5000):
            raise ValueError("limit must be between 1 and 5000")
