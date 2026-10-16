"""Tests for the requests service: its filters, the search and its paging."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import parse_qs

import pytest

from app.domain.models import MAX_QUERY_LIMIT
from app.domain.requests import RequestFilters, StatusRange
from app.services.requests import (
    MAX_EVENT_REQUESTS,
    PAGE_SIZE,
    clean_text,
    parse_route,
    parse_status,
)
from app.services.windows import window_for_hours
from services.request_fakes import (
    NOW,
    FakeSource,
    FloodSource,
    SpySource,
    event_line,
    make_filters,
    make_service,
    request_line,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2xx", StatusRange(200, 300, "2xx")),
        ("4xx", StatusRange(400, 500, "4xx")),
        ("5xx", StatusRange(500, 600, "5xx")),
        ("503", StatusRange(503, 504, "503")),
        (" 503 ", StatusRange(503, 504, "503")),
        (None, None),
        ("", None),
        ("  ", None),
    ],
)
def test_status_parsing_accepts_classes_and_codes(
    value: str | None, expected: StatusRange | None
) -> None:
    """A class, an exact code, or nothing at all parses; anything else raises."""
    assert parse_status(value) == expected


@pytest.mark.parametrize("value", ["abc", "6xx", "99", "600", "5 x", "5xx5"])
def test_status_parsing_rejects_other_values(value: str) -> None:
    """Anything that is not a known class or a real status code raises."""
    with pytest.raises(ValueError):
        parse_status(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("\t", None),
        ("/v2/predict", "/v2/predict"),
        ("  /v2/predict  ", "/v2/predict"),
    ],
)
def test_clean_text_normalises_blank_filters(
    value: str | None, expected: str | None
) -> None:
    """A filter box the form submits empty means no filter at all."""
    assert clean_text(value) == expected


def test_route_filter() -> None:
    """Only the requests to the named route survive."""
    events = [request_line(10), request_line(20, route="/v2/fixtures")]
    page = make_service(FakeSource(events)).search(make_filters(route="/v2/fixtures"))
    assert [row.route for row in page.rows] == ["/v2/fixtures"]


def test_status_class_filter() -> None:
    """A class keeps only its own codes, an exact code only that one."""
    events = [request_line(1, 200), request_line(2, 404), request_line(3, 503)]
    service = make_service(FakeSource(events))
    assert [
        r.status for r in service.search(make_filters(status=parse_status("5xx"))).rows
    ] == [503]
    assert [
        r.status for r in service.search(make_filters(status=parse_status("4xx"))).rows
    ] == [404]
    assert [
        r.status for r in service.search(make_filters(status=parse_status("503"))).rows
    ] == [503]


def test_rows_are_newest_first_and_link_to_the_detail() -> None:
    """Rows come newest first and each links to its own detail page."""
    events = [
        request_line(5, request_id="req-aaaaaaaa"),
        request_line(30, request_id="req-bbbbbbbb"),
    ]
    rows = make_service(FakeSource(events)).search(make_filters()).rows
    assert [row.request_id for row in rows] == ["req-aaaaaaaa", "req-bbbbbbbb"]
    assert rows[0].link == "/requests/req-aaaaaaaa"


def test_event_filter_keeps_only_matching_requests() -> None:
    """The event filter reads the event's lines and keeps their requests."""
    events = [
        request_line(10, request_id="req-aaaaaaaa"),
        request_line(20, request_id="req-bbbbbbbb"),
        event_line(15, "retry", "req-aaaaaaaa", {"dependency": "ollama_chat"}),
    ]
    page = make_service(FakeSource(events)).search(make_filters(event="retry"))
    assert [row.request_id for row in page.rows] == ["req-aaaaaaaa"]


def test_degraded_filter_also_narrows_by_component() -> None:
    """The Overview's tile link narrows the degradations to one component."""
    events = [
        request_line(10, request_id="req-aaaaaaaa"),
        request_line(11, request_id="req-bbbbbbbb"),
        event_line(5, "component.degraded", "req-aaaaaaaa", {"component": "assistant"}),
        event_line(6, "component.degraded", "req-bbbbbbbb", {"component": "fixtures"}),
    ]
    page = make_service(FakeSource(events)).search(
        make_filters(event="component.degraded", component="assistant")
    )
    assert [row.request_id for row in page.rows] == ["req-aaaaaaaa"]


