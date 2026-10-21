"""RequestsService rows, their labels and links, and the active-filter chips."""

from __future__ import annotations

from dataclasses import replace
from urllib.parse import parse_qs

import pytest

from app.services.requests import (
    parse_status,
)

from .requests_helpers import (
    FakeSource,
    make_filters,
    make_service,
    request_line,
)


def test_resolve_hours_defaults_and_rejects() -> None:
    """The requests page offers the same windows as the Overview."""
    service = make_service(FakeSource([]))
    assert service.resolve_hours(None) == 24
    assert service.resolve_hours(168) == 168
    with pytest.raises(ValueError):
        service.resolve_hours(5)


def test_a_row_carries_its_labels_and_both_links() -> None:
    """A row is rendered-ready: age, duration, error text and its two links."""
    service = make_service(
        FakeSource([request_line(9 * 60, status_code=503, request_id="req-aaaaaaaa")])
    )
    row = service.search(make_filters()).rows[0]
    assert row.relative_time == "9 h ago"
    assert row.duration_label == "12 ms"
    assert row.status_tone == "fail"
    assert row.error_text == "request finished"
    assert row.link == "/requests/req-aaaaaaaa"
    assert row.panel_link is not None
    assert "/partials/requests/req-aaaaaaaa/panel" in row.panel_link
    assert row.open_link is not None and "open=req-aaaaaaaa" in row.open_link


def test_a_2xx_row_has_no_error_line() -> None:
    """A healthy request shows nothing under its route."""
    service = make_service(FakeSource([request_line(1, request_id="req-aaaaaaaa")]))
    assert service.search(make_filters()).rows[0].error_text is None


def test_a_row_error_text_prefers_the_error_code() -> None:
    """When a request recorded an error code, that is the line under it."""
    line = replace(
        request_line(1, status_code=503, request_id="req-aaaaaaaa"),
        attributes={
            "method": "GET",
            "route": "/v2/predict",
            "status": 503,
            "duration_ms": 12,
            "error_code": "cold_start_timeout",
        },
    )
    row = make_service(FakeSource([line])).search(make_filters()).rows[0]
    assert row.error_text == "cold_start_timeout"


def test_chips_name_each_active_filter_in_a_stable_order() -> None:
    """One chip per active filter: status, then event, then component."""
    service = make_service(FakeSource([]))
    filters = make_filters(
        route="/v2/predict",
        status=parse_status("5xx"),
        event="component.degraded",
        component="assistant",
    )
    assert [(chip.field, chip.label) for chip in service.chips(filters)] == [
        ("status", "5xx"),
        ("event", "component.degraded"),
        ("component", "assistant"),
    ]


def test_a_chip_removes_only_its_own_filter() -> None:
    """A chip's link keeps every other filter, and the route in the box."""
    service = make_service(FakeSource([]))
    filters = make_filters(
        route="/v2/predict", status=parse_status("5xx"), event="retry"
    )
    by_field = {chip.field: chip for chip in service.chips(filters)}

    status = parse_qs(by_field["status"].remove_link.split("?", 1)[1])
    assert "status" not in status
    assert status["event"] == ["retry"]
    assert status["route"] == ["/v2/predict"]

    event = parse_qs(by_field["event"].remove_link.split("?", 1)[1])
    assert "event" not in event
    assert event["status"] == ["5xx"]


def test_a_component_chip_keeps_the_event_it_belongs_to() -> None:
    """Removing a component leaves its degraded event in place."""
    service = make_service(FakeSource([]))
    filters = make_filters(event="component.degraded", component="assistant")
    chip = next(chip for chip in service.chips(filters) if chip.field == "component")
    kept = parse_qs(chip.remove_link.split("?", 1)[1])
    assert "component" not in kept
    assert kept["event"] == ["component.degraded"]


def test_removing_the_degraded_event_drops_its_component_too() -> None:
    """A component means nothing without its event, so both go together."""
    service = make_service(FakeSource([]))
    filters = make_filters(event="component.degraded", component="assistant")
    chip = next(chip for chip in service.chips(filters) if chip.field == "event")
    kept = parse_qs(chip.remove_link.split("?", 1)[1])
    assert "event" not in kept
    assert "component" not in kept


def test_no_filters_means_no_chips() -> None:
    """A bare list has nothing to remove."""
    assert make_service(FakeSource([])).chips(make_filters()) == ()


def test_clear_link_drops_every_filter_but_keeps_the_window() -> None:
    """\"Clear all\" is the list for the same window with no filters at all."""
    service = make_service(FakeSource([]))
    filters = make_filters(
        route="/v2/predict", status=parse_status("5xx"), event="retry"
    )
    cleared = parse_qs(service.clear_link(filters).split("?", 1)[1])
    assert list(cleared) == ["hours"]

    kept = parse_qs(service.list_link(filters).split("?", 1)[1])
    assert kept["route"] == ["/v2/predict"]
    assert kept["status"] == ["5xx"]
    assert kept["event"] == ["retry"]
