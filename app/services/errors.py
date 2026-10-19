"""Builds the errors page model from the telemetry source.

Crashes, platform events and degraded components become grouped counts; the
handled errors also carry a per-interval sparkline, so the page shows when a code
started misbehaving, and each crash group is bucketed from its own events so the
page can show when it fired. Every read asks only for the events it shows and is
counted in the truncation check.
"""

from __future__ import annotations

from datetime import datetime

from app.config import WINDOW_HOURS, Config
from app.domain.clock import Clock
from app.domain.errors import (
    CrashGroupRow,
    DegradedComponentRow,
    ErrorsModel,
    HandledErrorRow,
    HandledRouteRow,
    PlatformEventRow,
    SourceUnavailableError,
    Sparkline,
)
from app.domain.models import (
    MAX_QUERY_LIMIT,
    ErrorGroup,
    EventQuery,
    PlatformEvent,
    TelemetryEvent,
    TimeWindow,
)
from app.services.events import status, status_tone, text
from app.services.labels import display_name, relative_time, split_class_name
from app.services.links import chart_label, requests_link
from app.services.source_status import LOCAL_CRASH_NOTE
from app.services.stats import bucket_by_interval
from app.services.windows import interval_for, resolve_window_hours, window_for_hours
from app.sources.base import TelemetrySource

__all__ = [
    "WINDOW_HOURS",
    "ErrorsModel",
    "ErrorsService",
    "SourceUnavailableError",
    "Sparkline",
    "window_for_hours",
]

ERROR_EVENTS: tuple[str, ...] = ("app.error",)
CRASH_EVENTS: tuple[str, ...] = ("app.crash",)
DEGRADED_EVENT: tuple[str, ...] = ("component.degraded",)

# Platform events the page flags, because the instance did not stay up: the
# memory limit was hit, the container exited, or it never started listening.
HIGHLIGHTED_PLATFORM: tuple[str, ...] = (
    "out_of_memory",
    "container_exit",
    "startup_failed",
)


class ErrorsService:
    """Turns a window of telemetry into the errors page model."""

    def __init__(self, source: TelemetrySource, clock: Clock, settings: Config) -> None:
        """Store the source, clock and settings the service reads through."""
        self._source = source
        self._clock = clock
        self._settings = settings

    def resolve_hours(self, hours: int | None) -> int:
        """Return the requested window size, defaulting and validating it."""
        return resolve_window_hours(hours, self._settings.default_window_hours)

    def build_for_hours(self, hours: int) -> ErrorsModel:
        """Return the errors model for the given window size in hours."""
        return self.build(window_for_hours(hours, self._clock()))

    def build(self, window: TimeWindow) -> ErrorsModel:
        """Return the errors model for the given window."""
        handled = self._read(window, ERROR_EVENTS)
        crashes = self._read(window, CRASH_EVENTS)
        degraded = self._read(window, DEGRADED_EVENT)
        now = self._clock()
        intervals = _intervals_by_type([*crashes, *handled], window)
        capabilities = self._source.capabilities()
        return ErrorsModel(
            window=window,
            crash_groups=tuple(
                self._crash_row(group, window, intervals.get(group.exception_type), now)
                for group in self._source.error_groups(window)
            ),
            handled_errors=self._handled_rows(handled, window),
            platform_events=tuple(
                _platform_row(event) for event in self._source.platform_events(window)
            ),
            degraded=self._degraded_rows(degraded, window),
            truncated=MAX_QUERY_LIMIT in (len(handled), len(crashes), len(degraded)),
            limit=MAX_QUERY_LIMIT,
            crash_groups_available=capabilities.error_reporting,
            platform_events_available=capabilities.platform_events,
            crash_group_note=self._crash_group_note(),
        )

    def _crash_group_note(self) -> str | None:
        """Say so when the groups were grouped locally, not by Error Reporting."""
        if self._settings.source == "local":
            return LOCAL_CRASH_NOTE
        return None

    def _read(
        self, window: TimeWindow, events: tuple[str, ...]
    ) -> list[TelemetryEvent]:
        """Read only the wanted event types in the window, newest first."""
        query = EventQuery(window=window, events=events, limit=MAX_QUERY_LIMIT)
        return self._source.events(query)

    @staticmethod
    def _crash_row(
        group: ErrorGroup,
        window: TimeWindow,
        sparkline: Sparkline | None,
        now: datetime,
    ) -> CrashGroupRow:
        """One crash group, with only the first line of its message."""
        first_line = group.message.splitlines()[0] if group.message else ""
        return CrashGroupRow(
            exception_type=group.exception_type,
            short_name=split_class_name(group.exception_type)[0],
            message=first_line,
            count=group.count,
            first_seen=group.first_seen,
            last_seen=group.last_seen,
            last_seen_label=relative_time(group.last_seen, now),
            routes=group.affected_routes,
            sparkline=sparkline,
            link=requests_link(window, event="app.crash"),
        )

    @staticmethod
    def _handled_rows(
        events: list[TelemetryEvent], window: TimeWindow
    ) -> tuple[HandledErrorRow, ...]:
        """Handled errors grouped by code, most recent first."""
        grouped: dict[str | None, list[TelemetryEvent]] = {}
        for event in events:
            grouped.setdefault(text(event.attributes.get("error_code")), []).append(
                event
            )
        rows = [
            ErrorsService._handled_row(code, items, window)
            for code, items in grouped.items()
        ]
        rows.sort(key=lambda row: row.last_seen, reverse=True)
        return tuple(rows)

    @staticmethod
    def _handled_row(
        error_code: str | None,
        items: list[TelemetryEvent],
        window: TimeWindow,
    ) -> HandledErrorRow:
        """One code's row: a part per route, and one sparkline for the code."""
        by_route: dict[str | None, list[TelemetryEvent]] = {}
        for event in items:
            by_route.setdefault(text(event.attributes.get("route")), []).append(event)
        routes = [_route_row(route, found, window) for route, found in by_route.items()]
        routes.sort(key=lambda row: row.last_seen, reverse=True)
        found_status = next((status(event) for event in items if status(event)), None)
        return HandledErrorRow(
            error_code=error_code,
            display_name=display_name(error_code) if error_code else "(none)",
            status=found_status,
            status_tone=status_tone(found_status),
            routes=tuple(routes),
            count=len(items),
            last_seen=max(event.timestamp for event in items),
            sparkline=_sparkline(items, window),
            link=requests_link(window, event="app.error", status=found_status),
        )

    @staticmethod
    def _degraded_rows(
        events: list[TelemetryEvent], window: TimeWindow
    ) -> tuple[DegradedComponentRow, ...]:
        """Degraded responses grouped by component and route, noisiest first."""
        grouped: dict[tuple[str | None, str | None], int] = {}
        for event in events:
            key = (
                text(event.attributes.get("component")),
                text(event.attributes.get("route")),
            )
            grouped[key] = grouped.get(key, 0) + 1
        rows = [
            DegradedComponentRow(
                component=component or "<unknown>",
                route=route or "<unknown>",
                count=count,
                link=requests_link(
                    window, event="component.degraded", component=component
                ),
            )
            for (component, route), count in grouped.items()
        ]
        rows.sort(key=lambda row: row.count, reverse=True)
        return tuple(rows)


