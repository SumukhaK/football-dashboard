"""Tests for domain models."""

from datetime import UTC, datetime, timedelta
from typing import Any

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


def test_from_log_line_parses_a_fixture_line() -> None:
    """A committed sample line becomes a typed event with a UTC timestamp."""
    import json
    from pathlib import Path

    fixtures = Path(__file__).resolve().parents[1] / "fixtures" / "events.jsonl"
    lines = [json.loads(text) for text in fixtures.read_text().splitlines()]
    line = next(line for line in lines if line["request_id"] is not None)
    event = TelemetryEvent.from_log_line(line)
    assert event.timestamp.tzinfo is not None
    assert event.timestamp.utcoffset() == timedelta(0)
    assert event.trace_id == line["trace_id"]
    assert event.span_id == line["logging.googleapis.com/spanId"]


def test_from_log_line_without_a_trace() -> None:
    """A line outside a request has no trace or span."""
    line: dict[str, Any] = {
        "timestamp": "2026-10-08T06:00:01.250Z",
        "severity": "INFO",
        "message": "Component fixtures loaded: ok",
        "event": "component.load",
        "request_id": None,
        "logging.googleapis.com/trace": None,
        "logging.googleapis.com/spanId": None,
        "trace_id": None,
        "revision": "football-api-00042-wum",
        "attributes": {},
    }
    event = TelemetryEvent.from_log_line(line)
    assert event.timestamp == datetime(2026, 10, 8, 6, 0, 1, 250000, tzinfo=UTC)
    assert event.trace_id is None and event.span_id is None
