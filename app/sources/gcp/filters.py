"""Pure builders for Cloud Logging filter strings."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from app.domain.models import EventQuery, TimeWindow

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
UNMATCHED_ROUTE = "<unmatched>"
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


def route_clause(route: str) -> str:
    """Restrict entries to one route template, rejecting anything else."""
    if route != UNMATCHED_ROUTE and not route.startswith("/"):
        raise ValueError(f"invalid route: {route!r}")
    return f"jsonPayload.attributes.route={quote(route)}"


def status_clause(min_status: int) -> str:
    """Restrict entries to an HTTP status at or above min_status."""
    return f"jsonPayload.attributes.status>={int(min_status)}"


def events_filter(service_name: str, query: EventQuery) -> str:
    """Build the full filter for an event query."""
    clauses = [service_clause(service_name), window_clause(query.window)]
    optional = [
        events_clause(query.events),
        request_id_clause(query.request_id) if query.request_id else None,
        route_clause(query.route) if query.route else None,
        status_clause(query.min_status) if query.min_status is not None else None,
    ]
    clauses.extend(clause for clause in optional if clause is not None)
    return " AND ".join(clauses)


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
