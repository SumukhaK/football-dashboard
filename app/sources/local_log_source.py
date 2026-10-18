"""Telemetry source backed by the backend's own JSON log file.

The backend writes one JSON object per log line (main repo step M2). Saved to a
file and pointed at with ``SOURCE=local``, those lines become the console's data
without any Google Cloud project. A local file is not a Google Cloud project:
it has no traces of its own and no Cloud Run platform logs, so the pages that
show those say so instead of showing nothing.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

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

# The byte-order marks a capture can leave at the front of the file. PowerShell
# 5.1's Tee-Object writes UTF-16LE with one; an editor can save UTF-8 with one.
_UTF8_BOM = b"\xef\xbb\xbf"
_UTF16_LE_BOM = b"\xff\xfe"
_UTF16_BE_BOM = b"\xfe\xff"


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
        except OSError as exc:
            raise read_error(self._path, exc) from exc
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


@dataclass(frozen=True)
class _Tail:
    """One bounded read of the log file: its text, its real size, and if cut."""

    text: str
    size: int
    truncated: bool


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


def read_error(path: Path, exc: OSError) -> SourceUnavailableError:
    """The error a file that cannot be read raises, by what went wrong."""
    if isinstance(exc, PermissionError):
        return SourceUnavailableError("permission_denied", f"{path} permission denied")
    reason = exc.strerror or exc.__class__.__name__
    return SourceUnavailableError("unavailable", f"{path} cannot be read: {reason}")


def read_tail(path: Path, max_bytes: int) -> _Tail:
    """Read the file's last max_bytes as text, bounded and by its own encoding.

    The size comes from the open file rather than the earlier stat, and the read
    is capped, so a backend appending while the console reads cannot make one
    read exceed the limit. The text is decoded by the file's byte-order mark, so
    the UTF-16 a Windows capture writes is read like UTF-8. When the read starts
    mid-file the first line is dropped only if it is a fragment: a window that
    opens exactly on a line start keeps its first whole line.
    """
    try:
        with path.open("rb") as handle:
            size = handle.seek(0, os.SEEK_END)
            encoding, newline = _file_format(handle)
            start = max(0, size - max_bytes)
            handle.seek(start)
            data = handle.read(max_bytes)
            whole = start == 0 or _opens_a_line(handle, start, newline)
    except FileNotFoundError as exc:
        raise not_found(path) from exc
    except OSError as exc:
        raise read_error(path, exc) from exc
    if not whole:
        data = _drop_fragment(data, newline)
    return _Tail(text=_decode(data, encoding), size=size, truncated=start > 0)


def _file_format(handle: BinaryIO) -> tuple[str, bytes]:
    """The text encoding and line-break bytes the file's first bytes announce."""
    handle.seek(0)
    head = handle.read(len(_UTF8_BOM))
    if head.startswith(_UTF16_LE_BOM):
        return "utf-16-le", b"\n\x00"
    if head.startswith(_UTF16_BE_BOM):
        return "utf-16-be", b"\x00\n"
    return "utf-8", b"\n"


def _opens_a_line(handle: BinaryIO, start: int, newline: bytes) -> bool:
    """Whether the byte at start begins a line rather than cutting through one."""
    if start < len(newline):
        return False
    handle.seek(start - len(newline))
    return handle.read(len(newline)) == newline


def _drop_fragment(data: bytes, newline: bytes) -> bytes:
    """Drop the bytes before the first whole line in the window."""
    end = data.find(newline)
    return data[end + len(newline) :] if end != -1 else b""


def _decode(data: bytes, encoding: str) -> str:
    """Decode a window, dropping the byte-order mark if the read began at it."""
    for mark in (_UTF8_BOM, _UTF16_LE_BOM, _UTF16_BE_BOM):
        if data.startswith(mark):
            data = data[len(mark) :]
            break
    return data.decode(encoding, "replace")


def read_snapshot(
    path: Path, max_bytes: int, contract: Contract, stamp: _Stamp, read_at: datetime
) -> _Snapshot:
    """Read the tail of the log file into events and the counts of that read."""
    tail = read_tail(path, max_bytes)
    counts = _Counts()
    events: list[TelemetryEvent] = []
    for line in tail.text.splitlines():
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
            file_size_bytes=tail.size,
            last_modified=stamp.modified,
            truncated=tail.truncated,
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
        _require_offset(payload["timestamp"])
        return TelemetryEvent.from_log_line(payload)
    except (ContractError, ValueError, TypeError, KeyError) as exc:
        counts.reject_invalid(str(exc))
        return None


def _require_offset(stamp: object) -> None:
    """Refuse a timestamp with no UTC offset before it can break the filter.

    ``datetime.fromisoformat`` accepts ``2026-10-08T16:00:00``, but a kept naive
    time makes the filter compare it with an aware window and raise, which would
    lose every other line in the same read. Counting it invalid is what the read
    already does with any other line it cannot use.
    """
    moment = datetime.fromisoformat(str(stamp))
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError(f"timestamp has no timezone offset: {stamp}")


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
