"""Tests for the overview service.

These use the committed fixtures for the component tiles (a fixed clock keeps
them deterministic) and a tiny in-test source for the arithmetic, so the
hand-computed numbers stay readable.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from app.config import REPO_ROOT, Config
from app.contract import load_contract
from app.domain.models import (
    MAX_QUERY_LIMIT,
    ErrorGroup,
    EventQuery,
    PlatformEvent,
    TelemetryEvent,
    TimeWindow,
    Trace,
)
from app.domain.overview import ComponentTile, HeadlineNumber, TileState
from app.services.overview import OverviewService, window_for_hours
from app.sources.filtering import select_events
from app.sources.fixture_source import FixtureSource

NOW = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)
COMPONENTS = tuple(load_contract().components)
HEADLINE_ORDER = [
    "requests",
    "error_rate",
    "p95_latency",
    "crashes",
    "rate_limited",
    "retries",
    "fallbacks",
]


class ListSource:
    """An in-test telemetry source backed by a fixed event list."""

    def __init__(self, events: Sequence[TelemetryEvent]) -> None:
        self._events = list(events)

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Return the stored events that match the query, newest first."""
        return select_events(self._events, query)

    def trace(self, trace_id: str) -> Trace | None:
        """There are no traces in the fake."""
        return None

    def error_groups(self, window: TimeWindow) -> list[ErrorGroup]:
        """There are no error groups in the fake."""
        return []

    def platform_events(self, window: TimeWindow) -> list[PlatformEvent]:
        """There are no platform events in the fake."""
        return []


class FullSource:
    """A source that always returns a full page of one request event."""

    def __init__(self) -> None:
        self._event = _request(datetime(2026, 10, 8, 11, 0, tzinfo=UTC), 200)

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Return exactly the query's limit, so the service flags truncation."""
        return [self._event] * query.limit

    def trace(self, trace_id: str) -> Trace | None:
        """There are no traces in the fake."""
        return None

    def error_groups(self, window: TimeWindow) -> list[ErrorGroup]:
        """There are no error groups in the fake."""
        return []

    def platform_events(self, window: TimeWindow) -> list[PlatformEvent]:
        """There are no platform events in the fake."""
        return []


def _service(source: object, now: datetime = NOW) -> OverviewService:
    """Build an overview service over the given source with a fixed clock."""
    return OverviewService(source, lambda: now, Config(), COMPONENTS)  # type: ignore[arg-type]


def _fixture_service() -> OverviewService:
    """An overview service over the committed fixtures with a fixed clock."""
    contract = load_contract()
    source = FixtureSource(REPO_ROOT / "fixtures", contract, now=NOW)
    return _service(source)


def _by_name(tiles: Sequence[ComponentTile], name: str) -> ComponentTile:
    """Return the tile with the given name or fail loudly."""
    for tile in tiles:
        if tile.name == name:
            return tile
    raise AssertionError(f"no tile named {name}")


def _by_key(headlines: Sequence[HeadlineNumber], key: str) -> HeadlineNumber:
    """Return the headline with the given key or fail loudly."""
    for headline in headlines:
        if headline.key == key:
            return headline
    raise AssertionError(f"no headline named {key}")


def _request(moment: datetime, status: int) -> TelemetryEvent:
    """Build an http.request event with the given status."""
    return TelemetryEvent(
        timestamp=moment,
        severity="INFO",
        event="http.request",
        message="request",
        request_id=None,
        trace_id=None,
        span_id=None,
        revision=None,
        attributes={
            "method": "GET",
            "route": "/v2/predict",
            "status": status,
            "duration_ms": 10,
            "error_code": None,
        },
    )


def _load(
    moment: datetime, component: str, status: str = "ok", reason: str | None = None
) -> TelemetryEvent:
    """Build a component.load event."""
    return TelemetryEvent(
        timestamp=moment,
        severity="INFO",
        event="component.load",
        message=f"Component {component} loaded: {status}",
        request_id=None,
        trace_id=None,
        span_id=None,
        revision=None,
        attributes={
            "component": component,
            "status": status,
            "duration_ms": 1,
            "reason": reason,
        },
    )


def _degraded(moment: datetime, component: str) -> TelemetryEvent:
    """Build a component.degraded event."""
    return TelemetryEvent(
        timestamp=moment,
        severity="WARNING",
        event="component.degraded",
        message=f"Component {component} not loaded",
        request_id=None,
        trace_id=None,
        span_id=None,
        revision=None,
        attributes={"component": component, "route": "/v2/predict"},
    )


