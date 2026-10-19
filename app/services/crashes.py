"""Builds the crashes page and issue detail from the crash source.

Events are grouped by issue here, not in SQL, so the sample data and BigQuery
share one code path. Installation ids only ever leave this module as counts.
"""

from __future__ import annotations

from collections import Counter

from app.config import DEFAULT_CRASH_APP_PACKAGE, WINDOW_HOURS
from app.domain.clock import Clock
from app.domain.crashes import (
    CrashesModel,
    CrashEvent,
    CrashEventRow,
    CrashFrame,
    CrashFrameRow,
    CrashIssueDetail,
    CrashIssueRow,
    CrashTypeChip,
)
from app.domain.errors import SourceUnavailableError
from app.domain.models import TimeWindow
from app.services.labels import split_class_name
from app.services.links import crash_detail_link, crash_panel_link, requests_link
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
LIST_PATH = "/crashes"
# Shown first, even at zero, so a quiet week still reads as "no fatals".
KNOWN_TYPES: tuple[str, ...] = ("FATAL", "NON_FATAL", "ANR")
# The words the page shows for the export's type codes, and the pill each one
# wears. A type outside them keeps its raw code and stays neutral.
TYPE_LABELS: dict[str, str] = {
    "FATAL": "Fatal",
    "NON_FATAL": "Non-fatal",
    "ANR": "Not responding",
}
TYPE_TONES: dict[str, str] = {
    "FATAL": "fail",
    "NON_FATAL": "warn",
    "ANR": "purple",
}
ALL_TYPES_LABEL = "All"


class CrashesService:
    """Turns a window of Crashlytics events into the crashes page models."""

    def __init__(
        self,
        source: CrashSource,
        clock: Clock,
        app_package: str = DEFAULT_CRASH_APP_PACKAGE,
    ) -> None:
        """Store the crash source, the clock and the app's own package."""
        self._source = source
        self._clock = clock
        self._app_package = app_package

    @staticmethod
    def resolve_hours(hours: int | None) -> int:
        """Return the requested window size; crashes default to seven days."""
        return resolve_window_hours(hours, DEFAULT_WINDOW_HOURS)

    @staticmethod
    def resolve_type(error_type: str | None) -> str | None:
        """Return the requested crash type; None means every type is shown.

        Only the types the page offers a chip for can be filtered on, so a
        value outside them is refused rather than silently ignored.
        """
        if error_type is None or error_type == "":
            return None
        if error_type not in KNOWN_TYPES:
            raise ValueError(f"not a crash type: {error_type!r}")
        return error_type

    def list_link(
        self,
        hours: int,
        error_type: str | None = None,
        open_id: str | None = None,
    ) -> str:
        """The list's own URL for a window, a type filter and an open panel."""
        window = window_for_hours(hours, self._clock())
        return requests_link(window, LIST_PATH, type=error_type, open=open_id)

    def build_for_hours(
        self, hours: int, error_type: str | None = None
    ) -> CrashesModel:
        """Return the crashes model for the window, narrowed to one crash type."""
        window = window_for_hours(hours, self._clock())
        events = self._source.crash_events(window, EVENT_LIMIT)
        totals = totals_by_type(events)
        return CrashesModel(
            window=window,
            totals=totals,
            issues=issue_rows(events, window, error_type),
            type_chips=type_chips(totals, window),
            type_filter=error_type,
            total_events=len(events),
            truncated=len(events) >= EVENT_LIMIT,
            limit=EVENT_LIMIT,
        )

    def detail_for_hours(self, issue_id: str, hours: int) -> CrashIssueDetail | None:
        """Return one issue's detail, or None when it has no events in the window."""
        window = window_for_hours(hours, self._clock())
        events = self._source.crash_events(window, EVENT_LIMIT)
        issue = next(
            (row for row in issue_rows(events, window) if row.issue_id == issue_id),
            None,
        )
        if issue is None:
            return None
        recent = self._source.issue_events(issue_id, window, DETAIL_EVENT_LIMIT)
        if not recent:
            return None
        return _detail(window, issue, recent, self._app_package)


