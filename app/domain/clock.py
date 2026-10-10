"""Injectable clock, so code that needs the current time stays testable."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

Clock = Callable[[], datetime]


def system_clock() -> datetime:
    """Return the current time in UTC."""
    return datetime.now(UTC)
