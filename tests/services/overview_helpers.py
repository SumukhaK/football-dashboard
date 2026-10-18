"""Fakes and builders shared by the overview service tests.

The component tiles read the committed fixtures, so their tests use
:func:`fixture_service` (a fixed clock keeps them deterministic); the arithmetic
tests use :class:`ListSource` with events built here, so the hand-computed
numbers stay readable.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

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
from app.domain.overview import ComponentTile, HeadlineNumber
from app.services.overview import OverviewService
from app.sources.base import TelemetrySource
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
        self._event = request_line(datetime(2026, 10, 8, 11, 0, tzinfo=UTC), 200)

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


class StormSource:
    """One failed load buried under a flood of degradations."""

    def __init__(self, load: TelemetryEvent, degraded: TelemetryEvent) -> None:
        self._load = load
        self._degraded = degraded

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Return a full page of degradations, or the single load."""
        if "component.load" in query.events:
            return [self._load]
        if "component.degraded" in query.events:
            return [self._degraded] * query.limit
        return []

    def trace(self, trace_id: str) -> Trace | None:
        """There are no traces in the fake."""
        return None

    def error_groups(self, window: TimeWindow) -> list[ErrorGroup]:
        """There are no error groups in the fake."""
        return []

    def platform_events(self, window: TimeWindow) -> list[PlatformEvent]:
        """There are no platform events in the fake."""
        return []


def make_service(source: TelemetrySource, now: datetime = NOW) -> OverviewService:
    """An overview service over the given source with a fixed clock."""
    return OverviewService(source, lambda: now, Config(), COMPONENTS)


def fixture_service() -> OverviewService:
    """An overview service over the committed fixtures with a fixed clock."""
    contract = load_contract()
    source = FixtureSource(REPO_ROOT / "fixtures", contract, now=NOW)
    return make_service(source)


def by_name(tiles: Sequence[ComponentTile], name: str) -> ComponentTile:
    """Return the tile with the given name or fail loudly."""
    for tile in tiles:
        if tile.name == name:
            return tile
    raise AssertionError(f"no tile named {name}")


def by_key(headlines: Sequence[HeadlineNumber], key: str) -> HeadlineNumber:
    """Return the headline with the given key or fail loudly."""
    for headline in headlines:
        if headline.key == key:
            return headline
    raise AssertionError(f"no headline named {key}")


def request_line(
    moment: datetime,
    status: int,
    route: str | None = "/v2/predict",
    duration_ms: float = 10,
) -> TelemetryEvent:
    """Build an http.request event with the given status, route and duration.

    A request the backend could not route carries no ``route`` attribute at all.
    """
    attributes: dict[str, object] = {
        "method": "GET",
        "status": status,
        "duration_ms": duration_ms,
        "error_code": None,
    }
    if route is not None:
        attributes["route"] = route
    return TelemetryEvent(
        timestamp=moment,
        severity="INFO",
        event="http.request",
        message="request",
        request_id=None,
        trace_id=None,
        span_id=None,
        revision=None,
        attributes=attributes,
    )


def load_line(
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


def refresh_line(moment: datetime, status: str = "ok") -> TelemetryEvent:
    """Build a refresh.run event with the given status."""
    return TelemetryEvent(
        timestamp=moment,
        severity="INFO",
        event="refresh.run",
        message="Daily refresh ran",
        request_id=None,
        trace_id=None,
        span_id=None,
        revision=None,
        attributes={"status": status, "error": None, "job": "daily_refresh"},
    )


def degraded_line(moment: datetime, component: str) -> TelemetryEvent:
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


def freshness_line(
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
