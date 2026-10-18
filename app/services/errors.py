"""Builds the errors page model from the telemetry source.

Crashes, platform events and degraded components become grouped counts; the
handled errors also carry a per-interval sparkline, so the page shows when a code
started misbehaving. Every read asks only for the events it shows and is counted
in the truncation check.
"""

from __future__ import annotations

from app.config import WINDOW_HOURS, Config
from app.domain.clock import Clock
from app.domain.errors import (
    CrashGroupRow,
    DegradedComponentRow,
    ErrorsModel,
    HandledErrorRow,
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
from app.services.events import status, text
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
    "window_for_hours",
]

ERROR_EVENTS: tuple[str, ...] = ("app.error",)
DEGRADED_EVENT: tuple[str, ...] = ("component.degraded",)

# Platform events the page highlights, because they mean a restart.
HIGHLIGHTED_PLATFORM: tuple[str, ...] = ("out_of_memory", "startup_failed")


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
        degraded = self._read(window, DEGRADED_EVENT)
        capabilities = self._source.capabilities()
        return ErrorsModel(
            window=window,
            crash_groups=tuple(
                self._crash_row(group, window)
                for group in self._source.error_groups(window)
            ),
            handled_errors=self._handled_rows(handled, window),
            platform_events=tuple(
                _platform_row(event) for event in self._source.platform_events(window)
            ),
            degraded=self._degraded_rows(degraded, window),
            truncated=MAX_QUERY_LIMIT in (len(handled), len(degraded)),
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
    def _crash_row(group: ErrorGroup, window: TimeWindow) -> CrashGroupRow:
        """One crash group, with only the first line of its message."""
        first_line = group.message.splitlines()[0] if group.message else ""
        return CrashGroupRow(
            exception_type=group.exception_type,
            message=first_line,
            count=group.count,
            first_seen=group.first_seen,
            last_seen=group.last_seen,
            routes=group.affected_routes,
            link=requests_link(window, event="app.crash"),
        )

    @staticmethod
    def _handled_rows(
        events: list[TelemetryEvent], window: TimeWindow
    ) -> tuple[HandledErrorRow, ...]:
        """Handled errors grouped by code and route, most recent first."""
        grouped: dict[tuple[str | None, str | None], list[TelemetryEvent]] = {}
        for event in events:
            key = (
                text(event.attributes.get("error_code")),
                text(event.attributes.get("route")),
            )
            grouped.setdefault(key, []).append(event)
        rows = [
            ErrorsService._handled_row(code, route, items, window)
            for (code, route), items in grouped.items()
        ]
        rows.sort(key=lambda row: row.last_seen, reverse=True)
        return tuple(rows)

    @staticmethod
    def _handled_row(
        error_code: str | None,
        route: str | None,
        items: list[TelemetryEvent],
        window: TimeWindow,
    ) -> HandledErrorRow:
        """One handled-error row with its sparkline and its request link."""
        found_status = next((status(event) for event in items if status(event)), None)
        return HandledErrorRow(
            error_code=error_code,
            route=route,
            status=found_status,
            count=len(items),
            last_seen=max(event.timestamp for event in items),
            sparkline=_sparkline(items, window),
            link=requests_link(
                window, route=route, status=found_status, event="app.error"
            ),
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


def _platform_row(event: PlatformEvent) -> PlatformEventRow:
    """One platform event, highlighted when it means the instance restarted."""
    return PlatformEventRow(
        timestamp=event.timestamp,
        kind=event.kind,
        revision=event.revision,
        message=event.message,
        highlighted=event.kind in HIGHLIGHTED_PLATFORM,
    )
