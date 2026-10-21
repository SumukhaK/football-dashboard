"""Tests for the bounded Cloud Logging client adapter."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC
from typing import Any, cast

from google.api_core.retry import Retry
from google.cloud.logging_v2.types import LogEntry as LogEntryPB
from google.protobuf.timestamp_pb2 import Timestamp  # type: ignore[import-untyped]

from app.sources.gcp.logging_client import GoogleLoggingClient


def proto_entry(*, text: str = "hello", severity: int = 400) -> LogEntryPB:
    """Build one proto-plus LogEntry shaped like a Cloud Logging response."""
    entry = LogEntryPB(log_name="projects/demo/logs/backend")
    entry.text_payload = text
    entry.severity = severity
    entry.timestamp = Timestamp(seconds=1_700_000_000)
    entry.trace = "projects/demo/traces/abc"
    entry.span_id = "0000000000000001"
    entry.resource.type = "cloud_run_revision"
    entry.resource.labels["service_name"] = "football-api"
    return entry


def proto_json_entry() -> LogEntryPB:
    """Build a structured entry like the backend writes."""
    entry = LogEntryPB(log_name="projects/demo/logs/backend")
    entry.json_payload = {
        "event": "http.request",
        "message": "hello",
        "attributes": {"route": "/v2/predict"},
    }
    entry.severity = 200
    entry.timestamp = Timestamp(seconds=1_700_000_000)
    entry.resource.type = "cloud_run_revision"
    return entry


class FakeRpcClient:
    """Records the low-level ListLogEntries call and returns proto entries."""

    def __init__(self, entries: Iterable[Any]) -> None:
        self._entries = list(entries)
        self.calls: list[dict[str, Any]] = []

    def list_log_entries(
        self,
        *,
        request: Any,
        retry: Retry | None = None,
        timeout: float | None = None,
    ) -> Iterable[Any]:
        """Return the canned entries and record the supported arguments."""
        self.calls.append({"request": request, "retry": retry, "timeout": timeout})
        return iter(self._entries)


def test_passes_supported_timeout_and_retry_to_the_low_level_client() -> None:
    """The adapter uses the RPC client's finite transport arguments."""
    rpc = FakeRpcClient([proto_entry()])
    adapter = GoogleLoggingClient("demo", rpc)
    retry = Retry(deadline=2.0)

    list(
        adapter.list_entries(
            filter_='resource.type="cloud_run_revision"',
            order_by="timestamp desc",
            max_results=10,
            page_size=10,
            timeout=2.0,
            retry=retry,
        )
    )

    call = rpc.calls[0]
    assert call["timeout"] == 2.0
    assert call["retry"] is retry
    request = call["request"]
    assert request.resource_names == ["projects/demo"]
    assert request.filter == 'resource.type="cloud_run_revision"'
    assert request.order_by == "timestamp desc"
    assert request.page_size == 10


def test_rebuilds_an_entry_with_payload_severity_trace_and_resource() -> None:
    """The adapter returns the same high-level entry fields readers already use."""
    adapter = GoogleLoggingClient("demo", FakeRpcClient([proto_entry()]))

    (entry,) = adapter.list_entries(
        filter_="", order_by="timestamp desc", max_results=10, page_size=10
    )
    concrete = cast(Any, entry)

    assert concrete.payload == "hello"
    assert concrete.severity == "WARNING"
    assert concrete.trace == "projects/demo/traces/abc"
    assert concrete.span_id == "0000000000000001"
    assert concrete.resource.labels == {"service_name": "football-api"}
    assert concrete.timestamp == Timestamp(seconds=1_700_000_000).ToDatetime(tzinfo=UTC)


def test_rebuilds_a_structured_payload_entry() -> None:
    """JSON payloads survive the low-level-to-high-level entry conversion."""
    adapter = GoogleLoggingClient("demo", FakeRpcClient([proto_json_entry()]))

    (entry,) = adapter.list_entries(filter_="", order_by="timestamp desc")

    concrete = cast(Any, entry)
    assert concrete.payload == {
        "event": "http.request",
        "message": "hello",
        "attributes": {"route": "/v2/predict"},
    }
    assert concrete.severity == "INFO"


def test_honours_the_row_cap() -> None:
    """The adapter keeps the high-level client's max_results behaviour."""
    adapter = GoogleLoggingClient(
        "demo", FakeRpcClient([proto_entry(), proto_entry(), proto_entry()])
    )

    entries = list(
        adapter.list_entries(
            filter_="", order_by="timestamp desc", max_results=2, page_size=10
        )
    )

    assert len(entries) == 2


def test_no_cap_reads_every_returned_entry() -> None:
    """A call without max_results is not silently truncated."""
    adapter = GoogleLoggingClient(
        "demo", FakeRpcClient([proto_entry(), proto_entry(), proto_entry()])
    )

    entries = list(adapter.list_entries(filter_="", order_by="timestamp desc"))

    assert len(entries) == 3


def test_unknown_severity_is_kept_as_its_number() -> None:
    """A severity outside the SDK catalogue is not invented."""
    adapter = GoogleLoggingClient("demo", FakeRpcClient([proto_entry(severity=999)]))

    (entry,) = adapter.list_entries(filter_="", order_by="timestamp desc")

    assert cast(Any, entry).severity == "999"
