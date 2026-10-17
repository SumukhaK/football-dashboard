"""Frozen view models for the data and jobs page.

These belong to the domain: they describe what the page shows, with no knowledge
of FastAPI or of any telemetry source.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.models import TimeWindow
from app.domain.overview import TileState


@dataclass(frozen=True)
class FreshnessRow:
    """One league's newest freshness reading, graded against the thresholds."""

    competition: str
    matches_through: str | None
    age_hours: float | None
    timestamp: datetime
    state: TileState


@dataclass(frozen=True)
class FallbackRow:
    """One fallback to the previous data."""

    timestamp: datetime
    from_path: str
    to_path: str
    cause: str


@dataclass(frozen=True)
class RefreshRunRow:
    """One daily refresh attempt and the fallbacks that belonged to it.

    ``refresh.run`` is a completion record: ``duration_ms`` covers the whole
    run, so the fallbacks shown here happened inside it or just after its
    completion, depending on which one the producer logged.
    """

    timestamp: datetime
    status: str
    duration_ms: float | None
    dataset: str | None
    error: str | None
    fallbacks: tuple[FallbackRow, ...] = ()


@dataclass(frozen=True)
class DownloadFailure:
    """The failed download attempts that shared one status."""

    status: str
    http_status: int | None
    count: int


@dataclass(frozen=True)
class DownloadRow:
    """One dependency's download attempts, retries and last error."""

    dependency: str
    attempts: int
    failures: tuple[DownloadFailure, ...]
    retries: int
    last_error: str | None


@dataclass(frozen=True)
class ReloadRow:
    """One component load that happened during a measured refresh."""

    timestamp: datetime
    component: str
    status: str
    duration_ms: float | None
    reason: str | None


@dataclass(frozen=True)
class DataJobsModel:
    """Everything the data and jobs page renders."""

    window: TimeWindow
    freshness: tuple[FreshnessRow, ...]
    refreshes: tuple[RefreshRunRow, ...]
    downloads: tuple[DownloadRow, ...]
    reloads: tuple[ReloadRow, ...]
    freshness_lookback_hours: int
    truncated: bool = False
    limit: int = 0
