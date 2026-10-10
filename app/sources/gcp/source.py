"""GcpSource: the four Google Cloud readers behind the TelemetrySource protocol."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.config import Config
from app.contract import Contract
from app.domain.models import (
    ErrorGroup,
    EventQuery,
    PlatformEvent,
    TelemetryEvent,
    TimeWindow,
    Trace,
)
from app.sources.gcp.errors import guarded
from app.sources.gcp.errors_reader import ErrorsReader
from app.sources.gcp.logging_reader import LoggingReader
from app.sources.gcp.platform_reader import PlatformReader
from app.sources.gcp.trace_reader import TraceReader


@dataclass(frozen=True)
class GcpReaders:
    """One reader per Google API."""

    logging: LoggingReader
    traces: TraceReader
    errors: ErrorsReader
    platform: PlatformReader


class GcpSource:
    """Read-only telemetry from Cloud Logging, Cloud Trace and Error Reporting.

    Readers are built on first use, so starting the console never needs
    credentials; a credentials problem shows up as a source error on a page.
    """

    def __init__(self, build_readers: Callable[[], GcpReaders]) -> None:
        self._build_readers = build_readers
        self._readers: GcpReaders | None = None

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Return events matching the query, newest first."""
        return self._get_readers().logging.events(query)

    def trace(self, trace_id: str) -> Trace | None:
        """Return one trace, or None when it does not exist."""
        return self._get_readers().traces.trace(trace_id)

    def error_groups(self, window: TimeWindow) -> list[ErrorGroup]:
        """Return error groups that overlap the window."""
        return self._get_readers().errors.error_groups(window)

    def platform_events(self, window: TimeWindow) -> list[PlatformEvent]:
        """Return platform events inside the window, newest first."""
        return self._get_readers().platform.platform_events(window)

    def _get_readers(self) -> GcpReaders:
        """Build the readers once, mapping credential errors to source errors."""
        if self._readers is None:
            self._readers = guarded("Google Cloud", self._build_readers)
        return self._readers


def google_readers(settings: Config, contract: Contract) -> GcpReaders:
    """Create the real Google clients (Application Default Credentials only)."""
    # Imported here so fixture-only runs and tests never load the Google SDKs.
    from google.cloud import errorreporting_v1beta1, trace_v1
    from google.cloud import logging as cloud_logging

    project_id = settings.gcp_project_id or ""
    # The logging Client constructor has no type annotations upstream.
    logging_client = cloud_logging.Client(  # type: ignore[no-untyped-call]
        project=project_id
    )
    service = settings.api_service_name
    return GcpReaders(
        logging=LoggingReader(
            logging_client, contract, service, settings.gcp_page_size
        ),
        traces=TraceReader(trace_v1.TraceServiceClient(), project_id),
        errors=ErrorsReader(
            errorreporting_v1beta1.ErrorStatsServiceClient(), project_id, service
        ),
        platform=PlatformReader(
            logging_client, project_id, service, settings.platform_patterns
        ),
    )
