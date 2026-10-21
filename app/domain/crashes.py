"""Crashlytics crash events and the crashes page's view models.

Field names follow the Crashlytics BigQuery export schema. The export has no
issue title, so a crash's title and subtitle come from its first exception.
The installation id is kept on the event only so pages can count distinct
installs; no view model carries it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.models import TimeWindow


@dataclass(frozen=True)
class CrashFrame:
    """One stack frame of a crash."""

    symbol: str
    file: str | None
    line: int | None
    library: str | None
    blamed: bool


@dataclass(frozen=True)
class CrashException:
    """One exception of a crash; nested ones are causes."""

    type: str
    message: str
    nested: bool
    frames: tuple[CrashFrame, ...] = ()


@dataclass(frozen=True)
class CrashEvent:
    """One Crashlytics event (a crash, non-fatal or ANR)."""

    event_id: str
    timestamp: datetime
    issue_id: str
    error_type: str
    app_version: str
    device: str
    os_version: str
    installation_uuid: str
    exceptions: tuple[CrashException, ...] = ()
    blame_frame: CrashFrame | None = None


@dataclass(frozen=True)
class CrashTypeChip:
    """One crash-type filter chip; the "All" chip carries no value."""

    value: str | None
    label: str
    count: int
    link: str


@dataclass(frozen=True)
class CrashFrameRow:
    """One stack frame, split into its method and where it came from.

    ``in_app`` marks a frame in the app's own code and ``first_app`` the first
    such frame, which is the one worth highlighting.
    """

    method: str
    package: str
    file: str | None
    line: int | None
    in_app: bool
    first_app: bool


@dataclass(frozen=True)
class CrashIssueRow:
    """Every event of one issue in the window."""

    issue_id: str
    title: str
    subtitle: str
    short_name: str
    package: str
    error_type: str
    type_label: str
    type_tone: str
    events: int
    installs: int
    first_seen: datetime
    last_seen: datetime
    app_versions: tuple[str, ...]
    link: str
    panel_link: str
    open_link: str


@dataclass(frozen=True)
class CrashesModel:
    """Everything the crashes page renders."""

    window: TimeWindow
    totals: tuple[tuple[str, int], ...]
    issues: tuple[CrashIssueRow, ...]
    type_chips: tuple[CrashTypeChip, ...] = ()
    type_filter: str | None = None
    total_events: int = 0
    truncated: bool = False
    limit: int = 0


@dataclass(frozen=True)
class CrashEventRow:
    """One recent event of an issue."""

    timestamp: datetime
    app_version: str
    device: str
    os_version: str
    error_type: str


@dataclass(frozen=True)
class CrashIssueDetail:
    """One issue: its recent events and the latest event's frames."""

    window: TimeWindow
    issue: CrashIssueRow
    events: tuple[CrashEventRow, ...]
    blame_frame: CrashFrame | None
    frames: tuple[CrashFrameRow, ...]
    truncated: bool = False
