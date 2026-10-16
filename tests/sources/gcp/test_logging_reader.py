"""Tests for LoggingReader with a fake Cloud Logging client."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from gcp_fakes import FakeLoggingClient, as_cloud_entry
from google.api_core import exceptions as api_exceptions

from app.contract import load_contract
from app.domain.errors import SourceUnavailableError
from app.domain.models import EventQuery, TimeWindow
from app.sources.gcp.logging_reader import LoggingReader

END = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)
WINDOW = TimeWindow(start=END - timedelta(days=2), end=END)


def make_reader(client: FakeLoggingClient, page_size: int = 1000) -> LoggingReader:
    """Build a reader over the fake client."""
    return LoggingReader(client, load_contract(), "football-api", page_size)


def test_maps_entries_to_events(fixture_lines: list[dict[str, Any]]) -> None:
    """Entries become events with their request and trace IDs, newest first."""
    lines = fixture_lines[:3]
    newest_first = list(reversed(lines))
    client = FakeLoggingClient([as_cloud_entry(line) for line in lines])
    events = make_reader(client).events(EventQuery(window=WINDOW))
    assert [e.request_id for e in events] == [
        line["request_id"] for line in newest_first
    ]
    assert [e.event for e in events] == [line["event"] for line in newest_first]


def test_sends_filter_order_and_page_size() -> None:
    """The reader asks for newest first, with the built filter and page size."""
    client = FakeLoggingClient()
    make_reader(client, page_size=200).events(
        EventQuery(window=WINDOW, route="/v2/predict", limit=50)
    )
    call = client.calls[0]
    assert call["order_by"] == "timestamp desc"
    assert call["page_size"] == 50
    assert call["max_results"] == 50
    assert 'jsonPayload.attributes.route="/v2/predict"' in call["filter_"]


def test_stops_at_limit(fixture_lines: list[dict[str, Any]]) -> None:
    """Even if the client yields more, only limit entries are read."""
    client = FakeLoggingClient([as_cloud_entry(line) for line in fixture_lines[:20]])
    events = make_reader(client).events(EventQuery(window=WINDOW, limit=7))
    assert len(events) == 7


def test_many_request_ids_become_several_reads() -> None:
    """Ids are read in chunks, so one Cloud Logging filter stays short."""
    ids = tuple(f"req-{number:08d}" for number in range(250))
    client = FakeLoggingClient()
    make_reader(client).events(EventQuery(window=WINDOW, request_ids=ids))
    assert len(client.calls) == 3
    first = client.calls[0]["filter_"]
    assert "req-00000000" in first and "req-00000099" in first
    assert "req-00000100" not in first
    assert "req-00000249" in client.calls[-1]["filter_"]


def test_tied_rows_come_back_ordered_by_request_id(
    fixture_lines: list[dict[str, Any]],
) -> None:
    """Cloud Logging leaves ties unordered, so paging needs the id to break them."""
    shared = "2026-10-07T18:01:00.942Z"
    lines = []
    for request_id in ("req-00000100", "req-00000101", "req-00000102"):
        line = dict(fixture_lines[0])
        line["timestamp"] = shared
        line["request_id"] = request_id
        lines.append(line)
    client = FakeLoggingClient([as_cloud_entry(line) for line in lines])
    reader = make_reader(client)

    found = reader.events(EventQuery(window=WINDOW))
    assert [event.request_id for event in found] == [
        "req-00000102",
        "req-00000101",
        "req-00000100",
    ]

    after = reader.events(
        EventQuery(
            window=WINDOW,
            before=datetime(2026, 10, 7, 18, 1, 0, 942000, tzinfo=UTC),
            before_id="req-00000102",
        )
    )
    assert [event.request_id for event in after] == ["req-00000101", "req-00000100"]


def test_a_cursor_id_trims_rows_sharing_its_timestamp(
    fixture_lines: list[dict[str, Any]],
) -> None:
    """Cloud Logging cannot order ids, so ties at the cursor are trimmed here."""
    shared = "2026-10-07T18:01:00.942Z"
    lines = []
    for request_id in ("req-00000101", "req-00000100"):
        line = dict(fixture_lines[0])
        line["timestamp"] = shared
        line["request_id"] = request_id
        lines.append(line)
    client = FakeLoggingClient([as_cloud_entry(line) for line in lines])
    query = EventQuery(
        window=WINDOW,
        before=datetime(2026, 10, 7, 18, 1, 0, 942000, tzinfo=UTC),
        before_id="req-00000101",
    )
    events = make_reader(client).events(query)
    assert [event.request_id for event in events] == ["req-00000100"]


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (api_exceptions.PermissionDenied("no"), "permission_denied"),
        (api_exceptions.ResourceExhausted("slow"), "quota"),
        (api_exceptions.ServiceUnavailable("down"), "unavailable"),
    ],
)
def test_google_errors_become_source_errors(error: Exception, kind: str) -> None:
    """Client errors surface as SourceUnavailableError of the right kind."""
    client = FakeLoggingClient(error=error)
    with pytest.raises(SourceUnavailableError) as raised:
        make_reader(client).events(EventQuery(window=WINDOW))
    assert raised.value.kind == kind


def _paged_lines(
    template: dict[str, Any], tied: int, older: int
) -> list[dict[str, Any]]:
    """Newest-first lines: ``tied`` sharing the cursor's moment, then ``older``."""
    lines = []
    for number in range(tied + older):
        line = dict(template)
        seconds = 0 if number < tied else number
        line["timestamp"] = (END - timedelta(hours=1, seconds=seconds)).isoformat()
        line["request_id"] = f"req-{tied + older - number:08d}"
        lines.append(line)
    return lines


def _cursor_query(line: dict[str, Any], limit: int) -> EventQuery:
    """The query for the page after ``line``."""
    return EventQuery(
        window=WINDOW,
        before=datetime.fromisoformat(line["timestamp"]),
        before_id=line["request_id"],
        limit=limit,
    )


def test_a_cursor_page_is_full_although_the_cursor_row_is_read_again(
    fixture_lines: list[dict[str, Any]],
) -> None:
    """The re-read cursor row does not cost a row, so "load more" stays."""
    lines = _paged_lines(fixture_lines[0], tied=1, older=300)
    client = FakeLoggingClient([as_cloud_entry(line) for line in lines])
    events = make_reader(client).events(_cursor_query(lines[0], limit=101))
    assert len(events) == 101
    assert events[0].request_id == lines[1]["request_id"]
    assert [call["max_results"] for call in client.calls] == [102]


def test_ties_at_the_cursor_trigger_one_wider_read(
    fixture_lines: list[dict[str, Any]],
) -> None:
    """Rows already shown at the cursor's moment are replaced by a wider read."""
    lines = _paged_lines(fixture_lines[0], tied=4, older=10)
    client = FakeLoggingClient([as_cloud_entry(line) for line in lines])
    cursor = min(lines[:4], key=lambda line: str(line["request_id"]))
    events = make_reader(client).events(_cursor_query(cursor, limit=5))
    assert [event.request_id for event in events] == [
        line["request_id"] for line in lines[4:9]
    ]
    assert [call["max_results"] for call in client.calls] == [6, 9]


def test_a_short_last_page_is_read_once(
    fixture_lines: list[dict[str, Any]],
) -> None:
    """When Cloud Logging runs out of rows there is nothing more to read."""
    lines = _paged_lines(fixture_lines[0], tied=1, older=3)
    client = FakeLoggingClient([as_cloud_entry(line) for line in lines])
    events = make_reader(client).events(_cursor_query(lines[0], limit=101))
    assert len(events) == 3
    assert len(client.calls) == 1
