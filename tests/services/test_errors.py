"""Tests for the errors service."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.config import Config
from app.contract import load_contract
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
from app.services.errors import ErrorsService
from app.services.source_status import LOCAL_CRASH_NOTE
from app.services.windows import window_for_hours
from app.sources.base import TelemetrySource
from app.sources.filtering import (
    overlapping_groups,
    platform_in_window,
    select_events,
)
from app.sources.fixture_source import FixtureSource
from app.sources.local_log_source import LocalLogSource

NOW = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)
WINDOW = window_for_hours(24, NOW)


def _error(
    minutes_ago: int,
    code: str,
    route: str,
    status_code: int,
    exception_type: str = "builtins.ValueError",
) -> TelemetryEvent:
    """One app.error line."""
    return TelemetryEvent(
        timestamp=NOW - timedelta(minutes=minutes_ago),
        severity="ERROR",
        event="app.error",
        message="handled",
        request_id="req-00000001",
        trace_id=None,
        span_id=None,
        revision=None,
        attributes={
            "route": route,
            "status": status_code,
            "error_code": code,
            "exception_type": exception_type,
        },
    )


def _crash(when: datetime, exception_type: str, route: str) -> TelemetryEvent:
    """One uncaught app.crash line at an exact moment."""
    return TelemetryEvent(
        timestamp=when,
        severity="ERROR",
        event="app.crash",
        message=f"{exception_type.rsplit('.', 1)[-1]}: boom",
        request_id="req-00000002",
        trace_id=None,
        span_id=None,
        revision=None,
        attributes={"route": route, "exception_type": exception_type},
    )


def _degraded(minutes_ago: int, component: str, route: str) -> TelemetryEvent:
    """One component.degraded line."""
    return TelemetryEvent(
        timestamp=NOW - timedelta(minutes=minutes_ago),
        severity="WARNING",
        event="component.degraded",
        message="not loaded",
        request_id="req-00000001",
        trace_id=None,
        span_id=None,
        revision=None,
        attributes={"component": component, "route": route},
    )


def _group(
    group_id: str,
    exception_type: str,
    message: str,
    count: int,
    first_minutes_ago: int,
    last_minutes_ago: int,
) -> ErrorGroup:
    """One error group from Error Reporting."""
    return ErrorGroup(
        group_id=group_id,
        exception_type=exception_type,
        message=message,
        count=count,
        first_seen=NOW - timedelta(minutes=first_minutes_ago),
        last_seen=NOW - timedelta(minutes=last_minutes_ago),
        affected_routes=("/v2/predict",),
    )


def _platform(minutes_ago: int, kind: str) -> PlatformEvent:
    """One Cloud Run platform event."""
    return PlatformEvent(
        timestamp=NOW - timedelta(minutes=minutes_ago),
        kind=kind,
        revision="football-api-00042-wum",
        message=f"{kind} happened",
    )


class FakeSource:
    """An in-test source over fixed events, groups and platform events."""

    def __init__(
        self,
        events: Sequence[TelemetryEvent] = (),
        groups: Sequence[ErrorGroup] = (),
        platform: Sequence[PlatformEvent] = (),
    ) -> None:
        self._events = list(events)
        self._groups = list(groups)
        self._platform = list(platform)

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Return the stored events that match the query, newest first."""
        return select_events(self._events, query)

    def trace(self, trace_id: str) -> Trace | None:
        """There are no traces in the fake."""
        return None

    def error_groups(self, window: TimeWindow) -> list[ErrorGroup]:
        """Return the stored groups that overlap the window."""
        return overlapping_groups(self._groups, window)

    def platform_events(self, window: TimeWindow) -> list[PlatformEvent]:
        """Return the stored platform events inside the window."""
        return platform_in_window(self._platform, window)

    def capabilities(self) -> SourceCapabilities:
        """Say every query can be answered; the fake is not a local log file."""
        return ALL_CAPABILITIES


def _service(source: TelemetrySource) -> ErrorsService:
    """An errors service over the given source with a fixed clock."""
    return ErrorsService(source, lambda: NOW, Config())


