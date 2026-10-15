"""Builds the overview page model from the telemetry source.

The service reads the current window and the one before it (for the "change"
figures) and reduces them to the small frozen models the page renders. Each read
asks only for the event types it needs, so a quiet page does not spend the query
budget on events it never shows. Arithmetic lives in :mod:`app.services.stats`,
window maths in :mod:`app.services.windows`, tile grading in
:mod:`app.services.tiles`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta

from app.config import WINDOW_HOURS, Config
from app.domain.clock import Clock
from app.domain.errors import SourceUnavailableError
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
)
from app.services.events import by_event, durations, in_status_class, status
from app.services.links import chart_label, requests_link
from app.services.stats import bucket_by_interval, percentile, rate
from app.services.tiles import component_tiles
from app.services.windows import interval_for, window_for_hours
from app.sources.base import TelemetrySource

__all__ = [
    "WINDOW_HOURS",
    "OverviewModel",
    "OverviewService",
    "SourceUnavailableError",
    "interval_for",
    "window_for_hours",
]

# Only the event types the overview reads; the source is asked for nothing else.
REQUESTS_EVENT: tuple[str, ...] = ("http.request",)
COUNTED_EVENTS: tuple[str, ...] = (
    "app.crash",
    "ratelimit.rejected",
    "retry",
    "fallback",
)
TILE_EVENTS: tuple[str, ...] = (
    "component.load",
    "component.degraded",
    "refresh.run",
    "data.freshness",
)

# http.request status classes used by the traffic chart.
STATUS_CLASSES: tuple[tuple[str, int, int], ...] = (
    ("2xx", 200, 300),
    ("4xx", 400, 500),
    ("5xx", 500, 600),
)


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

    def resolve_hours(self, hours: int | None) -> int:
        """Return the requested window size, defaulting and validating it."""
        resolved = self._settings.default_window_hours if hours is None else hours
        if resolved not in WINDOW_HOURS:
            raise ValueError(f"unsupported window: {resolved}")
        return resolved

    def build_for_hours(self, hours: int) -> OverviewModel:
        """Return the overview model for the given window size in hours."""
        return self.build(window_for_hours(hours, self._clock()))

    def build(self, window: TimeWindow) -> OverviewModel:
        """Return the overview model for the given window."""
        requests = self._read(window, REQUESTS_EVENT)
        counted = self._read(window, COUNTED_EVENTS)
        length = window.end - window.start
        earlier = TimeWindow(start=window.start - length, end=window.start)
        previous_requests = self._read(earlier, REQUESTS_EVENT)
        previous_counted = self._read(earlier, COUNTED_EVENTS)
        truncated = MAX_QUERY_LIMIT in (
            len(requests),
            len(counted),
            len(previous_requests),
            len(previous_counted),
        )
        return OverviewModel(
            window=window,
            tiles=self._component_tiles(window),
            headlines=self._headline_numbers(
                requests, counted, previous_requests, previous_counted, window
            ),
            traffic=self._traffic_series(requests, window),
            latency=self._latency_series(requests, window),
            slowest_routes=self._slowest_routes(requests, window),
            last_refreshed=self._clock(),
            truncated=truncated,
            limit=MAX_QUERY_LIMIT,
        )

    def _read(
        self, window: TimeWindow, events: tuple[str, ...]
    ) -> list[TelemetryEvent]:
        """Read only the wanted event types in the window, newest first."""
        query = EventQuery(window=window, events=events, limit=MAX_QUERY_LIMIT)
        return self._source.events(query)

    def _component_tiles(self, window: TimeWindow) -> tuple[ComponentTile, ...]:
        """Grade every tile from the events read over the tile lookback."""
        lookback = TimeWindow(
            start=window.end - timedelta(hours=self._settings.tile_lookback_hours),
            end=window.end,
        )
        events = self._read(lookback, TILE_EVENTS)
        return component_tiles(events, window, self._components, self._settings)

    def _headline_numbers(
        self,
        requests: list[TelemetryEvent],
        counted: list[TelemetryEvent],
        previous_requests: list[TelemetryEvent],
        previous_counted: list[TelemetryEvent],
        window: TimeWindow,
    ) -> tuple[HeadlineNumber, ...]:
        """The headline figures, in the guide's order, each linking to /requests."""
        return (
            self._count_headline(
                "requests", "Requests", requests, previous_requests, window
            ),
            self._rate_headline(requests, previous_requests, window),
            self._latency_headline(requests, previous_requests, window),
            self._event_headline(
                "crashes", "Crashes", counted, previous_counted, "app.crash", window
            ),
            self._event_headline(
                "rate_limited",
                "429s",
                counted,
                previous_counted,
                "ratelimit.rejected",
                window,
            ),
            self._event_headline(
                "retries", "Retries", counted, previous_counted, "retry", window
            ),
            self._event_headline(
                "fallbacks", "Fallbacks", counted, previous_counted, "fallback", window
            ),
        )

    @staticmethod
    def _count_headline(
        key: str,
        label: str,
        current: list[TelemetryEvent],
        previous: list[TelemetryEvent],
        window: TimeWindow,
    ) -> HeadlineNumber:
        """A headline counting a whole already-filtered read."""
        return HeadlineNumber(
            key,
            label,
            float(len(current)),
            float(len(previous)),
            link=requests_link(window),
        )

    @staticmethod
    def _event_headline(
        key: str,
        label: str,
        current: list[TelemetryEvent],
        previous: list[TelemetryEvent],
        event_name: str,
        window: TimeWindow,
    ) -> HeadlineNumber:
        """A headline counting one event type."""
        return HeadlineNumber(
            key,
            label,
            float(len(by_event(current, event_name))),
            float(len(by_event(previous, event_name))),
            link=requests_link(window, event=event_name),
        )

    @staticmethod
    def _rate_headline(
        current: list[TelemetryEvent],
        previous: list[TelemetryEvent],
        window: TimeWindow,
    ) -> HeadlineNumber:
        """The error-rate headline (status >= 500 over all requests)."""
        return HeadlineNumber(
            "error_rate",
            "Error rate",
            OverviewService._error_rate(current),
            OverviewService._error_rate(previous),
            is_percent=True,
            link=requests_link(window, min_status=500),
        )

    @staticmethod
    def _latency_headline(
        current: list[TelemetryEvent],
        previous: list[TelemetryEvent],
        window: TimeWindow,
    ) -> HeadlineNumber:
        """The p95 latency headline, in milliseconds."""
        return HeadlineNumber(
            "p95_latency",
            "p95 latency (ms)",
            percentile(durations(current), 0.95),
            percentile(durations(previous), 0.95),
            link=requests_link(window),
        )

    @staticmethod
    def _error_rate(requests: list[TelemetryEvent]) -> float | None:
        """Failures (status >= 500) over all requests."""
        failures = sum(1 for event in requests if (status(event) or 0) >= 500)
        return rate(failures, len(requests))

    def _traffic_series(
        self, requests: list[TelemetryEvent], window: TimeWindow
    ) -> Chart:
        """Requests per interval, stacked by status class."""
        buckets = bucket_by_interval(
            requests, window, interval_for(window.end - window.start)
        )
        labels = tuple(chart_label(bucket.start, window) for bucket in buckets)
        series = tuple(
            Series(
                name,
                tuple(
                    float(
                        sum(
                            1
                            for event in bucket.events
                            if in_status_class(event, low, high)
                        )
                    )
                    for bucket in buckets
                ),
            )
            for name, low, high in STATUS_CLASSES
        )
        return Chart(labels=labels, series=series)

    def _latency_series(
        self, requests: list[TelemetryEvent], window: TimeWindow
    ) -> Chart:
        """p50 and p95 latency per interval."""
        buckets = bucket_by_interval(
            requests, window, interval_for(window.end - window.start)
        )
        labels = tuple(chart_label(bucket.start, window) for bucket in buckets)
        series = tuple(
            Series(
                name,
                tuple(percentile(durations(bucket.events), q) for bucket in buckets),
            )
            for name, q in (("p50", 0.5), ("p95", 0.95))
        )
        return Chart(labels=labels, series=series)

    @staticmethod
    def _slowest_routes(
        requests: list[TelemetryEvent], window: TimeWindow
    ) -> tuple[RouteRow, ...]:
        """The ten routes with the highest p95, most expensive first."""
        grouped: dict[str, list[TelemetryEvent]] = {}
        for event in requests:
            route = str(event.attributes.get("route", "<unknown>"))
            grouped.setdefault(route, []).append(event)
        rows = [
            OverviewService._route_row(route, items, window)
            for route, items in grouped.items()
        ]
        rows.sort(
            key=lambda row: row.p95_ms if row.p95_ms is not None else -1.0, reverse=True
        )
        return tuple(rows[:10])

    @staticmethod
    def _route_row(
        route: str, items: list[TelemetryEvent], window: TimeWindow
    ) -> RouteRow:
        """One slowest-routes row from a route's requests."""
        failures = sum(1 for event in items if (status(event) or 0) >= 500)
        return RouteRow(
            route=route,
            requests=len(items),
            p95_ms=percentile(durations(items), 0.95),
            error_rate=rate(failures, len(items)),
            link=requests_link(window, route=route),
        )
