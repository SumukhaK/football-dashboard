"""Tests for the overview's headlines, chart series and the links it builds."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.config import Config
from app.domain.models import TelemetryEvent, TimeWindow
from app.domain.overview import GoodDirection, HeadlineNumber
from app.services.overview import window_for_hours

from .overview_helpers import (
    HEADLINE_ORDER,
    NOW,
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


@pytest.mark.parametrize(
    ("statuses", "expected_rate"),
    [([307], 0.0), ([307, 500], 0.5), ([200, 500], 0.5)],
)
def test_headline_sparklines_include_all_request_statuses(
    statuses: list[int], expected_rate: float
) -> None:
    """A redirect is a request: the sparklines count it as the headline does."""
    events = [request_line(NOW - timedelta(minutes=5), status) for status in statuses]
    model = make_service(ListSource(events), NOW).build(TimeWindow.last_hours(1, NOW))
    counts = model.sparkline("requests")
    rates = model.sparkline("error_rate")
    assert counts is not None and rates is not None

    assert sum(value or 0.0 for value in counts.values) == len(events)
    assert by_key(model.headlines, "requests").value == len(events)
    assert [value for value in rates.values if value is not None] == [expected_rate]
    assert by_key(model.headlines, "error_rate").value == expected_rate


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
    latency = by_key(model.headlines, "p95_latency")
    assert latency.label == "p95 latency"
    assert latency.unit == "ms"


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


def test_change_tone_follows_the_good_direction() -> None:
    """A move the right way reads ok, the other way fail, a tie neutral."""
    rising = HeadlineNumber(
        "requests", "Requests", 10.0, 8.0, good_direction=GoodDirection.UP
    )
    falling = HeadlineNumber(
        "requests", "Requests", 8.0, 10.0, good_direction=GoodDirection.UP
    )
    cheaper = HeadlineNumber(
        "error_rate",
        "Error rate",
        0.01,
        0.02,
        is_percent=True,
        good_direction=GoodDirection.DOWN,
    )
    dearer = HeadlineNumber(
        "error_rate",
        "Error rate",
        0.02,
        0.01,
        is_percent=True,
        good_direction=GoodDirection.DOWN,
    )
    flat = HeadlineNumber(
        "p95_latency", "p95 latency", 5.0, 5.0, good_direction=GoodDirection.DOWN
    )

    assert rising.change_tone == "ok"
    assert falling.change_tone == "fail"
    assert cheaper.change_tone == "ok"
    assert dearer.change_tone == "fail"
    assert flat.change_tone == "neutral"


def test_headline_good_directions_match_the_guide() -> None:
    """Lower is better for errors, latency and crashes; requests go the other way."""
    model = make_service(ListSource([]), NOW).build(TimeWindow.last_hours(24, NOW))

    directions = {headline.key: headline.good_direction for headline in model.headlines}
    assert directions["requests"] is GoodDirection.UP
    assert directions["error_rate"] is GoodDirection.DOWN
    assert directions["p95_latency"] is GoodDirection.DOWN
    assert directions["crashes"] is GoodDirection.DOWN


def test_no_earlier_data_when_the_previous_window_is_empty() -> None:
    """An empty previous window leaves every card without a change to show."""
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    window = TimeWindow(start=now - timedelta(hours=1), end=now)
    model = make_service(
        ListSource([request_line(now - timedelta(minutes=5), 200)]), now
    ).build(window)

    assert by_key(model.headlines, "requests").value == 1
    for key in ("requests", "error_rate", "p95_latency", "crashes"):
        assert by_key(model.headlines, key).change is None
        assert by_key(model.headlines, key).change_tone == "neutral"


def test_error_rate_highlights_at_exactly_one_percent() -> None:
    """A route failing at exactly one percent wears the fail pill."""
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    window = TimeWindow(start=now - timedelta(hours=1), end=now)
    events = [request_line(now - timedelta(minutes=5), 500)]
    events += [request_line(now - timedelta(minutes=5), 200) for _ in range(99)]
    model = make_service(ListSource(events), now).build(window)

    row = model.slowest_routes[0]
    assert row.error_rate == 0.01
    assert row.highlight_error_rate is True


def test_error_rate_below_one_percent_is_not_highlighted() -> None:
    """Just under one percent is not worth a red pill."""
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    window = TimeWindow(start=now - timedelta(hours=1), end=now)
    events = [request_line(now - timedelta(minutes=5), 500)]
    events += [request_line(now - timedelta(minutes=5), 200) for _ in range(100)]
    model = make_service(ListSource(events), now).build(window)

    row = model.slowest_routes[0]
    assert row.error_rate is not None
    assert row.error_rate < 0.01
    assert row.highlight_error_rate is False


def test_slowest_route_duration_is_formatted() -> None:
    """A route's p95 is handed to the template as a formatted duration."""
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    window = TimeWindow(start=now - timedelta(hours=1), end=now)
    model = make_service(
        ListSource([request_line(now - timedelta(minutes=5), 200, duration_ms=2500)]),
        now,
    ).build(window)

    row = model.slowest_routes[0]
    assert row.p95_ms == 2500
    assert row.p95_label == "2.5 s"


def test_slowest_route_bars_are_relative_on_a_log_scale() -> None:
    """The inline p95 bar fills the widest row and shrinks on a log scale."""
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    window = TimeWindow(start=now - timedelta(hours=1), end=now)
    events = [
        request_line(now - timedelta(minutes=5), 200, route="/slow", duration_ms=10000),
        request_line(now - timedelta(minutes=5), 200, route="/fast", duration_ms=10),
    ]
    model = make_service(ListSource(events), now).build(window)

    bars = {row.route: row.p95_bar_pct for row in model.slowest_routes}
    assert bars["/slow"] == 100.0
    assert bars["/fast"] == 25.0


def test_a_route_with_no_measurable_latency_gets_no_bar() -> None:
    """A p95 that is missing or under a millisecond draws no bar at all."""
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    window = TimeWindow(start=now - timedelta(hours=1), end=now)
    model = make_service(
        ListSource([request_line(now - timedelta(minutes=5), 200, duration_ms=0)]),
        now,
    ).build(window)

    assert model.slowest_routes[0].p95_bar_pct == 0.0
