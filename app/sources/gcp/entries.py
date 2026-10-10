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


def convert_entries(
    entries: Iterable[LogEntryLike], contract: Contract
) -> ConvertedEntries:
    """Convert entries to events, skipping and counting ones that break the contract."""
    events: list[TelemetryEvent] = []
    skipped = 0
    for entry in entries:
        line = to_contract_line(entry)
        try:
            validate_event(contract, line)
        except ContractError:
            skipped += 1
            continue
        events.append(TelemetryEvent.from_log_line(line))
    if skipped:
        logger.warning("Skipped %d log entries that do not match the contract", skipped)
    return ConvertedEntries(events=events, skipped=skipped)
