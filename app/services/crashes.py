"""Builds the crashes page and issue detail from the crash source.

Events are grouped by issue here, not in SQL, so the sample data and BigQuery
share one code path. Installation ids only ever leave this module as counts.
"""

from __future__ import annotations

from collections import Counter

from app.config import WINDOW_HOURS
from app.domain.clock import Clock
from app.domain.crashes import (
    CrashesModel,
    CrashEvent,
    CrashEventRow,
    CrashFrame,
    CrashIssueDetail,
    CrashIssueRow,
)
from app.domain.errors import SourceUnavailableError
from app.domain.models import TimeWindow
from app.services.windows import resolve_window_hours, window_for_hours
from app.sources.base import CrashSource

__all__ = [
    "WINDOW_HOURS",
    "CrashIssueDetail",
    "CrashesModel",
    "CrashesService",
    "SourceUnavailableError",
]

DEFAULT_WINDOW_HOURS = 168
EVENT_LIMIT = 5000
DETAIL_EVENT_LIMIT = 50
FRAME_LIMIT = 10
# Shown first, even at zero, so a quiet week still reads as "no fatals".
KNOWN_TYPES: tuple[str, ...] = ("FATAL", "NON_FATAL", "ANR")


class CrashesService:
    """Turns a window of Crashlytics events into the crashes page models."""

    def __init__(self, source: CrashSource, clock: Clock) -> None:
        """Store the crash source and the clock."""
        self._source = source
        self._clock = clock

    @staticmethod
    def resolve_hours(hours: int | None) -> int:
        """Return the requested window size; crashes default to seven days."""
        return resolve_window_hours(hours, DEFAULT_WINDOW_HOURS)

    def build_for_hours(self, hours: int) -> CrashesModel:
        """Return the crashes model for the given window size in hours."""
        window = window_for_hours(hours, self._clock())
        events = self._source.crash_events(window, EVENT_LIMIT)
        return CrashesModel(
            window=window,
            totals=totals_by_type(events),
            issues=issue_rows(events),
            truncated=len(events) >= EVENT_LIMIT,
            limit=EVENT_LIMIT,
        )

    def detail_for_hours(self, issue_id: str, hours: int) -> CrashIssueDetail | None:
        """Return one issue's detail, or None when it has no events in the window."""
        window = window_for_hours(hours, self._clock())
        events = self._source.crash_events(window, EVENT_LIMIT)
        issue = next(
            (row for row in issue_rows(events) if row.issue_id == issue_id), None
        )
        if issue is None:
            return None
        recent = self._source.issue_events(issue_id, window, DETAIL_EVENT_LIMIT)
        return _detail(window, issue, recent) if recent else None


def totals_by_type(events: list[CrashEvent]) -> tuple[tuple[str, int], ...]:
    """Event counts per error type: the known types first, then the rest."""
    counts = Counter(event.error_type for event in events)
    others = sorted(set(counts) - set(KNOWN_TYPES))
    return tuple((kind, counts[kind]) for kind in (*KNOWN_TYPES, *others))


def issue_rows(events: list[CrashEvent]) -> tuple[CrashIssueRow, ...]:
    """One row per issue, most recently seen first."""
    grouped: dict[str, list[CrashEvent]] = {}
    for event in events:
        grouped.setdefault(event.issue_id, []).append(event)
    rows = [_issue_row(issue_id, items) for issue_id, items in grouped.items()]
    return tuple(sorted(rows, key=lambda row: row.last_seen, reverse=True))


def _issue_row(issue_id: str, events: list[CrashEvent]) -> CrashIssueRow:
    """Counts and times for one issue, titled from its newest event."""
    latest = max(events, key=lambda event: event.timestamp)
    title, subtitle = _title(latest)
    return CrashIssueRow(
        issue_id=issue_id,
        title=title,
        subtitle=subtitle,
        error_type=latest.error_type,
        events=len(events),
        installs=len({e.installation_uuid for e in events if e.installation_uuid}),
        first_seen=min(event.timestamp for event in events),
        last_seen=latest.timestamp,
        app_versions=tuple(sorted({event.app_version for event in events})),
    )


def _title(event: CrashEvent) -> tuple[str, str]:
    """The export has no issue title: use the outer exception, else the blame frame."""
    outer = next((e for e in event.exceptions if not e.nested), None)
    if outer is not None:
        return outer.type, outer.message
    if event.blame_frame is not None:
        return event.blame_frame.symbol, ""
    return event.error_type, ""


def _detail(
    window: TimeWindow, issue: CrashIssueRow, recent: list[CrashEvent]
) -> CrashIssueDetail:
    """Recent events, and the blame frame and top frames of the newest one."""
    latest = max(recent, key=lambda event: event.timestamp)
    outer = next((e for e in latest.exceptions if not e.nested), None)
    frames: tuple[CrashFrame, ...] = outer.frames[:FRAME_LIMIT] if outer else ()
    return CrashIssueDetail(
        window=window,
        issue=issue,
        events=tuple(
            CrashEventRow(
                timestamp=event.timestamp,
                app_version=event.app_version,
                device=event.device,
                os_version=event.os_version,
                error_type=event.error_type,
            )
            for event in recent
        ),
        blame_frame=latest.blame_frame,
        frames=frames,
    )
