"""Frozen view models for the overview page.

These belong to the domain: they describe what the page shows, with no
knowledge of FastAPI or of any telemetry source.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.domain.models import TimeWindow


class TileState(StrEnum):
    """The state a component tile is showing."""

    OK = "ok"
    DEGRADED = "degraded"
    FAILED = "failed"
    NO_DATA = "no data"


@dataclass(frozen=True)
class ComponentTile:
    """One component's latest state inside the window."""

    name: str
    state: TileState
    detail: str
    since: datetime | None
    degraded_count: int = 0
    link: str | None = None


@dataclass(frozen=True)
class HeadlineNumber:
    """A single headline figure and its change from the previous window."""

    key: str
    label: str
    value: float | None
    previous: float | None
    is_percent: bool = False
    link: str = ""

    @property
    def change(self) -> float | None:
        """The change against the previous window, or None when unknown."""
        if self.value is None or self.previous is None:
            return None
        return self.value - self.previous


@dataclass(frozen=True)
class Series:
    """One line or stack of a chart."""

    name: str
    values: tuple[float | None, ...]


@dataclass(frozen=True)
class Chart:
    """A chart with shared labels and one or more series."""

    labels: tuple[str, ...]
    series: tuple[Series, ...]


@dataclass(frozen=True)
class RouteRow:
    """One row of the slowest-routes table."""

    route: str
    requests: int
    p95_ms: float | None
    error_rate: float | None
    link: str = ""


@dataclass(frozen=True)
class OverviewModel:
    """Everything the overview page renders."""

    window: TimeWindow
    tiles: tuple[ComponentTile, ...]
    headlines: tuple[HeadlineNumber, ...]
    traffic: Chart
    latency: Chart
    slowest_routes: tuple[RouteRow, ...]
    last_refreshed: datetime
    truncated: bool = False
    limit: int = 0
