"""Tests for the pure statistics helpers used by the overview page."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.domain.models import TelemetryEvent, TimeWindow
from app.services.stats import bucket_by_interval, percentile, rate


def _event(moment: datetime) -> TelemetryEvent:
    """Build a minimal telemetry event at the given moment."""
    return TelemetryEvent(
        timestamp=moment,
        severity="INFO",
        event="http.request",
        message="request",
        request_id=None,
        trace_id=None,
        span_id=None,
        revision=None,
        attributes={},
    )


def test_percentile_uses_nearest_rank() -> None:
    """Nearest-rank percentile picks the value at ceil(q * n)."""
    values = [float(n) for n in range(1, 11)]  # 1..10
    assert percentile(values, 0.5) == 5.0
    assert percentile(values, 0.95) == 10.0
    assert percentile(values, 1.0) == 10.0
    assert percentile(values, 0.0) == 1.0


def test_percentile_left_of_lowest_rank() -> None:
    """A quantile that rounds up to the first rank is the smallest value."""
    assert percentile([3.0, 1.0, 2.0], 0.1) == 1.0


def test_percentile_single_value() -> None:
    """A single value is returned whatever the quantile."""
    assert percentile([7.0], 0.95) == 7.0


def test_percentile_empty_list_is_none() -> None:
    """There is no percentile of nothing."""
    assert percentile([], 0.5) is None


def test_rate_returns_none_when_denominator_is_zero() -> None:
    """Dividing by zero is reported as no rate, never an error."""
    assert rate(0, 0) is None


def test_rate_is_the_fraction() -> None:
    """A normal rate is numerator over denominator."""
    assert rate(3, 4) == 0.75


def _window(hours: int = 1) -> TimeWindow:
    """A one-hour window starting at midnight UTC on 2026-10-08."""
    start = datetime(2026, 10, 8, 0, 0, tzinfo=UTC)
    return TimeWindow(start=start, end=start + timedelta(hours=hours))


def test_bucket_by_interval_places_events_at_edges() -> None:
    """The window start is in the first bucket; the window end is excluded."""
    window = _window()
    start = window.start
    events = [
        _event(start),
        _event(start + timedelta(minutes=29)),
        _event(start + timedelta(minutes=30)),
        _event(start + timedelta(minutes=59)),
        _event(window.end),
    ]
    buckets = bucket_by_interval(events, window, timedelta(minutes=30))

    assert len(buckets) == 2
    assert buckets[0].start == start
    assert len(buckets[0].events) == 2
    assert buckets[1].start == start + timedelta(minutes=30)
    assert len(buckets[1].events) == 2


def test_bucket_by_interval_ignores_events_outside_window() -> None:
    """Events before the window and at the end are dropped."""
    window = _window()
    before = _event(window.start - timedelta(minutes=1))
    inside = _event(window.start + timedelta(minutes=5))
    buckets = bucket_by_interval([before, inside], window, timedelta(minutes=30))
    assert sum(len(bucket.events) for bucket in buckets) == 1
