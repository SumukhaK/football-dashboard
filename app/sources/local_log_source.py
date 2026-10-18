"""Telemetry source backed by the backend's own JSON log file.

The backend writes one JSON object per log line (main repo step M2). Saved to a
file and pointed at with ``SOURCE=local``, those lines become the console's data
without any Google Cloud project. A local file is not a Google Cloud project:
it has no traces of its own and no Cloud Run platform logs, so the pages that
show those say so instead of showing nothing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from app.contract import Contract, ContractError, validate_event
from app.domain.clock import Clock
from app.domain.errors import SourceUnavailableError
from app.domain.models import (
    MAX_QUERY_LIMIT,
    ErrorGroup,
    EventQuery,
    LocalReadStats,
    PlatformEvent,
    SourceCapabilities,
    TelemetryEvent,
    TimeWindow,
    Trace,
)
from app.sources.filtering import select_events

# A local file has no traces and no Cloud Run platform events, but it can group
# the exception types in its own app.crash lines.
CAPABILITIES = SourceCapabilities(
    traces=False, error_reporting=True, platform_events=False
)

# How many rejected lines' messages the read keeps for the source page.
SAMPLE_ERROR_LIMIT = 5

# The group name a crash line without an exception type falls back to.
UNKNOWN_EXCEPTION = "unknown"

# How much of a rejected line a sample message quotes, so it stays one line.
SAMPLE_LINE_LENGTH = 80


class LocalLogSource:
    """Reads the backend's JSON log file, re-reading it only when it changes."""

    def __init__(
        self, path: Path, max_bytes: int, contract: Contract, clock: Clock
    ) -> None:
        """Store the file to read, the tail limit, the contract and the clock."""
        self._path = path
        self._max_bytes = max_bytes
        self._contract = contract
        self._clock = clock
        self._stamp: _Stamp | None = None
        self._snapshot: _Snapshot | None = None

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Return events matching the query, newest first."""
        return select_events(self._read().events, query)

    def trace(self, trace_id: str) -> Trace | None:
        """A log file holds no traces, so there is never one to return."""
        return None

    def error_groups(self, window: TimeWindow) -> list[ErrorGroup]:
        """Group the window's app.crash lines by exception type."""
        returned = EventQuery(
            window=window, events=("app.crash",), limit=MAX_QUERY_LIMIT
        )
        return crash_groups(select_events(self._read().events, returned))

    def platform_events(self, window: TimeWindow) -> list[PlatformEvent]:
        """A log file holds no Cloud Run platform events."""
        return []

    def capabilities(self) -> SourceCapabilities:
        """What a log file can answer: events and its own crash groups."""
        return CAPABILITIES

    def read_stats(self) -> LocalReadStats:
        """Return what the last read of the file did, line by line."""
        return self._read().stats

    def _read(self) -> _Snapshot:
        """Return the last read, re-reading the file when it has changed.

        A stat on every call is what keeps new lines visible; the file itself is
        only read when its size or modification time says it changed.
        """
        stamp = self._stat()
        if self._snapshot is None or stamp != self._stamp:
            self._snapshot = read_snapshot(
                self._path, self._max_bytes, self._contract, stamp, self._clock()
            )
            self._stamp = stamp
        return self._snapshot

    def _stat(self) -> _Stamp:
        """Return the size and modification time the file is watched by."""
        try:
            found = self._path.stat()
        except FileNotFoundError as exc:
            raise not_found(self._path) from exc
        return _Stamp(size=found.st_size, modified_ns=found.st_mtime_ns)


@dataclass(frozen=True)
class _Stamp:
    """The two file facts a change is noticed by, and the page is shown."""

    size: int
    modified_ns: int

    @property
    def modified(self) -> datetime:
        """The file's modification time, in UTC."""
        return datetime.fromtimestamp(self.modified_ns / 1_000_000_000, tz=UTC)


@dataclass(frozen=True)
class _Snapshot:
    """One read of the log file, held until the file changes again."""

    events: tuple[TelemetryEvent, ...]
    stats: LocalReadStats


@dataclass
class _Counts:
    """The running counts of one read of the log file."""

    lines_read: int = 0
    skipped_non_json: int = 0
    skipped_invalid: int = 0
    sample_errors: list[str] = field(default_factory=list)

    def reject_non_json(self, line: str) -> None:
        """Count a line that is not JSON, keeping the start of it as a sample."""
        self.skipped_non_json += 1
        self._sample(f"not JSON: {_short(line)}")

    def reject_invalid(self, message: str) -> None:
        """Count a line that breaks the contract, keeping the reason as a sample."""
        self.skipped_invalid += 1
        self._sample(message)

    def _sample(self, message: str) -> None:
        """Keep a message for the source page, up to the sample limit."""
        if len(self.sample_errors) < SAMPLE_ERROR_LIMIT:
            self.sample_errors.append(message)


