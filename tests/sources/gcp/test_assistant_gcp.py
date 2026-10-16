"""The assistant page's reads through Cloud Logging, over the GCP fake.

The page is one service over the ``TelemetrySource`` protocol, so the fixture
tests and this file exercise the same code. This one feeds the committed fixture
lines through ``FakeLoggingClient`` to pin down what the page actually asks a
production project for: the events it names, the window it carries and the
number of Cloud Logging calls one page load costs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from gcp_fakes import FakeLoggingClient, as_cloud_entry

from app.config import DEFAULT_PLATFORM_PATTERNS, Config
from app.contract import load_contract
from app.domain.models import MAX_QUERY_LIMIT
from app.services.assistant import AssistantService
from app.services.windows import window_for_hours
from app.sources.gcp.errors_reader import ErrorsReader
from app.sources.gcp.logging_reader import LoggingReader
from app.sources.gcp.platform_reader import PlatformReader
from app.sources.gcp.source import GcpReaders, GcpSource
from app.sources.gcp.trace_reader import TraceReader

NOW = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)
PAGE_SIZE = 1000
GAVE_UP = "5051c1ccd17f9acae01f5057ca02135e"

ANSWER_FILTER = 'jsonPayload.event=("assistant.answer" OR "assistant.abstain")'
CALL_FILTER = 'jsonPayload.event=("assistant.tool" OR "retry" OR "fallback")'
DEPENDENCY_FILTER = 'jsonPayload.event=("dependency.call")'


class EmptyTraceClient:
    """Always answers with a trace that has no spans."""

    def get_trace(self, *, project_id: str, trace_id: str) -> Any:
        """Return a trace-shaped object with no spans."""
        return type("T", (), {"spans": []})()


class EmptyErrorsClient:
    """Always answers with no error groups."""

    def list_group_stats(self, request: Any) -> Any:
        """Return no groups."""
        return iter([])


def source_over(client: FakeLoggingClient) -> GcpSource:
    """A GCP source whose logging reader reads the fake client."""
    contract = load_contract()
    return GcpSource(
        lambda: GcpReaders(
            logging=LoggingReader(client, contract, "football-api", PAGE_SIZE),
            traces=TraceReader(EmptyTraceClient(), "demo"),
            errors=ErrorsReader(EmptyErrorsClient(), "demo", "football-api"),
            platform=PlatformReader(
                client, "demo", "football-api", DEFAULT_PLATFORM_PATTERNS
            ),
        )
    )


def build_model(client: FakeLoggingClient) -> Any:
    """Run the assistant service over the fake Cloud Logging client."""
    service = AssistantService(source_over(client), lambda: NOW, Config())
    return service.build(window_for_hours(24, NOW))


def fixture_client(lines: list[dict[str, Any]]) -> FakeLoggingClient:
    """A fake client that answers with the committed fixture lines."""
    return FakeLoggingClient([as_cloud_entry(line) for line in lines])


def test_the_page_names_the_events_and_the_window_it_reads() -> None:
    """Each of the three reads asks for its own events inside the window."""
    client = FakeLoggingClient()
    build_model(client)

    filters = [call["filter_"] for call in client.calls]
    assert [ANSWER_FILTER in f for f in filters] == [True, False, False]
    assert [CALL_FILTER in f for f in filters] == [False, True, False]
    assert [DEPENDENCY_FILTER in f for f in filters] == [False, False, True]
    for clause in filters:
        assert 'timestamp>="2026-10-07T18:00:00.000Z"' in clause
        assert 'timestamp<"2026-10-08T18:00:00.000Z"' in clause


def test_a_page_load_is_three_cloud_logging_reads(
    fixture_lines: list[dict[str, Any]],
) -> None:
    """One read per group of sections, each capped at the query limit."""
    client = fixture_client(fixture_lines)
    build_model(client)

    assert len(client.calls) == 3
    for call in client.calls:
        assert call["max_results"] == MAX_QUERY_LIMIT
        assert call["page_size"] == PAGE_SIZE
        assert call["order_by"] == "timestamp desc"


def test_the_fixture_day_reads_the_same_through_cloud_logging(
    fixture_lines: list[dict[str, Any]],
) -> None:
    """The committed sample day adds up the same on the GCP source."""
    client = fixture_client(fixture_lines)
    model = build_model(client)

    assert model.answers == 7
    assert {row.path: row.answers for row in model.by_path} == {
        "router": 1,
        "model": 3,
        "model_with_tools": 3,
    }
    tools = {row.tool: row for row in model.tools}
    assert tools["predict_match"].errors == 1
    calls = {row.dependency: row for row in model.model_calls}
    assert calls["ollama_chat"].retries == 4
    assert [item.request_id for item in calls["ollama_chat"].gave_up] == [GAVE_UP]
    assert model.truncated is False
