"""The tool, model-call and fallback parts of the assistant page.

``gave_up_requests`` is the one rule on the page that reads a sequence of lines
rather than a single one, so it lives on its own and is unit tested on its own.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from app.domain.assistant import (
    FAILURE_STATUSES,
    MODEL_DEPENDENCIES,
    FallbackRow,
    GaveUpRequest,
    ModelCallRow,
    StatusCount,
    ToolRow,
)
from app.domain.models import TelemetryEvent
from app.services.events import durations, text
from app.services.links import request_detail_link
from app.services.stats import percentile, rate

UNKNOWN = "<unknown>"


def gave_up_requests(calls: Sequence[TelemetryEvent]) -> set[str]:
    """The requests whose newest recorded call to a dependency failed.

    A call with no request id cannot be attributed to a request, so it decides
    nothing here. The newest call is the one that counted, not the highest
    attempt number: one request calls the same dependency once per tool round and
    every round starts again at attempt 1, so a request that retried and then
    succeeded in its first round must not hide a later round that failed for
    good. Two calls with the same timestamp are settled by the higher attempt.
    """
    latest: dict[str, TelemetryEvent] = {}
    for call in calls:
        if call.request_id is None:
            continue
        current = latest.get(call.request_id)
        if current is None or _latest_key(call) > _latest_key(current):
            latest[call.request_id] = call
    return {
        request_id
        for request_id, call in latest.items()
        if text(call.attributes.get("status")) != "ok"
    }


def tool_rows(tools: Sequence[TelemetryEvent]) -> tuple[ToolRow, ...]:
    """One row per tool, worst error rate first, then by tool name."""
    grouped: dict[str, list[TelemetryEvent]] = {}
    for tool in tools:
        name = text(tool.attributes.get("tool")) or UNKNOWN
        grouped.setdefault(name, []).append(tool)
    rows = [_tool_row(name, events) for name, events in grouped.items()]
    rows.sort(key=lambda row: (-(row.error_rate or 0.0), row.tool))
    return tuple(rows)


def model_call_rows(
    calls: Sequence[TelemetryEvent], retries: Sequence[TelemetryEvent]
) -> tuple[ModelCallRow, ...]:
    """One row per model dependency, in the contract's order.

    A dependency appears when it was called or when it was retried, so a retry
    whose call line was pushed out of the read is still visible.
    """
    by_dependency: dict[str, list[TelemetryEvent]] = {}
    for call in calls:
        dependency = text(call.attributes.get("dependency"))
        if dependency in MODEL_DEPENDENCIES:
            by_dependency.setdefault(dependency, []).append(call)
    for retry in retries:
        dependency = text(retry.attributes.get("dependency"))
        if dependency in MODEL_DEPENDENCIES:
            by_dependency.setdefault(dependency, [])
    return tuple(
        _model_call_row(dependency, by_dependency[dependency], retries)
        for dependency in sorted(by_dependency, key=_dependency_key)
    )


def fallback_rows(fallbacks: Sequence[TelemetryEvent]) -> tuple[FallbackRow, ...]:
    """Fallbacks counted per from/to/cause, most common first, then by name."""
    counts: dict[tuple[str, str, str], int] = {}
    for fallback in fallbacks:
        key = (
            text(fallback.attributes.get("from_path")) or UNKNOWN,
            text(fallback.attributes.get("to_path")) or UNKNOWN,
            text(fallback.attributes.get("cause")) or UNKNOWN,
        )
        counts[key] = counts.get(key, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return tuple(
        FallbackRow(from_path=from_path, to_path=to_path, cause=cause, count=count)
        for (from_path, to_path, cause), count in ordered
    )


def status_counts(calls: Sequence[TelemetryEvent]) -> tuple[StatusCount, ...]:
    """The failed attempts of one dependency, the contract's statuses first."""
    counts: dict[str, int] = {}
    for call in calls:
        found = text(call.attributes.get("status")) or UNKNOWN
        if found != "ok":
            counts[found] = counts.get(found, 0) + 1
    return tuple(
        StatusCount(status=status, count=counts[status])
        for status in sorted(counts, key=_status_key)
    )


def _model_call_row(
    dependency: str,
    calls: Sequence[TelemetryEvent],
    retries: Sequence[TelemetryEvent],
) -> ModelCallRow:
    """One dependency's attempts, failure rate, retries and gave-up requests."""
    failures = status_counts(calls)
    return ModelCallRow(
        dependency=dependency,
        attempts=len(calls),
        failures=failures,
        failure_rate=rate(sum(item.count for item in failures), len(calls)),
        retries=sum(
            1
            for retry in retries
            if text(retry.attributes.get("dependency")) == dependency
        ),
        gave_up=tuple(
            GaveUpRequest(request_id=request_id, link=request_detail_link(request_id))
            for request_id in sorted(gave_up_requests(calls))
        ),
    )


def _tool_row(tool: str, events: Sequence[TelemetryEvent]) -> ToolRow:
    """One tool's calls, errors, error rate, p95 and newest error message."""
    errors = [
        event for event in events if text(event.attributes.get("status")) == "error"
    ]
    newest = max(errors, key=lambda event: event.timestamp) if errors else None
    return ToolRow(
        tool=tool,
        calls=len(events),
        errors=len(errors),
        error_rate=rate(len(errors), len(events)),
        p95_ms=percentile(durations(events), 0.95),
        last_error=text(newest.attributes.get("error")) if newest else None,
    )


def _latest_key(call: TelemetryEvent) -> tuple[datetime, int]:
    """The order two calls of one request are judged in: newest first, then attempt.

    The timestamp leads because attempt numbers restart with every tool round;
    the attempt only breaks a tie between calls that share a timestamp.
    """
    attempt = call.attributes.get("attempt")
    return (call.timestamp, attempt if isinstance(attempt, int) else 0)


def _dependency_key(dependency: str) -> tuple[int, str]:
    """Sort the contract's dependencies first, in order, then any other by name."""
    rank = (
        MODEL_DEPENDENCIES.index(dependency)
        if dependency in MODEL_DEPENDENCIES
        else len(MODEL_DEPENDENCIES)
    )
    return (rank, dependency)


def _status_key(status: str) -> tuple[int, str]:
    """Sort the named failure statuses first, in contract order."""
    rank = (
        FAILURE_STATUSES.index(status)
        if status in FAILURE_STATUSES
        else len(FAILURE_STATUSES)
    )
    return (rank, status)
