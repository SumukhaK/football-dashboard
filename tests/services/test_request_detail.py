"""Tests for the request detail: the timeline, the trace and its waterfall."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from app.config import Config
from app.domain.models import MAX_QUERY_LIMIT, EventQuery, Span, Trace

from .requests_helpers import (
    NOW,
    RETRY_TRACE,
    WINDOW,
    FakeSource,
    event_line,
    fixture_service,
    make_filters,
    make_service,
    request_line,
)


def test_detail_returns_none_for_an_unknown_request() -> None:
    """An id with no lines has no detail page."""
    assert make_service(FakeSource([])).detail("req-unknownx") is None


def test_detail_shows_the_timeline_and_the_retry_markers() -> None:
    """The known fixture chat has an ordered timeline and two retry markers."""
    service, source = fixture_service()
    requests = source.events(
        EventQuery(window=WINDOW, events=("http.request",), limit=MAX_QUERY_LIMIT)
    )
    target = next(event for event in requests if event.trace_id == RETRY_TRACE)

    detail = service.detail(target.request_id or "")
    assert detail is not None
    assert detail.route == "/v2/assistant/chat"
    assert detail.status == 200
    assert detail.trace_id == RETRY_TRACE
    assert detail.trace_url is None

    stamps = [entry.timestamp for entry in detail.timeline]
    assert stamps == sorted(stamps)
    assert any(entry.event == "http.request" for entry in detail.timeline)

    markers = [marker for row in detail.waterfall for marker in row.markers]
    assert [marker.name for marker in markers] == ["retry", "retry"]


def test_detail_links_to_the_cloud_console_when_reading_from_gcp() -> None:
    """Only a Google Cloud source offers the console link to the trace."""
    span = Span(
        span_id="s1",
        parent_id=None,
        name="GET /v2/predict",
        start=NOW - timedelta(seconds=1),
        end=NOW,
    )
    event = request_line(1, request_id="req-aaaaaaaa", trace_id="t-1")
    settings = Config(source="gcp", gcp_project_id="demo-project")
    detail = make_service(
        FakeSource([event], [Trace("t-1", (span,))]), settings
    ).detail("req-aaaaaaaa")
    assert detail is not None
    assert detail.trace_url == (
        "https://console.cloud.google.com/traces/list" "?project=demo-project&tid=t-1"
    )
    assert len(detail.waterfall) == 1


def test_panel_is_none_for_an_unknown_request() -> None:
    """An id with no lines has no panel either."""
    assert make_service(FakeSource([])).panel("req-unknownx", make_filters()) is None


def test_panel_formats_the_age_the_duration_and_the_way_back() -> None:
    """The panel is rendered-ready: its age, its duration and its close link."""
    service = make_service(
        FakeSource([request_line(9 * 60, status_code=200, request_id="req-aaaaaaaa")])
    )
    panel = service.panel("req-aaaaaaaa", make_filters(route="/v2/predict"))
    assert panel is not None
    assert panel.relative_time == "9 h ago"
    assert panel.duration_label == "12 ms"
    assert panel.summary is None
    assert panel.close_link.startswith("/requests?")
    assert "route=%2Fv2%2Fpredict" in panel.close_link
    assert "open=" not in panel.close_link


def test_panel_summarises_a_crash_by_the_last_line_of_its_traceback() -> None:
    """A crashed request is named by the exception its traceback ends on."""
    crash = replace(
        event_line(5, "app.crash", "req-aaaaaaaa"),
        message=(
            "Traceback (most recent call last):\n"
            '  File "/app/outlook.py", line 112\n'
            "ZeroDivisionError: division by zero"
        ),
    )
    service = make_service(
        FakeSource([request_line(6, request_id="req-aaaaaaaa"), crash])
    )
    panel = service.panel("req-aaaaaaaa", make_filters())
    assert panel is not None
    assert panel.summary == "ZeroDivisionError: division by zero"
    assert panel.summary_tone == "fail"


def test_panel_summarises_a_server_error_by_its_code() -> None:
    """A 5xx with a code says the code; a 4xx is a warning, not a failure."""
    failed = replace(
        request_line(5, status_code=503, request_id="req-aaaaaaaa"),
        attributes={
            "method": "GET",
            "route": "/v2/predict",
            "status": 503,
            "duration_ms": 12,
            "error_code": "database_unreachable",
        },
    )
    panel = make_service(FakeSource([failed])).panel("req-aaaaaaaa", make_filters())
    assert panel is not None
    assert panel.summary == "database_unreachable"
    assert panel.summary_tone == "fail"
