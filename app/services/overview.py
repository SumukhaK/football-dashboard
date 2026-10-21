"""Builds the overview page model from the telemetry source.

The service reads the current window and the one before it (for the "change"
figures) and reduces them to the small frozen models the page renders. Each read
asks only for the event types it needs, so a quiet page does not spend the query
budget on events it never shows. Arithmetic lives in :mod:`app.services.stats`,
window maths in :mod:`app.services.windows`, tile grading in
:mod:`app.services.tiles`, and the chart series in
:mod:`app.services.overview_charts`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import replace
from datetime import timedelta

from app.config import WINDOW_HOURS, Config
from app.domain.clock import Clock
from app.domain.errors import SourceUnavailableError
from app.domain.models import (
    MAX_QUERY_LIMIT,
    EventQuery,
    TelemetryEvent,
    TimeWindow,
    is_route_filter,
)
from app.domain.overview import (
    ERROR_RATE_HIGHLIGHT,
    GoodDirection,
    HeadlineNumber,
    OverviewModel,
    RouteRow,
)
from app.domain.release_comparison import ReleaseComparison
from app.services.events import by_event, durations, is_failure
from app.services.labels import format_duration_ms
from app.services.links import requests_link
from app.services.overview_charts import (
    latency_series,
    sparkline_series,
    traffic_series,
)
from app.services.release_comparison import compare_releases
from app.services.stats import percentile, rate
from app.services.tiles import component_tiles
from app.services.windows import interval_for, resolve_window_hours, window_for_hours
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
DEGRADED_EVENT: tuple[str, ...] = ("component.degraded",)
TILE_EVENTS: tuple[str, ...] = (
    "component.load",
    "refresh.run",
    "data.freshness",
)

# The minor headline figures, in order, as (key, label, event type).
EVENT_HEADLINES: tuple[tuple[str, str, str], ...] = (
    ("crashes", "Server crashes", "app.crash"),
    ("rate_limited", "Rate limited", "ratelimit.rejected"),
    ("retries", "Retries", "retry"),
    ("fallbacks", "Fallbacks", "fallback"),
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
        return resolve_window_hours(hours, self._settings.default_window_hours)

    def build_for_hours(self, hours: int) -> OverviewModel:
        """Return the overview model for the given window size in hours."""
        return self.build(window_for_hours(hours, self._clock()))

    def build(
        self,
        window: TimeWindow,
        *,
        compare_releases: bool = False,
        release_labels: tuple[str, ...] = (),
    ) -> OverviewModel:
        """Return the overview model for the given window."""
        requests = self._read(window, REQUESTS_EVENT)
        counted = self._read(window, COUNTED_EVENTS)
        degraded = self._read(window, DEGRADED_EVENT)
        tiles_events = self._read(self._lookback(window), TILE_EVENTS)
        earlier = self._previous(window)
        previous = (
            self._read(earlier, REQUESTS_EVENT),
            self._read(earlier, COUNTED_EVENTS),
        )
        pages = (requests, counted, degraded, tiles_events, *previous)
        truncated = any(len(page) == MAX_QUERY_LIMIT for page in pages)
        traffic = traffic_series(requests, window)
        latency = latency_series(requests, window)
        return OverviewModel(
            window=window,
            tiles=component_tiles(
                tiles_events, degraded, window, self._components, self._settings
            ),
            headlines=self._headline_numbers(
                requests, counted, previous[0], previous[1], window
            ),
            traffic=traffic,
            latency=latency,
            slowest_routes=self._slowest_routes(requests, window),
            last_refreshed=self._clock(),
            sparklines=sparkline_series(requests, latency, window),
            truncated=truncated,
            limit=MAX_QUERY_LIMIT,
            release_comparison=self._comparison(
                window, requests, counted, release_labels, compare_releases
            ),
        )

    def _comparison(
        self,
        window: TimeWindow,
        requests: list[TelemetryEvent],
        counted: list[TelemetryEvent],
        labels: tuple[str, ...],
        enabled: bool,
    ) -> ReleaseComparison | None:
        """Add one bounded assistant read, never a query for each discovered release."""
        if not enabled:
            return None
        answers = self._read(window, ("assistant.answer",))
        return compare_releases(requests, counted, answers, labels, self._settings)

    def _read(
        self, window: TimeWindow, events: tuple[str, ...]
    ) -> list[TelemetryEvent]:
        """Read only the wanted event types in the window, newest first."""
        query = EventQuery(window=window, events=events, limit=MAX_QUERY_LIMIT)
        return self._source.events(query)

    def _lookback(self, window: TimeWindow) -> TimeWindow:
        """The window the component tiles read, which reaches further back."""
        return TimeWindow(
            start=window.end - timedelta(hours=self._settings.tile_lookback_hours),
            end=window.end,
        )

    @staticmethod
    def _previous(window: TimeWindow) -> TimeWindow:
        """The window of the same length that comes immediately before this one."""
        length = window.end - window.start
        return TimeWindow(start=window.start - length, end=window.start)

    def _headline_numbers(
        self,
        requests: list[TelemetryEvent],
        counted: list[TelemetryEvent],
        previous_requests: list[TelemetryEvent],
        previous_counted: list[TelemetryEvent],
        window: TimeWindow,
    ) -> tuple[HeadlineNumber, ...]:
        """The headline figures, in the guide's order, each linking to /requests."""
        # An empty earlier window holds no data at all, so every card says
        # "no earlier data" instead of reading a change against a zero.
        earlier = bool(previous_requests) or bool(previous_counted)
        cards = (
            self._count_headline(
                "requests", "Requests", requests, previous_requests, window, earlier
            ),
            self._rate_headline(requests, previous_requests, window),
            self._latency_headline(requests, previous_requests, window),
        )
        events = tuple(
            self._event_headline(
                key,
                label,
                counted,
                previous_counted,
                event_name,
                window,
                earlier,
            )
            for key, label, event_name in EVENT_HEADLINES
        )
        return cards + events

    @staticmethod
    def _count_headline(
        key: str,
        label: str,
        current: list[TelemetryEvent],
        previous: list[TelemetryEvent],
        window: TimeWindow,
        earlier: bool,
    ) -> HeadlineNumber:
        """A headline counting a whole already-filtered read."""
        return HeadlineNumber(
            key,
            label,
            float(len(current)),
            float(len(previous)) if earlier else None,
            link=requests_link(window),
            good_direction=GoodDirection.UP,
        )

    @staticmethod
    def _event_headline(
        key: str,
        label: str,
        current: list[TelemetryEvent],
        previous: list[TelemetryEvent],
        event_name: str,
        window: TimeWindow,
        earlier: bool,
    ) -> HeadlineNumber:
        """A headline counting one event type; fewer is better."""
        return HeadlineNumber(
            key,
            label,
            float(len(by_event(current, event_name))),
            float(len(by_event(previous, event_name))) if earlier else None,
            link=requests_link(window, event=event_name),
            good_direction=GoodDirection.DOWN,
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
            link=requests_link(window, status="5xx"),
            good_direction=GoodDirection.DOWN,
        )

    @staticmethod
    def _latency_headline(
        current: list[TelemetryEvent],
        previous: list[TelemetryEvent],
        window: TimeWindow,
    ) -> HeadlineNumber:
        """The p95 latency headline, in milliseconds; lower is better."""
        return HeadlineNumber(
            "p95_latency",
            "p95 latency",
            percentile(durations(current), 0.95),
            percentile(durations(previous), 0.95),
            link=requests_link(window),
            good_direction=GoodDirection.DOWN,
            unit="ms",
        )

    @staticmethod
    def _error_rate(requests: list[TelemetryEvent]) -> float | None:
        """Failures (status >= 500) over all requests."""
        failures = sum(1 for event in requests if is_failure(event))
        return rate(failures, len(requests))

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
        return tuple(_with_bars(rows[:10]))

    @staticmethod
    def _route_row(
        route: str, items: list[TelemetryEvent], window: TimeWindow
    ) -> RouteRow:
        """One slowest-routes row from a route's requests."""
        failures = sum(1 for event in items if is_failure(event))
        error_rate = rate(failures, len(items))
        p95 = percentile(durations(items), 0.95)
        return RouteRow(
            route=route,
            requests=len(items),
            p95_ms=p95,
            error_rate=error_rate,
            # A request with no route attribute is grouped under the label
            # <unknown>, which is a label and not a route filter the requests
            # page can apply, so that row links to the unfiltered list.
            link=requests_link(window, route=route if is_route_filter(route) else None),
            p95_label=format_duration_ms(p95),
            highlight_error_rate=(
                error_rate is not None and error_rate >= ERROR_RATE_HIGHLIGHT
            ),
        )


def _with_bars(rows: list[RouteRow]) -> list[RouteRow]:
    """Fill each row's inline p95 bar, relative to the largest p95 shown."""
    largest = max((row.p95_ms or 0.0) for row in rows) if rows else 0.0
    return [replace(row, p95_bar_pct=_log_bar(row.p95_ms, largest)) for row in rows]


def _log_bar(value: float | None, largest: float) -> float:
    """A p95's bar width from 0 to 100, on a log scale against the largest."""
    if value is None or largest <= 1:
        return 0.0
    return 100.0 * math.log10(max(value, 1.0)) / math.log10(largest)