def _freshness(
    moment: datetime, competition: str, age_hours: float | None
) -> TelemetryEvent:
    """Build a data.freshness event."""
    return TelemetryEvent(
        timestamp=moment,
        severity="INFO",
        event="data.freshness",
        message=f"{competition} data loaded",
        request_id=None,
        trace_id=None,
        span_id=None,
        revision=None,
        attributes={
            "competition": competition,
            "matches_through": None,
            "age_hours": age_hours,
        },
    )


def test_assistant_tile_is_failed_before_the_recovery() -> None:
    """The failed assistant load from the fixtures shows as a red tile."""
    window = TimeWindow(
        start=datetime(2026, 10, 7, 18, 0, tzinfo=UTC),
        end=datetime(2026, 10, 8, 4, 30, tzinfo=UTC),
    )
    model = _fixture_service().build(window)

    assistant = _by_name(model.tiles, "assistant")
    assert assistant.state is TileState.FAILED
    assert "Ollama" in assistant.detail


def test_refresh_tile_is_amber_after_a_failed_run() -> None:
    """A last failed refresh with an older success is the amber tile."""
    window = TimeWindow(
        start=datetime(2026, 10, 7, 18, 0, tzinfo=UTC),
        end=datetime(2026, 10, 8, 4, 30, tzinfo=UTC),
    )
    model = _fixture_service().build(window)

    refresh = _by_name(model.tiles, "daily_refresh")
    assert refresh.state is TileState.DEGRADED
    assert "503" in refresh.detail


def test_recovered_window_shows_amber_assistant_and_stale_data() -> None:
    """After the second revision the assistant is amber and data is stale."""
    model = _fixture_service().build(TimeWindow.last_hours(24, NOW))

    received = _by_name(model.tiles, "assistant")
    assert received.state is TileState.DEGRADED
    assert received.degraded_count == 2

    freshness = _by_name(model.tiles, "data_freshness")
    assert freshness.state is TileState.FAILED


def test_error_rate_and_previous_window_comparison() -> None:
    """The error rate and its change come from hand-counted requests."""
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    window = TimeWindow(start=now - timedelta(hours=1), end=now)
    events = [
        _request(now - timedelta(minutes=10), 200),
        _request(now - timedelta(minutes=20), 200),
        _request(now - timedelta(minutes=30), 500),
        _request(now - timedelta(minutes=40), 503),
        _request(now - timedelta(hours=1, minutes=10), 200),
        _request(now - timedelta(hours=1, minutes=20), 200),
        _request(now - timedelta(hours=1, minutes=30), 200),
        _request(now - timedelta(hours=1, minutes=40), 500),
    ]
    model = _service(ListSource(events), now).build(window)

    headline = _by_key(model.headlines, "error_rate")
    assert headline.value == 0.5
    assert headline.previous == 0.25
    assert headline.change == 0.25


def test_traffic_series_sums_to_the_request_count() -> None:
    """Every request lands in exactly one traffic bucket."""
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    window = TimeWindow(start=now - timedelta(hours=1), end=now)
    events = [
        _request(now - timedelta(minutes=5), 200),
        _request(now - timedelta(minutes=15), 404),
        _request(now - timedelta(minutes=25), 500),
    ]
    model = _service(ListSource(events), now).build(window)

    total = sum(
        value
        for series in model.traffic.series
        for value in series.values
        if value is not None
    )
    assert total == 3
    assert {series.name for series in model.traffic.series} == {"2xx", "4xx", "5xx"}


def test_chart_labels_are_compact() -> None:
    """Chart labels are HH:MM, never raw ISO timestamps."""
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    window = TimeWindow(start=now - timedelta(hours=1), end=now)
    model = _service(
        ListSource([_request(now - timedelta(minutes=5), 200)]), now
    ).build(window)

    assert model.traffic.labels
    for label in model.traffic.labels:
        assert "T" not in label
        assert "+00" not in label
        assert len(label) <= 12


def test_empty_window_has_no_data_tiles_and_no_rates() -> None:
    """Nothing in the window means grey tiles and None numbers, not crashes."""
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    window = TimeWindow(start=now - timedelta(hours=1), end=now)
    model = _service(ListSource([]), now).build(window)

    assert model.tiles
    assert all(tile.state is TileState.NO_DATA for tile in model.tiles)
    assert _by_key(model.headlines, "error_rate").value is None
    assert _by_key(model.headlines, "p95_latency").value is None
    assert _by_key(model.headlines, "requests").value == 0


def test_headline_order_and_p95_units() -> None:
    """Headlines follow the guide's order and p95 names its unit."""
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    window = TimeWindow(start=now - timedelta(hours=1), end=now)
    model = _service(ListSource([]), now).build(window)

    assert [headline.key for headline in model.headlines] == HEADLINE_ORDER
    assert "ms" in _by_key(model.headlines, "p95_latency").label


