"""Window sizes and chart intervals shared by the pages.

Kept apart from the overview service so that service stays small, and so every
page picks its window and chart resolution the same way.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.config import WINDOW_HOURS
from app.domain.models import TimeWindow

# Chart resolution by window span: 1 minute, 5 minutes, 15 minutes, 2 hours.
INTERVAL_STEPS: tuple[tuple[timedelta, timedelta], ...] = (
    (timedelta(hours=1), timedelta(minutes=1)),
    (timedelta(hours=6), timedelta(minutes=5)),
    (timedelta(days=1), timedelta(minutes=15)),
    (timedelta(days=7), timedelta(hours=2)),
)


def resolve_window_hours(hours: int | None, default: int) -> int:
    """Return the requested window size, defaulting and validating it."""
    resolved = default if hours is None else hours
    if resolved not in WINDOW_HOURS:
        raise ValueError(f"unsupported window: {resolved}")
    return resolved


def interval_for(span: timedelta) -> timedelta:
    """Return the chart interval that suits a window of the given span."""
    for limit, interval in INTERVAL_STEPS:
        if span <= limit:
            return interval
    return INTERVAL_STEPS[-1][1]


def floor_to(moment: datetime, interval: timedelta) -> datetime:
    """Round a moment down to the nearest whole interval."""
    seconds = int(interval.total_seconds())
    epoch = int(moment.timestamp())
    return datetime.fromtimestamp(epoch - epoch % seconds, tz=UTC)


def ceil_to(moment: datetime, interval: timedelta) -> datetime:
    """Round a moment up to the next whole interval (a boundary stays put)."""
    floored = floor_to(moment, interval)
    return floored if floored == moment else floored + interval


def window_for_hours(hours: int, now: datetime) -> TimeWindow:
    """Return the window of the given size ending at the end of now's interval.

    Rounding the end *up* to the chart interval keeps two promises at once: two
    loads inside one interval produce the same window, so the source cache hits
    and Google API reads stay low, and the newest events (which sit in the
    current, still-partial interval) stay inside the window rather than being
    dropped. The final bucket is then partly in the future, which is harmless
    because it simply holds fewer events.
    """
    interval = interval_for(timedelta(hours=hours))
    end = ceil_to(now, interval)
    return TimeWindow(start=end - timedelta(hours=hours), end=end)
