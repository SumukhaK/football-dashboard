"""Domain models for telemetry events, traces, and errors.

Frozen (immutable) models. Behaviours are limited to small derived properties.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

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


# The shape of a request id as the backend logs it, and the marker it logs for a
# route it could not match. Both the Cloud Logging filter builder and the routes
# need them, so they live here rather than in either one.
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
UNMATCHED_ROUTE = "<unmatched>"


def is_route_filter(route: str) -> bool:
    """Whether a route filter names a path or the unmatched marker."""
    return route == UNMATCHED_ROUTE or route.startswith("/")


MAX_QUERY_LIMIT = 5000


@dataclass(frozen=True)
class EventQuery:
    """Filters for reading telemetry events; the window is start-inclusive."""

    window: TimeWindow
    events: tuple[str, ...] = ()
    request_id: str | None = None
    request_ids: tuple[str, ...] = ()
    route: str | None = None
    min_status: int | None = None
    max_status: int | None = None
    before: datetime | None = None
    before_id: str | None = None
    limit: int = 1000

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= MAX_QUERY_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_QUERY_LIMIT}")
        if (
            self.min_status is not None
            and self.max_status is not None
            and self.min_status >= self.max_status
        ):
            raise ValueError("min_status must be below max_status")
        if self.request_id is not None and self.request_ids:
            raise ValueError("request_id and request_ids cannot both be set")
        if self.before_id is not None and self.before is None:
            raise ValueError("before_id needs a before timestamp")


@dataclass(frozen=True)
class SourceCapabilities:
    """What a telemetry source can answer, so a page can say what is missing.

    error_reporting means "this source can supply error groups", however it got
    them: Google Cloud reads them from Error Reporting, a local log file groups
    its own app.crash lines.
    """

    traces: bool
    error_reporting: bool
    platform_events: bool


# The sample files and Google Cloud both answer every kind of query.
ALL_CAPABILITIES = SourceCapabilities(
    traces=True, error_reporting=True, platform_events=True
)


@dataclass(frozen=True)
class LocalReadStats:
    """What one read of a local log file did, line by line."""

    lines_read: int
    events_kept: int
    skipped_non_json: int
    skipped_invalid: int
    sample_errors: tuple[str, ...]
    file_size_bytes: int
    last_modified: datetime | None
    truncated: bool
    read_at: datetime

    @property
    def skipped_lines(self) -> int:
        """The lines the read rejected, whichever way they were rejected."""
        return self.skipped_non_json + self.skipped_invalid