def test_short_window_still_grades_the_tiles() -> None:
    """A one-hour window grades a failed load from the lookback, not grey."""
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    window = TimeWindow(start=now - timedelta(hours=1), end=now)
    load = _load(now - timedelta(hours=2), "assistant", status="failed", reason="boom")
    model = _service(ListSource([load]), now).build(window)

    tile = _by_name(model.tiles, "assistant")
    assert tile.state is TileState.FAILED
    assert "boom" in tile.detail


def test_degraded_outside_the_window_is_not_counted() -> None:
    """The degraded count is limited to the window, not the lookback."""
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    window = TimeWindow(start=now - timedelta(hours=1), end=now)
    events = [
        _load(now - timedelta(hours=2), "assistant", status="ok"),
        _degraded(now - timedelta(hours=2), "assistant"),
    ]
    model = _service(ListSource(events), now).build(window)

    tile = _by_name(model.tiles, "assistant")
    assert tile.state is TileState.OK
    assert tile.degraded_count == 0
    assert tile.link is None


def test_degraded_without_any_load_is_amber() -> None:
    """A component that only degraded is amber, not a silent grey."""
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    window = TimeWindow(start=now - timedelta(hours=1), end=now)
    model = _service(
        ListSource([_degraded(now - timedelta(minutes=10), "goals_model")]), now
    ).build(window)

    tile = _by_name(model.tiles, "goals_model")
    assert tile.state is TileState.DEGRADED
    assert tile.degraded_count == 1
    assert tile.link is not None


def test_unknown_component_status_is_failed() -> None:
    """An unknown load status is loud, not quietly grey."""
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    window = TimeWindow(start=now - timedelta(hours=1), end=now)
    load = _load(now - timedelta(minutes=10), "explanation", status="weird")
    model = _service(ListSource([load]), now).build(window)

    tile = _by_name(model.tiles, "explanation")
    assert tile.state is TileState.FAILED
    assert "unknown status" in tile.detail


def test_null_age_is_not_fresh() -> None:
    """A null age_hours means unknown, which is at least amber."""
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    window = TimeWindow(start=now - timedelta(hours=1), end=now)
    reading = _freshness(now - timedelta(minutes=10), "premier_league", None)
    model = _service(ListSource([reading]), now).build(window)

    tile = _by_name(model.tiles, "data_freshness")
    assert tile.state is TileState.DEGRADED
    assert "no data for" in tile.detail


def test_truncated_read_is_flagged() -> None:
    """A read that returns exactly the limit marks the model truncated."""
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    window = TimeWindow(start=now - timedelta(hours=1), end=now)
    model = _service(FullSource(), now).build(window)

    assert model.truncated is True
    assert model.limit == MAX_QUERY_LIMIT


def test_normal_read_is_not_flagged_as_truncated() -> None:
    """A small source is not reported as truncated."""
    model = _fixture_service().build(TimeWindow.last_hours(24, NOW))
    assert model.truncated is False


def test_links_are_url_encoded() -> None:
    """Route templates are percent-encoded in the links the service builds."""
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    window = TimeWindow(start=now - timedelta(hours=1), end=now)
    event = TelemetryEvent(
        timestamp=now - timedelta(minutes=5),
        severity="INFO",
        event="http.request",
        message="request",
        request_id=None,
        trace_id=None,
        span_id=None,
        revision=None,
        attributes={
            "method": "GET",
            "route": "/v2/teams/{team}/outlook",
            "status": 500,
            "duration_ms": 5,
            "error_code": "boom",
        },
    )
    model = _service(ListSource([event]), now).build(window)

    row = model.slowest_routes[0]
    assert "%7Bteam%7D" in row.link
    assert "hours=1" in row.link
    assert _by_key(model.headlines, "error_rate").link.endswith("min_status=500")
    assert "event=app.crash" in _by_key(model.headlines, "crashes").link


def test_window_end_is_floored_for_cache_hits() -> None:
    """Two loads inside one interval produce the same window."""
    base = datetime(2026, 10, 8, 12, 7, 3, tzinfo=UTC)
    first = window_for_hours(24, base)
    second = window_for_hours(24, base + timedelta(seconds=5))
    assert first == second
    assert window_for_hours(24, base + timedelta(minutes=15)) != first


def test_resolve_hours_uses_the_settings_default() -> None:
    """A missing hours resolves to the setting, and unknown ones are rejected."""
    service = _service(ListSource([]))
    assert service.resolve_hours(None) == Config().default_window_hours
    assert service.resolve_hours(6) == 6
    with pytest.raises(ValueError):
        service.resolve_hours(5)