def totals_by_type(events: list[CrashEvent]) -> tuple[tuple[str, int], ...]:
    """Event counts per error type: the known types first, then the rest."""
    counts = Counter(event.error_type for event in events)
    others = sorted(set(counts) - set(KNOWN_TYPES))
    return tuple((kind, counts[kind]) for kind in (*KNOWN_TYPES, *others))


def type_chips(
    totals: tuple[tuple[str, int], ...], window: TimeWindow
) -> tuple[CrashTypeChip, ...]:
    """The "All" chip and one chip per known type, each with its window count.

    The counts describe the whole window, not the filtered list, so a chip
    always says how much it would show.
    """
    counts = dict(totals)
    known = [
        CrashTypeChip(
            value=kind,
            label=type_label(kind),
            count=counts.get(kind, 0),
            link=requests_link(window, LIST_PATH, type=kind),
        )
        for kind in KNOWN_TYPES
    ]
    return (
        CrashTypeChip(
            value=None,
            label=ALL_TYPES_LABEL,
            count=sum(counts.values()),
            link=requests_link(window, LIST_PATH),
        ),
        *known,
    )


def type_label(error_type: str) -> str:
    """The words for a crash type; a type outside the three keeps its code."""
    return TYPE_LABELS.get(error_type, error_type)


def type_tone(error_type: str) -> str:
    """The pill tone for a crash type; an unknown one stays neutral."""
    return TYPE_TONES.get(error_type, "neutral")


def issue_rows(
    events: list[CrashEvent], window: TimeWindow, error_type: str | None = None
) -> tuple[CrashIssueRow, ...]:
    """One row per issue, most recently seen first, narrowed to one crash type."""
    matched = [
        event
        for event in events
        if error_type is None or event.error_type == error_type
    ]
    grouped: dict[str, list[CrashEvent]] = {}
    for event in matched:
        grouped.setdefault(event.issue_id, []).append(event)
    rows = [
        _issue_row(issue_id, items, window, error_type)
        for issue_id, items in grouped.items()
    ]
    return tuple(sorted(rows, key=lambda row: row.last_seen, reverse=True))


def frame_rows(
    frames: tuple[CrashFrame, ...], app_package: str
) -> tuple[CrashFrameRow, ...]:
    """Split each frame, and mark the first one that is the app's own code."""
    rows: list[CrashFrameRow] = []
    marked = False
    for frame in frames:
        method, package = split_class_name(frame.symbol)
        in_app = _in_app(frame.symbol, app_package)
        rows.append(
            CrashFrameRow(
                method=method,
                package=package,
                file=frame.file,
                line=frame.line,
                in_app=in_app,
                first_app=in_app and not marked,
            )
        )
        marked = marked or in_app
    return tuple(rows)


def _in_app(symbol: str, app_package: str) -> bool:
    """Whether a frame's symbol sits in the app's own package."""
    return symbol == app_package or symbol.startswith(app_package + ".")


def _issue_row(
    issue_id: str, events: list[CrashEvent], window: TimeWindow, error_type: str | None
) -> CrashIssueRow:
    """Counts and times for one issue, titled from its newest event."""
    latest = max(events, key=lambda event: event.timestamp)
    title, subtitle = _title(latest)
    short_name, package = split_class_name(title)
    return CrashIssueRow(
        issue_id=issue_id,
        title=title,
        subtitle=subtitle,
        short_name=short_name,
        package=package,
        error_type=latest.error_type,
        type_label=type_label(latest.error_type),
        type_tone=type_tone(latest.error_type),
        events=len(events),
        installs=len({e.installation_uuid for e in events if e.installation_uuid}),
        first_seen=min(event.timestamp for event in events),
        last_seen=latest.timestamp,
        app_versions=tuple(sorted({event.app_version for event in events})),
        link=requests_link(window, crash_detail_link(issue_id)),
        panel_link=requests_link(window, crash_panel_link(issue_id), type=error_type),
        open_link=requests_link(window, LIST_PATH, type=error_type, open=issue_id),
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
    window: TimeWindow,
    issue: CrashIssueRow,
    recent: list[CrashEvent],
    app_package: str,
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
        frames=frame_rows(frames, app_package),
    )
