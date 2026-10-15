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
    """Entries become events with their request and trace IDs."""
    lines = fixture_lines[:3]
    client = FakeLoggingClient([as_cloud_entry(line) for line in lines])
    events = make_reader(client).events(EventQuery(window=WINDOW))
    assert [e.request_id for e in events] == [line["request_id"] for line in lines]
    assert [e.event for e in events] == [line["event"] for line in lines]


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
