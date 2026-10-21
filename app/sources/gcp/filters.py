"""Pure builders for Cloud Logging filter strings."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime

from app.domain.models import (
    REQUEST_ID_PATTERN,
    EventQuery,
    TimeWindow,
    is_route_filter,
)
from app.domain.releases import ReleaseSelection

# Cloud Logging caps a filter at 20,000 characters; 100 ids of up to 64
# characters stays well inside it with room for the rest of the clauses.
IDS_PER_CLAUSE = 100
SYSTEM_LOG_SUFFIX = "run.googleapis.com%2Fvarlog%2Fsystem"


def quote(value: str) -> str:
    """Quote a value for a filter, escaping backslashes and double quotes."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def rfc3339(moment: datetime) -> str:
    """Format a moment as RFC 3339 UTC with milliseconds and a Z suffix."""
    utc = moment.astimezone(UTC)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"


def service_clause(service_name: str) -> str:
    """Restrict entries to one Cloud Run service."""
    return (
        'resource.type="cloud_run_revision" AND '
        f"resource.labels.service_name={quote(service_name)}"
    )


def window_clause(window: TimeWindow) -> str:
    """Restrict entries to the window, start included and end excluded."""
    return (
        f"timestamp>={quote(rfc3339(window.start))} AND "
        f"timestamp<{quote(rfc3339(window.end))}"
    )


def events_clause(events: tuple[str, ...]) -> str | None:
    """Restrict entries to the named events; None when every event is wanted."""
    if not events:
        return None
    return "jsonPayload.event=(" + " OR ".join(quote(e) for e in events) + ")"


def request_id_clause(request_id: str) -> str:
    """Restrict entries to one request, rejecting malformed ids."""
    if not REQUEST_ID_PATTERN.fullmatch(request_id):
        raise ValueError(f"invalid request id: {request_id!r}")
    return f"jsonPayload.request_id={quote(request_id)}"


def request_ids_clause(request_ids: Sequence[str]) -> str:
    """Restrict entries to a set of requests, rejecting malformed ids."""
    for request_id in request_ids:
        if not REQUEST_ID_PATTERN.fullmatch(request_id):
            raise ValueError(f"invalid request id: {request_id!r}")
    joined = " OR ".join(quote(request_id) for request_id in request_ids)
    return f"jsonPayload.request_id=({joined})"


def chunk_request_ids(
    request_ids: Sequence[str], size: int = IDS_PER_CLAUSE
) -> list[tuple[str, ...]]:
    """Split ids into chunks small enough to keep one filter short."""
    return [
        tuple(request_ids[start : start + size])
        for start in range(0, len(request_ids), size)
    ]


def route_clause(route: str) -> str:
    """Restrict entries to one route template, rejecting anything else."""
    if not is_route_filter(route):
        raise ValueError(f"invalid route: {route!r}")
    return f"jsonPayload.attributes.route={quote(route)}"


def status_clause(min_status: int, max_status: int | None = None) -> str:
    """Restrict entries to an HTTP status in ``[min_status, max_status)``."""
    clause = f"jsonPayload.attributes.status>={int(min_status)}"
    if max_status is not None:
        clause += f" AND jsonPayload.attributes.status<{int(max_status)}"
    return clause


def before_clause(before: datetime, before_id: str | None = None) -> str:
    """Restrict entries to those older than a pagination cursor.

    With a ``before_id`` the timestamp bound is inclusive: rows sharing the
    cursor's timestamp are read and the ones at or after the cursor id are
    dropped in memory, because Cloud Logging has no ordering comparison for
    string fields.
    """
    operator = "<=" if before_id is not None else "<"
    return f"timestamp{operator}{quote(rfc3339(before))}"


def events_filter(service_name: str, query: EventQuery) -> str:
    """Build the full filter for an event query."""
    clauses = [service_clause(service_name), window_clause(query.window)]
    optional = [
        release_clause(query.release),
        f"severity={quote(query.severity)}" if query.severity else None,
        events_clause(query.events),
        request_id_clause(query.request_id) if query.request_id else None,
        request_ids_clause(query.request_ids) if query.request_ids else None,
        route_clause(query.route) if query.route else None,
        (
            status_clause(query.min_status, query.max_status)
            if query.min_status is not None
            else None
        ),
        (
            before_clause(query.before, query.before_id)
            if query.before is not None
            else None
        ),
    ]
    clauses.extend(clause for clause in optional if clause is not None)
    return " AND ".join(clauses)


def release_clause(selection: ReleaseSelection) -> str | None:
    """Push exact case-sensitive candidates; unknown needs strict local typing."""
    if selection.kind == "all":
        return None
    if selection.kind == "unknown":
        # Logging compares array elements too, so no scalar-only NOT-regex is safe.
        return "jsonPayload:*"
    assert selection.value is not None
    return "jsonPayload.api_version=~" + quote("^" + re.escape(selection.value) + "$")


def system_log_filter(project_id: str, service_name: str, window: TimeWindow) -> str:
    """Build the filter for Cloud Run's own system log of the service."""
    log_name = f"projects/{project_id}/logs/{SYSTEM_LOG_SUFFIX}"
    return " AND ".join(
        [
            service_clause(service_name),
            f"logName={quote(log_name)}",
            window_clause(window),
        ]
    )