def test_blank_filter_boxes_behave_like_no_filters() -> None:
    """The form submits every box, so empty ones must not empty the list."""
    events = [request_line(10, request_id="req-aaaaaaaa")]
    service = make_service(FakeSource(events))
    blank = service.filters(None, "", "  ", "", "", None)
    assert [row.request_id for row in service.search(blank).rows] == ["req-aaaaaaaa"]


def test_an_event_filter_finds_a_request_behind_a_full_read() -> None:
    """A rare event 100 hours back is found behind thousands of newer requests."""
    recent = [
        request_line(minute, request_id=f"req-{minute:08d}")
        for minute in range(1, MAX_QUERY_LIMIT + 1)
    ]
    crashed = request_line(6000, request_id="req-crashed0")
    crash = event_line(6000, "app.crash", "req-crashed0")
    service = make_service(FakeSource([*recent, crashed, crash]))
    page = service.search(
        RequestFilters(window=window_for_hours(168, NOW), hours=168, event="app.crash")
    )
    assert [row.request_id for row in page.rows] == ["req-crashed0"]


def test_an_event_filter_reads_the_requests_by_id() -> None:
    """The request read is narrowed by request id and asks for one extra row."""
    events = [
        request_line(10, request_id="req-aaaaaaaa"),
        event_line(15, "retry", "req-aaaaaaaa"),
    ]
    source = SpySource(events)
    make_service(source).search(make_filters(event="retry"))
    assert [query.limit for query in source.queries] == [MAX_QUERY_LIMIT, PAGE_SIZE + 1]
    assert source.queries[-1].request_ids == ("req-aaaaaaaa",)


def test_an_unfiltered_search_reads_one_extra_row() -> None:
    """No event filter means one read of a page plus one, never the cap."""
    events = [
        request_line(minute, request_id=f"req-{minute:08d}") for minute in range(1, 151)
    ]
    source = SpySource(events)
    make_service(source).search(make_filters())
    assert len(source.queries) == 1
    assert source.queries[0].limit == PAGE_SIZE + 1
    assert source.queries[0].request_ids == ()


def test_an_event_filter_with_no_matches_lists_nothing() -> None:
    """An event that never occurs cannot match a request, so nothing is read."""
    source = SpySource([request_line(10, request_id="req-aaaaaaaa")])
    page = make_service(source).search(make_filters(event="app.crash"))
    assert page.rows == ()
    assert page.next_link is None
    assert [query.events for query in source.queries] == [("app.crash",)]


def test_a_component_filter_with_no_matches_lists_nothing() -> None:
    """A degradation of another component cannot match either."""
    events = [
        request_line(10, request_id="req-aaaaaaaa"),
        event_line(5, "component.degraded", "req-aaaaaaaa", {"component": "fixtures"}),
    ]
    source = SpySource(events)
    page = make_service(source).search(
        make_filters(event="component.degraded", component="assistant")
    )
    assert page.rows == ()
    assert page.next_link is None
    assert [query.events for query in source.queries] == [("component.degraded",)]


def test_a_component_is_only_kept_for_the_degraded_event() -> None:
    """A component the form carries over must not narrow a different event."""
    service = make_service(FakeSource([]))
    stale = service.filters(None, None, None, "retry", "assistant", None)
    assert stale.component is None
    kept = service.filters(None, None, None, "component.degraded", "assistant", None)
    assert kept.component == "assistant"


def test_a_stale_component_does_not_empty_a_new_event() -> None:
    """Switching from a degraded link to retry still lists the retries."""
    events = [
        request_line(10, request_id="req-aaaaaaaa"),
        event_line(15, "retry", "req-aaaaaaaa", {"dependency": "ollama_chat"}),
    ]
    service = make_service(FakeSource(events))
    filters = service.filters(None, None, None, "retry", "assistant", None)
    assert [row.request_id for row in service.search(filters).rows] == ["req-aaaaaaaa"]


def test_pagination_cursor_returns_the_next_page_without_overlap() -> None:
    """A full page carries a cursor; the next page continues from it."""
    events = [
        request_line(minute, request_id=f"req-{minute:08d}") for minute in range(1, 151)
    ]
    service = make_service(FakeSource(events))
    first = service.search(make_filters())
    assert len(first.rows) == 100
    assert first.next_link is not None and "before=" in first.next_link

    second = service.search(make_filters(before=first.rows[-1].timestamp))
    assert len(second.rows) == 50
    assert second.next_link is None
    assert second.rows[0].timestamp < first.rows[-1].timestamp


