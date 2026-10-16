"""Tests for the overview's headlines, chart series and the links it builds."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.config import Config
from app.domain.models import TelemetryEvent, TimeWindow
from app.services.overview import window_for_hours

from .overview_helpers import (
    HEADLINE_ORDER,
    ListSource,
    by_key,
    make_service,
    request_line,
)


def test_error_rate_and_previous_window_comparison() -> None:
    """The error rate and its change come from hand-counted requests."""
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    window = TimeWindow(start=now - timedelta(hours=1), end=now)
    events = [
        request_line(now - timedelta(minutes=10), 200),
        request_line(now - timedelta(minutes=20), 200),
        request_line(now - timedelta(minutes=30), 500),
        request_line(now - timedelta(minutes=40), 503),
        request_line(now - timedelta(hours=1, minutes=10), 200),
        request_line(now - timedelta(hours=1, minutes=20), 200),
        request_line(now - timedelta(hours=1, minutes=30), 200),
        request_line(now - timedelta(hours=1, minutes=40), 500),
    ]
    model = make_service(ListSource(events), now).build(window)

    headline = by_key(model.headlines, "error_rate")
    assert headline.value == 0.5
    assert headline.previous == 0.25
    assert headline.change == 0.25


def test_traffic_series_sums_to_the_request_count() -> None:
    """Every request lands in exactly one traffic bucket."""
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    window = TimeWindow(start=now - timedelta(hours=1), end=now)
    events = [
        request_line(now - timedelta(minutes=5), 200),
        request_line(now - timedelta(minutes=15), 404),
        request_line(now - timedelta(minutes=25), 500),
    ]
    model = make_service(ListSource(events), now).build(window)

    total = sum(
        value
        for series in model.traffic.series
        for value in series.values
        if value is not None
    )
    assert total == 3
    assert {series.name for series in model.traffic.series} == {"2xx", "4xx", "5xx"}


def test_chart_labels_are_compact() -> None:
    """Chart labels are HH:MM, never raw ISO timestamps."""
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    window = TimeWindow(start=now - timedelta(hours=1), end=now)
    model = make_service(
        ListSource([request_line(now - timedelta(minutes=5), 200)]), now
    ).build(window)

    assert model.traffic.labels
    for label in model.traffic.labels:
        assert "T" not in label
        assert "+00" not in label
        assert len(label) <= 12


def test_headline_order_and_p95_units() -> None:
    """Headlines follow the guide's order and p95 names its unit."""
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    window = TimeWindow(start=now - timedelta(hours=1), end=now)
    model = make_service(ListSource([]), now).build(window)

    assert [headline.key for headline in model.headlines] == HEADLINE_ORDER
    assert "ms" in by_key(model.headlines, "p95_latency").label


def test_links_are_url_encoded() -> None:
    """Route templates are percent-encoded in the links the service builds."""
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    window = TimeWindow(start=now - timedelta(hours=1), end=now)
    event = TelemetryEvent(
        timestamp=now - timedelta(minutes=5),
        severity="INFO",
        event="http.request",
        message="request",
        request_id=None,
        trace_id=None,
        span_id=None,
        revision=None,
        attributes={
            "method": "GET",
            "route": "/v2/teams/{team}/outlook",
            "status": 500,
            "duration_ms": 5,
            "error_code": "boom",
        },
    )
    model = make_service(ListSource([event]), now).build(window)

    row = model.slowest_routes[0]
    assert "%7Bteam%7D" in row.link
    assert "hours=1" in row.link
    assert by_key(model.headlines, "error_rate").link.endswith("status=5xx")
    assert "event=app.crash" in by_key(model.headlines, "crashes").link


def test_an_unrouted_request_row_links_without_a_route_filter() -> None:
    """A request with no route is grouped as <unknown>: a label, not a filter."""
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    window = TimeWindow(start=now - timedelta(hours=1), end=now)
    events = [request_line(now - timedelta(minutes=5), 200, route=None)]
    model = make_service(ListSource(events), now).build(window)

    row = model.slowest_routes[0]
    assert row.route == "<unknown>"
    assert "route=" not in row.link
    assert row.link.startswith("/requests?")


def test_window_end_rounds_up_to_the_chart_interval() -> None:
    """Two loads inside one interval share a window; a boundary moment stays put."""
    base = datetime(2026, 10, 8, 12, 7, 3, tzinfo=UTC)
    first = window_for_hours(24, base)
    assert first.end == datetime(2026, 10, 8, 12, 15, tzinfo=UTC)
    assert window_for_hours(24, base + timedelta(seconds=5)) == first
    assert window_for_hours(24, base + timedelta(minutes=15)) != first

    boundary = datetime(2026, 10, 8, 12, 15, tzinfo=UTC)
    assert window_for_hours(24, boundary).end == boundary


def test_twenty_four_hour_window_counts_a_recent_failure() -> None:
    """A 500 ten minutes before now is counted in the 24 h window."""
    now = datetime(2026, 10, 8, 17, 59, tzinfo=UTC)
    model = make_service(
        ListSource([request_line(now - timedelta(minutes=10), 500)]), now
    ).build_for_hours(24)

    assert by_key(model.headlines, "requests").value == 1
    assert by_key(model.headlines, "error_rate").value == 1.0


def test_resolve_hours_uses_the_settings_default() -> None:
    """A missing hours resolves to the setting, and unknown ones are rejected."""
    service = make_service(ListSource([]))
    assert service.resolve_hours(None) == Config().default_window_hours
    assert service.resolve_hours(6) == 6
    with pytest.raises(ValueError):
        service.resolve_hours(5)
