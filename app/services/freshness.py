"""The data-freshness rule, shared by the overview tile and the data page.

The thresholds live in the settings; this is the one place that turns an age in
hours into a state, so the overview tile and the data page can never disagree
about what "stale" means. It also picks the newest reading per competition,
which both pages need.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.config import Config
from app.domain.data_jobs import FreshnessRow
from app.domain.models import TelemetryEvent
from app.domain.overview import TileState


def age_hours(event: TelemetryEvent) -> float | None:
    """The age in hours on a freshness reading, or None when unknown."""
    value = event.attributes.get("age_hours")
    return float(value) if isinstance(value, (int, float)) else None


def matches_through(event: TelemetryEvent) -> str | None:
    """The ISO date a reading's matches run through, or None when unknown."""
    value = event.attributes.get("matches_through")
    return value if isinstance(value, str) else None


def newest_per_competition(
    events: Iterable[TelemetryEvent],
) -> dict[str, TelemetryEvent]:
    """The newest freshness reading for each competition."""
    found: dict[str, TelemetryEvent] = {}
    for event in events:
        key = str(event.attributes.get("competition"))
        seen = found.get(key)
        if seen is None or event.timestamp > seen.timestamp:
            found[key] = event
    return found


def state_for(age: float | None, has_unknown: bool, settings: Config) -> TileState:
    """Grade a freshness age: unknown is at least amber, and red wins."""
    if age is not None and age > settings.freshness_error_hours:
        return TileState.FAILED
    warn = age is not None and age >= settings.freshness_warn_hours
    return TileState.DEGRADED if has_unknown or warn else TileState.OK


def freshness_rows(
    events: Iterable[TelemetryEvent], settings: Config
) -> tuple[FreshnessRow, ...]:
    """One graded row per league, stalest first (unknown first, ties by name).

    A reading with no age is the stalest thing there is: an unknown age is at
    least amber, so it should not be buried under a known-good league.
    """
    rows = [
        FreshnessRow(
            competition=competition,
            matches_through=matches_through(event),
            age_hours=age_hours(event),
            timestamp=event.timestamp,
            state=state_for(age_hours(event), age_hours(event) is None, settings),
        )
        for competition, event in newest_per_competition(events).items()
    ]
    rows.sort(
        key=lambda row: (
            row.age_hours is not None,
            -(row.age_hours or 0.0),
            row.competition,
        )
    )
    return tuple(rows)