def test_the_cursor_keeps_rows_that_share_a_timestamp() -> None:
    """Two rows at the boundary's timestamp are shown once each, not skipped."""
    events = [
        request_line(minute, request_id=f"req-{minute:08d}") for minute in range(1, 100)
    ]
    events += [
        request_line(100, request_id="req-00000101"),
        request_line(100, request_id="req-00000100"),
    ]
    service = make_service(FakeSource(events))
    first = service.search(make_filters())
    assert len(first.rows) == 100
    assert first.rows[-1].request_id == "req-00000101"
    assert first.next_link is not None

    cursor = parse_qs(first.next_link.split("?", 1)[1])
    assert cursor["before_id"] == ["req-00000101"]
    second = service.search(
        make_filters(
            before=datetime.fromisoformat(cursor["before"][0]),
            before_id=cursor["before_id"][0],
        )
    )
    assert [row.request_id for row in second.rows] == ["req-00000100"]
    assert second.next_link is None


def test_a_short_page_has_no_cursor() -> None:
    """Fewer rows than a page means there is nothing more to load."""
    page = make_service(FakeSource([request_line(1), request_line(2)])).search(
        make_filters()
    )
    assert page.next_link is None
    assert page.truncated is False


def test_a_flood_of_requests_is_normal_paging_not_truncation() -> None:
    """More rows than a page is what the cursor is for, so no banner is shown."""
    service = make_service(FloodSource(request_line(1, request_id="req-00000001")))
    page = service.search(make_filters())
    assert len(page.rows) == PAGE_SIZE
    assert page.next_link is not None
    assert page.truncated is False


def test_hitting_the_query_cap_on_the_event_read_flags_truncation() -> None:
    """A capped event read sets truncated, so the page can say to narrow it."""
    service = make_service(FloodSource(request_line(1, request_id="req-00000001")))
    page = service.search(make_filters(event="retry"))
    assert page.truncated is True


def test_resolve_hours_defaults_and_rejects() -> None:
    """The requests page offers the same windows as the Overview."""
    service = make_service(FakeSource([]))
    assert service.resolve_hours(None) == 24
    assert service.resolve_hours(168) == 168
    with pytest.raises(ValueError):
        service.resolve_hours(5)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("  ", None),
        (" /v2/predict ", "/v2/predict"),
        ("<unmatched>", "<unmatched>"),
    ],
)
def test_route_parsing_accepts_templates(
    value: str | None, expected: str | None
) -> None:
    """A route template, the unmatched marker or nothing parses."""
    assert parse_route(value) == expected


@pytest.mark.parametrize("value", ["chat", "v2/predict", "<unknown>"])
def test_route_parsing_rejects_other_values(value: str) -> None:
    """A route that cannot match a logged template raises on every source."""
    with pytest.raises(ValueError):
        parse_route(value)
    with pytest.raises(ValueError):
        make_service(FakeSource([])).filters(None, value, None, None, None, None)


def test_an_event_filter_reads_only_the_newest_requests() -> None:
    """Past the id cap, the newest requests are read and the banner is set."""
    count = MAX_EVENT_REQUESTS + 50
    events = [request_line(m, request_id=f"req-{m:08d}") for m in range(1, count + 1)]
    events += [event_line(m, "retry", f"req-{m:08d}") for m in range(1, count + 1)]
    source = SpySource(events)
    page = make_service(source).search(make_filters(event="retry"))
    read = source.queries[-1].request_ids
    assert len(read) == MAX_EVENT_REQUESTS
    assert read[0] == "req-00000001"
    assert "req-00000200" in read and "req-00000201" not in read
    assert page.truncated is True


def test_an_event_filter_under_the_id_cap_is_not_truncated() -> None:
    """Exactly the cap is still a complete read."""
    count = MAX_EVENT_REQUESTS
    events = [request_line(m, request_id=f"req-{m:08d}") for m in range(1, count + 1)]
    events += [event_line(m, "retry", f"req-{m:08d}") for m in range(1, count + 1)]
    page = make_service(FakeSource(events)).search(make_filters(event="retry"))
    assert page.truncated is False
    assert len(page.rows) == PAGE_SIZE
