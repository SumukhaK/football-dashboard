"""Builds the data and jobs page model from the telemetry source.

Freshness is read over the same lookback the overview tile uses, so a short
window never empties the freshness table; the refresh, fallback, reload and
download sections use the picked window. Every read asks only for the event
types the page shows and is counted in the truncation check.

Relating a load or a fallback to the refresh it happened in is an inference from
the completion record, so it lives in :mod:`app.services.refresh_runs`.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from datetime import datetime, timedelta

from app.config import WINDOW_HOURS, Config
from app.domain.clock import Clock
from app.domain.data_jobs import (
    DataJobsModel,
    DownloadFailure,
    DownloadRow,
    FallbackRow,
    RefreshRunRow,
    ReloadRow,
)
from app.domain.errors import SourceUnavailableError
from app.domain.models import MAX_QUERY_LIMIT, EventQuery, TelemetryEvent, TimeWindow
from app.services.events import by_event, duration_ms, text
from app.services.freshness import freshness_rows
from app.services.refresh_runs import (
    RunInterval,
    owner_of,
    pair_fallbacks,
    run_intervals,
)
from app.services.windows import resolve_window_hours, window_for_hours
from app.sources.base import TelemetrySource

__all__ = [
    "WINDOW_HOURS",
    "DataJobsModel",
    "DataJobsService",
    "SourceUnavailableError",
    "window_for_hours",
]

# The dependencies whose download runs the page reports. Their rows always show,
# even in a window with no attempts, so "no downloads" is visible rather than
# implied; any other downloading dependency is listed after them.
DOWNLOAD_DEPENDENCIES: tuple[str, ...] = ("football_data", "openfootball")
DOWNLOAD_OPERATION = "download"

JOB_EVENTS: tuple[str, ...] = ("refresh.run", "fallback", "component.load")
DOWNLOAD_EVENTS: tuple[str, ...] = ("dependency.call", "retry")
FRESHNESS_EVENTS: tuple[str, ...] = ("data.freshness",)


class DataJobsService:
    """Turns a window of telemetry into the data and jobs page model."""

    def __init__(self, source: TelemetrySource, clock: Clock, settings: Config) -> None:
        """Store the source, clock and settings the service reads through."""
        self._source = source
        self._clock = clock
        self._settings = settings

    def resolve_hours(self, hours: int | None) -> int:
        """Return the requested window size, defaulting and validating it."""
        return resolve_window_hours(hours, self._settings.data_default_window_hours)

    def build_for_hours(self, hours: int) -> DataJobsModel:
        """Return the model for the given window size in hours."""
        return self.build(window_for_hours(hours, self._clock()))

    def build(self, window: TimeWindow) -> DataJobsModel:
        """Return the data and jobs model for the given window."""
        jobs = self._read(window, JOB_EVENTS)
        downloads = self._read(window, DOWNLOAD_EVENTS)
        lookback = _lookback(window, self._settings.tile_lookback_hours)
        freshness = self._read(lookback, FRESHNESS_EVENTS)
        runs = _ordered_runs(jobs)
        paired = pair_fallbacks(runs, by_event(jobs, "fallback"))
        return DataJobsModel(
            window=window,
            freshness=freshness_rows(freshness, self._settings),
            refreshes=_refresh_rows(runs, paired),
            downloads=_download_rows(downloads),
            reloads=_reload_rows(jobs, run_intervals(runs)),
            freshness_lookback_hours=self._settings.tile_lookback_hours,
            truncated=MAX_QUERY_LIMIT in (len(jobs), len(downloads), len(freshness)),
            limit=MAX_QUERY_LIMIT,
        )

    def _read(
        self, window: TimeWindow, events: tuple[str, ...]
    ) -> list[TelemetryEvent]:
        """Read only the wanted event types in the window, newest first."""
        query = EventQuery(window=window, events=events, limit=MAX_QUERY_LIMIT)
        return self._source.events(query)


def _lookback(window: TimeWindow, hours: int) -> TimeWindow:
    """The window the given number of hours long that ends where window ends."""
    return TimeWindow(start=window.end - timedelta(hours=hours), end=window.end)


def _ordered_runs(events: list[TelemetryEvent]) -> list[TelemetryEvent]:
    """The refresh runs, oldest first, in a deterministic order."""
    return sorted(by_event(events, "refresh.run"), key=_run_order)


def _run_order(event: TelemetryEvent) -> tuple[datetime, str, str]:
    """A deterministic order for runs that share a timestamp."""
    return (
        event.timestamp,
        text(event.attributes.get("status")) or "",
        text(event.attributes.get("dataset")) or "",
    )


def _refresh_rows(
    runs: list[TelemetryEvent], paired: Mapping[int, tuple[TelemetryEvent, ...]]
) -> tuple[RefreshRunRow, ...]:
    """One row per run, newest first, each with the fallbacks it owns."""
    rows = [_refresh_row(run, paired.get(index, ())) for index, run in enumerate(runs)]
    rows.reverse()
    return tuple(rows)


def _refresh_row(
    run: TelemetryEvent, fallbacks: tuple[TelemetryEvent, ...]
) -> RefreshRunRow:
    """One refresh row from its event and the fallbacks paired with it."""
    return RefreshRunRow(
        timestamp=run.timestamp,
        status=_text_attribute(run, "status"),
        duration_ms=duration_ms(run),
        dataset=text(run.attributes.get("dataset")),
        error=text(run.attributes.get("error")),
        fallbacks=tuple(_fallback_row(event) for event in fallbacks),
    )


def _fallback_row(event: TelemetryEvent) -> FallbackRow:
    """One fallback row from its event."""
    return FallbackRow(
        timestamp=event.timestamp,
        from_path=_text_attribute(event, "from_path"),
        to_path=_text_attribute(event, "to_path"),
        cause=_text_attribute(event, "cause"),
    )


def _download_rows(events: list[TelemetryEvent]) -> tuple[DownloadRow, ...]:
    """One row per download dependency, the known two first, then any others."""
    calls = [
        event for event in by_event(events, "dependency.call") if _is_download(event)
    ]
    retries = [event for event in by_event(events, "retry") if _is_download(event)]
    seen = {_named(event, "dependency") for event in calls + retries}
    others = sorted(seen - set(DOWNLOAD_DEPENDENCIES))
    names = (*DOWNLOAD_DEPENDENCIES, *others)
    return tuple(_download_row(name, calls, retries) for name in names)


def _is_download(event: TelemetryEvent) -> bool:
    """Whether the call or retry is a match-data download."""
    return text(event.attributes.get("operation")) == DOWNLOAD_OPERATION


def _download_row(
    name: str, calls: list[TelemetryEvent], retries: list[TelemetryEvent]
) -> DownloadRow:
    """One dependency's attempts, failures by status, retries and last error."""
    own = [event for event in calls if _named(event, "dependency") == name]
    failed = [event for event in own if _call_status(event) != "ok"]
    return DownloadRow(
        dependency=name,
        attempts=len(own),
        failures=_failures(failed),
        retries=len(
            [event for event in retries if _named(event, "dependency") == name]
        ),
        last_error=(
            _error_text(max(failed, key=lambda event: event.timestamp))
            if failed
            else None
        ),
    )


