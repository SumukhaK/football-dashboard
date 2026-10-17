"""Correlating refresh telemetry with the producer's run lifecycle.

``refresh.run`` is a completion record, not a start marker: the backend emits it
after the download step and the reload step have both finished, so its
``duration_ms`` covers the whole run. A component load or a fixture fallback
therefore happens *inside* the interval from ``timestamp - duration`` to
``timestamp``, while a whole-run failure fallback is logged after the failed
completion.

Only timestamps, durations and revisions are available, so every match here is
an inference, not a guaranteed run identity. A missing or unusable duration
supports no interval, and an event that more than one run could explain is left
unassigned rather than guessed at.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.domain.models import TelemetryEvent
from app.services.events import text

# The fallback triples the refresh produces. A fallback is a cross-feature
# event, so the paths and the cause together identify one: proximity alone, or
# the word "failed", cannot tell a fixture fallback from a tool-round one.
FIXTURE_FALLBACK: tuple[str, str, str] = (
    "fresh_fixtures",
    "previous_fixtures",
    "fixtures_refresh_failed",
)
FAILURE_FALLBACK: tuple[str, str, str] = (
    "fresh_match_data",
    "previous_match_data",
    "refresh_failed",
)

# A whole-run failure fallback follows its failed completion immediately. This
# bound is a conservative inference limit for that one triple, and is kept
# separate from the measured interval used for loads and fixture fallbacks.
FAILURE_FALLBACK_LIMIT = timedelta(minutes=5)


@dataclass(frozen=True)
class RunInterval:
    """The span one refresh run covered, inferred from its completion record."""

    index: int
    end: datetime
    start: datetime | None
    status: str
    revision: str | None


def usable_duration(event: TelemetryEvent) -> float | None:
    """The duration in ms when it can bound an interval, otherwise None.

    A missing, boolean, non-numeric, negative, non-finite or unrepresentable
    duration does not describe how long a run took, so it supports no interval.
    """
    value = event.attributes.get("duration_ms")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    try:
        timedelta(milliseconds=value)
    except OverflowError:
        return None
    return float(value)


def run_intervals(runs: Sequence[TelemetryEvent]) -> tuple[RunInterval, ...]:
    """The inferred interval of each run, in the order the runs are given."""
    return tuple(_interval(index, run) for index, run in enumerate(runs))


def _interval(index: int, run: TelemetryEvent) -> RunInterval:
    """One run's interval, without one when its duration cannot bound it."""
    duration = usable_duration(run)
    start = None
    if duration is not None:
        start = run.timestamp - timedelta(milliseconds=duration)
    return RunInterval(
        index=index,
        end=run.timestamp,
        start=start,
        status=text(run.attributes.get("status")) or "unknown",
        revision=run.revision,
    )


def owner_of(
    intervals: Sequence[RunInterval], event: TelemetryEvent
) -> RunInterval | None:
    """The one run interval that contains the event, or None.

    None covers both "no run covers it" and "more than one run does": a load or
    a fixture fallback that two overlapping runs could each explain is left
    unassigned rather than duplicated.
    """
    found = [interval for interval in intervals if _covers(interval, event)]
    return found[0] if len(found) == 1 else None


def _covers(interval: RunInterval, event: TelemetryEvent) -> bool:
    """Whether the event sits inside the interval and matches its revision."""
    if interval.start is None or not interval.start <= event.timestamp <= interval.end:
        return False
    return _same_revision(interval.revision, event.revision)


def _same_revision(run_revision: str | None, event_revision: str | None) -> bool:
    """Whether both revisions are absent, or both are recorded and equal."""
    return (
        run_revision is None or event_revision is None or run_revision == event_revision
    )


def fallback_triple(event: TelemetryEvent) -> tuple[str, str, str]:
    """The from_path, to_path and cause a fallback recorded."""
    return (
        text(event.attributes.get("from_path")) or "",
        text(event.attributes.get("to_path")) or "",
        text(event.attributes.get("cause")) or "",
    )


def failure_interval(
    intervals: Sequence[RunInterval], event: TelemetryEvent
) -> RunInterval | None:
    """The failed run a whole-run fallback followed, or None.

    Only the newest run that completed at or before the fallback can own it, so
    a fallback is never carried back across a newer run to an older failure, and
    a run that succeeded never owns one. Two runs that completed at the same
    moment are indistinguishable, so neither is chosen.
    """
    after = [
        interval
        for interval in intervals
        if timedelta(0) <= event.timestamp - interval.end <= FAILURE_FALLBACK_LIMIT
    ]
    if not after:
        return None
    latest = max(interval.end for interval in after)
    newest = [interval for interval in after if interval.end == latest]
    only = newest[0] if len(newest) == 1 else None
    if only is None or only.status != "failed":
        return None
    return only if _same_revision(only.revision, event.revision) else None


def pair_fallbacks(
    runs: Sequence[TelemetryEvent], fallbacks: Sequence[TelemetryEvent]
) -> dict[int, tuple[TelemetryEvent, ...]]:
    """The fallbacks each run owns, keyed by the run's index in ``runs``.

    Each fallback is attached to at most one run. Unrelated fallbacks, the wrong
    cause and known revision mismatches are ignored; those events stay in the
    source for the features that own them.
    """
    intervals = run_intervals(runs)
    paired: dict[int, list[TelemetryEvent]] = {}
    for event in sorted(fallbacks, key=_fallback_order):
        owner = _fallback_owner(intervals, event)
        if owner is not None:
            paired.setdefault(owner.index, []).append(event)
    return {index: tuple(events) for index, events in paired.items()}


def _fallback_owner(
    intervals: Sequence[RunInterval], event: TelemetryEvent
) -> RunInterval | None:
    """The run a recognised fallback belongs to, by its lifecycle position."""
    triple = fallback_triple(event)
    if triple == FIXTURE_FALLBACK:
        return owner_of(intervals, event)
    if triple == FAILURE_FALLBACK:
        return failure_interval(intervals, event)
    return None


def _fallback_order(event: TelemetryEvent) -> tuple[datetime, str, str, str]:
    """A deterministic order for fallbacks that share a timestamp."""
    return (event.timestamp, *fallback_triple(event))