def test_handled_errors_group_by_code_summing_their_routes() -> None:
    """One row per code: the counts add up and each route is kept once."""
    events = [
        _error(10, "not_found", "/v2/predict", 404),
        _error(20, "not_found", "/v2/predict", 404),
        _error(30, "not_found", "/v2/teams/{team}/outlook", 404),
    ]
    model = _service(FakeSource(events)).build(WINDOW)
    assert len(model.handled_errors) == 1
    row = model.handled_errors[0]
    assert row.error_code == "not_found"
    assert row.count == 3
    assert [route.route for route in row.routes] == [
        "/v2/predict",
        "/v2/teams/{team}/outlook",
    ]
    assert sum(route.count for route in row.routes) == 3


def test_a_code_carries_its_display_name() -> None:
    """The code's display name travels with the row, ready for the template."""
    events = [_error(10, "not_found", "/v2/predict", 404)]
    row = _service(FakeSource(events)).build(WINDOW).handled_errors[0]
    assert row.display_name == "Not found"


def test_a_code_shows_its_route_or_the_number_of_routes() -> None:
    """One route names that route; several become "N routes"."""
    one = _service(
        FakeSource([_error(5, "invalid_team", "/v2/teams/{team}/outlook", 400)])
    ).build(WINDOW)
    assert one.handled_errors[0].route_label == "/v2/teams/{team}/outlook"

    many = _service(
        FakeSource(
            [
                _error(5, "not_found", "/v2/predict", 404),
                _error(9, "not_found", "/v2/teams/{team}/outlook", 404),
            ]
        )
    ).build(WINDOW)
    assert many.handled_errors[0].route_label == "2 routes"


def test_each_route_part_of_a_code_keeps_its_own_link() -> None:
    """The per-route rows inside the details still filter the request list."""
    events = [
        _error(5, "not_found", "/v2/predict", 404),
        _error(9, "not_found", "/v2/teams/{team}/outlook", 404),
    ]
    row = _service(FakeSource(events)).build(WINDOW).handled_errors[0]
    links = {route.route: route.link for route in row.routes}
    assert "route=%2Fv2%2Fpredict" in links["/v2/predict"]
    assert "status=404" in links["/v2/predict"]
    assert "event=app.error" in links["/v2/predict"]


def test_handled_errors_are_newest_first() -> None:
    """The most recently seen code sits at the top."""
    events = [_error(300, "old", "/a", 500), _error(5, "new", "/b", 500)]
    model = _service(FakeSource(events)).build(WINDOW)
    assert [row.error_code for row in model.handled_errors] == ["new", "old"]


def test_sparkline_keeps_every_error_once() -> None:
    """The sparkline has one value per interval and counts each error once."""
    events = [_error(minute, "boom", "/v2/predict", 500) for minute in (5, 40, 60, 600)]
    model = _service(FakeSource(events)).build(WINDOW)
    row = model.handled_errors[0]
    assert len(row.sparkline.labels) == len(row.sparkline.values)
    assert sum(row.sparkline.values) == 4


def test_crash_groups_sorted_by_last_seen_with_a_short_message() -> None:
    """Groups come most recently seen first, with only the message's first line."""
    groups = [
        _group("g1", "builtins.ValueError", "boom\nsecond line", 2, 600, 300),
        _group("g2", "builtins.KeyError", "later", 1, 60, 10),
    ]
    model = _service(FakeSource(groups=groups)).build(WINDOW)
    assert [row.exception_type for row in model.crash_groups] == [
        "builtins.KeyError",
        "builtins.ValueError",
    ]
    assert model.crash_groups[1].message == "boom"
    assert model.crash_groups[1].short_name == "ValueError"
    assert model.crash_groups[1].last_seen_label == "5 h ago"
    assert model.crash_groups[0].link.startswith("/requests?")
    assert "event=app.crash" in model.crash_groups[0].link


def test_a_crash_group_counts_its_events_per_interval() -> None:
    """The sparkline buckets the group's own events, edges included."""
    exception_type = "builtins.ValueError"
    events = [
        _crash(WINDOW.start, exception_type, "/v2/predict"),
        _crash(WINDOW.end - timedelta(minutes=1), exception_type, "/v2/predict"),
        _crash(WINDOW.end, exception_type, "/v2/predict"),
    ]
    group = _group("g1", exception_type, "boom", 2, 600, 10)
    row = _service(FakeSource(events, groups=[group])).build(WINDOW).crash_groups[0]
    sparkline = row.sparkline
    assert sparkline is not None
    assert len(sparkline.labels) == len(sparkline.values) == 96
    assert sparkline.values[0] == 1
    assert sparkline.values[-1] == 1
    assert sum(sparkline.values) == 2


