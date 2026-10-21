"""Per-request selection applied before the existing source cache and limits."""

from dataclasses import replace

from app.domain.models import (
    ErrorGroup,
    EventQuery,
    PlatformEvent,
    SourceCapabilities,
    TelemetryEvent,
    TimeWindow,
    Trace,
)
from app.domain.releases import ReleaseSelection
from app.sources.base import TelemetrySource


class ReleaseSource:
    """Bind backend event reads without mutating any shared service or cache."""

    def __init__(self, source: TelemetrySource, release: ReleaseSelection) -> None:
        """Keep the existing cached source and this request's immutable choice."""
        self.source = source
        self.release = release

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Apply selection before source reads, including comparison and lookback."""
        return self.source.events(replace(query, release=self.release))

    def trace(self, trace_id: str) -> Trace | None:
        """Read only an explicitly correlated trace."""
        return self.source.trace(trace_id)

    def error_groups(self, window: TimeWindow) -> list[ErrorGroup]:
        """Provider groups remain explicitly source-wide until attribution is available."""
        return self.source.error_groups(window)

    def platform_events(self, window: TimeWindow) -> list[PlatformEvent]:
        """Provider events remain explicitly source-wide until attribution is available."""
        return self.source.platform_events(window)

    def capabilities(self) -> SourceCapabilities:
        """Preserve provider availability without fabricating telemetry."""
        return self.source.capabilities()
