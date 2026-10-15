"""Tests for the requests service, its filters and the request detail."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.config import Config
from app.contract import load_contract
from app.domain.models import (
    MAX_QUERY_LIMIT,
    ErrorGroup,
    EventQuery,
    PlatformEvent,
    Span,
    TelemetryEvent,
    TimeWindow,
    Trace,
)
from app.domain.requests import RequestFilters, StatusRange
from app.services.requests import RequestsService, parse_status
from app.services.windows import window_for_hours
from app.sources.base import TelemetrySource
from app.sources.filtering import select_events
from app.sources.fixture_source import FixtureSource

NOW = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)
WINDOW = window_for_hours(24, NOW)
RETRY_TRACE = "923a736994e3bf911a61dbe22e44158b"


def _request(
    minutes_ago: int,
    status_code: int = 200,
    route: str = "/v2/predict",
    request_id: str = "req-00000001",
    trace_id: str | None = None,
) -> TelemetryEvent:
    """An http.request line, minutes_ago before NOW."""
    return TelemetryEvent(
        timestamp=NOW - timedelta(minutes=minutes_ago),
        severity="INFO",
        event="http.request",
        message="request finished",
        request_id=request_id,
        trace_id=trace_id,
        span_id=None,
        revision="rev-0001",
        attributes={
            "method": "GET",
            "route": route,
            "status": status_code,
            "duration_ms": 12,
            "error_code": None,
        },
    )


def _event(
    minutes_ago: int,
    name: str,
    request_id: str | None,
    attributes: dict[str, Any] | None = None,
) -> TelemetryEvent:
    """Another catalogued line of a request."""
    return TelemetryEvent(
        timestamp=NOW - timedelta(minutes=minutes_ago),
        severity="WARNING",
        event=name,
        message=name,
        request_id=request_id,
        trace_id=None,
        span_id=None,
        revision=None,
        attributes=attributes or {},
    )


class FakeSource:
    """An in-test source over a fixed event and trace list."""

    def __init__(
        self,
        events: Sequence[TelemetryEvent],
        traces: Sequence[Trace] = (),
    ) -> None:
        self._events = list(events)
        self._traces = {trace.trace_id: trace for trace in traces}

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Return the stored events that match the query, newest first."""
        return select_events(self._events, query)

    def trace(self, trace_id: str) -> Trace | None:
        """Return one of the stored traces, or None."""
        return self._traces.get(trace_id)

    def error_groups(self, window: TimeWindow) -> list[ErrorGroup]:
        """There are no error groups in the fake."""
        return []

    def platform_events(self, window: TimeWindow) -> list[PlatformEvent]:
        """There are no platform events in the fake."""
        return []


class FloodSource:
    """A source that always returns a full page, to exercise the query cap."""

    def __init__(self, event: TelemetryEvent) -> None:
        self._event = event

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Return exactly the query's limit."""
        return [self._event] * query.limit

    def trace(self, trace_id: str) -> Trace | None:
        """There are no traces in the fake."""
        return None

    def error_groups(self, window: TimeWindow) -> list[ErrorGroup]:
        """There are no error groups in the fake."""
        return []

    def platform_events(self, window: TimeWindow) -> list[PlatformEvent]:
        """There are no platform events in the fake."""
        return []


def _service(
    source: TelemetrySource, settings: Config | None = None
) -> RequestsService:
    """A requests service over the given source with a fixed clock."""
    return RequestsService(source, lambda: NOW, settings or Config())


def _filters(**overrides: Any) -> RequestFilters:
    """The default filters, with any field overridden."""
    return RequestFilters(window=WINDOW, hours=24, **overrides)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2xx", StatusRange(200, 300, "2xx")),
        ("4xx", StatusRange(400, 500, "4xx")),
        ("5xx", StatusRange(500, 600, "5xx")),
        ("503", StatusRange(503, 504, "503")),
        (None, None),
        ("", None),
    ],
)
def test_status_parsing_accepts_classes_and_codes(
    value: str | None, expected: StatusRange | None
) -> None:
    """A class, an exact code, or nothing at all parses; anything else raises."""
    assert parse_status(value) == expected


@pytest.mark.parametrize("value", ["abc", "6xx", "99", "600", "5xx "])
def test_status_parsing_rejects_other_values(value: str) -> None:
    """Anything that is not a known class or a real status code raises."""
    with pytest.raises(ValueError):
        parse_status(value)


def test_route_filter() -> None:
    """Only the requests to the named route survive."""
    events = [_request(10), _request(20, route="/v2/fixtures")]
    page = _service(FakeSource(events)).search(_filters(route="/v2/fixtures"))
    assert [row.route for row in page.rows] == ["/v2/fixtures"]


