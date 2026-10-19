"""Errors raised by telemetry sources, and the errors page's view models.

The source error lives here because a page banner and a source failure are two
sides of the same concern; the frozen rows below describe what the errors page
shows, with no knowledge of FastAPI or of any telemetry source.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.domain.models import TimeWindow

SourceErrorKind = Literal[
    "permission_denied", "quota", "unavailable", "not_found", "invalid_data"
]


class SourceUnavailableError(Exception):
    """A telemetry source could not be read."""

    def __init__(self, kind: SourceErrorKind, detail: str) -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind: SourceErrorKind = kind
        self.detail = detail


@dataclass(frozen=True)
class CrashGroupRow:
    """One crash group from Error Reporting, as a "Server crashes" row."""

    exception_type: str
    short_name: str
    message: str
    count: int
    first_seen: datetime
    last_seen: datetime
    last_seen_label: str
    routes: tuple[str, ...]
    # The group's own events bucketed by interval. None when no event in the
    # window carries the group's exception type, so no distribution is drawn
    # rather than a false flat line.
    sparkline: Sparkline | None
    link: str


@dataclass(frozen=True)
class Sparkline:
    """A small per-interval series drawn beside a row."""

    labels: tuple[str, ...]
    values: tuple[float, ...]


@dataclass(frozen=True)
class HandledRouteRow:
    """One route's share of a handled error code."""

    route: str | None
    status: int | None
    status_tone: str
    count: int
    last_seen: datetime
    link: str


@dataclass(frozen=True)
class HandledErrorRow:
    """Handled ``app.error`` lines sharing one error code."""

    error_code: str | None
    display_name: str
    status: int | None
    status_tone: str
    routes: tuple[HandledRouteRow, ...]
    count: int
    last_seen: datetime
    sparkline: Sparkline
    link: str

    @property
    def route_label(self) -> str:
        """The route itself when the code hit one, else how many it hit."""
        if len(self.routes) == 1:
            return self.routes[0].route or "<unknown>"
        return f"{len(self.routes)} routes"


@dataclass(frozen=True)
class PlatformEventRow:
    """One Cloud Run platform event."""

    timestamp: datetime
    kind: str
    revision: str
    message: str
    highlighted: bool


@dataclass(frozen=True)
class DegradedComponentRow:
    """One component/route pair that answered 503 because it was not loaded."""

    component: str
    route: str
    count: int
    link: str


@dataclass(frozen=True)
class ErrorsModel:
    """Everything the errors page renders."""

    window: TimeWindow
    crash_groups: tuple[CrashGroupRow, ...]
    handled_errors: tuple[HandledErrorRow, ...]
    platform_events: tuple[PlatformEventRow, ...]
    degraded: tuple[DegradedComponentRow, ...]
    truncated: bool = False
    limit: int = 0
    # Whether the source can supply each group of rows at all; a source that
    # cannot gets one line saying so instead of an empty table.
    crash_groups_available: bool = True
    platform_events_available: bool = True
    # Where the crash groups were grouped, when that is not Error Reporting.
    crash_group_note: str | None = None
    # Said when two groups claim one exception type, so their events cannot be
    # told apart and neither row can carry a distribution.
    crash_series_note: str | None = None
