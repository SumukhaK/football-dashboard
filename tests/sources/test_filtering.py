"""Tests for the shared in-memory filters."""

from __future__ import annotations

from datetime import timedelta

from source_helpers import BASE, EventFactory

from app.domain.models import EventQuery, PlatformEvent, TimeWindow
from app.sources.filtering import matches, platform_in_window, select_events

WINDOW = TimeWindow(start=BASE, end=BASE + timedelta(hours=1))


def test_window_includes_start_and_excludes_end(event_factory: EventFactory) -> None:
    """An event at the start matches; one at the end does not."""
    query = EventQuery(window=TimeWindow(start=BASE, end=BASE.replace(minute=5)))
    assert matches(event_factory(0), query)
    assert not matches(event_factory(5), query)


def test_event_name_filter(event_factory: EventFactory) -> None:
    """Only the named events match; an empty tuple matches all."""
    crash = event_factory(1, event="app.crash")
    assert matches(crash, EventQuery(window=WINDOW, events=("app.crash",)))
    assert not matches(crash, EventQuery(window=WINDOW, events=("http.request",)))
    assert matches(crash, EventQuery(window=WINDOW))


def test_request_id_filter(event_factory: EventFactory) -> None:
    """Only the given request's lines match."""
    query = EventQuery(window=WINDOW, request_id="req-00000001")
    assert matches(event_factory(1), query)
    assert not matches(event_factory(1, request_id="req-00000002"), query)


def test_route_filter(event_factory: EventFactory) -> None:
    """Route matches the route template exactly."""
    query = EventQuery(window=WINDOW, route="/v2/fixtures")
    assert matches(event_factory(1), query)
    other = event_factory(1, attributes={"route": "/v2/predict", "status": 200})
    assert not matches(other, query)


def test_min_status_filter(event_factory: EventFactory) -> None:
    """min_status keeps statuses at or above it and drops lines with none."""
    query = EventQuery(window=WINDOW, min_status=500)
    error = event_factory(1, attributes={"route": "/v2/predict", "status": 500})
    assert matches(error, query)
    assert not matches(event_factory(1), query)
    no_status = event_factory(1, event="component.load", attributes={})
    assert not matches(no_status, query)


def test_combined_filters(event_factory: EventFactory) -> None:
    """Every filter must hold at once."""
    query = EventQuery(
        window=WINDOW, events=("http.request",), route="/v2/fixtures", min_status=200
    )
    assert matches(event_factory(1), query)
    assert not matches(event_factory(1, event="app.error"), query)


def test_select_events_sorts_newest_first_and_limits(
    event_factory: EventFactory,
) -> None:
    """Results come newest first and stop at the limit."""
    events = [event_factory(minute) for minute in (3, 10, 7)]
    found = select_events(events, EventQuery(window=WINDOW, limit=2))
    assert [e.timestamp.minute for e in found] == [10, 7]


def test_platform_in_window_sorts_newest_first() -> None:
    """Platform events outside the window are dropped, the rest sorted."""
    events = [
        PlatformEvent(BASE.replace(minute=m), "instance_started", "rev", "x")
        for m in (5, 20)
    ] + [PlatformEvent(BASE - timedelta(hours=1), "container_exit", "rev", "x")]
    found = platform_in_window(events, WINDOW)
    assert [e.timestamp.minute for e in found] == [20, 5]