def _sparkline(events: list[TelemetryEvent], window: TimeWindow) -> Sparkline:
    """The per-interval counts of one handled error, for its sparkline."""
    buckets = bucket_by_interval(
        events, window, interval_for(window.end - window.start)
    )
    return Sparkline(
        labels=tuple(chart_label(bucket.start, window) for bucket in buckets),
        values=tuple(float(len(bucket.events)) for bucket in buckets),
    )


def _intervals_by_type(
    events: list[TelemetryEvent], window: TimeWindow
) -> dict[str, Sparkline]:
    """The per-interval counts of the events that share an exception type.

    A crash group is an aggregate from Error Reporting, so the only honest way
    to draw its distribution is to bucket the events that name the same
    exception type: the uncaught ``app.crash`` lines, and the handled errors
    raised with it. A group nothing matches gets no entry, so no line is drawn
    for it rather than a flat zero.
    """
    grouped: dict[str, list[TelemetryEvent]] = {}
    for event in events:
        found = text(event.attributes.get("exception_type"))
        if found:
            grouped.setdefault(found, []).append(event)
    return {name: _sparkline(items, window) for name, items in grouped.items()}


def _route_row(
    route: str | None, items: list[TelemetryEvent], window: TimeWindow
) -> HandledRouteRow:
    """One route's part of a code: how often, its status and its link."""
    found_status = next((status(event) for event in items if status(event)), None)
    return HandledRouteRow(
        route=route,
        status=found_status,
        status_tone=status_tone(found_status),
        count=len(items),
        last_seen=max(event.timestamp for event in items),
        link=requests_link(window, route=route, status=found_status, event="app.error"),
    )


def _platform_row(event: PlatformEvent) -> PlatformEventRow:
    """One platform event, highlighted when it means the instance restarted."""
    return PlatformEventRow(
        timestamp=event.timestamp,
        kind=event.kind,
        revision=event.revision,
        message=event.message,
        highlighted=event.kind in HIGHLIGHTED_PLATFORM,
    )
