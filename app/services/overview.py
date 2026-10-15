"""Builds the overview page model from the telemetry source.

The service reads two windows (the current one and the one before it, for the
"change" figures) and reduces them to the small frozen models the page renders.
All arithmetic lives in :mod:`app.services.stats`, so the helpers here only
group, pick the latest of a kind, and name things.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta

from app.config import Config
from app.domain.clock import Clock
from app.domain.models import (
    MAX_QUERY_LIMIT,
    EventQuery,
    TelemetryEvent,
    TimeWindow,
)
from app.domain.overview import (
    Chart,
    ComponentTile,
    HeadlineNumber,
    OverviewModel,
    RouteRow,
    Series,
    TileState,
)
from app.services.stats import bucket_by_interval, percentile, rate
from app.sources.base import TelemetrySource

# The window choices the picker offers, in hours (7 days == 168 hours).
WINDOW_HOURS: tuple[int, ...] = (1, 6, 24, 168)
DEFAULT_WINDOW_HOURS = 24

# Chart resolution by window span: 1 minute, 5 minutes, 15 minutes, 2 hours.
INTERVAL_STEPS: tuple[tuple[timedelta, timedelta], ...] = (
    (timedelta(hours=1), timedelta(minutes=1)),
    (timedelta(hours=6), timedelta(minutes=5)),
    (timedelta(days=1), timedelta(minutes=15)),
    (timedelta(days=7), timedelta(hours=2)),
)

# http.request status classes used by the traffic chart.
STATUS_CLASSES: tuple[tuple[str, int, int], ...] = (
    ("2xx", 200, 300),
    ("4xx", 400, 500),
    ("5xx", 500, 600),
)

_LOAD_STATES: dict[str, TileState] = {
    "ok": TileState.OK,
    "degraded": TileState.DEGRADED,
    "failed": TileState.FAILED,
}


def interval_for(span: timedelta) -> timedelta:
    """Return the chart interval that suits a window of the given span."""
    for limit, interval in INTERVAL_STEPS:
        if span <= limit:
            return interval
    return INTERVAL_STEPS[-1][1]


def window_for_hours(hours: int, now: datetime) -> TimeWindow:
    """Return the window covering the last ``hours`` ending at ``now``."""
    if hours not in WINDOW_HOURS:
        raise ValueError(f"unsupported window: {hours}")
    return TimeWindow.last_hours(hours, now)


def _status(event: TelemetryEvent) -> int | None:
    """The HTTP status recorded on an event, or None when there is none."""
    value = event.attributes.get("status")
    return value if isinstance(value, int) else None


def _duration_ms(event: TelemetryEvent) -> float | None:
    """The duration recorded on an event, or None when there is none."""
    value = event.attributes.get("duration_ms")
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _durations(events: Iterable[TelemetryEvent]) -> list[float]:
    """The durations of the events that have one."""
    return [value for event in events if (value := _duration_ms(event)) is not None]


def _by_event(events: Iterable[TelemetryEvent], name: str) -> list[TelemetryEvent]:
    """The events of one catalogue name."""
    return [event for event in events if event.event == name]


class OverviewService:
    """Turns a window of telemetry into the overview page model."""

    def __init__(
        self,
        source: TelemetrySource,
        clock: Clock,
        settings: Config,
        components: Sequence[str],
    ) -> None:
        """Store the source, clock, settings and the component names to tile."""
        self._source = source
        self._clock = clock
        self._settings = settings
        self._components = tuple(components)

    def build(self, window: TimeWindow) -> OverviewModel:
        """Return the overview model for the given window."""
        current = self._read(window)
        length = window.end - window.start
        previous = self._read(TimeWindow(start=window.start - length, end=window.start))
        return OverviewModel(
            window=window,
            tiles=self._component_tiles(current),
            headlines=self._headline_numbers(current, previous),
            traffic=self._traffic_series(current, window),
            latency=self._latency_series(current, window),
            slowest_routes=self._slowest_routes(current),
            last_refreshed=self._clock(),
        )

    def build_for_hours(self, hours: int) -> OverviewModel:
        """Return the overview model for one of the picker's windows."""
        return self.build(window_for_hours(hours, self._clock()))

    def _read(self, window: TimeWindow) -> list[TelemetryEvent]:
        """Read every event in the window (newest first)."""
        return self._source.events(EventQuery(window=window, limit=MAX_QUERY_LIMIT))

    def _component_tiles(
        self, events: list[TelemetryEvent]
    ) -> tuple[ComponentTile, ...]:
        """One tile per component plus the refresh and freshness tiles."""
        loads = _by_event(events, "component.load")
        degraded = _by_event(events, "component.degraded")
        tiles = [
            self._component_tile(name, loads, degraded) for name in self._components
        ]
        tiles.append(self._refresh_tile(_by_event(events, "refresh.run")))
        tiles.append(self._freshness_tile(_by_event(events, "data.freshness")))
        return tuple(tiles)

    def _component_tile(
        self,
        name: str,
        loads: list[TelemetryEvent],
        degraded: list[TelemetryEvent],
    ) -> ComponentTile:
        """The tile for one component, from its latest load and degradations."""
        mine = [event for event in loads if event.attributes.get("component") == name]
        if not mine:
            return ComponentTile(
                name, TileState.NO_DATA, "no load in this window", None
            )
        latest = max(mine, key=lambda event: event.timestamp)
        state = _LOAD_STATES.get(
            str(latest.attributes.get("status")), TileState.NO_DATA
        )
        count = sum(
            1 for event in degraded if event.attributes.get("component") == name
        )
        if state is TileState.OK and count:
            state = TileState.DEGRADED
        reason = latest.attributes.get("reason")
        detail = str(reason) if reason else latest.message
        return ComponentTile(name, state, detail, latest.timestamp, count)

    def _refresh_tile(self, runs: list[TelemetryEvent]) -> ComponentTile:
        """The daily-refresh tile: red after two failures, amber after one."""
        if not runs:
            return ComponentTile(
                "daily_refresh", TileState.NO_DATA, "no run in this window", None
            )
        ordered = sorted(runs, key=lambda event: event.timestamp, reverse=True)
        last = ordered[0]
        state = self._refresh_state(ordered)
        error = last.attributes.get("error")
        detail = str(error) if error else "last run succeeded"
        return ComponentTile("daily_refresh", state, detail, last.timestamp)

    @staticmethod
    def _refresh_state(runs: list[TelemetryEvent]) -> TileState:
        """Grade the refresh tile from the newest runs (newest first)."""
        if runs[0].attributes.get("status") != "failed":
            return TileState.OK
        if len(runs) >= 2 and runs[1].attributes.get("status") == "failed":
            return TileState.FAILED
        return TileState.DEGRADED

    def _freshness_tile(self, events: list[TelemetryEvent]) -> ComponentTile:
        """The data-freshness tile from the oldest league age in the window."""
        if not events:
            return ComponentTile(
                "data_freshness", TileState.NO_DATA, "no reading in this window", None
            )
        latest = self._latest_per_competition(events)
        worst = max(latest.values(), key=self._age_hours)
        age = self._age_hours(worst)
        competition = worst.attributes.get("competition")
        detail = f"oldest {age:.0f}h ({competition})"
        return ComponentTile(
            "data_freshness", self._freshness_state(age), detail, worst.timestamp
        )

    @staticmethod
    def _latest_per_competition(
        events: list[TelemetryEvent],
    ) -> dict[str, TelemetryEvent]:
        """The newest freshness reading for each competition."""
        found: dict[str, TelemetryEvent] = {}
        for event in events:
            key = str(event.attributes.get("competition"))
            seen = found.get(key)
            if seen is None or event.timestamp > seen.timestamp:
                found[key] = event
        return found

    @staticmethod
    def _age_hours(event: TelemetryEvent) -> float:
        """The age in hours recorded on a freshness reading (0 when absent)."""
        value = event.attributes.get("age_hours")
        return float(value) if isinstance(value, (int, float)) else 0.0

    def _freshness_state(self, age: float) -> TileState:
        """Grade an age in hours against the configured thresholds."""
        if age > self._settings.freshness_error_hours:
            return TileState.FAILED
        if age >= self._settings.freshness_warn_hours:
            return TileState.DEGRADED
        return TileState.OK

    def _headline_numbers(
        self, current: list[TelemetryEvent], previous: list[TelemetryEvent]
    ) -> tuple[HeadlineNumber, ...]:
        """The headline figures, each with its previous-window value."""
        return (
            self._headline("requests", "Requests", current, previous, "http.request"),
            self._headline("crashes", "Crashes", current, previous, "app.crash"),
            self._headline(
                "rate_limited", "429s", current, previous, "ratelimit.rejected"
            ),
            self._headline("retries", "Retries", current, previous, "retry"),
            self._headline("fallbacks", "Fallbacks", current, previous, "fallback"),
            self._rate_headline(current, previous),
            self._latency_headline(current, previous),
        )

    @staticmethod
    def _headline(
        key: str,
        label: str,
        current: list[TelemetryEvent],
        previous: list[TelemetryEvent],
        event_name: str,
    ) -> HeadlineNumber:
        """A count headline for one event name."""
        now = float(len(_by_event(current, event_name)))
        before = float(len(_by_event(previous, event_name)))
        return HeadlineNumber(key, label, now, before)

    @staticmethod
    def _rate_headline(
        current: list[TelemetryEvent], previous: list[TelemetryEvent]
    ) -> HeadlineNumber:
        """The error-rate headline (status >= 500 over all requests)."""
        return HeadlineNumber(
            "error_rate",
            "Error rate",
            OverviewService._error_rate(_by_event(current, "http.request")),
            OverviewService._error_rate(_by_event(previous, "http.request")),
            is_percent=True,
        )

    @staticmethod
    def _latency_headline(
        current: list[TelemetryEvent], previous: list[TelemetryEvent]
    ) -> HeadlineNumber:
        """The p95 latency headline."""
        return HeadlineNumber(
            "p95_latency",
            "p95 latency",
            percentile(_durations(_by_event(current, "http.request")), 0.95),
            percentile(_durations(_by_event(previous, "http.request")), 0.95),
        )

    @staticmethod
    def _error_rate(requests: list[TelemetryEvent]) -> float | None:
        """Failures (status >= 500) over all requests."""
        failures = sum(1 for event in requests if (_status(event) or 0) >= 500)
        return rate(failures, len(requests))

    def _traffic_series(
        self, events: list[TelemetryEvent], window: TimeWindow
    ) -> Chart:
        """Requests per interval, stacked by status class."""
        buckets = bucket_by_interval(
            _by_event(events, "http.request"),
            window,
            interval_for(window.end - window.start),
        )
        labels = tuple(bucket.start.isoformat() for bucket in buckets)
        series = tuple(
            Series(
                name,
                tuple(
                    float(
                        sum(1 for event in bucket.events if _in_class(event, low, high))
                    )
                    for bucket in buckets
                ),
            )
            for name, low, high in STATUS_CLASSES
        )
        return Chart(labels=labels, series=series)

    def _latency_series(
        self, events: list[TelemetryEvent], window: TimeWindow
    ) -> Chart:
        """p50 and p95 latency per interval."""
        buckets = bucket_by_interval(
            _by_event(events, "http.request"),
            window,
            interval_for(window.end - window.start),
        )
        labels = tuple(bucket.start.isoformat() for bucket in buckets)
        quantiles = (("p50", 0.5), ("p95", 0.95))
        series = tuple(
            Series(
                name,
                tuple(percentile(_durations(bucket.events), q) for bucket in buckets),
            )
            for name, q in quantiles
        )
        return Chart(labels=labels, series=series)

    @staticmethod
    def _slowest_routes(events: list[TelemetryEvent]) -> tuple[RouteRow, ...]:
        """The ten routes with the highest p95, most expensive first."""
        grouped: dict[str, list[TelemetryEvent]] = {}
        for event in _by_event(events, "http.request"):
            grouped.setdefault(
                str(event.attributes.get("route", "<unknown>")), []
            ).append(event)
        rows = [
            OverviewService._route_row(route, items) for route, items in grouped.items()
        ]
        rows.sort(
            key=lambda row: row.p95_ms if row.p95_ms is not None else -1.0, reverse=True
        )
        return tuple(rows[:10])

    @staticmethod
    def _route_row(route: str, items: list[TelemetryEvent]) -> RouteRow:
        """One slowest-routes row from a route's requests."""
        failures = sum(1 for event in items if (_status(event) or 0) >= 500)
        return RouteRow(
            route=route,
            requests=len(items),
            p95_ms=percentile(_durations(items), 0.95),
            error_rate=rate(failures, len(items)),
        )


def _in_class(event: TelemetryEvent, low: int, high: int) -> bool:
    """Whether an event's status falls in ``[low, high)``."""
    status = _status(event)
    return status is not None and low <= status < high
