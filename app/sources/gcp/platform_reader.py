"""Classify Cloud Run's own system log lines as platform events."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, Protocol

from app.domain.models import PlatformEvent, TimeWindow
from app.sources.gcp.errors import guarded
from app.sources.gcp.filters import system_log_filter
from app.sources.gcp.logging_reader import NEWEST_FIRST, LoggingClient

PLATFORM_EVENT_LIMIT = 1000


class ResourceLike(Protocol):
    """The monitored resource on a log entry."""

    @property
    def labels(self) -> Mapping[str, str]: ...


class SystemEntryLike(Protocol):
    """The parts of a Cloud Run system log entry this reader uses."""

    @property
    def payload(self) -> Any: ...  # Any: system lines are text, some are JSON.
    @property
    def timestamp(self) -> datetime | None: ...
    @property
    def resource(self) -> ResourceLike | None: ...


class PlatformReader:
    """Reads the system log and keeps lines that match a known pattern."""

    def __init__(
        self,
        client: LoggingClient,
        project_id: str,
        service_name: str,
        patterns: tuple[tuple[str, str], ...],
    ) -> None:
        self._client = client
        self._project_id = project_id
        self._service_name = service_name
        self._patterns = patterns

    def platform_events(self, window: TimeWindow) -> list[PlatformEvent]:
        """Return classified platform events inside the window, newest first."""
        log_filter = system_log_filter(self._project_id, self._service_name, window)
        entries = guarded("Cloud Logging", lambda: self._fetch(log_filter))
        found = (self._classify(entry) for entry in entries)
        return [event for event in found if event is not None]

    def _fetch(self, log_filter: str) -> list[Any]:  # Any: real or fake entries.
        """Read the system log entries for the window."""
        return list(
            self._client.list_entries(
                filter_=log_filter,
                order_by=NEWEST_FIRST,
                max_results=PLATFORM_EVENT_LIMIT,
                page_size=PLATFORM_EVENT_LIMIT,
            )
        )

    def _classify(self, entry: SystemEntryLike) -> PlatformEvent | None:
        """Return a platform event when the entry's text matches a pattern."""
        text = entry.payload if isinstance(entry.payload, str) else str(entry.payload)
        kind = next((k for needle, k in self._patterns if needle in text), None)
        if kind is None or entry.timestamp is None:
            return None
        labels: Iterable[tuple[str, str]] = (
            entry.resource.labels.items() if entry.resource else ()
        )
        revision = dict(labels).get("revision_name", "unknown")
        return PlatformEvent(
            timestamp=entry.timestamp, kind=kind, revision=revision, message=text
        )
