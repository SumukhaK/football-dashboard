"""Tests for the overview service.

These use the committed fixtures for the component tiles (a fixed clock keeps
them deterministic) and a tiny in-test source for the arithmetic, so the
hand-computed numbers stay readable.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from app.config import REPO_ROOT, Config
from app.contract import load_contract
from app.domain.models import (
    ErrorGroup,
    EventQuery,
    PlatformEvent,
    TelemetryEvent,
    TimeWindow,
    Trace,
)
from app.domain.overview import ComponentTile, HeadlineNumber, TileState
from app.services.overview import OverviewService
from app.sources.filtering import select_events
from app.sources.fixture_source import FixtureSource

NOW = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)
COMPONENTS = tuple(load_contract().components)


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
