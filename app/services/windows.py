"""Window sizes and chart intervals shared by the pages.

Kept apart from the overview service so that service stays small, and so every
page picks its window and chart resolution the same way.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.domain.models import TimeWindow

# Chart resolution by window span: 1 minute, 5 minutes, 15 minutes, 2 hours.
INTERVAL_STEPS: tuple[tuple[timedelta, timedelta], ...] = (
    (timedelta(hours=1), timedelta(minutes=1)),
    (timedelta(hours=6), timedelta(minutes=5)),
    (timedelta(days=1), timedelta(minutes=15)),
    (timedelta(days=7), timedelta(hours=2)),
)


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


def window_for_hours(hours: int, now: datetime) -> TimeWindow:
    """Return the window of the given size ending at the start of now's interval.

    Flooring the end to the chart interval puts repeat loads inside the same
    interval, so the source cache hits and Google API reads stay low.
    """
    interval = interval_for(timedelta(hours=hours))
    end = floor_to(now, interval)
    return TimeWindow(start=end - timedelta(hours=hours), end=end)
