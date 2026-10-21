"""Attribution must follow retained evidence and filter before grouping."""

from dataclasses import replace
from datetime import timedelta
from typing import Literal

import pytest

from app.domain.errors import SourceUnavailableError
from app.domain.models import (
    MAX_QUERY_LIMIT,
    EventQuery,
    PlatformEvent,
    TelemetryEvent,
    TimeWindow,
)
from app.domain.releases import ReleaseCatalogue, ReleaseSelection
from app.sources.scoped import ReleaseSource
from tests.services.requests_helpers import NOW, WINDOW, FakeSource, event_line


def test_identical_exception_is_grouped_after_release_and_time_selection() -> None:
    """A newer release's duplicate exception must not inflate this release count."""
    crash = event_line(
        1, "app.crash", None, {"exception_type": "ValueError", "route": "/v2/chat"}
    )
    rows = [replace(crash, api_version=v) for v in ("2.5.1", "2.6.0", "2.6.0", None)]
    rows.append(replace(crash, timestamp=NOW - timedelta(days=8), api_version="2.5.1"))
    groups = ReleaseSource(
        FakeSource(rows), ReleaseSelection("exact", "2.5.1")
    ).error_groups(WINDOW)
    assert len(groups) == 1 and groups[0].count == 1


class PlatformSource(FakeSource):
    """A fixed source with independent service platform events."""

    def platform_events(self, window: TimeWindow) -> list[PlatformEvent]:
        """Return both known and unmapped revisions."""
        return [
            PlatformEvent(NOW - timedelta(minutes=1), "container_exit", r, r)
            for r in ("old", "new", "both", "missing")
        ]


def test_platform_mapping_never_guesses_conflicting_or_missing_revisions() -> None:
    """All-release evidence is required even under an exact selected release."""
    rows = [
        replace(event_line(1, "retry", None), revision=r, api_version=v)
        for r, v in [
            ("old", "2.5.1"),
            ("new", "2.6.0"),
            ("both", "2.5.1"),
            ("both", "2.6.0"),
        ]
    ]
    events = ReleaseSource(
        PlatformSource(rows), ReleaseSelection("exact", "2.5.1")
    ).platform_events(WINDOW)
    assert {e.revision for e in events} == {"old", "both", "missing"}
    assert next(e for e in events if e.revision == "old").api_version == "2.5.1"
    assert all(e.api_version is None for e in events if e.revision != "old")


def test_capped_crash_evidence_is_unavailable_not_a_zero_or_complete_count() -> None:
    """A retained log cap cannot silently present exact grouped counts."""
    crash = event_line(1, "app.crash", None)
    with pytest.raises(SourceUnavailableError, match="cap"):
        ReleaseSource(
            FakeSource([crash] * MAX_QUERY_LIMIT), ReleaseSelection("unknown")
        ).error_groups(WINDOW)


@pytest.mark.parametrize("kind", ["all", "unknown", "exact"])
def test_platform_incomplete_metadata_stays_unattributed(
    kind: Literal["all", "unknown", "exact"],
) -> None:
    """An incomplete catalogue cannot provide a proven revision mapping."""

    class Incomplete(PlatformSource):
        def release_catalogue(self, window: TimeWindow) -> ReleaseCatalogue:
            return ReleaseCatalogue(("2.6.0",), False, True)

    selection = ReleaseSelection(kind, "2.6.0" if kind == "exact" else None)
    source = Incomplete(
        [replace(event_line(1, "retry", None), revision="new", api_version="2.6.0")]
    )
    events = ReleaseSource(source, selection).platform_events(WINDOW)
    assert len(events) == 4
    assert all(e.api_version is None and e.attribution_note for e in events)


def test_historical_all_groups_use_only_that_exact_window() -> None:
    """A historic all-release view cannot substitute today's rolling provider count."""
    from app.sources.attribution import retained_error_groups

    crash = event_line(1, "app.crash", None, {"exception_type": "E"})
    rows = [replace(crash, timestamp=NOW - timedelta(days=3)), crash]
    window = TimeWindow(NOW - timedelta(days=4), NOW - timedelta(days=2))
    assert (
        retained_error_groups(FakeSource(rows), window, ReleaseSelection())[0].count
        == 1
    )


def test_mapping_failure_preserves_platform_records_as_unknown() -> None:
    """A metadata source failure cannot erase independently read platform events."""

    class BrokenMetadata(PlatformSource):
        def events(self, query: EventQuery) -> list[TelemetryEvent]:
            raise SourceUnavailableError("unavailable", "mapping offline")

    events = ReleaseSource(
        BrokenMetadata([]), ReleaseSelection("exact", "2.6.0")
    ).platform_events(WINDOW)
    assert len(events) == 4 and all(e.api_version is None for e in events)
