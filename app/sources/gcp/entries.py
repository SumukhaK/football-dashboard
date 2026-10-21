"""Rebuild contract log lines from Cloud Logging entries.

Cloud Logging lifts some special keys out of a JSON log line and stores them
on the entry instead: severity, timestamp, the trace and the span ID. The
contract check needs the original line, so they are put back here.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from app.contract import Contract, ContractError, validate_event
from app.domain.models import TelemetryEvent
from app.sources.gcp.filters import rfc3339

logger = logging.getLogger(__name__)

TRACE_KEY = "logging.googleapis.com/trace"
SPAN_KEY = "logging.googleapis.com/spanId"


class LogEntryLike(Protocol):
    """The parts of a Cloud Logging entry this module reads."""

    @property
    def payload(self) -> Any: ...  # Any: dict for JSON entries, str for text.
    @property
    def timestamp(self) -> datetime | None: ...
    @property
    def severity(self) -> str | None: ...
    @property
    def trace(self) -> str | None: ...
    @property
    def span_id(self) -> str | None: ...


@dataclass(frozen=True)
class ConvertedEntries:
    """Events rebuilt from a batch of entries, and how many were skipped."""

    events: list[TelemetryEvent]
    skipped: int


def to_contract_line(entry: LogEntryLike) -> dict[str, Any]:
    """Return the original contract line for one JSON log entry."""
    payload: Mapping[str, Any] = (
        entry.payload if isinstance(entry.payload, dict) else {}
    )
    line = dict(payload)
    if entry.timestamp is not None:
        line["timestamp"] = rfc3339(entry.timestamp)
    if entry.severity:
        line["severity"] = str(entry.severity)
    line[TRACE_KEY] = entry.trace or None
    line[SPAN_KEY] = entry.span_id or None
    return line


def _error_category(exc: Exception) -> str:
    """Extract a safe category name from a validation or conversion error."""
    msg = str(exc).lower()
    if "missing common field" in msg or "missing required attribute" in msg:
        return "missing_field"
    if "timestamp" in msg:
        return "invalid_timestamp"
    if "attributes" in msg:
        return "invalid_attributes"
    if "event" in msg:
        return "invalid_event"
    if "contract version" in msg:
        return "version_mismatch"
    if "forbidden" in msg:
        return "forbidden_field"
    if isinstance(exc, KeyError):
        return "missing_field"
    return "malformed_shape"


def convert_entries(
    entries: Iterable[LogEntryLike], contract: Contract
) -> ConvertedEntries:
    """Convert entries to events, skipping and counting ones that break the contract."""
    events: list[TelemetryEvent] = []
    skipped = 0
    categories: dict[str, int] = {}
    for entry in entries:
        try:
            line = to_contract_line(entry)
            validate_event(contract, line)
            events.append(TelemetryEvent.from_log_line(line))
        except (ContractError, ValueError, TypeError, KeyError) as exc:
            skipped += 1
            cat = _error_category(exc)
            categories[cat] = categories.get(cat, 0) + 1
            continue
    if skipped:
        summary = ", ".join(f"{cat}: {cnt}" for cat, cnt in sorted(categories.items()))
        logger.warning(
            "Skipped %d log entries that do not match the contract (%s)",
            skipped,
            summary,
        )
    return ConvertedEntries(events=events, skipped=skipped)
