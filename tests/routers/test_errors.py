"""Tests for the errors routes."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.config import Config
from app.dependencies import get_errors
from app.domain.errors import SourceUnavailableError
from app.domain.models import (
    ALL_CAPABILITIES,
    ErrorGroup,
    EventQuery,
    PlatformEvent,
    SourceCapabilities,
    TelemetryEvent,
    TimeWindow,
    Trace,
)
from app.services.errors import AMBIGUOUS_SERIES_NOTE, ErrorsService
from app.services.source_status import LOCAL_CRASH_NOTE, LOCAL_ONLY_NOTE
from app.sources.filtering import overlapping_groups, select_events
from tests.auth.console import console, console_client

from .pages_helpers import fixture_line, make_local_client, make_local_log

CLOCK_TIME = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)

GROUP_TYPES = (
    "backend.app.exceptions.AssistantNotAvailableError",
    "builtins.KeyError",
    "builtins.ValueError",
    "builtins.ZeroDivisionError",
)


def _client() -> TestClient:
    """A signed-in test client over the fixture source with a fixed clock."""
    return console_client(clock=lambda: CLOCK_TIME)


def test_errors_page_lists_the_groups_and_the_platform_event() -> None:
    """GET /errors names the fixture crash groups and the out-of-memory."""
    response = _client().get("/errors")
    assert response.status_code == 200
    body = response.text
    for exception_type in GROUP_TYPES:
        assert exception_type in body
    assert "out_of_memory" in body
    assert "Memory limit of 2 GiB exceeded" in body


def test_errors_page_offers_the_window_picker() -> None:
    """The picker swaps the errors body and pushes a shareable URL."""
    body = _client().get("/errors").text
    assert 'aria-label="Time window"' in body
    assert 'hx-target="#errors-body"' in body
    assert 'hx-push-url="/errors?hours=' in body


def test_partial_returns_body_only() -> None:
    """The HTMX partial renders the errors body, not a whole document."""
    response = _client().get("/partials/errors?hours=24")
    assert response.status_code == 200
    assert "<!DOCTYPE html>" not in response.text
    assert 'id="errors-body"' in response.text
    assert "Handled errors" in response.text


def test_unsupported_hours_returns_structured_422() -> None:
    """A window the picker does not offer is a 422 with error and detail."""
    response = _client().get("/partials/errors?hours=5")
    assert response.status_code == 422
    assert "error" in response.json()


class BrokenSource:
    """A telemetry source whose reads always fail."""

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Always fails."""
        raise SourceUnavailableError("unavailable", "google is down")

    def trace(self, trace_id: str) -> Trace | None:
        """Always fails."""
        raise SourceUnavailableError("unavailable", "google is down")

    def error_groups(self, window: TimeWindow) -> list[ErrorGroup]:
        """Always fails."""
        raise SourceUnavailableError("unavailable", "google is down")

    def platform_events(self, window: TimeWindow) -> list[PlatformEvent]:
        """Always fails."""
        raise SourceUnavailableError("unavailable", "google is down")

    def capabilities(self) -> SourceCapabilities:
        """Reads fail, but the source still says what it can answer."""
        return ALL_CAPABILITIES


def test_source_error_renders_a_banner_with_status_200() -> None:
    """A failing source shows a banner and 200, never a 500."""
    signed = console(clock=lambda: CLOCK_TIME)
    broken = ErrorsService(BrokenSource(), lambda: CLOCK_TIME, Config())
    signed.app.dependency_overrides[get_errors] = lambda: broken

    response = signed.client.get("/errors")
    assert response.status_code == 200
    assert "google is down" in response.text


def test_a_local_log_file_shows_the_groups_it_grouped_itself(tmp_path: Path) -> None:
    """The crash groups come from the file's app.crash lines, and it says so."""
    path, _ = make_local_log(tmp_path)
    body = make_local_client(path).get("/errors").text
    exception_type = fixture_line("app.crash")["attributes"]["exception_type"]
    assert exception_type in body
    assert LOCAL_CRASH_NOTE in body


def test_a_local_log_file_marks_the_platform_events_not_available(
    tmp_path: Path,
) -> None:
    """A local file holds no Cloud Run platform log, so the section says so."""
    path, _ = make_local_log(tmp_path)
    body = make_local_client(path).get("/errors").text
    assert "Platform events" in body
    assert body.count(LOCAL_ONLY_NOTE) == 1
    assert "No platform events in this window" not in body


def _sparkline_data(body: str) -> list[dict[str, Any]]:
    """The sparkline JSON block, as the browser's charts.js reads it."""
    match = re.search(
        r'<script type="application/json" id="errors-sparkline-data"[^>]*>'
        r"(.*?)</script>",
        body,
        re.DOTALL,
    )
    assert match is not None, "the page has no sparkline data block"
    data: list[dict[str, Any]] = json.loads(match.group(1))
    return data


def test_the_page_shows_issue_lists_instead_of_tables() -> None:
    """The redesign's four sections, with no table left on the page."""
    body = _client().get("/errors").text
    assert "Server crashes" in body
    assert "Crash groups" not in body
    for heading in ("Handled errors", "Platform events", "Degraded components"):
        assert heading in body
    assert "<table" not in body


def test_a_server_crash_reads_as_an_issue_row() -> None:
    """The short name is bold, its module stays in the title, last seen is relative."""
    body = _client().get("/errors").text
    assert (
        '<span class="issue-name" title="builtins.ValueError">ValueError</span>' in body
    )
    assert "first seen " in body
    assert "last seen " in body


