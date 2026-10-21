"""Conservative release attribution from bounded retained backend telemetry."""

from dataclasses import replace

from app.domain.errors import SourceUnavailableError
from app.domain.models import (
    MAX_QUERY_LIMIT,
    ErrorGroup,
    EventQuery,
    PlatformEvent,
    TelemetryEvent,
    TimeWindow,
)
from app.domain.releases import ReleaseSelection
from app.sources.base import LocalLogStats, ReleaseDiscovery, TelemetrySource
from app.sources.local_log_source import crash_groups


def complete_evidence(
    source: TelemetrySource, window: TimeWindow, rows: list[TelemetryEvent]
) -> bool:
    """Never treat a byte tail, skipped records or a capped scan as full evidence."""
    if len(rows) >= MAX_QUERY_LIMIT:
        return False
    if isinstance(source, LocalLogStats):
        stats = source.read_stats()
        if stats and (stats.truncated or stats.skipped_invalid):
            return False
    return (
        not isinstance(source, ReleaseDiscovery)
        or not source.release_catalogue(window).truncated
    )


def retained_error_groups(
    source: TelemetrySource, window: TimeWindow, release: ReleaseSelection
) -> list[ErrorGroup]:
    """Filter app.crash records at the source before grouping the exact period."""
    rows = source.events(
        EventQuery(
            window, events=("app.crash",), release=release, limit=MAX_QUERY_LIMIT
        )
    )
    if not complete_evidence(source, window, rows):
        raise SourceUnavailableError(
            "unavailable",
            "Unavailable for this release/period: retained crash evidence reached a cap or is incomplete.",
        )
    return crash_groups(rows)


def attributed_platform_events(
    source: TelemetrySource, window: TimeWindow, release: ReleaseSelection
) -> list[PlatformEvent]:
    """Retain unattributed records, never infer API release from revision names."""
    events = source.platform_events(window)
    if not events:
        return []
    mapping, complete = _revision_mapping(source, window)
    attributed = [_attribute(event, mapping, complete) for event in events]
    return [
        e
        for e in attributed
        if release.kind == "all"
        or e.api_version is None
        or e.api_version == release.value
    ]


def _revision_mapping(
    source: TelemetrySource, window: TimeWindow
) -> tuple[dict[str, set[str | None]], bool]:
    """Read all releases so a selected release cannot hide conflicting evidence."""
    try:
        rows = source.events(EventQuery(window, limit=MAX_QUERY_LIMIT))
        complete = complete_evidence(source, window, rows)
    except SourceUnavailableError:
        return {}, False
    mapping: dict[str, set[str | None]] = {}
    for row in rows:
        if row.revision:
            mapping.setdefault(row.revision, set()).add(row.api_version)
    return mapping, complete


def _attribute(
    event: PlatformEvent, mapping: dict[str, set[str | None]], complete: bool
) -> PlatformEvent:
    """Only one known recorded release from complete evidence is attributable."""
    versions = mapping.get(event.revision, set())
    version = next(iter(versions)) if complete and len(versions) == 1 else None
    note = None
    if version is None:
        note = (
            "Revision evidence is incomplete/unavailable"
            if not complete
            else "No unambiguous recorded API release for this revision"
        )
    return replace(event, api_version=version, attribution_note=note)