def _failures(failed: list[TelemetryEvent]) -> tuple[DownloadFailure, ...]:
    """The failed calls grouped by status, commonest first, ties by status."""
    counts = Counter((_call_status(event), _http_status(event)) for event in failed)
    rows = [
        DownloadFailure(status=status, http_status=code, count=count)
        for (status, code), count in counts.items()
    ]
    rows.sort(key=lambda row: (-row.count, row.status, row.http_status or 0))
    return tuple(rows)


def _error_text(event: TelemetryEvent) -> str:
    """The status of a failed call, with its HTTP status when it has one."""
    code = _http_status(event)
    return (
        f"{_call_status(event)} ({code})" if code is not None else _call_status(event)
    )


def _reload_rows(
    events: list[TelemetryEvent], intervals: tuple[RunInterval, ...]
) -> tuple[ReloadRow, ...]:
    """Component loads that happened during a measured refresh, newest first."""
    rows = [
        _reload_row(event)
        for event in by_event(events, "component.load")
        if owner_of(intervals, event) is not None
    ]
    rows.sort(key=_reload_order, reverse=True)
    return tuple(rows)


def _reload_order(row: ReloadRow) -> tuple[datetime, str]:
    """A deterministic order for reloads that share a timestamp."""
    return (row.timestamp, row.component)


def _reload_row(event: TelemetryEvent) -> ReloadRow:
    """One reload row from its component.load event."""
    return ReloadRow(
        timestamp=event.timestamp,
        component=_named(event, "component"),
        status=_call_status(event),
        duration_ms=duration_ms(event),
        reason=text(event.attributes.get("reason")),
    )


def _call_status(event: TelemetryEvent) -> str:
    """The status of a call, load or refresh, or ``error`` when it has none."""
    return _text_attribute(event, "status")


def _named(event: TelemetryEvent, attribute: str) -> str:
    """A naming attribute of an event, or ``<unknown>`` when it is absent."""
    value = text(event.attributes.get(attribute))
    return value if value else "<unknown>"


def _text_attribute(event: TelemetryEvent, attribute: str) -> str:
    """An attribute of an event as text, or ``unknown`` when it is absent."""
    return text(event.attributes.get(attribute)) or "unknown"


def _http_status(event: TelemetryEvent) -> int | None:
    """The HTTP status recorded on a call, or None when there is none."""
    value = event.attributes.get("http_status")
    return value if isinstance(value, int) else None