def test_a_group_counts_the_handled_errors_that_share_its_type() -> None:
    """A group built from 5xx lines gets the same buckets as one from crashes."""
    exception_type = "backend.app.exceptions.AssistantNotAvailableError"
    events = [_error(5, "assistant_down", "/v2/assistant/chat", 503, exception_type)]
    group = _group("g1", exception_type, "Request failed", 1, 5, 5)
    row = _service(FakeSource(events, groups=[group])).build(WINDOW).crash_groups[0]
    assert row.sparkline is not None
    assert sum(row.sparkline.values) == 1


def test_a_crash_group_with_no_matching_events_has_no_sparkline() -> None:
    """An aggregate the events cannot explain draws nothing, not a false zero."""
    group = _group("g1", "builtins.ValueError", "boom", 4, 600, 10)
    row = _service(FakeSource(groups=[group])).build(WINDOW).crash_groups[0]
    assert row.sparkline is None


def test_platform_events_are_newest_first_and_highlight_crashes() -> None:
    """Newest first, and only the restart-causing kinds are highlighted."""
    platform = [
        _platform(60, "instance_started"),
        _platform(5, "out_of_memory"),
        _platform(30, "startup_failed"),
        _platform(90, "container_exit"),
    ]
    model = _service(FakeSource(platform=platform)).build(WINDOW)
    assert [row.kind for row in model.platform_events] == [
        "out_of_memory",
        "startup_failed",
        "instance_started",
        "container_exit",
    ]
    assert [row.highlighted for row in model.platform_events] == [
        True,
        True,
        False,
        False,
    ]


def test_degraded_counts_group_by_component_and_route() -> None:
    """The noisiest component/route pair comes first, each linking out."""
    events = [
        _degraded(5, "assistant", "/v2/assistant/chat"),
        _degraded(6, "assistant", "/v2/assistant/chat"),
        _degraded(7, "fixtures", "/v2/fixtures"),
    ]
    model = _service(FakeSource(events)).build(WINDOW)
    assert [row.count for row in model.degraded] == [2, 1]
    assert model.degraded[0].component == "assistant"
    assert "component=assistant" in model.degraded[0].link


def test_fixture_page_lists_the_groups_and_the_out_of_memory() -> None:
    """The committed fixtures show four crash groups and the OOM restart."""
    source = FixtureSource(Config().fixture_dir, load_contract(), now=NOW)
    model = _service(source).build(WINDOW)
    assert len(model.crash_groups) == 4
    assert any(
        row.kind == "out_of_memory" and row.highlighted for row in model.platform_events
    )
    assert sum(row.count for row in model.degraded) == 2
    assert model.truncated is False
    # Every fixture group can be bucketed, and the buckets agree with the
    # aggregate Error Reporting count - including the one built from 5xx lines.
    for row in model.crash_groups:
        assert row.sparkline is not None
        assert sum(row.sparkline.values) == row.count


def test_resolve_hours_defaults_and_rejects() -> None:
    """The errors page offers the same windows as the Overview."""
    service = _service(FakeSource())
    assert service.resolve_hours(None) == 24
    assert service.build_for_hours(1).window.end == NOW


def test_a_local_source_marks_the_platform_events_unavailable(tmp_path: Path) -> None:
    """A local file groups its own crashes, and has no Cloud Run platform log."""
    log = tmp_path / "api.jsonl"
    log.write_text("", encoding="utf-8")
    settings = Config(source="local", local_log_path=log)
    source = LocalLogSource(log, 1_000_000, load_contract(), lambda: NOW)
    model = ErrorsService(source, lambda: NOW, settings).build(WINDOW)
    assert model.crash_groups_available is True
    assert model.platform_events_available is False
    assert model.crash_group_note == LOCAL_CRASH_NOTE


def test_the_sample_files_carry_no_group_note() -> None:
    """With the sample files the groups are the console's own, so no note."""
    model = _service(FakeSource()).build(WINDOW)
    assert model.crash_groups_available is True
    assert model.platform_events_available is True
    assert model.crash_group_note is None
