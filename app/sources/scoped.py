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
from app.sources.attribution import attributed_platform_events, retained_error_groups
from app.sources.base import TelemetrySource


class ReleaseSource:
    """Bind backend event reads without mutating any shared service or cache."""

    def __init__(
        self,
        source: TelemetrySource,
        release: ReleaseSelection,
        *,
        derive_errors: bool = True,
    ) -> None:
        """Keep the existing cached source and this request's immutable choice."""
        self.source = source
        self.release = release
        self.derive_errors = derive_errors

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Apply selection before source reads, including comparison and lookback."""
        return self.source.events(replace(query, release=self.release))

    def trace(self, trace_id: str) -> Trace | None:
        """Read only an explicitly correlated trace."""
        return self.source.trace(trace_id)

    def error_groups(self, window: TimeWindow) -> list[ErrorGroup]:
        """Use retained matching logs when provider release/end-time identity is unproven."""
        if self.derive_errors:
            return retained_error_groups(self.source, window, self.release)
        return self.source.error_groups(window)

    def platform_events(self, window: TimeWindow) -> list[PlatformEvent]:
        """Attribute with all-release evidence; keep unknown attribution explicit."""
        return attributed_platform_events(self.source, window, self.release)

    def capabilities(self) -> SourceCapabilities:
        """Preserve provider availability without fabricating telemetry."""
        capabilities = self.source.capabilities()
        return (
            replace(capabilities, error_reporting=True)
            if self.derive_errors
            else capabilities
        )
