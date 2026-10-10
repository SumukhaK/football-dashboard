"""Tests for the Cloud Logging filter builders."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.domain.models import EventQuery, TimeWindow
from app.sources.gcp import filters

WINDOW = TimeWindow(
    start=datetime(2026, 10, 8, 6, 0, tzinfo=UTC),
    end=datetime(2026, 10, 8, 7, 30, 0, 250000, tzinfo=UTC),
)
SERVICE = (
    'resource.type="cloud_run_revision" AND resource.labels.service_name="football-api"'
)


def test_quote_escapes_backslashes_and_quotes() -> None:
    """Backslashes are doubled and quotes escaped inside the quotes."""
    assert filters.quote('a"b\\c') == '"a\\"b\\\\c"'


def test_service_clause() -> None:
    """The base clause pins the resource type and service name."""
    assert filters.service_clause("football-api") == SERVICE


def test_window_clause_uses_rfc3339_milliseconds() -> None:
    """Start is inclusive, end exclusive, both in UTC with milliseconds."""
    assert filters.window_clause(WINDOW) == (
        'timestamp>="2026-10-08T06:00:00.000Z" AND '
        'timestamp<"2026-10-08T07:30:00.250Z"'
    )


def test_events_clause() -> None:
    """Events are ORed; an empty tuple adds no clause."""
    assert filters.events_clause(("http.request", "app.error")) == (
        'jsonPayload.event=("http.request" OR "app.error")'
    )
    assert filters.events_clause(()) is None


def test_request_id_clause_accepts_and_rejects() -> None:
    """Valid ids are quoted; malformed ids raise ValueError."""
    assert filters.request_id_clause("abc12345") == 'jsonPayload.request_id="abc12345"'
    for bad in ("short", 'quote"injection1', "x" * 65):
        with pytest.raises(ValueError):
            filters.request_id_clause(bad)


def test_route_clause_accepts_and_rejects() -> None:
    """Routes must start with / or be <unmatched>; values are escaped."""
    assert filters.route_clause("/v2/teams/{team}/outlook") == (
        'jsonPayload.attributes.route="/v2/teams/{team}/outlook"'
    )
    assert filters.route_clause("<unmatched>") == (
        'jsonPayload.attributes.route="<unmatched>"'
    )
    with pytest.raises(ValueError):
        filters.route_clause("v2/fixtures")


def test_status_clause() -> None:
    """Status compares numerically."""
    assert filters.status_clause(500) == "jsonPayload.attributes.status>=500"


def test_events_filter_combines_every_clause() -> None:
    """All set filters are joined with AND, in a stable order."""
    query = EventQuery(
        window=WINDOW,
        events=("http.request",),
        request_id="abc12345",
        route="/v2/predict",
        min_status=400,
    )
    built = filters.events_filter("football-api", query)
    assert built == " AND ".join(
        [
            SERVICE,
            filters.window_clause(WINDOW),
            'jsonPayload.event=("http.request")',
            'jsonPayload.request_id="abc12345"',
            'jsonPayload.attributes.route="/v2/predict"',
            "jsonPayload.attributes.status>=400",
        ]
    )


def test_events_filter_minimal() -> None:
    """With only a window, the filter is the service and time clauses."""
    built = filters.events_filter("football-api", EventQuery(window=WINDOW))
    assert built == f"{SERVICE} AND {filters.window_clause(WINDOW)}"


def test_system_log_filter() -> None:
    """The platform filter targets Cloud Run's system log for the project."""
    built = filters.system_log_filter("demo", "football-api", WINDOW)
    assert 'logName="projects/demo/logs/run.googleapis.com%2Fvarlog%2Fsystem"' in built
    assert built.startswith(SERVICE)
