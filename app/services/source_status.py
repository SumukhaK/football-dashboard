"""The source page, and the sidebar footer's line about a local log file.

Where the pages differ in what they can show, this is where the console says
which source is on and what that source can answer. A source reading a local log
file also gets its read described line by line, because a local run's most
common question is "is the console seeing my file at all?".
"""

from __future__ import annotations

from app.config import Config
from app.domain.errors import SourceUnavailableError
from app.domain.models import LocalReadStats, SourceCapabilities
from app.domain.source_status import CapabilityRow, SourceStatusModel
from app.sources.base import LocalLogStats, TelemetrySource

__all__ = [
    "LOCAL_CRASH_NOTE",
    "LOCAL_ONLY_NOTE",
    "SourceStatusService",
    "SourceUnavailableError",
]

# Shown in place of a section a local log file cannot fill at all.
LOCAL_ONLY_NOTE = (
    "Not available from a local log file. Shown when the console reads Google Cloud."
)

# Shown beside the crash groups a local log file grouped itself.
LOCAL_CRASH_NOTE = (
    "Grouped from local app.crash logs; grouping may differ from Google Cloud "
    "Error Reporting."
)


class SourceStatusService:
    """Builds the source page, and the footer's line for a local log file."""

    def __init__(self, source: TelemetrySource, settings: Config) -> None:
        """Store the source and the settings the page reads."""
        self._source = source
        self._settings = settings

    def build(self) -> SourceStatusModel:
        """Return everything the source page renders.

        Raises SourceUnavailableError when a local log file cannot be read, so
        the page can show the same banner as every other page.
        """
        return SourceStatusModel(
            source=self._settings.source,
            capabilities=capability_rows(self._source.capabilities()),
            stats=self.read_stats(),
        )

    def read_stats(self) -> LocalReadStats | None:
        """The local log's counts, or None when this source reads no log file."""
        if not isinstance(self._source, LocalLogStats):
            return None
        return self._source.read_stats()

    def footer_stats(self) -> LocalReadStats | None:
        """The footer's counts, or None when there is nothing to say.

        The footer is on every page, so a log file that cannot be read must not
        break the render: the page itself already reports the failure.
        """
        try:
            return self.read_stats()
        except SourceUnavailableError:
            return None


def capability_rows(capabilities: SourceCapabilities) -> tuple[CapabilityRow, ...]:
    """The capabilities as named rows, in a fixed order."""
    return (
        CapabilityRow(
            name="Error Reporting groups", available=capabilities.error_reporting
        ),
        CapabilityRow(name="Platform events", available=capabilities.platform_events),
        CapabilityRow(name="Traces", available=capabilities.traces),
    )
