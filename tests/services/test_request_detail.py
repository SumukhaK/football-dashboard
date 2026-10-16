"""Tests for the request detail: the timeline, the trace and its waterfall."""

from __future__ import annotations

from datetime import timedelta

from app.config import Config
from app.domain.models import MAX_QUERY_LIMIT, EventQuery, Span, Trace

from .requests_helpers import (
    NOW,
    RETRY_TRACE,
    WINDOW,
    FakeSource,
    fixture_service,
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
