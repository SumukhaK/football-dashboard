"""Tests for the trace waterfall geometry."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.domain.models import Span, SpanEvent, Trace
from app.services.waterfall import build_waterfall

START = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def _span(
    span_id: str,
    parent_id: str | None,
    name: str,
    offset_ms: int,
    duration_ms: int,
    events: tuple[SpanEvent, ...] = (),
    attributes: dict[str, Any] | None = None,
) -> Span:
    """A span starting offset_ms after START, with an optional attribute map."""
    start = START + timedelta(milliseconds=offset_ms)
    return Span(
        span_id=span_id,
        parent_id=parent_id,
        name=name,
        start=start,
        end=start + timedelta(milliseconds=duration_ms),
        attributes=attributes or {},
        events=events,
    )


def test_depth_offsets_and_widths_for_a_three_level_trace() -> None:
    """Nesting becomes depth, and times become offsets and percentages."""
    trace = Trace(
        trace_id="t1",
        spans=(
            _span("root", None, "POST /x", 0, 1000),
            _span("child", "root", "assistant.retrieve", 0, 600),
            _span("grand", "child", "assistant.embed", 100, 400),
        ),
    )
    rows = build_waterfall(trace)
    assert [row.name for row in rows] == [
        "POST /x",
        "assistant.retrieve",
        "assistant.embed",
    ]
    assert [row.depth for row in rows] == [0, 1, 2]
    assert [row.offset_ms for row in rows] == [0, 0, 100]
    assert [row.width_pct for row in rows] == [100.0, 60.0, 40.0]
    assert rows[2].left_pct == 10.0
    assert [row.indent_px for row in rows] == [0, 12, 24]


def test_spans_out_of_order_still_nest() -> None:
    """A shuffled span list is ordered by the parent links, not the input."""
    trace = Trace(
        trace_id="t2",
        spans=(
            _span("grand", "child", "assistant.embed", 100, 400),
            _span("root", None, "POST /x", 0, 1000),
            _span("child", "root", "assistant.retrieve", 0, 600),
        ),
    )
    rows = build_waterfall(trace)
    assert [row.name for row in rows] == [
        "POST /x",
        "assistant.retrieve",
        "assistant.embed",
    ]


def test_span_events_become_markers_at_the_right_offset() -> None:
    """A retry marker sits where the span event happened."""
    retry = SpanEvent(
        name="retry",
        timestamp=START + timedelta(milliseconds=600),
        attributes={"attempt": 1, "wait_ms": 500, "cause": "timeout"},
    )
    trace = Trace(
        trace_id="t3",
        spans=(
            _span("root", None, "POST /x", 0, 1000),
            _span("call", "root", "dependency.ollama_chat", 0, 600, (retry,)),
        ),
    )
    call = build_waterfall(trace)[1]
    assert len(call.markers) == 1
    marker = call.markers[0]
    assert marker.name == "retry"
    assert marker.offset_ms == 600
    assert marker.left_pct == 60.0
    assert "cause=timeout" in marker.detail
    assert "attempt=1" in marker.detail


def test_single_span_trace_fills_the_axis() -> None:
    """One span with no children is one full-width row at depth zero."""
    rows = build_waterfall(
        Trace(
            trace_id="t4",
            spans=(
                _span(
                    "only",
                    None,
                    "GET /health",
                    0,
                    50,
                    attributes={"http.response.status_code": 200},
                ),
            ),
        )
    )
    assert len(rows) == 1
    assert rows[0].depth == 0
    assert rows[0].offset_ms == 0
    assert rows[0].width_pct == 100.0
    assert rows[0].title == "http.response.status_code=200"


def test_empty_trace_returns_no_rows() -> None:
    """A trace with no spans produces nothing to draw."""
    assert build_waterfall(Trace(trace_id="t5", spans=())) == []
