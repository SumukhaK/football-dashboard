"""Mixed release aggregates, correlation safety and bounded retained log pages."""

from dataclasses import replace
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from app.config import Config
from app.contract import load_contract
from app.domain.errors import SourceUnavailableError
from app.domain.models import (
    MAX_QUERY_LIMIT,
    EventQuery,
    TelemetryEvent,
    TimeWindow,
    Trace,
)
from app.domain.releases import ReleaseSelection
from app.services.access import AccessService
from app.services.assistant import AssistantService
from app.services.data_jobs import DataJobsService
from app.services.logs import logs_page
from app.services.overview import OverviewService
from app.services.request_detail import request_detail
from app.services.view_scope import parse_scope
from app.sources.base import TelemetrySource
from app.sources.fixture_source import FixtureSource
from app.sources.gcp.filters import events_filter
from app.sources.scoped import ReleaseSource
from tests.services.requests_helpers import (
    NOW,
    WINDOW,
    FakeSource,
    event_line,
    request_line,
)


def _build(kind: str, source: TelemetrySource) -> object:
    settings = Config()
    clock = lambda: NOW
    if kind == "overview":
        return OverviewService(
            source, clock, settings, load_contract().components
        ).build(WINDOW)
    if kind == "assistant":
        return AssistantService(source, clock, settings).build(WINDOW)
    if kind == "data":
        return DataJobsService(source, clock, settings).build(WINDOW)
    return AccessService(source, clock, settings).build(WINDOW)


@pytest.mark.parametrize("kind", ["overview", "assistant", "data", "access"])
@pytest.mark.parametrize("version", ["2.6.0", "unknown", "absent"])
def test_every_metric_equals_a_source_containing_only_the_selected_release(
    kind: str, version: str
) -> None:
    """Totals, deltas, percentiles, costs and freshness cannot borrow another release."""
    base = FixtureSource(Config().fixture_dir, load_contract(), now=NOW)
    rows = base.events(
        EventQuery(
            TimeWindow(NOW - timedelta(days=7), NOW + timedelta(seconds=1)),
            limit=MAX_QUERY_LIMIT,
        )
    )
    mixed = [replace(e, api_version=v) for v in ("2.5.1", "2.6.0", None) for e in rows]
    selection = ReleaseSelection.from_query(version)
    expected = FakeSource([e for e in mixed if e.api_version == selection.value])
    assert _build(kind, ReleaseSource(FakeSource(mixed), selection)) == _build(
        kind, expected
    )


class RecordingSource(FakeSource):
    """Record source and trace calls without an external service."""

    def __init__(self) -> None:
        super().__init__([])
        self.queries: list[EventQuery] = []
        self.trace_ids: list[str] = []

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Record the immutable query and apply the real shared predicates."""
        self.queries.append(query)
        return super().events(query)

    def trace(self, trace_id: str) -> Trace | None:
        """Record an attempted waterfall read."""
        self.trace_ids.append(trace_id)


def test_only_the_request_line_can_identify_the_trace() -> None:
    """An incidental earlier log trace cannot become the request waterfall."""
    source = RecordingSource()
    source._events = [
        replace(event_line(2, "retry", "req-00000001"), trace_id="unrelated"),
        request_line(1, trace_id="own"),
    ]
    detail = request_detail(source, lambda: NOW, Config(), "req-00000001")
    assert detail and detail.trace_id == "own"
    assert source.trace_ids == ["own"]
    source._events[-1] = request_line(1)
    missing_trace = request_detail(source, lambda: NOW, Config(), "req-00000001")
    assert missing_trace and missing_trace.trace_id is None
    assert source.trace_ids == ["own"]


def test_ambiguous_request_identity_never_fetches_trace() -> None:
    """Conflicting retained request records cannot select an arbitrary release."""
    source = RecordingSource()
    source._events = [
        replace(request_line(1, trace_id="a"), api_version="2.5.1"),
        replace(request_line(2, trace_id="b"), api_version="2.6.0"),
    ]
    with pytest.raises(SourceUnavailableError, match="ambiguous"):
        request_detail(source, lambda: NOW, Config(), "req-00000001")
    assert source.trace_ids == []


def test_logs_filter_before_limit_and_keep_tied_events_across_pages() -> None:
    """A timestamp/request-id cursor would drop these 205 distinct log entries."""
    source = RecordingSource()
    source._events = [
        replace(
            event_line(1, "retry", "req-00000001"),
            api_version="2.6.0",
            message=f"line-{i:03d}",
        )
        for i in range(205)
    ]
    source._events += [
        replace(event_line(0, "retry", None), api_version="2.5.1") for _ in range(6000)
    ]
    scope = parse_scope({"hours": "24", "api_version": "2.6.0"}, NOW)
    first = logs_page(source, Config(), scope, NOW, severity="WARNING", event="retry")
    assert len(first.rows) == 100 and first.next_link and not first.truncated
    params = {k: v[0] for k, v in parse_qs(urlsplit(first.next_link).query).items()}
    frozen = parse_scope(params, NOW)
    second = logs_page(
        source, Config(), frozen, NOW, page=1, severity="WARNING", event="retry"
    )
    third = logs_page(
        source, Config(), frozen, NOW, page=2, severity="WARNING", event="retry"
    )
    assert len({row.message for row in first.rows + second.rows + third.rows}) == 205
    assert third.next_link is None
    assert all(
        q.window == source.queries[0].window and q.release == scope.release
        for q in source.queries
    )
    assert params["severity"] == "WARNING" and params["event"] == "retry"


def test_severity_is_validated_and_pushed_to_google() -> None:
    """A severity filter is exact and reaches Cloud Logging before result caps."""
    query = EventQuery(WINDOW, severity="ERROR", limit=1)
    assert 'severity="ERROR"' in events_filter("api", query)
    with pytest.raises(ValueError, match="severity"):
        EventQuery(WINDOW, severity="ERROR OR true")
    events = [
        replace(event_line(1, "retry", None), severity="ERROR"),
        event_line(0, "retry", None),
    ]
    assert FakeSource(events).events(query) == events[:1]
