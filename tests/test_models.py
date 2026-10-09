"""Tests for domain models."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.models import Severity, Span, TelemetryEvent, TimeWindow, Trace


def test_severity_values() -> None:
    """Common severity levels should be valid."""
    valid = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    for val in valid:
        assert getattr(Severity, val) == val


def test_telemetry_event_fields() -> None:
    """TelemetryEvent should have all required fields."""
    event = TelemetryEvent(
        timestamp=datetime(2026, 10, 8, 18, 32, 27, 123000, tzinfo=UTC),
        severity="INFO",
        event="http.request",
        message="Sample event",
        request_id="req_123",
        trace_id="trace_abc",
        span_id=None,
        revision="rev_001",
        attributes={},
    )
    assert event is not None


def test_time_window_validation() -> None:
    """TimeWindow should reject invalid start/end order."""
    end = datetime(2026, 10, 8, 18, 0, 0, tzinfo=UTC)
    start = end + timedelta(hours=1)
    with pytest.raises(ValueError):
        TimeWindow(start=start, end=end)


def test_time_window_valid() -> None:
    """TimeWindow should accept valid start < end."""
    end = datetime(2026, 10, 8, 18, 0, 0, tzinfo=UTC)
    start = end - timedelta(hours=1)
    window = TimeWindow(start=start, end=end)
    assert window.start < window.end


def test_time_window_last_hours() -> None:
    """TimeWindow.last_hours should return a window of correct duration."""
    now = datetime(2026, 10, 8, 18, 0, 0, tzinfo=UTC)
    hours = 24
    window = TimeWindow.last_hours(hours, now)
    assert window.start == now - timedelta(hours=hours)
    assert window.end == now


def test_span_has_required_fields() -> None:
    """Span should have name, duration_ms, and status."""
    span = Span(
        name="http.request",
        start=datetime(2026, 10, 8, 18, 0, 0, tzinfo=UTC),
        end=datetime(2026, 10, 8, 18, 0, 0, 250000, tzinfo=UTC),
        span_id="span_001",
        parent_id=None,
    )
    assert span.name == "http.request"
    assert span.duration_ms == 250


def test_trace_has_spans() -> None:
    """Trace should contain a list of spans."""
    trace = Trace(trace_id="trace_001", spans=())
    assert len(trace.spans) == 0
    assert trace.trace_id == "trace_001"
