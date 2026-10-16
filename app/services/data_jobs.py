"""Builds the data and jobs page model from the telemetry source.

Freshness is read over the same lookback the overview tile uses, so a short
window never empties the freshness table; the refresh, fallback, reload and
download sections use the picked window. Every read asks only for the event
types the page shows and is counted in the truncation check.
"""

from __future__ import annotations

from collections import Counter
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

# A load this soon after a refresh is that refresh's reload, and a fallback this
# soon after a run belongs to it: the guide gives five minutes for both.
AFTER_A_REFRESH = timedelta(minutes=5)

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
        refreshes = _refresh_runs(jobs)
        return DataJobsModel(
            window=window,
            freshness=freshness_rows(freshness, self._settings),
            refreshes=refreshes,
            downloads=_download_rows(downloads),
            reloads=_reload_rows(jobs, refreshes),
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


def _refresh_runs(events: list[TelemetryEvent]) -> tuple[RefreshRunRow, ...]:
    """The refresh runs, newest first, each with the fallbacks that followed it."""
    ordered = sorted(by_event(events, "refresh.run"), key=lambda event: event.timestamp)
    paired = _pair_fallbacks(ordered, by_event(events, "fallback"))
    rows = [
        _refresh_row(run, paired.get(index, ())) for index, run in enumerate(ordered)
    ]
    rows.reverse()
    return tuple(rows)


def _refresh_row(
    run: TelemetryEvent, fallbacks: tuple[FallbackRow, ...]
) -> RefreshRunRow:
    """One refresh row from its event and the fallbacks paired with it."""
    return RefreshRunRow(
        timestamp=run.timestamp,
        status=_text_attribute(run, "status"),
        duration_ms=duration_ms(run),
        dataset=text(run.attributes.get("dataset")),
        error=text(run.attributes.get("error")),
        fallbacks=fallbacks,
    )


def _pair_fallbacks(
    runs: list[TelemetryEvent], fallbacks: list[TelemetryEvent]
) -> dict[int, tuple[FallbackRow, ...]]:
    """Attach each fallback to the newest run just before it, within five minutes."""
    paired: dict[int, list[FallbackRow]] = {}
    for event in sorted(fallbacks, key=lambda item: item.timestamp):
        index = _newest_run_before(runs, event.timestamp)
        if index is not None:
            paired.setdefault(index, []).append(_fallback_row(event))
    return {index: tuple(rows) for index, rows in paired.items()}


def _newest_run_before(runs: list[TelemetryEvent], moment: datetime) -> int | None:
    """The index of the newest run at most five minutes before moment, or None.

    ``runs`` is oldest first, so the last index that matches is the newest one.
    A fallback that lands between two runs belongs to the one it followed.
    """
    found: int | None = None
    for index, run in enumerate(runs):
        waited = moment - run.timestamp
        if timedelta(0) <= waited <= AFTER_A_REFRESH:
            found = index
    return found


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
    events: list[TelemetryEvent], refreshes: tuple[RefreshRunRow, ...]
) -> tuple[ReloadRow, ...]:
    """Component loads that followed a refresh, newest first."""
    moments = [run.timestamp for run in refreshes]
    rows = [
        _reload_row(event)
        for event in by_event(events, "component.load")
        if _after_a_refresh(event.timestamp, moments)
    ]
    rows.sort(key=lambda row: row.timestamp, reverse=True)
    return tuple(rows)


def _after_a_refresh(moment: datetime, refresh_moments: list[datetime]) -> bool:
    """Whether moment falls within five minutes after one of the refreshes."""
    return any(
        timedelta(0) <= moment - refresh <= AFTER_A_REFRESH
        for refresh in refresh_moments
    )


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
