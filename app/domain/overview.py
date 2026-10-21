"""Frozen view models for the overview page.

These belong to the domain: they describe what the page shows, with no
knowledge of FastAPI or of any telemetry source.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.domain.models import TimeWindow
from app.domain.release_comparison import ReleaseComparison

# A route's error rate is worth a fail pill only from one percent up; below that
# it is noise on a small sample. The guide names this threshold.
ERROR_RATE_HIGHLIGHT = 0.01

# The four cards the redesign promotes above the rest of the headline figures.
CARD_HEADLINE_KEYS: tuple[str, ...] = (
    "requests",
    "error_rate",
    "p95_latency",
    "crashes",
)


class TileState(StrEnum):
    """The state a component tile is showing."""

    OK = "ok"
    DEGRADED = "degraded"
    FAILED = "failed"
    NO_DATA = "no data"


class GoodDirection(StrEnum):
    """Which way a headline's change has to move to read as good.

    ``UP`` means a rise is an improvement (more requests); ``DOWN`` means a
    fall is (fewer errors, less latency, fewer crashes).
    """

    UP = "up"
    DOWN = "down"


@dataclass(frozen=True)
class ComponentTile:
    """One component's latest state inside the window."""

    name: str
    state: TileState
    detail: str
    since: datetime | None
    degraded_count: int = 0
    link: str | None = None
    display_name: str = ""


@dataclass(frozen=True)
class HeadlineNumber:
    """A single headline figure and its change from the previous window."""

    key: str
    label: str
    value: float | None
    previous: float | None
    is_percent: bool = False
    link: str = ""
    good_direction: GoodDirection = GoodDirection.UP
    unit: str = ""

    @property
    def change(self) -> float | None:
        """The change against the previous window, or None when unknown."""
        if self.value is None or self.previous is None:
            return None
        return self.value - self.previous

    @property
    def change_tone(self) -> str:
        """The pill tone for the change: ok when it improves, fail when it worsens."""
        change = self.change
        if change is None or change == 0:
            return "neutral"
        improved = (change > 0) == (self.good_direction is GoodDirection.UP)
        return "ok" if improved else "fail"


@dataclass(frozen=True)
class Sparkline:
    """A small per-interval series drawn inside one headline card."""

    key: str
    labels: tuple[str, ...]
    values: tuple[float | None, ...]


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
    p95_label: str = ""
    p95_bar_pct: float = 0.0
    highlight_error_rate: bool = False


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
    sparklines: tuple[Sparkline, ...] = ()
    truncated: bool = False
    limit: int = 0
    release_comparison: ReleaseComparison | None = None

    @property
    def attention(self) -> tuple[ComponentTile, ...]:
        """The tiles that are not OK, in tile order."""
        return tuple(tile for tile in self.tiles if tile.state is not TileState.OK)

    @property
    def healthy_count(self) -> int:
        """How many components are OK."""
        return sum(1 for tile in self.tiles if tile.state is TileState.OK)

    @property
    def cards(self) -> tuple[HeadlineNumber, ...]:
        """The large headline cards, in the guide's order."""
        return tuple(
            number for number in self.headlines if number.key in CARD_HEADLINE_KEYS
        )

    @property
    def minor_numbers(self) -> tuple[HeadlineNumber, ...]:
        """The remaining headline figures, shown as one small line."""
        return tuple(
            number for number in self.headlines if number.key not in CARD_HEADLINE_KEYS
        )

    def sparkline(self, key: str) -> Sparkline | None:
        """The sparkline for a headline key, or None when it has none."""
        return next((line for line in self.sparklines if line.key == key), None)