def test_status_class_filter() -> None:
    """A class keeps only its own codes, an exact code only that one."""
    events = [_request(1, 200), _request(2, 404), _request(3, 503)]
    service = _service(FakeSource(events))
    assert [
        r.status for r in service.search(_filters(status=parse_status("5xx"))).rows
    ] == [503]
    assert [
        r.status for r in service.search(_filters(status=parse_status("4xx"))).rows
    ] == [404]
    assert [
        r.status for r in service.search(_filters(status=parse_status("503"))).rows
    ] == [503]


def test_rows_are_newest_first_and_link_to_the_detail() -> None:
    """Rows come newest first and each links to its own detail page."""
    events = [
        _request(5, request_id="req-aaaaaaaa"),
        _request(30, request_id="req-bbbbbbbb"),
    ]
    rows = _service(FakeSource(events)).search(_filters()).rows
    assert [row.request_id for row in rows] == ["req-aaaaaaaa", "req-bbbbbbbb"]
    assert rows[0].link == "/requests/req-aaaaaaaa"


def test_event_filter_keeps_only_matching_requests() -> None:
    """The event filter reads the event's lines and keeps their requests."""
    events = [
        _request(10, request_id="req-aaaaaaaa"),
        _request(20, request_id="req-bbbbbbbb"),
        _event(15, "retry", "req-aaaaaaaa", {"dependency": "ollama_chat"}),
    ]
    page = _service(FakeSource(events)).search(_filters(event="retry"))
    assert [row.request_id for row in page.rows] == ["req-aaaaaaaa"]


def test_degraded_filter_also_narrows_by_component() -> None:
    """The Overview's tile link narrows the degradations to one component."""
    events = [
        _request(10, request_id="req-aaaaaaaa"),
        _request(11, request_id="req-bbbbbbbb"),
        _event(5, "component.degraded", "req-aaaaaaaa", {"component": "assistant"}),
        _event(6, "component.degraded", "req-bbbbbbbb", {"component": "fixtures"}),
    ]
    page = _service(FakeSource(events)).search(
        _filters(event="component.degraded", component="assistant")
    )
    assert [row.request_id for row in page.rows] == ["req-aaaaaaaa"]


def test_pagination_cursor_returns_the_next_page_without_overlap() -> None:
    """A full page carries a cursor; the next page continues from it."""
    events = [
        _request(minute, request_id=f"req-{minute:08d}") for minute in range(1, 151)
    ]
    service = _service(FakeSource(events))
    first = service.search(_filters())
    assert len(first.rows) == 100
    assert first.next_link is not None and "before=" in first.next_link

    second = service.search(_filters(before=first.rows[-1].timestamp))
    assert len(second.rows) == 50
    assert second.next_link is None
    assert second.rows[0].timestamp < first.rows[-1].timestamp


def test_a_short_page_has_no_cursor() -> None:
    """Fewer rows than a page means there is nothing more to load."""
    page = _service(FakeSource([_request(1), _request(2)])).search(_filters())
    assert page.next_link is None
    assert page.truncated is False


def test_hitting_the_query_cap_flags_truncation() -> None:
    """A full read sets truncated, so the page can say to narrow the filter."""
    service = _service(FloodSource(_request(1)))
    page = service.search(_filters())
    assert page.truncated is True


def test_detail_returns_none_for_an_unknown_request() -> None:
    """An id with no lines has no detail page."""
    assert _service(FakeSource([])).detail("req-unknownx") is None


def _fixture_service() -> tuple[RequestsService, FixtureSource]:
    """A requests service over the committed fixtures with a fixed clock."""
    source = FixtureSource(Config().fixture_dir, load_contract(), now=NOW)
    return _service(source), source


def test_detail_shows_the_timeline_and_the_retry_markers() -> None:
    """The known fixture chat has an ordered timeline and two retry markers."""
    service, source = _fixture_service()
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
    event = _request(1, request_id="req-aaaaaaaa", trace_id="t-1")
    settings = Config(source="gcp", gcp_project_id="demo-project")
    detail = _service(FakeSource([event], [Trace("t-1", (span,))]), settings).detail(
        "req-aaaaaaaa"
    )
    assert detail is not None
    assert detail.trace_url == (
        "https://console.cloud.google.com/traces/list" "?project=demo-project&tid=t-1"
    )
    assert len(detail.waterfall) == 1


def test_resolve_hours_defaults_and_rejects() -> None:
    """The requests page offers the same windows as the Overview."""
    service = _service(FakeSource([]))
    assert service.resolve_hours(None) == 24
    assert service.resolve_hours(168) == 168
    with pytest.raises(ValueError):
        service.resolve_hours(5)
