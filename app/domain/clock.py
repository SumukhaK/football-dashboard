"""Clock for testable time injection."""

from __future__ import annotations

from datetime import datetime, UTC
from typing import Callable

Clock = Callable[[], datetime]


def system_clock() -> datetime:
    """Return the current UTC time.

    Used by ``create_app``; injectable in tests.
    """
    return datetime.now(UTC)