def test_a_handled_error_row_names_its_code_its_route_and_its_status() -> None:
    """One row per code, carrying the status pill, the name and the route label."""
    body = _client().get("/errors").text
    assert '<span class="pill pill-warn">401</span>' in body
    assert ">Not signed in</a>" in body
    assert "10 routes" in body
    assert ">Missing feature columns</a>" in body
    assert '<span class="issue-meta mono">/v2/predict</span>' in body
    assert '<span class="pill pill-fail">503</span>' in body


def test_the_routes_behind_a_code_are_inside_a_details() -> None:
    """The per-route rows are collapsed, and each one still filters the requests list."""
    body = _client().get("/errors").text
    assert '<details class="issue-routes">' in body
    assert "<summary>10 routes</summary>" in body
    assert "<summary>1 route</summary>" in body
    assert "/v2/teams/{team}/outlook" in body
    assert 'href="/requests?hours=24&amp;route=%2Fv2%2Fpredict' in body


def test_every_row_series_reaches_the_chart_data() -> None:
    """Both row kinds publish a series, and every id has an element to draw into."""
    body = _client().get("/errors").text
    charts = _sparkline_data(body)
    ids = [chart["id"] for chart in charts]
    assert any(name.startswith("crash-sparkline-") for name in ids)
    assert any(name.startswith("error-sparkline-") for name in ids)
    for chart in charts:
        assert f'id="{chart["id"]}"' in body
        assert len(chart["labels"]) == len(chart["values"]) > 0


def test_the_platform_timeline_flags_the_events_that_ended_the_instance() -> None:
    """The out-of-memory kill and the container exit are flagged; starts are not."""
    body = _client().get("/errors").text
    assert body.count('class="platform-event is-highlighted"') == 2
    assert body.count('class="platform-event"') == 2


def test_the_platform_column_sits_beside_the_issues() -> None:
    """/errors keeps the timeline and the degraded list in the right-hand column."""
    body = _client().get("/errors").text
    side = body.split('<aside class="errors-side">')[1]
    assert "Platform events" in side
    assert "Degraded components" in side
    assert "Server crashes" not in side


class StubSource:
    """A source over fixed groups and events, for cases the fixtures cannot show."""

    def __init__(
        self,
        groups: Sequence[ErrorGroup] = (),
        events: Sequence[TelemetryEvent] = (),
    ) -> None:
        """Store the groups and events every read is answered from."""
        self._groups = list(groups)
        self._events = list(events)

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Return the stored events that match the query, newest first."""
        return select_events(self._events, query)

    def trace(self, trace_id: str) -> Trace | None:
        """There are no traces in the stub."""
        return None

    def error_groups(self, window: TimeWindow) -> list[ErrorGroup]:
        """Return the stored groups that overlap the window."""
        return overlapping_groups(self._groups, window)

    def platform_events(self, window: TimeWindow) -> list[PlatformEvent]:
        """The stub has no platform events."""
        return []

    def capabilities(self) -> SourceCapabilities:
        """Every query can be answered; the stub is not a local log file."""
        return ALL_CAPABILITIES


def _client_over(source: StubSource) -> TestClient:
    """A signed-in client whose errors page reads the given stub source."""
    signed = console(clock=lambda: CLOCK_TIME)
    service = ErrorsService(source, lambda: CLOCK_TIME, Config())
    signed.app.dependency_overrides[get_errors] = lambda: service
    return signed.client


def _group(group_id: str, exception_type: str, count: int) -> ErrorGroup:
    """One group from Error Reporting, last seen five minutes ago."""
    return ErrorGroup(
        group_id=group_id,
        exception_type=exception_type,
        message=group_id,
        count=count,
        first_seen=CLOCK_TIME - timedelta(minutes=6),
        last_seen=CLOCK_TIME - timedelta(minutes=5),
        affected_routes=("/v2/predict",),
    )


def _crash_event(minutes_ago: int, exception_type: str) -> TelemetryEvent:
    """One uncaught app.crash line at the given minute."""
    return TelemetryEvent(
        timestamp=CLOCK_TIME - timedelta(minutes=minutes_ago),
        severity="ERROR",
        event="app.crash",
        message="boom",
        request_id="req-00000001",
        trace_id=None,
        span_id=None,
        revision=None,
        attributes={"route": "/v2/predict", "exception_type": exception_type},
    )


def test_a_group_the_window_cannot_explain_draws_no_sparkline() -> None:
    """The row appears, with no element and no series rather than a flat line."""
    body = (
        _client_over(StubSource(groups=[_group("g1", "builtins.ValueError", 3)]))
        .get("/errors")
        .text
    )
    assert "ValueError" in body
    assert "crash-sparkline-0" not in body
    assert _sparkline_data(body) == []


def test_groups_that_share_a_type_render_no_chart_and_say_why() -> None:
    """Two groups of one exception type cannot be told apart, so the page says so."""
    kind = "backend.example.Problem"
    source = StubSource(
        groups=[_group("g-a", kind, 1), _group("g-b", kind, 2)],
        events=[_crash_event(5, kind), _crash_event(40, kind)],
    )
    body = _client_over(source).get("/errors").text
    assert body.count(">Problem</span>") == 2
    assert AMBIGUOUS_SERIES_NOTE in body
    assert "crash-sparkline-" not in body
    assert _sparkline_data(body) == []
