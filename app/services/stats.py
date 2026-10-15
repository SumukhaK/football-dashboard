"""Pure statistics helpers for the overview page.

Nothing here reads a source or a clock: every function takes plain values and
returns plain values, so the arithmetic can be tested on hand-written numbers.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.domain.models import TelemetryEvent, TimeWindow


@dataclass(frozen=True)
class Bucket:
    """One interval of a window and the events that fall in it."""

    start: datetime
    events: tuple[TelemetryEvent, ...]


def percentile(values: Sequence[float], q: float) -> float | None:
    """Return the nearest-rank percentile of values, or None when empty.

    The rank is ``ceil(q * n)`` counted from one, so ``q=0.95`` of ten values
    is the tenth (the largest), matching the way latency SLOs are read.
    """
    if not values:
        return None
    ordered = sorted(values)
    if q <= 0:
        return ordered[0]
    if q >= 1:
        return ordered[-1]
    rank = math.ceil(q * len(ordered))
    index = min(max(rank - 1, 0), len(ordered) - 1)
    return ordered[index]


def rate(numerator: int, denominator: int) -> float | None:
    """Return numerator/denominator, or None when the denominator is zero."""
    if denominator == 0:
        return None
    return numerator / denominator


def bucket_by_interval(
    events: Sequence[TelemetryEvent], window: TimeWindow, interval: timedelta
) -> list[Bucket]:
    """Group events into equal intervals covering the window.

    A bucket covers ``[start, start + interval)``: the window start belongs to
    the first bucket and the window end is outside the window, so it is dropped.
    """
    count = max(1, math.ceil((window.end - window.start) / interval))
    starts = [window.start + interval * index for index in range(count)]
    grouped: list[list[TelemetryEvent]] = [[] for _ in range(count)]
    for event in events:
        if not window.start <= event.timestamp < window.end:
            continue
        index = int((event.timestamp - window.start) / interval)
        if 0 <= index < count:
            grouped[index].append(event)
    return [
        Bucket(start=start, events=tuple(items))
        for start, items in zip(starts, grouped)
    ]
