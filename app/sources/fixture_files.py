"""Parsers for the four committed fixture files."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.contract import Contract, ContractError, validate_event
from app.domain.errors import SourceUnavailableError
from app.domain.models import (
    ErrorGroup,
    PlatformEvent,
    Span,
    SpanEvent,
    TelemetryEvent,
    Trace,
)

EVENTS_FILE = "events.jsonl"
TRACES_FILE = "traces.json"
ERROR_GROUPS_FILE = "error_groups.json"
PLATFORM_EVENTS_FILE = "platform_events.json"


def parse_time(value: str) -> datetime:
    """Parse an RFC 3339 timestamp from the fixtures into an aware datetime."""
    return datetime.fromisoformat(value)


def read_json(path: Path) -> Any:  # Any: json.loads returns untyped data.
    """Read a JSON file, turning a missing or broken file into a source error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SourceUnavailableError("not_found", f"{path} not found") from exc
    except json.JSONDecodeError as exc:
        raise SourceUnavailableError("invalid_data", f"{path}: {exc}") from exc


def load_events(path: Path, contract: Contract) -> list[TelemetryEvent]:
    """Load events.jsonl, validating every line against the contract."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise SourceUnavailableError("not_found", f"{path} not found") from exc
    return [
        _parse_event_line(text, number, contract)
        for number, text in enumerate(lines, start=1)
        if text.strip()
    ]


def _parse_event_line(text: str, number: int, contract: Contract) -> TelemetryEvent:
    """Validate and convert one events.jsonl line; data errors are loud."""
    try:
        line = json.loads(text)
        validate_event(contract, line)
    except (json.JSONDecodeError, ContractError) as exc:
        raise SourceUnavailableError(
            "invalid_data", f"{EVENTS_FILE} line {number}: {exc}"
        ) from exc
    return TelemetryEvent.from_log_line(line)


def load_traces(path: Path) -> list[Trace]:
    """Load traces.json into domain traces."""
    return [
        Trace(
            trace_id=item["trace_id"],
            spans=tuple(_parse_span(span) for span in item["spans"]),
        )
        for item in read_json(path)
    ]


def _parse_span(item: dict[str, Any]) -> Span:
    """Convert one span object from traces.json."""
    return Span(
        span_id=item["span_id"],
        parent_id=item["parent_id"],
        name=item["name"],
        start=parse_time(item["start"]),
        end=parse_time(item["end"]),
        attributes=item.get("attributes", {}),
        events=tuple(
            SpanEvent(
                name=event["name"],
                timestamp=parse_time(event["timestamp"]),
                attributes=event.get("attributes", {}),
            )
            for event in item.get("events", [])
        ),
    )


def load_error_groups(path: Path) -> list[ErrorGroup]:
    """Load error_groups.json into domain error groups."""
    return [
        ErrorGroup(
            group_id=item["group_id"],
            exception_type=item["exception_type"],
            message=item["message"],
            count=item["count"],
            first_seen=parse_time(item["first_seen"]),
            last_seen=parse_time(item["last_seen"]),
            affected_routes=tuple(item["affected_routes"]),
        )
        for item in read_json(path)
    ]


def load_platform_events(path: Path) -> list[PlatformEvent]:
    """Load platform_events.json into domain platform events."""
    return [
        PlatformEvent(
            timestamp=parse_time(item["timestamp"]),
            kind=item["kind"],
            revision=item["revision"],
            message=item["message"],
        )
        for item in read_json(path)
    ]
