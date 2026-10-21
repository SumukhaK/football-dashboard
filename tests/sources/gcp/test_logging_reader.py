"""Tests for LoggingReader with a fake Cloud Logging client."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from gcp_fakes import FakeLoggingClient, as_cloud_entry
from google.api_core import exceptions as api_exceptions
from google.api_core.retry import Retry

from app.contract import load_contract
from app.domain.errors import SourceUnavailableError
from app.domain.models import EventQuery, TimeWindow
from app.services.requests import IDS_FOR_REQUESTS
from app.sources.gcp.budget import RPC_TIMEOUT_SECONDS
from app.sources.gcp.logging_reader import TIE_MARGIN, LoggingClient, LoggingReader

END = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)
WINDOW = TimeWindow(start=END - timedelta(days=2), end=END)


def make_reader(
    client: LoggingClient,
    page_size: int = 1000,
    monotonic: Callable[[], float] | None = None,
) -> LoggingReader:
    """Build a reader over the fake client."""
    if monotonic is None:
        return LoggingReader(client, load_contract(), "football-api", page_size)
    return LoggingReader(
        client, load_contract(), "football-api", page_size, monotonic=monotonic
    )


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


def test_a_capped_id_list_is_two_reads() -> None:
    """The service's 200-id cap is two Cloud Logging calls, not fifty."""
    ids = tuple(f"req-{number:08d}" for number in range(IDS_FOR_REQUESTS))
    client = FakeLoggingClient()
    make_reader(client).events(EventQuery(window=WINDOW, request_ids=ids))
    assert len(client.calls) == 2


def test_a_cursor_read_asks_for_room_to_trim(
    fixture_lines: list[dict[str, Any]],
) -> None:
    """A cursor read re-reads the tie row, so it asks for more than a page.

    Cloud Logging cannot order ids, so the reader asks for the rows sharing the
    cursor's timestamp and trims them in memory; without the margin those rows
    eat into the page and the last page looks empty.
    """
    cursor = datetime(2026, 10, 7, 12, 0, 0, tzinfo=UTC)
    lines = []
    for index in range(300):
        line = dict(fixture_lines[0])
        line["timestamp"] = (cursor - timedelta(seconds=index)).isoformat()
        line["request_id"] = f"req-{index:08d}"
        lines.append(line)
    client = FakeLoggingClient([as_cloud_entry(line) for line in lines])

    events = make_reader(client).events(
        EventQuery(window=WINDOW, before=cursor, before_id="req-00000000", limit=101)
    )
    assert len(events) == 101
    assert events[0].request_id == "req-00000001"
    assert client.calls[0]["max_results"] == 101 + TIE_MARGIN


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


def test_bounds_each_logging_call_with_timeout_and_retry() -> None:
    """The real SDK pager gets a finite per-RPC timeout and retry deadline."""
    client = FakeLoggingClient()
    make_reader(client, monotonic=lambda: 0.0).events(EventQuery(window=WINDOW))

    call = client.calls[0]
    assert call["timeout"] == RPC_TIMEOUT_SECONDS
    assert isinstance(call["retry"], Retry)
    assert call["retry"].deadline == RPC_TIMEOUT_SECONDS


def test_read_budget_expiry_stops_before_the_next_id_chunk() -> None:
    """The budget covers all request-ID chunks, not one call at a time."""
    ids = tuple(f"req-{number:08d}" for number in range(250))
    client = FakeLoggingClient()
    # The first chunk runs at the start of the budget; the second starts after
    # the budget has expired, so it must never reach Cloud Logging.
    clock = lambda: 10.0 if client.calls else 0.0

    with pytest.raises(SourceUnavailableError) as raised:
        make_reader(client, monotonic=clock).events(
            EventQuery(window=WINDOW, request_ids=ids)
        )

    assert raised.value.kind == "unavailable"
    assert (
        raised.value.detail == "Cloud Logging: read budget exhausted; try again later"
    )
    assert len(client.calls) == 1


class ExpiringEntries:
    """An entry iterator that makes the budget expire while it is consumed."""

    def __init__(self, state: dict[str, bool]) -> None:
        self._state = state
        self._first = True

    def __iter__(self) -> ExpiringEntries:
        return self

    def __next__(self) -> Any:
        if self._first:
            self._first = False
            self._state["expired"] = True
            return object()
        raise StopIteration


class ExpiringLoggingClient:
    """Returns entries, but advances the fake clock during iteration."""

    def __init__(self, state: dict[str, bool]) -> None:
        self._state = state
        self.calls: list[dict[str, Any]] = []

    def list_entries(self, **kwargs: Any) -> Iterable[Any]:
        """Record the call and return the expiring iterator."""
        self.calls.append(kwargs)
        return ExpiringEntries(self._state)


def test_read_budget_expiry_during_page_iteration_is_a_source_error() -> None:
    """A page that runs out of time after it starts is not reported as empty."""
    state = {"expired": False}
    client = ExpiringLoggingClient(state)
    clock = lambda: 10.0 if state["expired"] else 0.0

    with pytest.raises(SourceUnavailableError) as raised:
        make_reader(client, monotonic=clock).events(EventQuery(window=WINDOW))

    assert raised.value.kind == "unavailable"
    assert (
        raised.value.detail == "Cloud Logging: read budget exhausted; try again later"
    )
    assert len(client.calls) == 1


class IterationFailureClient:
    """Raises after yielding one entry, as a failure on a later page would."""

    def __init__(self, error: Exception) -> None:
        self._error = error
        self.calls: list[dict[str, Any]] = []

    def list_entries(self, **kwargs: Any) -> Iterable[Any]:
        """Record the call and return an iterator that fails mid-read."""
        self.calls.append(kwargs)

        def entries() -> Iterable[Any]:
            yield object()
            raise self._error

        return entries()


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (api_exceptions.ServiceUnavailable("private"), "unavailable"),
        (
            api_exceptions.RetryError(
                "private wrapper", api_exceptions.ServiceUnavailable("private cause")
            ),
            "unavailable",
        ),
    ],
)
def test_a_paged_read_failure_during_iteration_is_a_source_error(
    error: Exception, kind: str
) -> None:
    """Errors raised while consuming pages reach the existing source error."""
    client = IterationFailureClient(error)

    with pytest.raises(SourceUnavailableError) as raised:
        make_reader(client).events(EventQuery(window=WINDOW))

    assert raised.value.kind == kind
    assert len(client.calls) == 1