def not_found(path: Path) -> SourceUnavailableError:
    """The error a missing log file raises, on the stat and on the read."""
    return SourceUnavailableError("not_found", f"{path} not found")


def read_tail(path: Path, max_bytes: int, size: int) -> tuple[str, bool]:
    """Return the file's last max_bytes of text, and whether it was cut short.

    When only the tail is read the first line is usually a fragment of a line,
    so it is dropped: a half-written log line is not a log line.
    """
    try:
        with path.open("rb") as handle:
            if size <= max_bytes:
                return handle.read().decode("utf-8", "replace"), False
            handle.seek(size - max_bytes)
            data = handle.read()
    except FileNotFoundError as exc:
        raise not_found(path) from exc
    end = data.find(b"\n")
    kept = data[end + 1 :] if end != -1 else b""
    return kept.decode("utf-8", "replace"), True


def read_snapshot(
    path: Path, max_bytes: int, contract: Contract, stamp: _Stamp, read_at: datetime
) -> _Snapshot:
    """Read the tail of the log file into events and the counts of that read."""
    data, truncated = read_tail(path, max_bytes, stamp.size)
    counts = _Counts()
    events: list[TelemetryEvent] = []
    for line in data.splitlines():
        if not line.strip():
            continue
        counts.lines_read += 1
        event = _event(line, contract, counts)
        if event is not None:
            events.append(event)
    return _Snapshot(
        events=tuple(events),
        stats=LocalReadStats(
            lines_read=counts.lines_read,
            events_kept=len(events),
            skipped_non_json=counts.skipped_non_json,
            skipped_invalid=counts.skipped_invalid,
            sample_errors=tuple(counts.sample_errors),
            file_size_bytes=stamp.size,
            last_modified=stamp.modified,
            truncated=truncated,
            read_at=read_at,
        ),
    )


def _event(line: str, contract: Contract, counts: _Counts) -> TelemetryEvent | None:
    """Convert one line, counting the lines that are not a contract event.

    One bad line never stops the read: the backend's start-up banner and any
    line written before logging is configured both land here on a real run.
    """
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        counts.reject_non_json(line)
        return None
    if not isinstance(payload, dict):
        counts.reject_invalid(f"not a JSON object: {_short(line)}")
        return None
    try:
        validate_event(contract, payload)
        return TelemetryEvent.from_log_line(payload)
    except (ContractError, ValueError, TypeError, KeyError) as exc:
        counts.reject_invalid(str(exc))
        return None


def crash_groups(events: list[TelemetryEvent]) -> list[ErrorGroup]:
    """Group app.crash lines by exception type, most recently seen first."""
    grouped: dict[str, list[TelemetryEvent]] = {}
    for event in events:
        grouped.setdefault(_exception_type(event), []).append(event)
    groups = [
        _crash_group(exception_type, items) for exception_type, items in grouped.items()
    ]
    groups.sort(key=lambda group: group.last_seen, reverse=True)
    return groups


def _crash_group(exception_type: str, items: list[TelemetryEvent]) -> ErrorGroup:
    """One group: how often, when, on which routes, and the traceback's first line."""
    newest = max(items, key=lambda item: item.timestamp)
    routes = sorted(
        {route for route in (_attribute(item, "route") for item in items) if route}
    )
    return ErrorGroup(
        group_id=exception_type,
        exception_type=exception_type,
        message=_first_line(newest.message),
        count=len(items),
        first_seen=min(item.timestamp for item in items),
        last_seen=max(item.timestamp for item in items),
        affected_routes=tuple(routes),
    )


def _exception_type(event: TelemetryEvent) -> str:
    """The exception class an app.crash line names, or a marker when it has none."""
    return _attribute(event, "exception_type") or UNKNOWN_EXCEPTION


def _attribute(event: TelemetryEvent, name: str) -> str | None:
    """One attribute as text, or None when the line did not carry it."""
    found = event.attributes.get(name)
    return None if found is None else str(found)


def _first_line(message: str) -> str:
    """The first line of a traceback message."""
    lines = message.splitlines()
    return lines[0] if lines else ""


def _short(line: str) -> str:
    """The start of a line, cut so a sample message stays on one line."""
    text = line.strip()
    if len(text) <= SAMPLE_LINE_LENGTH:
        return text
    return text[: SAMPLE_LINE_LENGTH - 3] + "..."
